"""Resume an existing run with slower HTTP pacing and unchanged scientific inputs.

This launcher intentionally lives outside src/afrijudge: existing run code hashes
and cached payloads remain valid. It changes scheduling only, not model requests,
provider selection, budget accounting, or the existing bounded retry count.
"""

import argparse
import asyncio
import hashlib
import json
import math
import re
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx


def retry_after_seconds(value: str | None, now: datetime | None = None) -> float:
    if not value:
        return 0
    try:
        seconds = float(value)
    except ValueError:
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            seconds = (deadline - (now or datetime.now(UTC))).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0
    return max(0, seconds) if math.isfinite(seconds) else 0


def safe_error(response: httpx.Response, headers: dict) -> str:
    fallback = f"HTTP {response.status_code}"
    try:
        error = response.json().get("error", {})
        parts = []
        if isinstance(error, dict):
            for field in ("code", "message"):
                if error.get(field) is not None:
                    parts.append(str(error[field]))
            metadata = error.get("metadata") or {}
            raw = metadata.get("raw") if isinstance(metadata, dict) else None
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except ValueError:
                    raw = None
            if isinstance(raw, dict):
                detail = raw.get("error", raw)
                if isinstance(detail, dict):
                    for field in ("code", "message"):
                        if detail.get(field) is not None:
                            parts.append(str(detail[field]))
        message = " | ".join(parts) or fallback
    except (ValueError, AttributeError):
        message = fallback + " (non-JSON response)"
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        message = message.replace(auth[7:], "[REDACTED]") if auth[7:] else message
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", message)
    message = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", message)
    return " ".join(message.split())[:400]


class Pacer:
    def __init__(self, interval: float, log_path: Path, clock=None, sleep=None):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Request interval must be finite and positive")
        self.interval = interval
        self.log_path = log_path
        self.lock = asyncio.Lock()
        self.next_request = 0.0
        self.clock = clock or time.monotonic
        self.sleep = sleep or asyncio.sleep
        self.streak = {}
        self.completed = 0

    def log(self, event: dict):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"timestamp": time.time(), **event}) + "\n")

    async def post(self, send, url, **kwargs):
        if str(url) != "https://openrouter.ai/api/v1/chat/completions":
            return await send(url, **kwargs)
        async with self.lock:
            await self.sleep(max(0, self.next_request - self.clock()))
            payload = kwargs.get("json", {})
            model = payload.get("model", "unknown")
            try:
                response = await send(url, **kwargs)
            except httpx.TransportError as exc:
                self.log(
                    {
                        "event": "transport_failure",
                        "model": model,
                        "providers": payload.get("provider", {}).get("only", []),
                        "exception_type": type(exc).__name__,
                    }
                )
                print(
                    f"[Transport failure] {model}: {type(exc).__name__}. "
                    "Billing status unknown; reservation retained.",
                    flush=True,
                )
                raise
            self.next_request = self.clock() + self.interval
            if response.status_code == 429:
                self.streak[model] = self.streak.get(model, 0) + 1
                delay = max(
                    60 * 2 ** min(self.streak[model] - 1, 3),
                    retry_after_seconds(response.headers.get("retry-after")),
                )
                self.next_request = max(self.next_request, self.clock() + delay)
                message = safe_error(response, kwargs.get("headers", {}))
                event = {
                    "event": "rate_limit",
                    "model": model,
                    "providers": payload.get("provider", {}).get("only", []),
                    "cooldown_seconds": delay,
                    "message": message,
                }
                self.log(event)
                print(
                    f"[Rate limit] {model}: {message}. Next API attempt waits at least "
                    f"{delay:.0f}s; completed responses remain cached.",
                    flush=True,
                )
            elif 400 <= response.status_code < 500:
                message = safe_error(response, kwargs.get("headers", {}))
                providers = payload.get("provider", {}).get("only", [])
                self.log(
                    {
                        "event": "http_rejection",
                        "status_code": response.status_code,
                        "model": model,
                        "providers": providers,
                        "message": message,
                    }
                )
                print(
                    f"[HTTP {response.status_code}] {model} via {','.join(providers)}: {message}",
                    flush=True,
                )
            elif response.is_success:
                self.streak[model] = 0
                self.completed += 1
                if self.completed % 25 == 0:
                    print(
                        f"[Pacing] {self.completed} successful HTTP responses this session "
                        "(excluding cached requests).",
                        flush=True,
                    )
            return response


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("--interval-seconds", type=float, default=6)
    options.add_argument("--timeout-seconds", type=float, default=300)
    options.add_argument("--config", default="config/pilot_budget.yaml")
    options.add_argument("--data", default="data/budget")
    options.add_argument("--run-dir", default="runs/budget")
    options.add_argument("--execute", action="store_true")
    args = options.parse_args()
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        options.error("--timeout-seconds must be finite and positive")
    directory = Path(args.run_dir)
    pacer = Pacer(args.interval_seconds, directory / "transport_events.jsonl")
    base = httpx.AsyncClient

    class PacedClient(base):
        async def post(self, url, **kwargs):
            kwargs.setdefault("timeout", args.timeout_seconds)
            return await pacer.post(super().post, url, **kwargs)

    from afrijudge.cli import main as cli_main

    previous_argv = sys.argv
    httpx.AsyncClient = PacedClient
    sys.argv = [
        "afrijudge",
        "run",
        "--config",
        args.config,
        "--data",
        args.data,
        "--run-dir",
        args.run_dir,
    ] + (["--execute"] if args.execute else [])
    if args.execute:
        pacer.log(
            {
                "event": "paced_launcher_start",
                "interval_seconds": args.interval_seconds,
                "timeout_seconds": args.timeout_seconds,
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            }
        )
    print(
        f"Paced launcher: one HTTP POST at a time; at least {args.interval_seconds:g}s "
        "between completed requests. Existing cache and budget are unchanged.",
        flush=True,
    )
    try:
        cli_main()
    finally:
        httpx.AsyncClient = base
        sys.argv = previous_argv


if __name__ == "__main__":
    main()
