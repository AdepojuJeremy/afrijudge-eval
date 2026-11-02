"""A separately accounted format diagnostic on saved pairs, dry-run by default.

No generation, foil creation, data editing or hypothesis tests occur here.
Actual paid validation requires --execute and the user's local API key.
"""

import asyncio
import json
import math
import os
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from afrijudge.client import Client, Ledger
from afrijudge.io import digest, read_jsonl, write_json, write_jsonl
from afrijudge.judge_v2 import PROTOCOL, messages, parse_record
from afrijudge.text import reconcile


def select_pairs(pairs: list[dict], config: dict, count: int) -> list[dict]:
    if not 1 <= count <= 10:
        raise ValueError("Format diagnostic supports 1 to 10 comparisons")
    pools = {}
    for lang in config["languages"]:
        pool = [
            p
            for p in pairs
            if p["experiment"] == "exp1"
            and p["lang"] == lang
            and p["item_id"] not in config.get("excluded_source_items", [])
        ]
        # Sorting before seeded shuffling makes selection independent of input order.
        pool.sort(key=lambda p: p["pair_id"])
        random.Random(f"format-v2:{config['seed']}:{lang}").shuffle(pool)
        pools[lang] = pool
    selected = []
    while len(selected) < count:
        before = len(selected)
        for lang in config["languages"]:
            if pools[lang] and len(selected) < count:
                selected.append(pools[lang].pop())
        if len(selected) == before:
            raise ValueError("Insufficient saved baseline comparisons after exclusions")
    return selected


def source_spend(directory: Path) -> float:
    """Read accounting including uncertain reserves without modifying the pilot DB."""
    path = directory / "ledger.sqlite"
    if not path.is_file():
        raise ValueError("Paid validation requires the original ledger.sqlite for accounting")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return db.execute("SELECT COALESCE(SUM(amount),0) FROM calls").fetchone()[0] / 1e6


def summarize(records: list[dict], pairs: list[dict], judges: list[str]) -> dict:
    by_group = defaultdict(Counter)
    lookup = {}
    pair_lookup = {p["pair_id"]: p for p in pairs}
    for r in records:
        p = pair_lookup[r["meta"]["pair_id"]]
        vote, diagnostic = parse_record(r)
        key = r["model_key"], p["lang"]
        by_group[key]["calls"] += 1
        by_group[key][diagnostic] += 1
        lookup[p["pair_id"], r["model_key"], r["meta"]["order"]] = vote
    reconciled = Counter(
        reconcile(
            lookup.get((p["pair_id"], j, "AB"), "INVALID"),
            lookup.get((p["pair_id"], j, "BA"), "INVALID"),
        )
        for p in pairs
        for j in judges
    )
    return {
        "status": "format_diagnostic_not_hypothesis_test",
        "planned_calls": len(pairs) * len(judges) * 2,
        "completed_response_records": len(records),
        "groups": [
            {"judge": j, "lang": lang, **dict(c)} for (j, lang), c in sorted(by_group.items())
        ],
        "reconciled_counts": dict(reconciled),
        "warning": "Zero observed failures in this small repeated-item sample would not "
        "prove reliability. "
        "This diagnostic does not validate semantics, rubrics, accuracy or novelty.",
    }


async def validate(args, config: dict):
    from afrijudge.cli import code_hash, run_lock

    if config.get("judge_protocol") != PROTOCOL:
        raise ValueError("Use the opt-in v2 configuration for format validation")
    source, target = Path(args.source_run), Path(args.run_dir)
    if target.resolve() == source.resolve() or source.resolve() in target.resolve().parents:
        raise ValueError("Use a separate validation directory outside the original pilot")
    if not 0 < args.max_spend_usd <= 1:
        raise ValueError("Validation spend limit must be positive and at most $1")
    if not math.isfinite(args.interval_seconds) or args.interval_seconds < 6:
        raise ValueError("Use at least six seconds between format requests")
    pairs = select_pairs(read_jsonl(source / "pairs.jsonl"), config, args.items)
    lock = json.loads((source / "models.lock.json").read_text())
    for j in config["judges"]:
        if lock["models"][j]["slug"] != config["models"][j]["slug"]:
            raise ValueError("Model panel differs from frozen source-run endpoints")
    plan = {
        "protocol": PROTOCOL,
        "comparisons": len(pairs),
        "judge_calls": len(pairs) * len(config["judges"]) * 2,
        "generation_calls": 0,
        "foil_calls": 0,
        "pair_ids": [p["pair_id"] for p in pairs],
        "maximum_new_run_spend_usd": args.max_spend_usd,
        "note": "Planning only; uses frozen model routes. Execution also checks the source ledger. "
        "Budget ceiling is a stopping limit, not a completion quote.",
    }
    if not args.execute:
        print(json.dumps(plan, indent=2))
        return plan
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ValueError("Set OPENROUTER_API_KEY locally; never put it in config")
    # Lock both runs to prevent this diagnostic racing the source pilot process.
    with run_lock(source), run_lock(target):
        source_manifest = json.loads((source / "manifest.json").read_text())
        ceiling = source_manifest["config"]["budget_limit_usd"]
        spent = source_spend(source)
        remaining = ceiling - spent
        if remaining <= 0:
            raise ValueError("No configuration headroom remains in the original pilot ceiling")
        limit = min(args.max_spend_usd, remaining)
        identity = {
            "config_hash": config["config_hash"],
            "pairs_hash": digest(pairs),
            "lock_hash": digest(lock),
            "protocol": PROTOCOL,
            "max_spend_usd": args.max_spend_usd,
            "code_hash": code_hash(),
        }
        manifest_path = target / "manifest.json"
        if manifest_path.exists():
            prior = json.loads(manifest_path.read_text())
            if prior["identity"] != identity:
                raise ValueError("Validation configuration changed; use a new validation directory")
        else:
            if any(p.name != ".lock" for p in target.iterdir()):
                raise ValueError("Validation requires a new empty directory")
            write_json(
                manifest_path,
                {
                    "identity": identity,
                    "source_spend_snapshot_usd": spent,
                    "source_config_ceiling_usd": ceiling,
                    "validation_limit_usd": limit,
                },
            )
        write_jsonl(target / "pairs.jsonl", pairs)
        write_json(target / "models.lock.json", lock)
        ledger = Ledger(target / "ledger.sqlite", limit)
        try:
            if ledger.unresolved():
                raise RuntimeError(
                    "Potentially billed validation request remains unresolved; "
                    "inspect its ledger before any retry"
                )
            cfg = {**config, "concurrency": 1}
            async with httpx.AsyncClient(timeout=600, follow_redirects=False) as http:
                client = Client(http, ledger, cfg, lock, key)
                completed = {r["request_id"] for r in ledger.records()}
                for p in pairs:
                    for j in config["judges"]:
                        for order in ("AB", "BA"):
                            record = await client.complete(
                                j,
                                messages(p, order),
                                {
                                    "stage": "judge",
                                    "pair_id": p["pair_id"],
                                    "order": order,
                                    "prompt_version": "2",
                                    "purpose": "format_validation_only",
                                },
                                config["judge_max_tokens"],
                            )
                            if record["request_id"] not in completed:
                                completed.add(record["request_id"])
                                await asyncio.sleep(args.interval_seconds)
            report = summarize(ledger.records(), pairs, config["judges"])
            report["spent_or_reserved_usd"] = ledger.spent
            write_json(target / "format_report.json", report)
            print(json.dumps(report, indent=2))
            return report
        finally:
            write_jsonl(target / "requests.jsonl", ledger.records())
            ledger.close()
