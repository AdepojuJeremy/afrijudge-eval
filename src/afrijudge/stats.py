"""Explicit-denominator pilot statistics and held-out calibration baselines.

Outputs are descriptive unless otherwise stated. No statistic establishes an
internal representation mechanism, equal response quality, or a causal decomposition.
"""

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from afrijudge.io import digest, read_jsonl, write_json

STABLE = {"A", "B", "TIE"}


def agreement(matrix: np.ndarray) -> dict:
    n, k = matrix.shape
    if not n or k < 2:
        return {
            "complete_stable_pairs": n,
            "raw_agreement": None,
            "fleiss_kappa": None,
            "gwet_ac1": None,
        }
    counts = np.stack([(matrix == c).sum(axis=1) for c in ("A", "B", "TIE")], axis=1)
    po = float(np.mean((counts * (counts - 1)).sum(axis=1) / (k * (k - 1))))
    proportions = counts.sum(axis=0) / (n * k)
    pe = float(np.sum(proportions**2))
    pe_ac1 = float(np.sum(proportions * (1 - proportions)) / 2)
    return {
        "complete_stable_pairs": n,
        "raw_agreement": po,
        "fleiss_kappa": (po - pe) / (1 - pe) if pe < 1 else None,
        "gwet_ac1": (po - pe_ac1) / (1 - pe_ac1),
    }


def error_dependence(errors: np.ndarray) -> dict:
    n, k = errors.shape
    corrs = []
    for i in range(k):
        for j in range(i + 1, k):
            if n > 1 and np.std(errors[:, i]) > 0 and np.std(errors[:, j]) > 0:
                corrs.append(float(np.corrcoef(errors[:, i], errors[:, j])[0, 1]))
    expected = k * (k - 1) // 2
    rho = float(np.mean(corrs)) if corrs else None
    # Do not replace undefined correlations by zero or silently clip negative ones.
    denom = 1 + (k - 1) * rho if rho is not None else None
    neff = k / denom if expected and len(corrs) == expected and denom > 0 else None
    return {
        "mean_defined_error_phi": rho,
        "defined_correlations": len(corrs),
        "possible_correlations": expected,
        "effective_votes_exchangeable_approx": neff,
    }


def cluster_ci(
    success: np.ndarray, groups: list[str], seed: int, repetitions: int = 1000
) -> list | None:
    ids = sorted(set(groups))
    if len(ids) < 2:
        return None
    totals = np.array(
        [sum(success[i] for i, g in enumerate(groups) if g == group) for group in ids]
    )
    sizes = np.array([groups.count(group) for group in ids])
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(ids), (repetitions, len(ids)))
    samples = totals[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    return np.quantile(samples, [0.025, 0.975]).tolist()


def validity(matrix: np.ndarray, gold: list[str], groups: list[str], seed: int) -> dict:
    n, k = matrix.shape
    if not n:
        return {"n_gold_pairs": 0}
    gold_arr = np.asarray(gold)
    correct = matrix == gold_arr[:, None]
    right = correct.sum(axis=1)
    wrong_label = np.where(gold_arr == "A", "B", "A")
    wrong = (matrix == wrong_label[:, None]).sum(axis=1)
    panel_correct = right > k / 2
    panel_decides = panel_correct | (wrong > k / 2)
    unanimous = (right == k) | (wrong == k)
    out = {
        "n_gold_pairs": n,
        "panel_accuracy_all_pairs": float(panel_correct.mean()),
        "panel_decision_coverage": float(panel_decides.mean()),
        "panel_accuracy_when_decided": float(panel_correct[panel_decides].mean())
        if panel_decides.any()
        else None,
        "panel_accuracy_cluster_ci95": cluster_ci(panel_correct, groups, seed),
        "false_supermajority_rate_all_pairs": float((wrong >= max(k - 1, 1)).mean()),
        "unanimous_pairs": int(unanimous.sum()),
        "unanimous_error_rate": float((wrong[unanimous] == k).mean()) if unanimous.any() else None,
        "single_judge_accuracy": correct.mean(axis=0).tolist(),
    }
    decisive = np.all(np.isin(matrix, ["A", "B"]), axis=1)
    errors = 1 - correct[decisive].astype(int)
    out["dependence_decisive_pairs"] = int(decisive.sum())
    out.update(error_dependence(errors))
    if len(errors) > 1:
        observed = float((errors.sum(axis=1) < k / 2).mean())
        rng = np.random.default_rng(seed)
        simulated = []
        for _ in range(1000):
            shuffled = np.column_stack([rng.permutation(errors[:, j]) for j in range(k)])
            simulated.append(float((shuffled.sum(axis=1) < k / 2).mean()))
        out["marginal_independence_diagnostic"] = {
            "observed_accuracy": observed,
            "shuffled_mean_accuracy": float(np.mean(simulated)),
            "gap_pp": 100 * (float(np.mean(simulated)) - observed),
            "lower_tail_monte_carlo_p": (1 + sum(v <= observed for v in simulated)) / 1001,
            "warning": (
                "Column shuffling destroys shared item difficulty; not an "
                "item-aware Condorcet test or causal evidence."
            ),
        }
    return out


def cross_validated_calibration(
    matrix: np.ndarray, gold: list[str], groups: list[str], seed: int
) -> dict:
    """Cross-fit weights and error-covariance penalties using training gold only."""
    ids = sorted(set(groups))
    if len(ids) < 10:
        return {"status": "insufficient_groups", "minimum": 10}
    np.random.default_rng(seed).shuffle(ids)
    fold_map = {key: i % 5 for i, key in enumerate(ids)}
    folds = np.array([fold_map[key] for key in groups])
    gold = np.array(gold)
    correct = (matrix == gold[:, None]).astype(float)
    outputs = defaultdict(list)
    for fold in range(5):
        train, test = folds != fold, folds == fold
        acc = (correct[train].sum(axis=0) + 1) / (train.sum() + 2)
        best = int(np.argmax(acc))
        weights = np.maximum(acc - 0.5, 0.01)
        penalty = np.ones(matrix.shape[1])
        # Error covariance is learned only on the training fold.
        for j in range(matrix.shape[1]):
            for k in range(matrix.shape[1]):
                if j != k and np.std(correct[train, j]) and np.std(correct[train, k]):
                    penalty[j] += max(
                        0, float(np.corrcoef(correct[train, j], correct[train, k])[0, 1])
                    )
        for name, w in (
            ("majority", np.ones(len(weights))),
            ("accuracy_weighted", weights),
            ("care_prototype", weights / penalty),
        ):
            a = (matrix[test] == "A") @ w
            b = (matrix[test] == "B") @ w
            # A strict majority of total weight; explicit ties/abstentions do not vanish.
            prediction = np.where(a > w.sum() / 2, "A", np.where(b > w.sum() / 2, "B", "ABSTAIN"))
            outputs[name].extend((prediction == gold[test]).tolist())
        outputs["calibration_selected_single"].extend(correct[test, best].astype(bool).tolist())
    return {
        "status": "exploratory_5fold_crossfit",
        "n_groups": len(ids),
        "accuracy_all_pairs": {k: float(np.mean(v)) for k, v in outputs.items()},
        "note": (
            "Prototype, not a validated LRL-CARE contribution. No held-out "
            "labels enter weight fitting."
        ),
    }


def analyze(run_dir: Path, config: dict) -> dict:
    pairs = read_jsonl(run_dir / "pairs.jsonl")
    verdicts = read_jsonl(run_dir / "verdicts.jsonl")
    artifact_path = run_dir / "artifacts.json"
    if artifact_path.exists():
        expected = json.loads(artifact_path.read_text())
        for filename, rows in (("pairs.jsonl", pairs), ("verdicts.jsonl", verdicts)):
            if digest(rows) != expected[filename]:
                raise ValueError(f"Research artifact changed: {filename}")
    lookup = {(r["pair_id"], r["judge"]): r["winner"] for r in verdicts}
    # Verified labels are a separate immutable-content-bound annotation overlay.
    review_path = run_dir / "foil_review.jsonl"
    verified = {}
    if review_path.exists():
        for row in read_jsonl(review_path):
            if row.get("gold") in ("A", "B"):
                if not row.get("reviewer", "").strip() or not row.get("notes", "").strip():
                    raise ValueError("Verified foil labels require reviewer and supporting notes")
                if row["pair_id"] in verified:
                    raise ValueError("Duplicate verified foil annotation")
                verified[row["pair_id"]] = row
    grouped = defaultdict(list)
    for pair in pairs:
        if pair["experiment"] == "exp2" and pair["pair_id"] in verified:
            annotation = verified[pair["pair_id"]]
            if annotation["content_hash"] != digest(
                {"prompt": pair["prompt"], "a": pair["a"], "b": pair["b"]}
            ):
                raise ValueError("Annotation content hash mismatch")
            pair = {**pair, "gold": annotation["gold"]}
        grouped[(pair["experiment"], pair["lang"], pair.get("condition", pair["stratum"]))].append(
            pair
        )
    report = {
        "schema_version": 1,
        "status": "pilot_descriptive",
        "groups": [],
        "judge_order": config["judges"],
        "warnings": [
            "Both-incorrect is not equal-quality; preference contrasts are descriptive.",
            (
                "Unvalidated foils have no gold label and cannot support "
                "false-consensus accuracy claims."
            ),
            "Diacritic stripping may change meaning; altered pairs have no inherited gold.",
            (
                "Prompt language probes use draft rubrics; no claim of equivalent "
                "human-validated instructions."
            ),
        ],
    }
    for (exp, lang, condition), subset in grouped.items():
        matrix = np.array(
            [[lookup.get((p["pair_id"], j), "INVALID") for j in config["judges"]] for p in subset]
        )
        stable = np.all(np.isin(matrix, list(STABLE)), axis=1)
        row = {
            "experiment": exp,
            "lang": lang,
            "condition": condition,
            "n_pairs": len(subset),
            "invalid_rate": float((matrix == "INVALID").mean()),
            "order_instability_rate": float((matrix == "ORDER_UNSTABLE").mean()),
            "explicit_tie_rate": float((matrix == "TIE").mean()),
            "agreement": agreement(matrix[stable]),
        }
        indices = [i for i, p in enumerate(subset) if p.get("gold") in ("A", "B")]
        row["validity"] = validity(
            matrix[indices],
            [subset[i]["gold"] for i in indices],
            [subset[i]["item_id"] for i in indices],
            config["seed"],
        )
        if indices:
            row["calibration"] = cross_validated_calibration(
                matrix[indices],
                [subset[i]["gold"] for i in indices],
                [subset[i]["item_id"] for i in indices],
                config["seed"],
            )
        if exp == "exp2":
            # Report preferences even before semantic validation, without calling them errors.
            foil_votes = [
                sum(
                    matrix[i, j] == ("A" if p["a"]["family"] != "human" else "B")
                    for j in range(len(config["judges"]))
                )
                for i, p in enumerate(subset)
            ]
            row["exploratory_foil_supermajority_rate"] = float(
                np.mean(np.array(foil_votes) >= len(config["judges"]) - 1)
            )
        if exp == "exp3":
            matches = [
                (lookup.get((p["baseline_pair_id"], j), "INVALID"), matrix[i, k])
                for i, p in enumerate(subset)
                for k, j in enumerate(config["judges"])
            ]
            comparable = [(a, b) for a, b in matches if a in STABLE and b in STABLE]
            row["comparable_baseline_votes"] = len(comparable)
            row["verdict_shift_rate_stable_only"] = (
                sum(a != b for a, b in comparable) / len(comparable) if comparable else None
            )
        report["groups"].append(row)
    # Same-pair family preference contrasts, never presented as identified pure bias.
    contrasts = defaultdict(list)
    for p in pairs:
        if p["experiment"] != "exp1" or p["stratum"] != "both_incorrect":
            continue
        for side, cand in (("A", p["a"]), ("B", p["b"])):
            own, others = [], []
            for j in config["judges"]:
                vote = lookup.get((p["pair_id"], j))
                if vote not in STABLE:
                    continue
                value = 0.5 if vote == "TIE" else float(vote == side)
                (own if config["models"][j]["family"] == cand["family"] else others).append(value)
            if own and others:
                contrasts[(p["lang"], cand["family"])].append(float(np.mean(own) - np.mean(others)))
    report["descriptive_family_preference"] = [
        {
            "lang": lang,
            "family": family,
            "n_pairs": len(v),
            "matched_own_minus_other": float(np.mean(v)),
        }
        for (lang, family), v in contrasts.items()
    ]
    gold_by_lang = {
        lang: [
            p
            for p in pairs
            if p["experiment"] == "exp1"
            and p["lang"] == lang
            and p["stratum"] == "correct_vs_incorrect"
        ]
        for lang in config["languages"]
    }
    common_ids = set.intersection(
        *({p["item_id"] for p in subset} for subset in gold_by_lang.values())
    )
    report["matched_language_comparison"] = {
        "n_common_source_items": len(common_ids),
        "note": (
            "Common underlying questions; generated response pairs still differ across languages."
        ),
        "languages": {},
    }
    for lang, subset in gold_by_lang.items():
        matched = [p for p in subset if p["item_id"] in common_ids]
        matrix = np.array(
            [[lookup.get((p["pair_id"], j), "INVALID") for j in config["judges"]] for p in matched]
        )
        matrix = matrix.reshape(len(matched), len(config["judges"]))
        report["matched_language_comparison"]["languages"][lang] = validity(
            matrix, [p["gold"] for p in matched], [p["item_id"] for p in matched], config["seed"]
        )
    manifest_path = run_dir / "manifest.json"
    if (
        manifest_path.exists()
        and json.loads(manifest_path.read_text()).get("mode") == "synthetic_demo"
    ):
        report["status"] = "SYNTHETIC_DEMO_NOT_RESEARCH_RESULTS"
    previous = run_dir / "report.json"
    if previous.exists():
        old_report = json.loads(previous.read_text())
        for key in ("spend_usd", "model_lock_hash"):
            if key in old_report:
                report[key] = old_report[key]
    write_json(run_dir / "report.json", report)
    return report
