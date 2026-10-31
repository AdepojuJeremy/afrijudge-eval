"""Read-only diagnosis of pending generation requests; no network or API key needed."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from afrijudge import prompts
from afrijudge.io import digest, read_jsonl


def generation_requests(config: dict, model_lock: dict, items: list[dict]):
    """Reconstruct the existing v0.1 payload hashes without sending requests.

    Kept outside the package to preserve unfinished runs' scientific code hashes.
    A mismatch is reported as unknown, never guessed or used to clear a charge.
    """
    for item in items:
        for key in config["generators"]:
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
                "messages": prompts.generation_messages(item),
                "max_tokens": config["generation_max_tokens"],
                "temperature": 0,
                "provider": provider,
                "usage": {"include": True},
            }
            if model.get("reasoning"):
                payload["reasoning"] = model["reasoning"]
            if "seed" in model.get("supported_parameters", []):
                payload["seed"] = config["seed"]
            meta = {
                "stage": "generation",
                "item_id": item["item_id"],
                "lang": item["lang"],
                "prompt_version": prompts.VERSION,
            }
            yield (
                digest({"payload": payload, "meta": meta}),
                {**meta, "model_key": key, "model": model["slug"], "provider": model["provider"]},
            )


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
    candidates = dict(generation_requests(manifest["config"], lock, items))
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
