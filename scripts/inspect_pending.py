"""Read-only diagnosis of pending experiment requests; no network or API key needed."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from afrijudge import prompts
from afrijudge.io import digest, read_jsonl


def request_identity(config, model_lock, key, messages, meta, max_tokens):
    """Reconstruct the exact payload hash; this never sends a request."""
    model = model_lock["models"][key]
    pin = float(model["pricing"]["prompt"])
    pout = float(model["pricing"]["completion"])
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
        payload["seed"] = config["seed"]
    return digest({"payload": payload, "meta": meta}), {
        **meta,
        "model_key": key,
        "model": model["slug"],
        "provider": model["provider"],
    }


def generation_requests(config: dict, model_lock: dict, items: list[dict]):
    for item in items:
        for key in config["generators"]:
            meta = {
                "stage": "generation",
                "item_id": item["item_id"],
                "lang": item["lang"],
                "prompt_version": prompts.VERSION,
            }
            yield request_identity(
                config,
                model_lock,
                key,
                prompts.generation_messages(item),
                meta,
                config["generation_max_tokens"],
            )


def foil_requests(config: dict, model_lock: dict, items: list[dict]):
    foil_keys = config["generators"][:2]
    for index, item in enumerate(items):
        key = foil_keys[index % len(foil_keys)]
        for condition in ("plain_error", "styled_error"):
            meta = {
                "stage": "foil",
                "item_id": item["item_id"],
                "lang": item["lang"],
                "condition": condition,
                "prompt_version": prompts.VERSION,
            }
            yield request_identity(
                config,
                model_lock,
                key,
                prompts.foil_messages(item, condition),
                meta,
                config["generation_max_tokens"],
            )


def judge_requests(config: dict, model_lock: dict, pairs: list[dict]):
    for pair in pairs:
        for key in config["judges"]:
            for order in ("AB", "BA"):
                meta = {
                    "stage": "judge",
                    "pair_id": pair["pair_id"],
                    "order": order,
                    "prompt_version": prompts.judge_version(config),
                }
                request_id, details = request_identity(
                    config,
                    model_lock,
                    key,
                    prompts.judge_messages(pair, order, config.get("judge_protocol", "v1")),
                    meta,
                    config["judge_max_tokens"],
                )
                yield request_id, {**details, "lang": pair["lang"], "item_id": pair["item_id"]}


def inspect(directory: Path, data_dir: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    lock = json.loads((directory / "models.lock.json").read_text())
    data_manifest = json.loads((data_dir / "manifest.json").read_text())
    if digest(lock) != manifest["model_lock_hash"]:
        raise ValueError("Model lock hash mismatch; cannot identify requests reliably")
    if digest(data_manifest) != manifest["identity"]["data_hash"]:
        raise ValueError("Data manifest mismatch")
    items = read_jsonl(data_dir / "exp1.jsonl")
    if digest(items) != data_manifest["hashes"]["exp1.jsonl"]:
        raise ValueError("Generation inputs changed")
    config = manifest["config"]
    candidates = dict(generation_requests(config, lock, items))
    translations = read_jsonl(data_dir / "exp2.jsonl")
    if digest(translations) != data_manifest["hashes"]["exp2.jsonl"]:
        raise ValueError("Translation inputs changed")
    candidates.update(foil_requests(config, lock, translations))
    pairs_path = directory / "pairs.jsonl"
    if pairs_path.exists():
        pairs = read_jsonl(pairs_path)
        artifacts_path = directory / "artifacts.json"
        if artifacts_path.exists():
            expected = json.loads(artifacts_path.read_text())["pairs.jsonl"]
            if digest(pairs) != expected:
                raise ValueError("Pair inputs changed")
        candidates.update(judge_requests(config, lock, pairs))
    connection = sqlite3.connect(
        (directory / "ledger.sqlite").resolve().as_uri() + "?mode=ro", uri=True
    )
    try:
        rows = connection.execute(
            "SELECT id,amount,created FROM calls WHERE state='pending'"
        ).fetchall()
        completed = connection.execute("SELECT COUNT(*) FROM calls WHERE state='done'").fetchone()[
            0
        ]
        done_cost = connection.execute(
            "SELECT COALESCE(SUM(amount),0) FROM calls WHERE state='done'"
        ).fetchone()[0]
    finally:
        connection.close()
    return {
        "completed_requests": completed,
        "completed_accounted_usd": done_cost / 1e6,
        "pending": [
            {
                "request_id": key,
                "reserved_usd": amount / 1e6,
                "reserved_at_lagos": datetime.fromtimestamp(created, UTC)
                .astimezone(ZoneInfo("Africa/Lagos"))
                .isoformat(),
                "request": candidates.get(key, {"stage": "unknown_not_matched"}),
            }
            for key, amount, created in rows
        ],
        "note": "Read-only. Reservation time can precede actual sending. A pending row does "
        "not establish whether the provider billed it. No charge or reservation was changed.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="runs/budget")
    parser.add_argument("--data", default="data/budget")
    args = parser.parse_args()
    print(json.dumps(inspect(Path(args.run_dir), Path(args.data)), indent=2))


if __name__ == "__main__":
    main()
