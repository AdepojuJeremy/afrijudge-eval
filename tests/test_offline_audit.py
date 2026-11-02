"""Regression checks for errors that would fabricate or change research votes."""

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "offline_audit", Path(__file__).parents[1] / "scripts/audit_completed_pilot.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
recover, reconcile = helper.recover, helper.reconcile


class RecoveryTests(unittest.TestCase):
    def record(self, text, status="success", finish="stop"):
        return {"content": text, "status": status, "finish_reason": finish}

    def test_complete_terminal_json_after_preamble(self):
        r = self.record('Analysis.\n```json\n{"reasoning":"Evidence.","verdict":"B"}\n```')
        self.assertEqual(recover(r), ("B", "completed_terminal_json"))

    def test_never_match_letter_inside_word(self):
        self.assertEqual(
            recover(self.record('{"reasoning":"Neither", "verdict":"Both are wrong"}'))[0],
            "INVALID",
        )

    def test_conflicting_example_is_not_a_final_verdict(self):
        s = (
            'Example: {"reasoning":"demo", "verdict":"A"}\n'
            'Final: {"reasoning":"real", "verdict":"B"}'
        )
        self.assertEqual(recover(self.record(s))[0], "INVALID")

    def test_truncation_is_never_recovered(self):
        s = 'Preamble. {"reasoning":"done", "verdict":"A"}'
        self.assertEqual(recover(self.record(s, "invalid_completion", "length"))[0], "INVALID")

    def test_unknown_provider_state_is_not_eligible(self):
        s = 'Preamble. {"reasoning":"done", "verdict":"A"}'
        self.assertEqual(recover(self.record(s, "provider_error", "stop"))[0], "INVALID")

    def test_duplicate_keys_in_new_recovery_are_rejected(self):
        s = 'Preamble. {"reasoning":"done", "verdict":"A", "verdict":"B"}'
        self.assertEqual(recover(self.record(s))[0], "INVALID")

    def test_option_letters_c_and_d_stay_invalid(self):
        self.assertEqual(
            recover(self.record('{"reasoning":"choice", "verdict":"D"}'))[0], "INVALID"
        )

    def test_preamble_with_valid_baseline_preserves_original(self):
        s = '{"reasoning":"Akọsilẹ̀", "verdict":"TIE"}'
        self.assertEqual(recover(self.record(s)), ("TIE", "original_valid"))

    def test_trailing_nonfence_commentary_not_recovered(self):
        s = 'Preamble {"reasoning":"x", "verdict":"A"} but I may choose B.'
        self.assertEqual(recover(self.record(s))[0], "INVALID")

    def test_explicit_final_opinion_not_guessed(self):
        self.assertEqual(recover(self.record("The winner is A."))[0], "INVALID")

    def test_reconciliation_preserves_instability(self):
        self.assertEqual(reconcile("A", "A"), "ORDER_UNSTABLE")
        self.assertEqual(reconcile("TIE", "A"), "ORDER_UNSTABLE")
        self.assertEqual(reconcile("A", "TIE"), "ORDER_UNSTABLE")
        self.assertEqual(reconcile("A", "B"), "A")
        self.assertEqual(reconcile("B", "A"), "B")
        self.assertEqual(reconcile("TIE", "TIE"), "TIE")
        self.assertEqual(reconcile("INVALID", "A"), "INVALID")


if __name__ == "__main__":
    unittest.main()
