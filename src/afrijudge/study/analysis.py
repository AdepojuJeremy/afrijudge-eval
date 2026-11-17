"""Analyze the complete AB/BA schedule using source-group uncertainty."""

from collections import Counter, defaultdict
from itertools import combinations

import numpy as np

from afrijudge.io import digest
from afrijudge.judge_v2 import parse_record
from afrijudge.study.benchmark import LANGUAGES
from afrijudge.study.stimuli import STYLES
from afrijudge.text import reconcile

CHOICES = ("A", "B")
H1_CONDITIONS = ("neutral_idiomatic", "wrong_calqued_shortcut")
DRAW_COUNT = 5000


def _ratio(num, den):
    return float(num / den) if den else None


def _interval(draws):
    if draws is None:
        return None
    return [float(x) for x in np.quantile(draws, (0.025, 0.975))]


def _bootstrap(values, seed):
    """Resample source-level vectors inside their design strata."""
    if not values:
        return None
    rng = np.random.default_rng(seed)
    strata = defaultdict(list)
    for strat, value in values:
        strata[strat].append(value)
    draws = np.zeros((DRAW_COUNT, len(values[0][1])))
    for rows in strata.values():
        arr = np.array(rows)
        indices = rng.integers(0, len(rows), (DRAW_COUNT, len(rows)))
        draws += arr[indices].sum(axis=1)
    return draws / len(values)


def _measure(values, seed):
    draws = _bootstrap(values, seed)
    mean = np.mean(np.array([val for _, val in values]), axis=0)
    return [
        {"estimate": float(x), "ci95": _interval(draws[:, i]), "source_groups": len(values)}
        for i, x in enumerate(mean)
    ]


def _record_votes(pairs, records, judges):
    lookup = {p["pair_id"]: digest(p) for p in pairs}
    seen, parse_diags = {}, Counter()
    for record in records:
        meta = record["meta"]
        key = meta["pair_id"], record["model_key"], meta["order"]
        if (
            key[0] not in lookup
            or meta.get("pair_hash") != lookup.get(key[0])
            or key[1] not in judges
            or key[2] not in ("AB", "BA")
            or key in seen
            or meta.get("stage") != "study_judge"
        ):
            raise ValueError(f"Unexpected or duplicate judged request: {key}")
        verdict, diagnostic = parse_record(record)
        seen[key] = verdict
        parse_diags[diagnostic] += 1
    expected = len(pairs) * len(judges) * 2
    if len(seen) != expected:
        raise ValueError(f"Incomplete judgment schedule: got {len(seen)} of {expected}")
    pair_votes = {}
    for pair in pairs:
        pid = pair["pair_id"]
        pair_votes[pid] = {
            judge: reconcile(seen[pid, judge, "AB"], seen[pid, judge, "BA"]) for judge in judges
        }
    return pair_votes, parse_diags


def _agreement(votes):
    combinations_count = 0
    stable_combinations = 0
    same = 0
    for a, b in combinations(votes, 2):
        combinations_count += 1
        if a not in CHOICES or b not in CHOICES:
            continue
        stable_combinations += 1
        same += a == b
    return same, stable_combinations, combinations_count


def _error_phi(items, models, votes):
    by_pair = []
    for j1, j2 in combinations(models, 2):
        choices = [
            [int(votes[p["pair_id"]][j] != p["gold"]) for j in (j1, j2)]
            for p in items
            if all(votes[p["pair_id"]][j] in CHOICES for j in (j1, j2))
        ]
        arr = np.asarray(choices, dtype=float)
        phi = None
        if len(arr) > 1 and np.all(arr.std(axis=0) > 0):
            phi = float(np.corrcoef(arr.T)[0, 1])
        by_pair.append({"judges": [j1, j2], "joint_decisions": len(choices), "phi": phi})
    vals = [row["phi"] for row in by_pair if row["phi"] is not None]
    return {"mean_estimable_phi": _ratio(sum(vals), len(vals)), "pairs": by_pair}


def _majority(votes):
    tally = Counter(x for x in votes if x in CHOICES)
    threshold = len(votes) // 2 + 1
    return next((choice for choice in CHOICES if tally[choice] >= threshold), None)


def _outcome_counts(items, outcomes):
    stats = Counter(
        "undecided" if outcome not in CHOICES else "correct" if outcome == item["gold"] else "wrong"
        for item, outcome in zip(items, outcomes, strict=True)
    )
    correct, wrong, undecided = (stats[k] for k in ("correct", "wrong", "undecided"))
    return {
        "items": len(items),
        "correct": correct,
        "wrong": wrong,
        "undecided": undecided,
        "correct_per_assigned_item": _ratio(correct, len(items)),
        "decision_coverage": _ratio(correct + wrong, len(items)),
        "accuracy_when_decisive": _ratio(correct, correct + wrong),
        "wrong_per_assigned_item": _ratio(wrong, len(items)),
    }


def _calibration(anchors, judges, votes):
    per_lang = {}
    for lang in LANGUAGES:
        items = [p for p in anchors if p["lang"] == lang]
        selected_votes = [votes[p["pair_id"]] for p in items]
        stats = {j: _outcome_counts(items, [row[j] for row in selected_votes]) for j in judges}
        ranking = sorted(
            judges,
            key=lambda j: (
                -stats[j]["correct"],
                -stats[j]["decision_coverage"],
                j,
            ),
        )
        correlations = _error_phi(items, judges, votes)
        # Shrink pairwise shared-error estimates, which are noisy for small anchor panels.
        penalties = dict.fromkeys(judges, 0.0)
        for c in correlations["pairs"]:
            n, phi = c["joint_decisions"], c["phi"]
            adjustment = max(0, phi if phi is not None else 0) * n / (n + 20)
            for j in c["judges"]:
                penalties[j] += adjustment
        weights = {}
        confusion = {}
        for j in judges:
            s = stats[j]
            accuracy = (s["correct"] + 2) / (s["correct"] + s["wrong"] + 4)
            coverage = (s["correct"] + s["wrong"] + 1) / (len(items) + 2)
            weights[j] = max(0, 2 * accuracy - 1) * coverage / (1 + penalties[j])
            # Supervised two-class Dawid–Skene with balanced pseudocounts. Correctness is
            # the label because candidate A is canonicalized to the H1 gold before analysis.
            confusion[j] = max(0.5, accuracy)
        per_lang[lang] = {
            "ranked_judges": ranking,
            "judges": stats,
            "weights": weights,
            "anchor_dawid_skene_reliability": confusion,
            "shared_errors": correlations,
        }
    return per_lang


def _h1(items, votes, calibrations, seed):
    cells = {}
    contrast_rows = defaultdict(dict)
    top1_correct = {}
    for lang in LANGUAGES:
        rank = calibrations[lang]["ranked_judges"]
        groups = {"all": rank, "anchor_top3": rank[:3], "anchor_bottom3": rank[-3:]}
        for condition in H1_CONDITIONS:
            part = [p for p in items if p["lang"] == lang and p["condition"] == condition]
            for p in part:
                top1_correct[p["domain"], p["source_id"], lang, condition] = int(
                    votes[p["pair_id"]][rank[0]] == p["gold"]
                )
            panels = {}
            for name, models in groups.items():
                selected = [[votes[p["pair_id"]][j] for j in models] for p in part]
                sums = np.array([_agreement(row) for row in selected]).sum(axis=0)
                outcomes = [_majority(row) for row in selected]
                panels[name] = {
                    **_outcome_counts(part, outcomes),
                    "stable_agreement_all_judge_pairs": _ratio(sums[0], sums[2]),
                    "agreement_given_two_stable_votes": _ratio(sums[0], sums[1]),
                    "joint_stable_coverage": _ratio(sums[1], sums[2]),
                    "order_unstable_votes": sum(row.count("ORDER_UNSTABLE") for row in selected),
                    "ties": sum(row.count("TIE") for row in selected),
                    "invalid_votes": sum(row.count("INVALID") for row in selected),
                    "shared_errors": _error_phi(part, models, votes),
                }
                for row, ballot, outcome in zip(part, selected, outcomes, strict=True):
                    agreed, _, all_pairs = _agreement(ballot)
                    key = row["domain"], row["source_id"]
                    contrast_rows[key][lang, condition, name] = [
                        agreed / all_pairs,
                        int(outcome == "B"),
                        int(outcome in CHOICES),
                        int(outcome == row["gold"]),
                    ]
            cells[f"{lang}:{condition}"] = panels
    neutral_style, wrong_style = H1_CONDITIONS
    contrasts = []
    for (domain, source_id), vals in contrast_rows.items():
        diffs = []
        for lang in LANGUAGES[1:]:
            low = np.array(vals[lang, wrong_style, "anchor_bottom3"])
            high = np.array(vals[lang, wrong_style, "anchor_top3"])
            neutral = np.array(vals[lang, neutral_style, "all"])
            shortcut = np.array(vals[lang, wrong_style, "all"])
            low_neutral = np.array(vals[lang, neutral_style, "anchor_bottom3"])
            high_neutral = np.array(vals[lang, neutral_style, "anchor_top3"])
            diffs.append(
                np.concatenate(
                    (
                        (low - high)[:3],
                        (shortcut - neutral)[:3],
                        [(low_neutral - high_neutral)[2]],
                        ((low - low_neutral) - (high - high_neutral))[:2],
                        [shortcut[3] - top1_correct[domain, source_id, lang, wrong_style]],
                    )
                )
            )
        contrasts.append((domain, np.mean(diffs, axis=0).tolist()))
    names = [
        "bottom3_minus_top3_shortcut_agreement",
        "bottom3_minus_top3_wrong_majority",
        "bottom3_minus_top3_shortcut_coverage",
        "shortcut_minus_neutral_full_panel_agreement",
        "shortcut_minus_neutral_full_panel_wrong_majority",
        "shortcut_minus_neutral_full_panel_coverage",
        "bottom3_minus_top3_neutral_coverage",
        "shortcut_agreement_change_bottom3_minus_top3",
        "shortcut_wrong_majority_change_bottom3_minus_top3",
        "full_panel_minus_top1_shortcut_correct_per_assigned_item",
    ]
    return {
        "cells": cells,
        "hau_yo_ig_contrasts": dict(
            zip(
                names,
                _measure(contrasts, seed),
                strict=True,
            )
        ),
    }


def _weighted(votes, weights, threshold, min_support=2):
    weighted_votes = {
        choice: sum(weights[j] for j in votes if votes[j] == choice) for choice in CHOICES
    }
    total = sum(weighted_votes.values())
    return next(
        (
            choice
            for choice in CHOICES
            if total
            and weighted_votes[choice] / total >= threshold
            and sum(votes[j] == choice and weights[j] > 0 for j in votes) >= min_support
        ),
        None,
    )


def _h3_choices(votes, calibration):
    ranking = calibration["ranked_judges"]
    reliability = calibration["anchor_dawid_skene_reliability"]
    ds_weights = {j: float(np.log(p / (1 - p))) for j, p in reliability.items()}
    full = _majority(list(votes.values()))
    return {
        "six_judge_majority": full,
        "family_equal_majority": full,
        "anchor_top1": votes[ranking[0]],
        "anchor_top3": _majority([votes[j] for j in ranking[:3]]),
        "anchor_dawid_skene": _weighted(votes, ds_weights, 0.500001, 1),
        "lrl_care": _weighted(votes, calibration["weights"], 0.6),
    }


def _h3(items, votes, calibration, seed):
    choices = [_h3_choices(votes[p["pair_id"]], calibration[p["lang"]]) for p in items]
    overall = {}
    methods = list(choices[0])
    for method in methods:
        overall[method] = _outcome_counts(items, [row[method] for row in choices])
    detailed = {}
    for lang in LANGUAGES:
        for condition in H1_CONDITIONS:
            indices = [
                i for i, p in enumerate(items) if (p["lang"], p["condition"]) == (lang, condition)
            ]
            detailed[f"{lang}:{condition}"] = {
                method: _outcome_counts(
                    [items[i] for i in indices],
                    [choices[i][method] for i in indices],
                )
                for method in overall
            }
    grouped = defaultdict(list)
    metrics = ("correct_per_assigned_item", "decision_coverage", "wrong_per_assigned_item")
    contrasts = list(combinations(methods, 2))
    for pair, row in zip(items, choices, strict=True):
        observed = np.array(
            [
                [out == pair["gold"], out in CHOICES, out in CHOICES and out != pair["gold"]]
                for out in row.values()
            ],
            dtype=float,
        )
        vals = [observed[methods.index(b)] - observed[methods.index(a)] for a, b in contrasts]
        grouped[pair["domain"], pair["source_id"]].append(np.ravel(vals))
    comparisons = _measure(
        [(domain, np.mean(rows, axis=0).tolist()) for (domain, _), rows in grouped.items()], seed
    )
    return {
        "overall": overall,
        "by_language_condition": detailed,
        "paired_held_out_differences": {
            f"{b}_minus_{a}": dict(
                zip(
                    metrics,
                    comparisons[3 * i : 3 * i + len(metrics)],
                    strict=True,
                )
            )
            for i, (a, b) in enumerate(contrasts)
        },
        "family_equal_note": "One vote per family makes this equivalent to the six-judge majority.",
    }


def _h2_candidates(pair, votes, families):
    outcomes = []
    for label, key in zip(CHOICES, ("a", "b"), strict=True):
        own_family = families[pair[key]["model_key"]]
        own, other = [], []
        for j, vote in votes.items():
            (own if families[j] == own_family else other).append(vote)
        if not own or not other:
            raise ValueError("Each H2 candidate needs both own-family and unrelated judges")
        own_stable, other_stable = (
            [v for v in own if v in CHOICES],
            [v for v in other if v in CHOICES],
        )
        decisive = bool(own_stable and other_stable)
        own_choice = own.count(label) / len(own)
        other_choice = other.count(label) / len(other)
        outcomes.append(
            {
                "family": own_family,
                "own_choice": own_choice,
                "other_choice": other_choice,
                "gap": own_choice - other_choice,
                "own_coverage": len(own_stable) / len(own),
                "other_coverage": len(other_stable) / len(other),
                "decisive_gap": (
                    own_stable.count(label) / len(own_stable)
                    - other_stable.count(label) / len(other_stable)
                )
                if decisive
                else None,
            }
        )
    return outcomes


def _h2(items, votes, families, seed):
    topics, cells, provenance_cells = defaultdict(dict), defaultdict(list), defaultdict(list)
    for pair in items:
        key = pair["lang"], pair["condition"]
        candidates = _h2_candidates(pair, votes[pair["pair_id"]], families)
        topics[pair["matchup"], pair["topic_id"], pair["original_lang"]][key] = np.mean(
            [candidate["gap"] for candidate in candidates]
        )
        cells[(*key, pair["matchup"])].extend(candidates)
        provenance_cells[(*key, pair["provenance"])].extend(candidates)
    contrasts = []
    native_contrasts = defaultdict(list)
    neutral, formal = STYLES
    for (matchup, _, origin), values in topics.items():
        if set(values) != {(lang, style) for lang in LANGUAGES for style in STYLES}:
            raise ValueError("H2 topic lacks one of the eight matched cells")
        neutral_diffs = [values[lang, neutral] - values["en", neutral] for lang in LANGUAGES[1:]]
        style_diffs = [values[lang, formal] - values[lang, neutral] for lang in LANGUAGES]
        contrasts.append(
            (
                matchup,
                [*neutral_diffs, *style_diffs, np.mean(neutral_diffs), np.mean(style_diffs[1:])],
            )
        )
        native_contrasts[origin].append(
            (
                matchup,
                [
                    values[origin, neutral] - values["en", neutral],
                    values[origin, formal] - values[origin, neutral],
                ],
            )
        )
    names = [
        *(f"{lang}_idiomatic_minus_english" for lang in LANGUAGES[1:]),
        *(f"{lang}_formal_minus_idiomatic" for lang in LANGUAGES),
        "pooled_non_english_idiomatic_minus_english",
        "pooled_non_english_formal_minus_idiomatic",
    ]

    def summary(rows):
        metrics = ("gap", "own_choice", "other_choice", "own_coverage", "other_coverage")
        decisive = [r["decisive_gap"] for r in rows if r["decisive_gap"] is not None]
        return {
            "candidate_evaluations": len(rows),
            **{k: float(np.mean([r[k] for r in rows])) for k in metrics},
            "decisive_candidates": len(decisive),
            "decisive_only_gap": _ratio(sum(decisive), len(decisive)),
        }

    return {
        "cells": {":".join(key): summary(rows) for key, rows in sorted(cells.items())},
        "cells_by_provenance": {
            ":".join(key): summary(rows) for key, rows in sorted(provenance_cells.items())
        },
        "paired_topic_contrasts": dict(zip(names, _measure(contrasts, seed), strict=True)),
        "matched_human_original_topic_contrasts": {
            lang: dict(
                zip(
                    ("human_original_minus_english_pivot", "formal_minus_human_original"),
                    _measure(rows, seed),
                    strict=True,
                )
            )
            for lang, rows in sorted(native_contrasts.items())
        },
        "leave_one_matchup_out": {
            matchup: dict(
                zip(
                    names,
                    (
                        float(v)
                        for v in np.mean(
                            [values for key, values in contrasts if key != matchup],
                            axis=0,
                        )
                    ),
                    strict=True,
                )
            )
            for matchup in sorted({k for k, _ in contrasts})
        },
        "english_condition": "formal English prose",
        "style_manipulated_in": ["question", "candidate_answer"],
        "note": "Question and answer styles are varied jointly. Provenance is tracked per cell.",
    }


def analyze(pairs, records, config):
    judges = config["judges"]
    families = {j: config["models"][j]["family"] for j in judges}
    anchors = [p for p in pairs if p["split"] == "anchor"]
    test = [p for p in pairs if p["split"] == "test"]
    h2 = [p for p in pairs if p["split"] == "h2"]
    votes, diagnostics = _record_votes(pairs, records, judges)
    calibration = _calibration(anchors, judges, votes)
    seed = config["seed"]
    return {
        "judge_calls": len(records),
        "comparison_pairs": len(pairs),
        "pairs_by_dataset": dict(Counter(p["dataset"] for p in pairs)),
        "protocol_diagnostics": dict(diagnostics),
        "invalid_judge_calls": len(records) - diagnostics["valid"],
        "resampling": {
            "draws": DRAW_COUNT,
            "unit": "matched source group",
            "h1_h3_stratification": "domain",
            "h2_stratification": "family matchup",
        },
        "anchors": calibration,
        "h1": _h1(test, votes, calibration, seed),
        "h2": _h2(h2, votes, families, seed),
        "h3": _h3(test, votes, calibration, seed),
    }
