from pathlib import Path

import pytest

from afrijudge.config import load_config
from afrijudge.cost import estimate


def inputs():
    config = load_config(Path(__file__).parents[1] / "config/pilot_config.yaml")
    lock = {
        "checked_at": 1,
        "models": {
            key: {"provider": "test", "pricing": {"prompt": 0.000001, "completion": 0.000002}}
            for key in config["models"]
        },
    }
    return config, lock


def test_cost_accounts_for_every_call_and_distinguishes_assumptions():
    config, lock = inputs()
    result = estimate(config, lock)
    rows = result["scenarios"][0]["models"]
    assert sum(r["generation_calls"] for r in rows) == 1200
    assert sum(r["foil_calls"] for r in rows) == 180
    assert sum(r["judge_calls"] for r in rows) == 10440
    assert result["scenarios"][0]["estimated_inference_usd"] == pytest.approx(
        1380 * (0.0005 + 0.0007) + 10440 * (0.00065 + 0.0003)
    )
    assert (
        result["scenarios"][1]["estimated_inference_usd"]
        > result["scenarios"][0]["estimated_inference_usd"]
    )


def test_odd_reference_count_preserves_foil_assignment():
    config, lock = inputs()
    config["samples"]["traps_per_language"] = 1
    rows = estimate(config, lock)["scenarios"][0]["models"]
    assert [r["foil_calls"] for r in rows[:2]] == [4, 2]


def test_cost_rejects_invalid_assumptions_and_unhandled_price_tiers():
    config, lock = inputs()
    with pytest.raises(ValueError):
        estimate(config, lock, judge_input=-1)
    lock["models"][config["generators"][0]]["pricing"]["overrides"] = [{"min_prompt_tokens": 100}]
    with pytest.raises(ValueError, match="pricing tier"):
        estimate(config, lock)
