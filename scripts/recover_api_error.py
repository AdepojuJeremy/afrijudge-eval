"""Explicitly requeue a cached provider-error outcome while retaining its cost."""

import argparse
import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from afrijudge.cli import run_lock
from afrijudge.io import write_jsonl


def inspect_record(connection, request_id):
    row = connection.execute(
        "SELECT state,amount,record FROM calls WHERE id=?", (request_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Request ID not found; it may already have been requeued")
    state, amount, raw = row
    record = json.loads(raw) if raw else {}
    if (
        state != "done"
        or record.get("status") not in ("invalid_completion", "provider_error")
        or record.get("content") != ""
        or record.get("finish_reason") is not None
    ):
        raise ValueError(
            "Refusing to requeue a successful, filtered, truncated, or unidentified outcome"
        )
    return amount, record


def recover(directory: Path, request_id: str, apply: bool = False) -> dict:
    """Caller holds the run lock. --apply acknowledges the terminal's error ID."""
    path = directory / "ledger.sqlite"
    if not path.exists():
        raise ValueError("Run ledger does not exist")
    with sqlite3.connect(path, isolation_level=None) as connection:
        amount, record = inspect_record(connection, request_id)
        result = {
            "request_id": request_id,
            "model": record.get("model_key"),
            "provider": record.get("pinned_provider"),
            "meta": record.get("meta"),
            "cost_usd_retained": amount / 1e6,
            "applied": False,
            "note": "Only use the exact ID reported by the provider-error terminal message. "
            "Any prior charge stays counted. Retrying can incur another charge.",
        }
        if not apply:
            return result
        backup_path = directory / (
            "ledger-before-api-recovery-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
            + ".sqlite"
        )
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        connection.execute("BEGIN IMMEDIATE")
        try:
            amount, record = inspect_record(connection, request_id)
            before = connection.execute("SELECT SUM(amount) FROM calls").fetchone()[0]
            archived = {
                "status": "provider_error_charge_retained",
                "original_request_id": request_id,
                "retained_reservation_usd": amount / 1e6,
                "original_record": record,
                "requeued_at": time.time(),
                "evidence": "user-selected terminal error ID",
            }
            connection.execute(
                "UPDATE calls SET id=?,state='accounting',record=? WHERE id=? AND state='done'",
                (
                    f"provider-error:{request_id}:{uuid.uuid4().hex}",
                    json.dumps(archived),
                    request_id,
                ),
            )
            after = connection.execute("SELECT SUM(amount) FROM calls").fetchone()[0]
            if before != after:
                raise AssertionError("Recovery must preserve cost accounting")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        audit = [
            json.loads(row[0])
            for row in connection.execute(
                "SELECT record FROM calls WHERE state='accounting' ORDER BY created,id"
            )
        ]
        write_jsonl(directory / "uncertain_charges.jsonl", audit)
        result.update({"applied": True, "backup": str(backup_path), "requests_requeued": 1})
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="runs/budget")
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    directory = Path(args.run_dir)
    with run_lock(directory):
        print(json.dumps(recover(directory, args.request_id, args.apply), indent=2))


if __name__ == "__main__":
    main()
