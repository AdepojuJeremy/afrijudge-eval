"""Resume an existing run with slower HTTP pacing and unchanged scientific inputs.

This launcher intentionally lives outside src/afrijudge: existing run code hashes
and cached payloads remain valid. It changes scheduling only, not model requests,
provider selection, or budget accounting. Rate-limit retry batches are bounded.
"""

import argparse
import asyncio
import contextvars
import hashlib
import json
import math
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

FILTER_EVENT = contextvars.ContextVar("provider_filter_event", default=None)
API_ERROR_EVENT = contextvars.ContextVar("provider_api_error", default=None)


def retry_rate_limits(original, cycles=8, delay=180, sleep=None, log=None):
    """Retry only explicit, exhausted HTTP-429 batches after their reserve is released.

    Transport failures, API error envelopes, budget errors, and cached provider
    errors remain fatal. Never change the payload, provider, or scientific config.
    """
    if type(cycles) is not int or not 1 <= cycles <= 16:
        raise ValueError("Rate-limit cycles must be an integer from 1 to 16")
    if not math.isfinite(delay) or delay < 0:
        raise ValueError("Retry delay must be finite and nonnegative")
    wait = sleep or asyncio.sleep

    async def complete(client, model_key, messages, meta, max_tokens):
        for cycle in range(cycles):
            try:
                return await original(client, model_key, messages, meta, max_tokens)
            except RuntimeError as exc:
                if str(exc) != "Rate limit exhausted; retry this run later" or cycle == cycles - 1:
                    raise
                event = {
                    "event": "rate_limit_batch_retry",
                    "model_key": model_key,
                    "completed_batch": cycle + 1,
                    "maximum_batches": cycles,
                    "cooldown_seconds": delay,
                    "meta": meta,
                }
                if log:
                    log(event)
                print(
                    f"[Automatic retry] {model_key}: rate-limit batch {cycle + 1}/{cycles} "
                    f"exhausted. Waiting {delay:g}s before the next batch; saved work reused.",
                    flush=True,
                )
                await wait(delay)
        raise AssertionError("Unreachable")

    return complete


def has_api_error(response: httpx.Response) -> bool:
    if not response.is_success:
        return False
    try:
        body = response.json()
        return isinstance(body, dict) and "error" in body
    except ValueError:
        return False


def is_content_filter(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        error = response.json().get("error", {})
        if not isinstance(error, dict):
            return False
        codes = [error.get("code")]
        metadata = error.get("metadata") or {}
        raw = metadata.get("raw") if isinstance(metadata, dict) else None
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict):
            detail = raw.get("error", raw)
            if isinstance(detail, dict):
                codes.append(detail.get("code"))
        return any(str(code).lower() == "content_filter" for code in codes)
    except (ValueError, AttributeError):
        return False


def filter_aware_completion(original):
    """Record an actual filter rejection as missing; never synthesize an answer."""

    async def complete(client, model_key, messages, meta, max_tokens):
        token = FILTER_EVENT.set(None)
        api_token = API_ERROR_EVENT.set(None)
        try:
            record = await original(client, model_key, messages, meta, max_tokens)
            if record.get("status") == "provider_error":
                raise RuntimeError(
                    f"Cached provider error for {record['request_id']}; recover it before resuming"
                )
            return record
        except RuntimeError as exc:
            api_error = API_ERROR_EVENT.get()
            match = re.fullmatch(
                r"Provider returned an error for ([0-9a-f]{64}); inspect local ledger", str(exc)
            )
            if api_error and match:
                key = match[1]
                record = client.ledger.cached(key)
                if record:
                    record.update({"status": "provider_error", "provider_error": api_error})
                    client.ledger.finish(key, record["cost_usd"], record)
                raise
            event = FILTER_EVENT.get()
            if not event or str(exc) != f"OpenRouter rejected {model_key}: HTTP 400":
                raise
            from afrijudge.io import digest

            # The ordinary client has released the clear HTTP 400 reservation.
            # Retain a conservative estimate instead of assuming zero billing.
            payload = event["payload"]
            key = digest({"payload": payload, "meta": meta})
            model = client.models[model_key]
            input_bound = sum(len(m["content"].encode()) + 256 for m in messages)
            cost = (
                input_bound * float(model["pricing"]["prompt"])
                + max_tokens * float(model["pricing"]["completion"])
            ) * 1.10 + 0.000001
            record = {
                "request_id": key,
                "meta": meta,
                "model_key": model_key,
                "requested_model": model["slug"],
                "returned_model": None,
                "provider": model["provider"],
                "pinned_provider": model["provider"],
                "generation_id": None,
                "timestamp": time.time(),
                "usage": {},
                "status": "provider_filtered",
                "http_status": 400,
                "finish_reason": "content_filter",
                "content": "",
                "cost_usd": cost,
                "cost_source": "reservation_estimate",
                "error_message": event["message"],
            }
            client.ledger.reserve(key, cost)
            client.ledger.finish(key, cost, record)
            print(
                f"[Filtered] {model_key}: saved as missing; continuing without "
                "editing the prompt or changing provider.",
                flush=True,
            )
            return record
        finally:
            FILTER_EVENT.reset(token)
            API_ERROR_EVENT.reset(api_token)

    return complete


def write_filter_summary(directory: Path):
    from afrijudge.io import write_json

    path = directory / "ledger.sqlite"
    if not path.exists():
        return
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        records = [
            json.loads(r[0])
            for r in connection.execute(
                "SELECT record FROM calls WHERE state='done' AND record IS NOT NULL"
            )
        ]
    groups = {}
    for record in records:
        meta = record.get("meta", {})
        key = (
            meta.get("stage", "unknown"),
            record.get("model_key", "unknown"),
            meta.get("lang", "see_pair_id"),
        )
        group = groups.setdefault(
            key,
            {
                "stage": key[0],
                "model": key[1],
                "lang": key[2],
                "recorded_outcomes": 0,
                "provider_filtered": 0,
            },
        )
        group["recorded_outcomes"] += 1
        group["provider_filtered"] += int(record.get("finish_reason") == "content_filter")
    summary = {
        "groups": list(groups.values()),
        "filtered_requests": [
            {
                "request_id": r["request_id"],
                "model": r.get("model_key"),
                "meta": r.get("meta"),
                "http_status": r.get("http_status"),
                "error_message": r.get("error_message"),
            }
            for r in records
            if r.get("finish_reason") == "content_filter"
        ],
        "note": "Filtered responses are missing outputs, not incorrect generated answers. "
        "Their conservative cost estimates remain counted; prompt and route are unchanged. "
        "Report coverage/selection effects alongside correctness results.",
    }
    write_json(directory / "provider_filter_summary.json", summary)
    report_path = directory / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text())
        report["provider_filter_summary"] = summary
        write_json(report_path, report)


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
                if is_content_filter(response):
                    FILTER_EVENT.set({"payload": payload, "message": message})
            elif has_api_error(response):
                message = safe_error(response, kwargs.get("headers", {}))
                event = {
                    "event": "provider_error",
                    "http_status": response.status_code,
                    "model": model,
                    "providers": payload.get("provider", {}).get("only", []),
                    "message": message,
                }
                self.log(event)
                API_ERROR_EVENT.set(event)
                print(f"[Provider error] {model}: {message}", flush=True)
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
    options.add_argument("--rate-limit-cycles", type=int, default=8)
    options.add_argument("--retry-delay-seconds", type=float, default=180)
    options.add_argument("--config", default="config/pilot_budget.yaml")
    options.add_argument("--data", default="data/budget")
    options.add_argument("--run-dir", default="runs/budget")
    options.add_argument("--execute", action="store_true")
    args = options.parse_args()
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        options.error("--timeout-seconds must be finite and positive")
    if not 1 <= args.rate_limit_cycles <= 16:
        options.error("--rate-limit-cycles must be between 1 and 16")
    if not math.isfinite(args.retry_delay_seconds) or args.retry_delay_seconds < 30:
        options.error("--retry-delay-seconds must be finite and at least 30")
    directory = Path(args.run_dir)
    pacer = Pacer(args.interval_seconds, directory / "transport_events.jsonl")
    base = httpx.AsyncClient

    class PacedClient(base):
        async def post(self, url, **kwargs):
            kwargs.setdefault("timeout", args.timeout_seconds)
            return await pacer.post(super().post, url, **kwargs)

    from afrijudge.cli import main as cli_main
    from afrijudge.client import Client

    previous_argv = sys.argv
    original_complete = Client.complete
    Client.complete = retry_rate_limits(
        filter_aware_completion(original_complete),
        cycles=args.rate_limit_cycles,
        delay=args.retry_delay_seconds,
        log=pacer.log,
    )
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
                "rate_limit_cycles": args.rate_limit_cycles,
                "retry_delay_seconds": args.retry_delay_seconds,
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
        Client.complete = original_complete
        sys.argv = previous_argv
        if args.execute:
            write_filter_summary(directory)


if __name__ == "__main__":
    main()
