import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from afrijudge.client import BudgetExceeded, Ledger

SPEC = importlib.util.spec_from_file_location(
    "requeue_pending", Path(__file__).parents[1] / "scripts/requeue_pending.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def test_requeue_preserves_budget_successes_and_backup(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite", 0.01)
    ledger.reserve("done", 0.001)
    ledger.finish("done", 0.001, {"content": "saved response"})
    ledger.reserve("unknown", 0.004)
    before = ledger.spent
    pending = [{"request_id": "unknown", "request": {"stage": "generation", "model": "test"}}]
    result = helper.retain_and_requeue(tmp_path, pending)
    assert ledger.spent == before
    assert ledger.unresolved() == []
    assert ledger.cached("unknown") is None
    assert ledger.cached("done") == {"content": "saved response"}
    assert len(ledger.records()) == 1  # Accounting is not a generated response.
    with sqlite3.connect(result["backup"]) as backup:
        assert (
            backup.execute("SELECT state FROM calls WHERE id='unknown'").fetchone()[0] == "pending"
        )
    ledger.reserve("unknown", 0.004)
    assert ledger.spent == 0.009
    with pytest.raises(BudgetExceeded):
        ledger.reserve("too-much", 0.002)
    ledger.close()
    audit = [
        json.loads(line) for line in (tmp_path / "uncertain_charges.jsonl").read_text().splitlines()
    ]
    assert audit[0]["original_request_id"] == "unknown"
    assert audit[0]["retained_reservation_usd"] == 0.004


def test_requeue_no_pending_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite", 1)
    assert helper.retain_and_requeue(tmp_path, [])["requests_requeued"] == 0
    assert ledger.spent == 0
    ledger.close()


@pytest.mark.parametrize("pending", [[], [{"request_id": "x", "request": {"stage": "unknown"}}]])
def test_unknown_or_changed_requests_fail_without_losing_reserve(tmp_path, pending):
    ledger = Ledger(tmp_path / "ledger.sqlite", 1)
    ledger.reserve("x", 0.004)
    with pytest.raises(ValueError):
        helper.retain_and_requeue(tmp_path, pending)
    assert ledger.unresolved() == ["x"]
    assert ledger.spent == 0.004
    ledger.close()
