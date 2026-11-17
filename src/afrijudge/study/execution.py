"""Pace model routes independently and resume through the shared SQLite ledger."""

import asyncio
import math
import sys
import time
from collections import defaultdict
from collections.abc import Callable

from afrijudge.client import RateLimitExhausted
from afrijudge.study.stimuli import Job

RATE_LIMIT_COOLDOWNS = (180,) * 8


class PacedHTTP:
    """Space POST starts independently for each pinned provider/model endpoint."""

    def __init__(self, http, interval: float):
        if not math.isfinite(interval) or interval < 0:
            raise ValueError("Invalid minimum seconds between requests")
        self.http = http
        self.interval = interval
        self.locks = defaultdict(asyncio.Lock)
        self.last = {}

    async def post(self, url, *, json, headers):
        route = json["provider"]["only"][0], json["model"]
        async with self.locks[route]:
            remaining = self.last.get(route, -self.interval) + self.interval - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)
            self.last[route] = time.monotonic()
        return await self.http.post(url, json=json, headers=headers)


async def dispatch(client, jobs: list[Job], max_tokens: int, *, progress: str) -> list:
    """Run one queue per pinned route, retaining successes when another queue fails."""
    queues = defaultdict(list)
    for position, job in enumerate(jobs):
        route = client.models[job.model]
        queues[(route["provider"], route["slug"])].append((position, job))
    results = [None] * len(jobs)
    errors = []
    completed = 0

    async def worker(route, queue):
        nonlocal completed
        for position, job in queue:
            for attempt in range(len(RATE_LIMIT_COOLDOWNS) + 1):
                try:
                    result = await client.complete(job.model, job.messages, job.meta, max_tokens)
                    results[position] = result
                    completed += 1
                    if completed % 100 == 0 or completed == len(jobs):
                        print(
                            f"[{progress}] {completed}/{len(jobs)} processed",
                            file=sys.stderr,
                            flush=True,
                        )
                    break
                except RateLimitExhausted:
                    if attempt == len(RATE_LIMIT_COOLDOWNS):
                        errors.append(f"{route[1]} via {route[0]}: rate limit exhausted")
                        return
                    wait = RATE_LIMIT_COOLDOWNS[attempt]
                    print(
                        f"[429] {route[1]} via {route[0]} cooling down for {wait}s "
                        f"({attempt + 1}/{len(RATE_LIMIT_COOLDOWNS)})",
                        file=sys.stderr,
                        flush=True,
                    )
                    await asyncio.sleep(wait)
                except Exception as exc:
                    errors.append(f"{route[1]} via {route[0]}: {exc}")
                    return

    await asyncio.gather(*(worker(route, queue) for route, queue in queues.items()))
    if errors:
        raise RuntimeError("Incomplete " + progress + "\n" + "\n".join(errors))
    return results


async def generate(client, jobs: list[Job], cap: int, validate: Callable, kind: str) -> list:
    """Retry only candidates with rejected shape or a length-truncated completion."""
    results = [None] * len(jobs)
    pending = {idx: ("", "", cap) for idx in range(len(jobs))}
    for attempt in range(4):
        by_cap = defaultdict(list)
        for idx, (error, draft, limit) in pending.items():
            job = jobs[idx]
            messages = list(job.messages)
            if attempt:
                if draft.strip():
                    messages.append({"role": "assistant", "content": draft})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Validation attempt {attempt} failed: {error} "
                        "Return a fresh, complete JSON object satisfying the original request."
                    ),
                })
            by_cap[limit].append(
                (
                    idx,
                    Job(
                        job.model,
                        messages,
                        {
                            **job.meta,
                            "generation_attempt": attempt,
                        },
                    ),
                )
            )
        pending = {}
        for limit, batch in by_cap.items():
            outputs = await dispatch(client, [job for _, job in batch], limit, progress=kind)
            for (idx, _), record in zip(batch, outputs, strict=True):
                draft = record.get("content", "")
                if record.get("finish_reason") == "length":
                    pending[idx] = ("The JSON was truncated.", draft, min(limit * 2, cap * 4))
                    continue
                try:
                    if record.get("status") != "success":
                        raise ValueError(f"Completion status {record.get('status')}")
                    results[idx] = validate(idx, draft)
                except ValueError as exc:
                    pending[idx] = (str(exc), draft, limit)
        if not pending:
            return results
    failures = [f"{jobs[idx].meta}: {error}" for idx, (error, _, _) in sorted(pending.items())]
    raise ValueError(f"{kind}: {len(pending)} drafts failed validation\n" + "\n".join(failures))
