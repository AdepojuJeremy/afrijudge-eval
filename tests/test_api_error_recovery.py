import importlib.util
from pathlib import Path

import pytest

from afrijudge.client import Ledger

SPEC = importlib.util.spec_from_file_location(
    "api_recovery", Path(__file__).parents[1] / "scripts/recover_api_error.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def test_api_error_recovery_is_dry_by_default_and_preserves_cost(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite", 1)
    ledger.reserve("failed", 0.004)
    record = {
        "status": "invalid_completion",
        "content": "",
        "finish_reason": None,
        "model_key": "m",
        "meta": {"stage": "judge"},
    }
    ledger.finish("failed", 0.004, record)
    ledger.reserve("valid", 0.001)
    ledger.finish("valid", 0.001, {"status": "success", "content": "saved"})
    assert not helper.recover(tmp_path, "failed")["applied"]
    assert ledger.cached("failed") == record
    result = helper.recover(tmp_path, "failed", True)
    assert result["requests_requeued"] == 1
    assert Path(result["backup"]).exists()
    assert ledger.cached("failed") is None
    assert ledger.spent == 0.005
    assert ledger.cached("valid")["content"] == "saved"
    ledger.reserve("failed", 0.004)
    assert ledger.spent == 0.009
    ledger.close()


@pytest.mark.parametrize(
    "status,content,finish",
    [
        ("success", "A", "stop"),
        ("provider_filtered", "", "content_filter"),
        ("invalid_completion", "", "length"),
        ("invalid_completion", "partial", None),
    ],
)
def test_api_recovery_refuses_other_outcomes(tmp_path, status, content, finish):
    ledger = Ledger(tmp_path / "ledger.sqlite", 1)
    ledger.reserve("x", 0.001)
    ledger.finish("x", 0.001, {"status": status, "content": content, "finish_reason": finish})
    with pytest.raises(ValueError, match="Refusing"):
        helper.recover(tmp_path, "x", True)
    assert ledger.spent == 0.001
    assert ledger.cached("x") is not None
    ledger.close()
