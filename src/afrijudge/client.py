"""Shared durable budget, payload cache, strict routing, and bounded API execution.

Reservations survive crashes. An ambiguous POST is never automatically replayed:
exactly-once billing cannot be guaranteed by an HTTP client without provider support.
"""

import asyncio
import json
import math
import sqlite3
import time
from pathlib import Path

import httpx

from afrijudge.io import digest

BASE_URL = "https://openrouter.ai/api/v1"


class BudgetExceeded(RuntimeError):
    """The next request cannot be reserved within the run's budget."""


class AmbiguousRequest(RuntimeError):
    """A request may have been billed; reconcile it before resuming."""


class Ledger:
    """SQLite transactions serialize budget reservations, including concurrent workers."""

    def __init__(self, path: Path, limit: float):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        self.limit = math.floor(limit * 1_000_000)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS calls (
            id TEXT PRIMARY KEY, state TEXT NOT NULL, amount INTEGER NOT NULL,
            record TEXT, created REAL NOT NULL)""")

    def close(self):
        self.db.close()

    @property
    def spent(self) -> float:
        return self.db.execute("SELECT COALESCE(SUM(amount),0) FROM calls").fetchone()[0] / 1e6

    def cached(self, key: str) -> dict | None:
        row = self.db.execute("SELECT state,record FROM calls WHERE id=?", (key,)).fetchone()
        if row and row[0] == "pending":
            raise AmbiguousRequest(f"Unresolved call {key}; see docs/operations.md")
        return json.loads(row[1]) if row and row[0] == "done" else None

    def reserve(self, key: str, upper_usd: float):
        amount = math.ceil(upper_usd * 1_000_000)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            used = self.db.execute("SELECT COALESCE(SUM(amount),0) FROM calls").fetchone()[0]
            if used + amount > self.limit:
                raise BudgetExceeded(
                    f"Next reservation exceeds ${self.limit / 1e6:.2f} run ceiling"
                )
            self.db.execute(
                "INSERT INTO calls VALUES (?, 'pending', ?, NULL, ?)", (key, amount, time.time())
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def release(self, key: str):
        self.db.execute("DELETE FROM calls WHERE id=? AND state='pending'", (key,))

    def finish(self, key: str, cost: float, record: dict):
        self.db.execute(
            "UPDATE calls SET state='done',amount=?,record=? WHERE id=?",
            (math.ceil(cost * 1e6), json.dumps(record, ensure_ascii=False), key),
        )

    def records(self) -> list[dict]:
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT record FROM calls WHERE state='done' ORDER BY created,id"
            )
        ]

    def unresolved(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT id FROM calls WHERE state='pending'")]


async def catalog(http: httpx.AsyncClient, config: dict) -> dict:
    """Check IDs and select a reproducible provider endpoint before any paid POST.

    Catalog membership alone does not guarantee endpoint availability or key access.
    Pin an endpoint from /endpoints; never remove precision restrictions on failure.
    """
    response = await http.get(f"{BASE_URL}/models")
    response.raise_for_status()
    live = {m["id"]: m for m in response.json()["data"]}
    selected = {}
    for key in dict.fromkeys(config["generators"] + config["judges"]):
        model = config["models"][key]
        slug = model["slug"]
        if slug not in live:
            raise ValueError(f"Unavailable model: {key} ({slug}); explicitly edit config")
        response = await http.get(f"{BASE_URL}/models/{slug}/endpoints")
        response.raise_for_status()
        endpoints = response.json()["data"]["endpoints"]
        candidates = []
        for endpoint in endpoints:
            if "/flex" in endpoint.get("tag", "") and not model.get("provider"):
                continue
            if (
                model.get("quantizations")
                and endpoint.get("quantization") not in model["quantizations"]
            ):
                continue
            if model.get("reasoning") and "reasoning" not in endpoint.get(
                "supported_parameters", []
            ):
                continue
            if model.get("provider") and endpoint.get("tag") != model["provider"]:
                continue
            pricing = endpoint.get("pricing", {})
            # Text-only requests must have bounded ordinary token pricing.
            if not endpoint.get("tag") or not {"prompt", "completion"} <= pricing.keys():
                continue
            pin, pout = float(pricing["prompt"]), float(pricing["completion"])
            # Image/search rates are irrelevant to text-only requests without tools.
            extra = [float(pricing.get("request", 0) or 0)]
            if any(extra) or not all(math.isfinite(p) and p >= 0 for p in (pin, pout)):
                continue
            candidates.append((pin + pout, endpoint))
        if not candidates:
            raise ValueError(
                f"No eligible priced endpoint for {slug}; inspect precision/provider config"
            )
        endpoint = min(candidates, key=lambda x: (x[0], x[1]["tag"]))[1]
        selected[key] = {
            **model,
            "provider": endpoint["tag"],
            "quantization": endpoint.get("quantization"),
            "pricing": endpoint["pricing"],
            "context_length": endpoint.get("context_length"),
            "max_completion_tokens": endpoint.get("max_completion_tokens"),
            "supported_parameters": endpoint.get("supported_parameters", []),
        }
    return {"checked_at": time.time(), "models": selected}


class Client:
    def __init__(
        self, http: httpx.AsyncClient, ledger: Ledger, config: dict, lock: dict, api_key: str
    ):
        self.http, self.ledger, self.config = http, ledger, config
        self.models, self.api_key = lock["models"], api_key
        self.semaphore = asyncio.Semaphore(config["concurrency"])

    async def complete(
        self, model_key: str, messages: list[dict], meta: dict, max_tokens: int
    ) -> dict:
        model = self.models[model_key]
        pin, pout = float(model["pricing"]["prompt"]), float(model["pricing"]["completion"])
        provider = {
            "only": [model["provider"]],
            "allow_fallbacks": False,
            "max_price": {"prompt": pin * 1e6, "completion": pout * 1e6},
        }
        if model.get("quantizations"):
            provider["quantizations"] = [model.get("quantization") or model["quantizations"][0]]
        payload = {
            "model": model["slug"],
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "provider": provider,
            "usage": {"include": True},
        }
        if model.get("reasoning"):
            payload["reasoning"] = model["reasoning"]
        if "seed" in model.get("supported_parameters", []):
            payload["seed"] = self.config["seed"]
        key = digest({"payload": payload, "meta": meta})
        async with self.semaphore:
            cached = self.ledger.cached(key)
            if cached:
                if cached.get("status") == "provider_error":
                    raise RuntimeError(f"Cached provider error for {key}; inspect local ledger")
                return cached
            # UTF-8 bytes plus generous chat framing is a conservative proxy, not a tokenizer.
            input_bound = sum(len(m["content"].encode()) + 256 for m in messages)
            if model.get("context_length") and input_bound + max_tokens > model["context_length"]:
                raise ValueError(f"Conservative context bound exceeded for {model_key}")
            if model.get("max_completion_tokens") and max_tokens > model["max_completion_tokens"]:
                raise ValueError(f"Output limit exceeded for {model_key}")
            upper = (input_bound * pin + max_tokens * pout) * 1.10 + 0.000001
            self.ledger.reserve(key, upper)
            for attempt in range(4):
                try:
                    response = await self.http.post(
                        f"{BASE_URL}/chat/completions",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "HTTP-Referer": "https://github.com/AdepojuJeremy/afrijudge-eval",
                            "X-OpenRouter-Title": "AfriJudge-Eval",
                        },
                    )
                except httpx.TransportError:
                    raise AmbiguousRequest(
                        f"Transport failure for {key}; reservation retained"
                    ) from None
                if response.status_code == 429:
                    if attempt < 3:
                        try:
                            delay = float(response.headers.get("retry-after", 2**attempt))
                        except ValueError:
                            delay = 2**attempt
                        await asyncio.sleep(min(max(delay, 0), 30))
                        continue
                    self.ledger.release(key)
                    raise RuntimeError("Rate limit exhausted; retry this run later")
                if 400 <= response.status_code < 500:
                    self.ledger.release(key)
                    raise RuntimeError(
                        f"OpenRouter rejected {model_key}: HTTP {response.status_code}"
                    )
                if response.status_code >= 500:
                    raise AmbiguousRequest(f"Server failure for {key}; reservation retained")
                try:
                    data = response.json()
                    usage = data.get("usage", {})
                    reported_cost = usage.get("cost")
                    cost = float(reported_cost) if reported_cost is not None else upper
                    if not math.isfinite(cost) or cost < 0:
                        raise ValueError("Invalid billing data")
                    choice = (data.get("choices") or [{}])[0]
                    text = choice.get("message", {}).get("content")
                    status = (
                        "success"
                        if isinstance(text, str)
                        and text.strip()
                        and choice.get("finish_reason") == "stop"
                        else "invalid_completion"
                    )
                    record = {
                        "request_id": key,
                        "meta": meta,
                        "model_key": model_key,
                        "requested_model": model["slug"],
                        "returned_model": data.get("model"),
                        "provider": data.get("provider"),
                        "pinned_provider": model["provider"],
                        "generation_id": data.get("id"),
                        "system_fingerprint": data.get("system_fingerprint"),
                        "timestamp": time.time(),
                        "usage": usage,
                        "cost_usd": cost,
                        "cost_source": "reported"
                        if reported_cost is not None
                        else "reservation_estimate",
                        "finish_reason": choice.get("finish_reason"),
                        "status": "provider_error" if "error" in data else status,
                        "content": text if isinstance(text, str) else "",
                    }
                    self.ledger.finish(key, cost, record)
                except (ValueError, TypeError, KeyError, IndexError):
                    raise AmbiguousRequest(
                        f"Malformed response for {key}; reservation retained"
                    ) from None
                if "error" in data:
                    raise RuntimeError(
                        f"Provider returned an error for {key}; inspect local ledger"
                    )
                if cost > upper:
                    raise BudgetExceeded(
                        "Reported charge exceeds reservation; stop and audit pricing"
                    )
                return record
        raise AssertionError("Unreachable")


async def bounded_map(function, jobs: list, concurrency: int) -> list:
    """Bound both scheduled tasks and network requests; drain workers on failure."""
    iterator = iter(enumerate(jobs))
    result = [None] * len(jobs)
    errors = []

    async def worker():
        for index, job in iterator:
            if errors:
                return
            try:
                result[index] = await function(job)
            except Exception as exc:
                errors.append(exc)
                return

    workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(jobs)))]
    await asyncio.gather(*workers)
    if errors:
        raise errors[0]
    return result
