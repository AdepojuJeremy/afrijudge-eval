"""Inspect or requeue one identified format request while retaining its reservation."""

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from inspect_pending import request_identity
from requeue_pending import retain_and_requeue

from afrijudge.cli import code_hash, run_lock
from afrijudge.config import load_config
from afrijudge.io import digest, read_jsonl
from afrijudge.judge_v2 import PROTOCOL, VERSION, messages


def recover(directory: Path, config: dict, request_id: str, apply: bool = False) -> dict:
    with run_lock(directory):
        identity = json.loads((directory / "manifest.json").read_text())["identity"]
        pairs = read_jsonl(directory / "pairs.jsonl")
        lock = json.loads((directory / "models.lock.json").read_text())
        expected = {
            "protocol": PROTOCOL,
            "config_hash": config["config_hash"],
            "code_hash": code_hash(),
            "pairs_hash": digest(pairs),
            "lock_hash": digest(lock),
        }
        if any(identity.get(k) != v for k, v in expected.items()):
            raise ValueError("Format manifest, configuration or saved inputs do not match")
        uri = (directory / "ledger.sqlite").resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            pending = connection.execute(
                "SELECT id,amount,created FROM calls WHERE state='pending'"
            ).fetchall()
        finally:
            connection.close()
        if len(pending) != 1 or pending[0][0] != request_id:
            raise ValueError("Expected exactly one pending request matching the supplied ID")
        for pair in pairs:
            for model in config["judges"]:
                for order in ("AB", "BA"):
                    meta = {
                        "stage": "judge",
                        "pair_id": pair["pair_id"],
                        "order": order,
                        "prompt_version": VERSION,
                        "purpose": "format_validation_only",
                    }
                    key, detail = request_identity(
                        config, lock, model, messages(pair, order), meta, config["judge_max_tokens"]
                    )
                    if key == request_id:
                        _, amount, created = pending[0]
                        result = {
                            "request_id": key,
                            "request": detail,
                            "reserved_usd": amount / 1e6,
                            "reserved_at": datetime.fromtimestamp(created, UTC).isoformat(),
                        }
                        if apply:
                            result.update(retain_and_requeue(directory, [result]))
                        return result
        raise ValueError("Pending request does not match any frozen format payload")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="runs/format-v2")
    parser.add_argument("--config", default="config/pilot_revision_v2.yaml")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--apply", action="store_true", help="Retain reserve and enable retry")
    args = parser.parse_args()
    try:
        result = recover(Path(args.run_dir), load_config(args.config), args.request_id, args.apply)
    except (ValueError, OSError, KeyError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
