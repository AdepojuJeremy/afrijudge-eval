"""Keep uncertain charge reservations counted while allowing generation retries."""

import argparse
import importlib.util
import json
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from afrijudge.cli import run_lock
from afrijudge.io import write_jsonl

SPEC = importlib.util.spec_from_file_location(
    "pending_inspection", Path(__file__).with_name("inspect_pending.py")
)
inspection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inspection)


def retain_and_requeue(directory: Path, pending: list[dict]) -> dict:
    """Atomic state transition. Caller must hold the run lock.

    `accounting` rows remain in Ledger.spent's SUM over all states, but are not
    completed outputs or unresolved calls. The original request ID can be retried.
    This acknowledges possible duplicate billing rather than assuming no charge.
    """
    connection = sqlite3.connect(directory / "ledger.sqlite", isolation_level=None)
    backup_path = None
    try:
        if pending:
            backup_path = directory / (
                "ledger-before-requeue-"
                + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                + "-"
                + uuid.uuid4().hex[:8]
                + ".sqlite"
            )
            with sqlite3.connect(backup_path) as backup:
                connection.backup(backup)
        connection.execute("BEGIN IMMEDIATE")
        try:
            rows = connection.execute(
                "SELECT id,amount,created FROM calls WHERE state='pending'"
            ).fetchall()
            metadata = {p["request_id"]: p for p in pending}
            if set(metadata) != {r[0] for r in rows}:
                raise ValueError("Pending rows changed; inspect again before recovery")
            if any(p["request"].get("stage") != "generation" for p in pending):
                raise ValueError("Only identified generation requests are supported")
            total_before = connection.execute("SELECT SUM(amount) FROM calls").fetchone()[0]
            for key, amount, created in rows:
                archived_id = f"uncertain-charge:{key}:{uuid.uuid4().hex}"
                record = {
                    "status": "uncertain_charge_reservation",
                    "original_request_id": key,
                    "retained_reservation_usd": amount / 1e6,
                    "reserved_at": created,
                    "requeued_at": time.time(),
                    "request": metadata[key]["request"],
                    "note": "Billing unknown; reserve retained. Retrying may incur another charge.",
                }
                cursor = connection.execute(
                    "UPDATE calls SET id=?,state='accounting',record=? "
                    "WHERE id=? AND state='pending'",
                    (archived_id, json.dumps(record), key),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Pending request changed during recovery")
            total_after = connection.execute("SELECT SUM(amount) FROM calls").fetchone()[0]
            if total_before != total_after:
                raise AssertionError("Recovery must not reduce budget accounting")
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
        return {
            "requests_requeued": len(rows),
            "uncertain_reservations_retained_usd": sum(r[1] for r in rows) / 1e6,
            "backup": str(backup_path) if backup_path else None,
            "note": "No API calls made. Successful outputs preserved. All uncertain reserves "
            "remain counted against the same run ceiling. Retries may be billed again.",
        }
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default="runs/budget")
    parser.add_argument("--data", default="data/budget")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up ledger, retain uncertain reserves, and enable retries",
    )
    args = parser.parse_args()
    directory = Path(args.run_dir)
    with run_lock(directory):
        diagnosis = inspection.inspect(directory, Path(args.data))
        if not args.apply:
            print(json.dumps(diagnosis, indent=2))
            print("Inspection only. --apply retains all uncertain reserves and enables retries.")
            return
        print(json.dumps(retain_and_requeue(directory, diagnosis["pending"]), indent=2))


if __name__ == "__main__":
    main()
