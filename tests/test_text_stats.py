import numpy as np
import pytest

from afrijudge.stats import (
    agreement,
    cluster_ci,
    cross_validated_calibration,
    error_dependence,
    validity,
)
from afrijudge.text import answer, reconcile, strip_marks, verdict


@pytest.mark.parametrize(
    "text,task,expected",
    [
        ("<answer>B</answer>", "mmlu", "B"),
        ("Reasoning 12. <answer>1,200.0</answer>", "mgsm", "1.2E+3"),
        ("The answer might be B or C", "mmlu", None),
        ("<answer>A</answer><answer>B</answer>", "mmlu", None),
        ("<answer>1,2</answer>", "mgsm", None),
        ("<answer>NaN</answer>", "mgsm", None),
        ("<answer>Infinity</answer>", "mgsm", None),
        ("<answer>AB</answer>", "mmlu", None),
    ],
)
def test_answer_is_conservative(text, task, expected):
    assert answer(text, task) == expected


def test_verdict_no_regex_guess():
    assert verdict('```json\n{"verdict":"A"}\n```') == "A"
    assert verdict('I choose A. {"verdict":"B"}') == "INVALID"
    assert verdict('{"verdict":"C"}') == "INVALID"


def test_swapped_orders_and_explicit_ties_are_distinct():
    assert reconcile("A", "B") == "A"
    assert reconcile("A", "A") == "ORDER_UNSTABLE"
    assert reconcile("TIE", "A") == "ORDER_UNSTABLE"
    assert reconcile("TIE", "TIE") == "TIE"
    assert reconcile("A", "INVALID") == "INVALID"


def test_unicode_composed_decomposed_match():
    assert strip_marks("ẹ́ ọ̀ ṣ ị́ Ọ́") == "e o s i O"


def test_six_judge_tie_is_not_correct_or_unanimous():
    matrix = np.array([["A"] * 3 + ["B"] * 3, ["B"] * 6, ["A"] * 6])
    result = validity(matrix, ["A"] * 3, ["i1", "i2", "i3"], 42)
    assert result["panel_accuracy_all_pairs"] == pytest.approx(1 / 3)
    assert result["panel_decision_coverage"] == pytest.approx(2 / 3)
    assert result["unanimous_error_rate"] == 0.5
    assert result["unanimous_pairs"] == 2


def test_invalid_and_quality_tie_are_not_false_consensus():
    matrix = np.array([["TIE"] * 6, ["INVALID"] * 6])
    result = validity(matrix, ["A"] * 2, ["1", "2"], 0)
    assert result["false_supermajority_rate_all_pairs"] == 0
    assert result["panel_accuracy_all_pairs"] == 0
    assert result["unanimous_error_rate"] is None


def test_undefined_correlations_are_not_independence():
    out = error_dependence(np.zeros((20, 6)))
    assert out["mean_defined_error_phi"] is None
    assert out["effective_votes_exchangeable_approx"] is None


def test_negative_error_correlation_is_retained():
    result = error_dependence(np.array([[0, 1], [1, 0], [0, 1], [1, 0]]))
    assert result["mean_defined_error_phi"] == pytest.approx(-1)
    assert result["effective_votes_exchangeable_approx"] is None


def test_agreement_degenerate_and_hand_computed():
    assert agreement(np.array([["A"] * 3] * 4))["fleiss_kappa"] is None
    result = agreement(np.array([["A", "A", "B"], ["B", "B", "A"]]))
    assert result["raw_agreement"] == pytest.approx(1 / 3)
    assert result["fleiss_kappa"] == pytest.approx(-1 / 3)
    assert result["gwet_ac1"] == pytest.approx(1 / 9)


def test_cluster_bootstrap_uses_group_ids():
    values = np.array([0, 0, 1, 1])
    assert cluster_ci(values, ["x"] * 4, 42) is None
    assert cluster_ci(values, ["x", "x", "y", "y"], 42) == [0, 1]


def test_crossfit_insufficient_groups_and_known_good_judge():
    matrix = np.array([["A", "B", "TIE"]] * 20)
    result = cross_validated_calibration(matrix, ["A"] * 20, [str(i) for i in range(20)], 42)
    assert result["accuracy_all_pairs"]["calibration_selected_single"] == 1
    assert result["accuracy_all_pairs"]["care_prototype"] == 1
    assert result["accuracy_all_pairs"]["majority"] == 0
    assert (
        cross_validated_calibration(matrix, ["A"] * 20, ["one"] * 20, 42)["status"]
        == "insufficient_groups"
    )
