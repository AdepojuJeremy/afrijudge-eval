"""Plan, build, run and analyze the Option C study without changing pilot runs."""

import json
import math
import os
from pathlib import Path

import httpx
import yaml

from afrijudge import judge_v2
from afrijudge.cli import run_lock
from afrijudge.client import Client, Ledger, catalog
from afrijudge.io import digest, read_jsonl, write_json, write_jsonl
from afrijudge.study.benchmark import LANGUAGES, TIERS, open_benchmark
from afrijudge.study.execution import PacedHTTP, dispatch, generate
from afrijudge.study.stimuli import (
    STYLES,
    Job,
    check_reviews,
    compile_pairs,
    export_reviews,
    h1_job,
    h2_answer_job,
    h2_output,
    h2_passage_job,
    h2_prompt_jobs,
    neutral_prose,
    shortcut_prose,
    validate_pairs,
)


def add_commands(subs):
    for name in (
        "study-plan",
        "study-preflight",
        "generate-all-stimuli",
        "study-run",
        "study-analyze",
    ):
        sub = subs.add_parser(name)
        sub.add_argument("--config", type=Path, default=Path("config/option_c.yaml"))
        sub.add_argument("--total-sources", type=int, choices=TIERS, default=300)
        sub.add_argument("--benchmark", type=Path)
        sub.add_argument("--run-dir", type=Path)
        sub.add_argument("--gen-max-tokens", type=int, default=1024)
        sub.add_argument("--judge-max-tokens", type=int, default=256)
        if name in ("generate-all-stimuli", "study-run"):
            sub.add_argument("--execute", action="store_true")
            sub.add_argument("--max-spend-usd", type=float)
            sub.add_argument("--interval-seconds", type=float, default=4.0)
        if name == "study-run":
            sub.add_argument("--auto-approve-programmatic", action="store_true")


def plan(total: int, judges: int, gen_cap: int, judge_cap: int) -> dict:
    tier = TIERS[total]
    anchors, tests = (sum(n) for n in zip(*tier, strict=True))
    topics = tier[-1][1]
    comparisons = {"h1_anchors": 4 * anchors, "h1_test": 8 * tests, "h2": 8 * topics}
    generation = {
        "h1_neutral": 4 * total,
        "h1_shortcut": 4 * tests,
        "h2_questions": 6 * topics,
        "h2_passages": 3 * topics,
        "h2_answers": 16 * topics,
    }
    counts = {k: v * judges * 2 for k, v in comparisons.items()}
    return {
        "source_groups_h1": total,
        "h1_language_items": 4 * total,
        "supplementary_afriqa_topics_h2": topics,
        "anchor_groups": anchors,
        "test_groups": tests,
        "comparison_pairs": comparisons,
        "total_comparison_pairs": sum(comparisons.values()),
        "judge_calls": counts,
        "total_judge_calls": sum(counts.values()),
        "generation_calls_before_repairs": generation,
        "total_generation_calls_before_repairs": sum(generation.values()),
        "gen_max_tokens": gen_cap,
        "judge_max_tokens": judge_cap,
    }


async def _assemble(client, data, cap):
    all_rows = [(row, lang) for row in data["sources"] for lang in LANGUAGES]

    def keyed(row, lang):
        return row["source_id"], lang

    outputs = await generate(
        client,
        [h1_job(row, lang, "neutral") for row, lang in all_rows],
        cap,
        lambda i, text: neutral_prose(text, *all_rows[i]),
        "H1 neutral",
    )
    neutral = {keyed(row, lang): out for (row, lang), out in zip(all_rows, outputs, strict=True)}
    test = [(r, lang) for r, lang in all_rows if r["split"] == "test"]
    shortcuts = await generate(
        client,
        [h1_job(r, lang, "shortcut", neutral[keyed(r, lang)]) for r, lang in test],
        cap,
        lambda i, text: shortcut_prose(text, *test[i], neutral[keyed(*test[i])]),
        "H1 shortcut",
    )
    shortcuts = {keyed(r, lang): out for (r, lang), out in zip(test, shortcuts, strict=True)}
    h2 = [row for row in data["sources"] if "h2" in row]
    questions, passages = {}, {}
    for row in h2:
        sid = row["source_id"]
        questions[sid, "en", STYLES[0]] = row["h2"]["english_question"]
        questions[sid, row["h2"]["original_lang"], STYLES[0]] = row["h2"]["question"]
        passages[sid, "en"] = row["h2"]["passage"]
    prompt_jobs = [job for row in h2 for job in h2_prompt_jobs(row, data["sha256"])]
    passage_jobs = [h2_passage_job(row, lang) for row in h2 for lang in LANGUAGES[1:]]
    for jobs, field, target, keys in (
        (prompt_jobs, "question", questions, ("source_id", "lang", "style")),
        (passage_jobs, "passage", passages, ("source_id", "lang")),
    ):
        results = await generate(
            client,
            jobs,
            cap,
            lambda i, text, field=field, jobs=jobs: h2_output(
                text,
                field,
                jobs[i].meta["lang"],
                jobs[i].meta.get("style", ""),
            ),
            f"H2 {field}",
        )
        for job, result in zip(jobs, results, strict=True):
            target[tuple(job.meta[k] for k in keys)] = result
    answer_jobs = []
    for row in h2:
        for lang in LANGUAGES:
            for style in STYLES:
                sid = row["source_id"]
                for model in row["h2_matchup"]:
                    answer_jobs.append(
                        h2_answer_job(
                            row,
                            lang,
                            style,
                            questions[sid, lang, style],
                            passages[sid, lang],
                            model,
                        )
                    )
    output = await generate(
        client,
        answer_jobs,
        cap,
        lambda i, text: h2_output(
            text,
            "answer",
            answer_jobs[i].meta["lang"],
            answer_jobs[i].meta["style"],
        ),
        "H2 candidates",
    )
    answers = {
        (*[job.meta[k] for k in ("source_id", "lang", "style")], job.model): text
        for job, text in zip(answer_jobs, output, strict=True)
    }
    return compile_pairs(data, neutral, shortcuts, questions, passages, answers)


def judge_jobs(pairs: list, judges: list, benchmark_id: str) -> list:
    return [
        Job(
            model,
            judge_v2.messages(pair, order, naturalistic=True),
            {
                "stage": "study_judge",
                "pair_id": pair["pair_id"],
                "order": order,
                "bench": benchmark_id,
                "pair_hash": digest(pair),
            },
        )
        for pair in pairs
        for model in judges
        for order in ("AB", "BA")
    ]


def _frozen(root: Path, meta: dict, expected: int) -> list:
    pairs = json.loads((root / "pairs.json").read_text())
    if meta.get("pairs_hash") != digest(pairs):
        raise ValueError("Frozen pairs were changed or have no recorded hash")
    return validate_pairs(pairs, expected)


def _settings(args):
    root = args.run_dir or Path(f"runs/option-c-{args.total_sources}")
    benchmark = args.benchmark or Path(f"study/benchmark-{args.total_sources}.json.gz")
    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if min(args.gen_max_tokens, args.judge_max_tokens) < 1:
        raise ValueError("Token caps must be positive")
    if len(cfg["judges"]) != 6 or len({cfg["models"][k]["family"] for k in cfg["judges"]}) != 6:
        raise ValueError("Option C uses six judges from six different model families")
    totals = plan(
        args.total_sources, len(cfg["judges"]), args.gen_max_tokens, args.judge_max_tokens
    )
    return root, benchmark, cfg, totals


def _pricing(totals: dict, lock: dict, judges: list, pairs: list | None = None) -> dict:
    models = lock["models"]
    unit = len(judges)
    p = [models[k]["pricing"] for k in judges]
    prompt = sum(float(x["prompt"]) for x in p) / unit
    completion = sum(float(x["completion"]) for x in p) / unit
    judge_count = totals["total_judge_calls"]
    estimate = {
        "assumed_judge_prompt_tokens": 600,
        "assumed_judge_completion_tokens_including_reasoning": 80,
        "estimated_judging_only_usd": round(judge_count * (600 * prompt + 80 * completion), 2),
        "average_judge_prompt_usd_per_million": round(prompt * 1e6, 4),
        "average_judge_completion_usd_per_million": round(completion * 1e6, 4),
    }
    if pairs:
        from afrijudge.client import reservation_upper

        estimate["judge_all_reservations_usd"] = round(
            sum(
                reservation_upper(models[job.model], job.messages, totals["judge_max_tokens"])
                for job in judge_jobs(pairs, judges, "")
            ),
            2,
        )
        estimate["reservation_note"] = "Each returned cost replaces that call's reservation."
    return estimate


async def _paid(args, root, benchmark, cfg, totals) -> dict:
    ceiling = args.max_spend_usd
    if ceiling is None or not math.isfinite(ceiling) or ceiling <= 0:
        raise ValueError("Set a positive --max-spend-usd ceiling for paid execution")
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ValueError("Set OPENROUTER_API_KEY in your shell")
    data = open_benchmark(benchmark)
    if data["total_sources"] != args.total_sources:
        raise ValueError("Benchmark and --total-sources differ")
    if not math.isfinite(args.interval_seconds) or args.interval_seconds < 0:
        raise ValueError("Invalid pacing interval")
    with run_lock(root):
        return await _locked_paid(args, root, data, cfg, totals, ceiling, key)


async def _locked_paid(args, root, data, cfg, totals, ceiling, key):
    identity = {
        "benchmark": data["sha256"],
        "config": digest(cfg),
        "generation_max_tokens": args.gen_max_tokens,
        "judge_max_tokens": args.judge_max_tokens,
        "protocol": "option_c_v1",
    }
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"id": identity}
    if manifest["id"] != identity:
        raise ValueError("Run inputs changed. Choose a separate --run-dir.")
    expected = totals["total_comparison_pairs"]
    judge_only = args.command == "study-run"
    pairs = _frozen(root, manifest, expected) if judge_only else None
    if judge_only:
        if args.auto_approve_programmatic:
            audit_rows = export_reviews(root / "review", pairs, cfg["seed"])
            approval = {"method": "programmatic", "audit_pairs": audit_rows}
        else:
            check_reviews(root / "review", pairs)
            approval = {"method": "human_review"}
        manifest["approval"] = approval
    ledger = Ledger(root / "ledger.sqlite", ceiling)
    try:
        async with httpx.AsyncClient(timeout=cfg["timeout_seconds"]) as http:
            lock_path = root / "models.lock.json"
            lock = (
                json.loads(lock_path.read_text())
                if lock_path.exists()
                else await catalog(
                    http,
                    cfg,
                )
            )
            if "model_lock_hash" in manifest and manifest["model_lock_hash"] != digest(lock):
                raise ValueError("Pinned model lock was modified")
            manifest["model_lock_hash"] = digest(lock)
            write_json(lock_path, lock)
            write_json(manifest_path, manifest)
            paced = PacedHTTP(http, args.interval_seconds)
            client = Client(paced, ledger, cfg, lock, key)
            if not judge_only:
                pairs = (
                    _frozen(root, manifest, expected)
                    if "pairs_hash" in manifest
                    else (await _assemble(client, data, args.gen_max_tokens))
                )
                if "pairs_hash" not in manifest:
                    write_json(root / "pairs.json", pairs)
                    manifest["pairs_hash"] = digest(pairs)
                    write_json(manifest_path, manifest)
                count = export_reviews(root / "review", pairs, cfg["seed"])
                return {
                    "mode": "review",
                    "pairs": len(pairs),
                    "audit_pairs": count,
                    "pricing": _pricing(totals, lock, cfg["judges"], pairs),
                    "spent_or_reserved_usd": ledger.spent,
                }
            jobs = judge_jobs(pairs, cfg["judges"], data["sha256"])
            records = await dispatch(client, jobs, args.judge_max_tokens, progress="Judging")
            write_jsonl(root / "judge_requests.jsonl", records)
        from afrijudge.study.analysis import analyze

        report = analyze(pairs, records, cfg)
        report.update(approval=approval, spent_or_reserved_usd=ledger.spent, run_identity=manifest)
        write_json(root / "report.json", report)
        return {
            "mode": "complete",
            "judge_calls": len(records),
            "report": str(root / "report.json"),
            "spent_or_reserved_usd": ledger.spent,
        }
    finally:
        try:
            write_jsonl(root / "requests.jsonl", ledger.records())
        finally:
            ledger.close()


async def run_command(args) -> dict:
    root, benchmark, cfg, totals = _settings(args)
    if args.command == "study-preflight":
        data = open_benchmark(benchmark)
        if data["total_sources"] != args.total_sources:
            raise ValueError("Benchmark and --total-sources differ")
        async with httpx.AsyncClient(timeout=60) as http:
            lock = await catalog(http, cfg)
        return {
            **totals,
            "models": lock["models"],
            "benchmark_hash": data["sha256"],
            "pricing": _pricing(totals, lock, cfg["judges"]),
        }
    if args.command == "study-analyze":
        from afrijudge.study.analysis import analyze

        with run_lock(root):
            meta = json.loads((root / "manifest.json").read_text())
            if meta["id"]["config"] != digest(cfg):
                raise ValueError("Analysis config differs from the recorded run configuration")
            pairs = _frozen(root, meta, totals["total_comparison_pairs"])
            records = read_jsonl(root / "judge_requests.jsonl")
            result = analyze(pairs, records, cfg)
            result["run_identity"] = meta
            if (root / "report.json").exists():
                old = json.loads((root / "report.json").read_text())
                result.update(
                    {k: old[k] for k in ("spent_or_reserved_usd", "approval") if k in old}
                )
            write_json(root / "report.json", result)
            return {"mode": "analysis", "report": str(root / "report.json")}
    if args.command == "study-plan" or not args.execute:
        return {"mode": "plan", **totals}
    return await _paid(args, root, benchmark, cfg, totals)
