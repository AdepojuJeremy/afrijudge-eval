"""Offline AfriJudge audit; standard library only. No network or API calls.

Outputs are a separate post-hoc sensitivity analysis. A complete final JSON
object may be recovered from a successful, stopped response with preamble.
Truncated responses, duplicate JSON keys and conflicting explicit verdicts are
never recovered. Semantic review flags are provisional and evidence-linked.
"""

import argparse
import collections
import csv
import hashlib
import json
import re
from pathlib import Path

VALID = ("A", "B", "TIE")
STABLE = VALID
FAMILIES = {
    "gpt4o": "openai",
    "gemini25pro": "google",
    "claude_sonnet": "anthropic",
    "llama33_70b": "meta",
    "qwen25_72b": "qwen",
    "cohere_multilingual": "cohere",
}
JUDGES = list(FAMILIES)


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def unique_object(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("Duplicate JSON key")
        out[key] = value
    return out


def strict(text):
    """Exact baseline parser copied from afrijudge.text.verdict/json_object."""
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    elif text.startswith("```\n") and text.endswith("```"):
        text = text[4:-3].strip()
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return "INVALID"
    return obj["verdict"] if isinstance(obj, dict) and obj.get("verdict") in VALID else "INVALID"


def objects(text):
    """Decode disjoint JSON objects, skipping braces within decoded objects."""
    dec = json.JSONDecoder(object_pairs_hook=unique_object)
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            obj, size = dec.raw_decode(text[start:])
        except (ValueError, TypeError):
            index = start + 1
            continue
        end = start + size
        yield start, end, obj
        index = end


def recover(rec):
    original = strict(rec["content"]) if rec["status"] == "success" else "INVALID"
    if original != "INVALID":
        return original, "original_valid"
    if rec["status"] != "success" or rec["finish_reason"] != "stop":
        return original, "ineligible_completion"
    text = rec["content"]
    found = [
        (a, b, obj)
        for a, b, obj in objects(text)
        if isinstance(obj, dict) and "reasoning" in obj and obj.get("verdict") in VALID
    ]
    final = [(a, b, obj) for a, b, obj in found if text[b:].strip() in ("", "```")]
    # Reject conflicting explicit valid verdict strings anywhere in the response.
    labels = re.findall(r'"verdict"\s*:\s*"(A|B|TIE)"', text)
    if len(final) == 1 and len(found) == 1 and set(labels) == {final[0][2]["verdict"]}:
        return final[0][2]["verdict"], "completed_terminal_json"
    return "INVALID", "unrecovered"


def reconcile(ab, ba):
    if "INVALID" in (ab, ba):
        return "INVALID"
    mapped = {"A": "B", "B": "A", "TIE": "TIE"}[ba]
    return ab if ab == mapped else "ORDER_UNSTABLE"


def taxonomy(rec, old, new):
    if old != "INVALID":
        return "original_valid"
    if rec["finish_reason"] == "length":
        return "token_limit_truncation"
    if rec["status"] == "provider_filtered":
        return "provider_filtered"
    if new != "INVALID":
        return "recoverable_completed_terminal_json"
    obs = list(objects(rec["content"]))
    vals = [o.get("verdict") for _, _, o in obs if isinstance(o, dict) and "verdict" in o]
    if any(isinstance(v, str) and v in ("C", "D") for v in vals):
        return "invalid_option_label_C_or_D"
    if any(v in VALID for v in vals):
        return "completed_json_with_extra_trailing_text_or_structure"
    if vals:
        return "other_invalid_verdict_value"
    if re.search(r'"verdict"\s*:\s*TIE\s*[,}]', rec["content"]):
        return "malformed_json_unquoted_TIE"
    if re.search(r'"verdict"\s*:', rec["content"]):
        return "other_json_syntax_or_unrecoverable_structure"
    line_label = re.search(r"(?im)^\s*verdict\s*:\s*(A|B|C|D|TIE)\s*$", rec["content"])
    if line_label:
        return (
            "plain_text_verdict_C_or_D"
            if line_label.group(1) in ("C", "D")
            else "plain_text_verdict_A_B_or_TIE_not_recovered"
        )
    if obs:
        return "json_object_without_exact_verdict_key"
    return "no_decodable_verdict_object_or_standard_verdict_line"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_jsonl(path, data):
    path.write_text(
        "".join(json.dumps(x, ensure_ascii=False, allow_nan=False) + "\n" for x in data)
    )


def write_csv(path, data, fields=None):
    fields = fields or list(data[0])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in data:
            w.writerow(
                {
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                    for k, v in row.items()
                }
            )


def audit_pair(pair):
    flags, evidence = [], []
    # Evidence establishes a source-context omission; no judgment outcomes used.
    if pair["item_id"] == "mmlu:426":
        flags.append("DEFECTIVE_SOURCE_CONTEXT")
        evidence.append(
            "Parallel English source asks how many workers are hired at wage "
            "$4.50; supplied prompt has no labor-demand, marginal-product or "
            "revenue schedule. Wage alone cannot determine quantity."
        )
    if pair["pair_id"] == "en:mmlu:70:correct_vs_incorrect":
        flags.append("REASONING_TAG_CONTRADICTION")
        evidence.append(
            "4*2.99 + 3*6.99 = 32.93, option C. Candidate B explicitly computes "
            "$32.93 but ends <answer>B</answer>; candidate A computes $32.93 and "
            "tags C."
        )
    provider = pair["item_id"] == "mgsm:246"
    if provider:
        flags.append("PROVIDER_FILTERED_MGSM246")
        evidence.append(
            "Source ID matches the eight Azure-filtered generation/judge records; "
            "filtering is a separate missing-data sensitivity, not a source defect."
        )
    # No absence-of-defect heuristic is promoted into a clean semantic label.
    semantic_exclusion = any(
        f in flags for f in ["DEFECTIVE_SOURCE_CONTEXT", "REASONING_TAG_CONTRADICTION"]
    )
    status = (
        "EXCLUDED_DEFECTIVE_SOURCE"
        if "DEFECTIVE_SOURCE_CONTEXT" in flags
        else "EXCLUDED_TAG_MISMATCH"
        if "REASONING_TAG_CONTRADICTION" in flags
        else "UNCERTAIN"
    )
    if not semantic_exclusion:
        flags.append("UNCERTAIN")
        evidence.append(
            "Full source correctness, candidate semantic correctness and "
            "reasoning/tag consistency have not been independently validated. No "
            "CLEAN label assigned from parser success alone."
        )
    return {
        "pair_id": pair["pair_id"],
        "lang": pair["lang"],
        "item_id": pair["item_id"],
        "stratum": pair["stratum"],
        "original_gold": pair["gold"],
        "audit_status": status,
        "audit_flags": flags,
        "provider_filter_sensitivity": provider,
        "evidence": evidence,
        "review_basis": "provisional_assistant_review_not_fluent_human_annotation",
        "reviewer": "",
        "human_review_status": "PENDING",
        "pair_content_sha256": hashlib.sha256(
            json.dumps(pair, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
    }


def metrics(subset, votes, scenario, lang):
    gold = [p for p in subset if p.get("gold") in ("A", "B")]
    n = len(gold)
    c = collections.Counter()
    for p in gold:
        ws = [votes[p["pair_id"], j] for j in JUDGES]
        g = p["gold"]
        wrong = "B" if g == "A" else "A"
        c["correct"] += ws.count(g) > 3
        c["wrong"] += ws.count(wrong) > 3
        c["wrong_supermajorities"] += ws.count(wrong) >= 5
        for w in ws:
            c[w] += 1
    decisions = c["correct"] + c["wrong"]

    def safe(a, b):
        return a / b if b else None

    row = {
        "scenario": scenario,
        "lang": lang,
        "n_exp1_pairs": len(subset),
        "n_gold_pairs": n,
        "correct_majorities": c["correct"],
        "incorrect_majorities": c["wrong"],
        "panel_accuracy_all_gold_pairs": safe(c["correct"], n),
        "strict_majority_coverage": safe(decisions, n),
        "panel_accuracy_when_decided": safe(c["correct"], decisions),
        "order_unstable_rate_gold_votes": safe(c["ORDER_UNSTABLE"], n * 6),
        "explicit_tie_rate_gold_votes": safe(c["TIE"], n * 6),
        "invalid_rate_gold_votes": safe(c["INVALID"], n * 6),
        "wrong_supermajorities": c["wrong_supermajorities"],
    }
    allvotes = [votes[p["pair_id"], j] for p in subset for j in JUDGES]
    for state, key in [
        ("INVALID", "invalid_rate_all_exp1_votes"),
        ("ORDER_UNSTABLE", "order_unstable_rate_all_exp1_votes"),
        ("TIE", "explicit_tie_rate_all_exp1_votes"),
    ]:
        row[key] = safe(allvotes.count(state), len(allvotes))
    individual = []
    for j in JUDGES:
        ws = [(votes[p["pair_id"], j], p["gold"]) for p in gold]
        correct = sum(v == g for v, g in ws)
        decisive = [(v, g) for v, g in ws if v in ("A", "B")]
        individual.append(
            {
                "scenario": scenario,
                "lang": lang,
                "judge": j,
                "n_gold_pairs": n,
                "correct": correct,
                "accuracy_all_gold_pairs": safe(correct, n),
                "decisive_coverage": safe(len(decisive), n),
                "accuracy_when_decisive": safe(sum(v == g for v, g in decisive), len(decisive)),
            }
        )
    preferences = collections.defaultdict(list)
    for p in subset:
        if p["stratum"] != "both_incorrect":
            continue
        for side, cand in [("A", p["a"]), ("B", p["b"])]:
            own, other = [], []
            for j in JUDGES:
                v = votes[p["pair_id"], j]
                if v not in STABLE:
                    continue
                val = 0.5 if v == "TIE" else float(v == side)
                (own if FAMILIES[j] == cand["family"] else other).append(val)
            if own and other:
                preferences[cand["family"]].append(sum(own) / len(own) - sum(other) / len(other))
    prefs = [
        {
            "scenario": scenario,
            "lang": lang,
            "family": family,
            "n_candidate_contrasts": len(vals),
            "matched_own_minus_other": sum(vals) / len(vals),
        }
        for family, vals in preferences.items()
    ]
    present = {x["family"] for x in prefs}
    prefs.extend(
        {
            "scenario": scenario,
            "lang": lang,
            "family": family,
            "n_candidate_contrasts": 0,
            "matched_own_minus_other": None,
        }
        for family in list(FAMILIES.values())[:-1]
        if family not in present
    )
    return row, individual, prefs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--requests", required=True, type=Path)
    ap.add_argument("--pairs", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--raw-verdicts", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise SystemExit(
            "Output directory must be empty: originals and previous audits are never overwritten."
        )
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = [args.requests, args.pairs, args.report] + (
        [args.raw_verdicts] if args.raw_verdicts else []
    )
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    reqs, pairs = rows(args.requests), rows(args.pairs)
    assert len({r["request_id"] for r in reqs}) == len(reqs), "Duplicate request IDs"
    assert len({p["pair_id"] for p in pairs}) == len(pairs), "Duplicate pair IDs"
    report = json.loads(args.report.read_text())
    assert JUDGES == report["judge_order"], "Unexpected model panel"
    lookup = {p["pair_id"]: p for p in pairs}
    parsed, recoveries, failures = [], [], []
    grouped = {"original": {}, "recovered": {}}
    diagnostics = collections.defaultdict(collections.Counter)
    for r in reqs:
        if r["meta"]["stage"] != "judge":
            continue
        meta = r["meta"]
        p = lookup[meta["pair_id"]]
        j = r["model_key"]
        order = meta["order"]
        assert j in JUDGES and order in ("AB", "BA")
        old = strict(r["content"]) if r["status"] == "success" else "INVALID"
        new, method = recover(r)
        key = p["pair_id"], j, order
        assert key not in grouped["original"], "Duplicate pair/judge/order"
        grouped["original"][key] = old
        grouped["recovered"][key] = new
        category = taxonomy(r, old, new)
        diag = diagnostics[j, p["lang"], p.get("prompt_lang", "en")]
        diag["total_judge_calls"] += 1
        diag[category] += 1
        rec = {
            "request_id": r["request_id"],
            "pair_id": p["pair_id"],
            "judge": j,
            "lang": p["lang"],
            "prompt_lang": p.get("prompt_lang", "en"),
            "order": order,
            "status": r["status"],
            "finish_reason": r["finish_reason"],
            "original_verdict": old,
            "recovered_verdict": new,
            "category": category,
        }
        parsed.append(rec)
        if method == "completed_terminal_json":
            recoveries.append({**rec, "raw_content": r["content"]})
        if old == "INVALID":
            failures.append(
                {
                    **rec,
                    "content_excerpt_head": r["content"][:200],
                    "content_excerpt_tail": r["content"][-250:],
                }
            )
    assert len(parsed) == len(pairs) * len(JUDGES) * 2
    if args.raw_verdicts:
        original = {r["request_id"]: r["verdict"] for r in rows(args.raw_verdicts)}
        assert len(original) == len(parsed)
        assert all(original[x["request_id"]] == x["original_verdict"] for x in parsed)
    resolved = {}
    for mode, raw in grouped.items():
        vv = []
        for p in pairs:
            for j in JUDGES:
                ab, ba = raw[p["pair_id"], j, "AB"], raw[p["pair_id"], j, "BA"]
                vv.append(
                    {
                        "pair_id": p["pair_id"],
                        "judge": j,
                        "judge_family": FAMILIES[j],
                        "ab": ab,
                        "ba": ba,
                        "winner": reconcile(ab, ba),
                    }
                )
        resolved[mode] = {(x["pair_id"], x["judge"]): x["winner"] for x in vv}
        write_jsonl(args.out / f"verdicts_{mode}.jsonl", vv)
    exp1 = [p for p in pairs if p["experiment"] == "exp1"]
    flags = [audit_pair(p) for p in exp1]
    flagmap = {r["pair_id"]: r for r in flags}
    write_jsonl(args.out / "exp1_audit_flags.jsonl", flags)
    write_csv(args.out / "exp1_audit_flags.csv", flags)
    write_jsonl(
        args.out / "exp1_review_packet.jsonl", [{**flagmap[p["pair_id"]], "pair": p} for p in exp1]
    )
    # Semantic review and provider missingness are explicitly separate axes.
    subsets = {
        "A_original_strict": ("original", exp1),
        "B_completed_json_recovery": ("recovered", exp1),
        "C_strictly_CLEAN": (
            "recovered",
            [p for p in exp1 if flagmap[p["pair_id"]]["audit_status"] == "CLEAN"],
        ),
        "D_no_confirmed_defect_including_UNCERTAIN": (
            "recovered",
            [p for p in exp1 if flagmap[p["pair_id"]]["audit_status"] in ("CLEAN", "UNCERTAIN")],
        ),
        "E_recovered_exclude_mgsm246_only": (
            "recovered",
            [p for p in exp1 if p["item_id"] != "mgsm:246"],
        ),
        "F_D_also_exclude_mgsm246": (
            "recovered",
            [
                p
                for p in exp1
                if flagmap[p["pair_id"]]["audit_status"] in ("CLEAN", "UNCERTAIN")
                and p["item_id"] != "mgsm:246"
            ],
        ),
    }
    summaries, individuals, preferences = [], [], []
    for scenario, (mode, subset) in subsets.items():
        for lang in ["en", "ha", "yo", "ig"]:
            a, b, c = metrics(
                [p for p in subset if p["lang"] == lang], resolved[mode], scenario, lang
            )
            summaries.append(a)
            individuals.extend(b)
            preferences.extend(c)
    for row in summaries:
        if row["scenario"] != "A_original_strict":
            continue
        expected = next(
            g
            for g in report["groups"]
            if g["experiment"] == "exp1"
            and g["lang"] == row["lang"]
            and g["condition"] == "correct_vs_incorrect"
        )
        assert row["n_gold_pairs"] == expected["validity"]["n_gold_pairs"]
        for key, oldkey in [
            ("panel_accuracy_all_gold_pairs", "panel_accuracy_all_pairs"),
            ("strict_majority_coverage", "panel_decision_coverage"),
            ("panel_accuracy_when_decided", "panel_accuracy_when_decided"),
        ]:
            assert abs(row[key] - expected["validity"][oldkey]) < 1e-12
        assert (
            abs(row["order_unstable_rate_gold_votes"] - expected["order_instability_rate"]) < 1e-12
        )
        assert abs(row["explicit_tie_rate_gold_votes"] - expected["explicit_tie_rate"]) < 1e-12
    # Reproduce original family preference exactly, including candidate-side units.
    oldprefs = {(x["lang"], x["family"]): x for x in report["descriptive_family_preference"]}
    for x in preferences:
        if x["scenario"] == "A_original_strict" and x["n_candidate_contrasts"]:
            y = oldprefs[x["lang"], x["family"]]
            assert x["n_candidate_contrasts"] == y["n_pairs"]
            assert abs(x["matched_own_minus_other"] - y["matched_own_minus_other"]) < 1e-12
    write_csv(args.out / "sensitivity_summary.csv", summaries)
    write_csv(args.out / "individual_judge_accuracy.csv", individuals)
    write_csv(args.out / "family_preference_descriptive.csv", preferences)
    write_json(
        args.out / "sensitivity_results.json",
        {"summary": summaries, "individual": individuals, "family_preference": preferences},
    )
    write_jsonl(args.out / "recovery_evidence.jsonl", recoveries)
    write_jsonl(args.out / "judge_failure_records.jsonl", failures)
    categories = sorted({x["category"] for x in parsed})
    ds = [
        {
            "judge": j,
            "lang": lang,
            "prompt_lang": pl,
            **{c: d[c] for c in ["total_judge_calls"] + categories},
        }
        for (j, lang, pl), d in sorted(diagnostics.items())
    ]
    write_csv(args.out / "failure_taxonomy_by_model_language_prompt.csv", ds)
    trunc = []
    for j in JUDGES:
        for lang in ["en", "ha", "yo", "ig"]:
            matches = [d for (jj, ll, pl), d in diagnostics.items() if jj == j and ll == lang]
            total = sum(d["total_judge_calls"] for d in matches)
            n = sum(d["token_limit_truncation"] for d in matches)
            trunc.append(
                {
                    "judge": j,
                    "lang": lang,
                    "judge_calls": total,
                    "truncated": n,
                    "truncation_rate": n / total if total else None,
                }
            )
    write_csv(args.out / "truncation_by_model_language.csv", trunc)
    filterrows = [
        {
            "request_id": r["request_id"],
            "stage": r["meta"]["stage"],
            "model": r["model_key"],
            "metadata": r["meta"],
        }
        for r in reqs
        if r["status"] == "provider_filtered"
    ]
    write_jsonl(args.out / "provider_filtered_records.jsonl", filterrows)
    checks = {
        "n_request_records": len(reqs),
        "n_pairs": len(pairs),
        "n_judge_records": len(parsed),
        "n_exp1_pairs": len(exp1),
        "recovered_completed_verdicts": len(recoveries),
        "judge_categories": dict(collections.Counter(x["category"] for x in parsed)),
        "provider_filtered_by_stage": dict(collections.Counter(x["stage"] for x in filterrows)),
        "audit_status_counts": dict(collections.Counter(x["audit_status"] for x in flags)),
        "original_report_metrics_reproduced": True,
        "original_family_preferences_reproduced": True,
        "raw_verdicts_reproduced": bool(args.raw_verdicts),
        "input_file_sha256": before,
    }
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    checks["input_files_unchanged"] = True
    write_json(args.out / "audit_checks.json", checks)
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
