"""Three pilot experiments sharing one generation pool, budget, and request cache."""

import copy
import random
from collections import Counter, defaultdict
from pathlib import Path

from afrijudge import prompts
from afrijudge.client import bounded_map
from afrijudge.config import LANGUAGES
from afrijudge.io import digest, read_jsonl, write_json, write_jsonl
from afrijudge.text import answer, features, nfc, reconcile, strip_marks, verdict


def candidate(text: str, key: str, family: str, correctness: bool | None = None) -> dict:
    text = nfc(text)
    return {
        "text": text,
        "generator": key,
        "family": family,
        "correct": correctness,
        "features": features(text),
    }


def make_pair(item: dict, a: dict, b: dict, stratum: str, gold: str | None, seed: int) -> dict:
    identity = f"{item['lang']}:{item['item_id']}:{stratum}"
    if random.Random(f"{seed}:{identity}").getrandbits(1):
        a, b = b, a
        gold = {"A": "B", "B": "A", None: None}[gold]
    return {
        "pair_id": identity,
        "item_id": item["item_id"],
        "lang": item["lang"],
        "prompt": item["prompt"],
        "a": a,
        "b": b,
        "stratum": stratum,
        "gold": gold,
        "experiment": "exp1",
        "prompt_lang": "en",
    }


def verifiable_pairs(config: dict, items: list[dict], records: list[dict]) -> tuple[list, dict]:
    bundles = defaultdict(list)
    counters = Counter()
    for record in records:
        meta = record["meta"]
        bundles[(meta["lang"], meta["item_id"])].append(record)
    pairs, accuracy = [], []
    for item in items:
        correct, incorrect = [], []
        for record in bundles[(item["lang"], item["item_id"])]:
            extracted = (
                answer(record["content"], item["task"]) if record["status"] == "success" else None
            )
            accuracy.append(
                {
                    "item_id": item["item_id"],
                    "lang": item["lang"],
                    "model": record["model_key"],
                    "parseable": extracted is not None,
                    "correct": extracted == item["gold"] if extracted is not None else None,
                }
            )
            if extracted is None:
                counters["unparseable_generation"] += 1
                continue
            key = record["model_key"]
            c = candidate(
                record["content"], key, config["models"][key]["family"], extracted == item["gold"]
            )
            (correct if c["correct"] else incorrect).append(c)
        rng = random.Random(f"{config['seed']}:{item['lang']}:{item['item_id']}")
        if correct and incorrect:
            pairs.append(
                make_pair(
                    item,
                    rng.choice(correct),
                    rng.choice(incorrect),
                    "correct_vs_incorrect",
                    "A",
                    config["seed"],
                )
            )
        else:
            counters["no_correct_incorrect_contrast"] += 1
        if len(incorrect) >= 2:
            a, b = rng.sample(incorrect, 2)
            # Both wrong does NOT establish equal quality or a gold tie.
            pairs.append(make_pair(item, a, b, "both_incorrect", None, config["seed"]))
        else:
            counters["fewer_than_two_incorrect"] += 1
    return pairs, {"exclusions": dict(counters), "generation_accuracy": accuracy}


def probe_pairs(config: dict, pairs: list[dict]) -> list[dict]:
    output = []
    for lang in ("yo", "ig"):
        pool = [
            p
            for p in pairs
            if p["lang"] == lang
            and (
                strip_marks(p["a"]["text"]) != p["a"]["text"]
                or strip_marks(p["b"]["text"]) != p["b"]["text"]
            )
        ]
        random.Random(f"{config['seed']}:{lang}:probe").shuffle(pool)
        # One contrast per underlying prompt, avoiding duplicate pseudo-independent probes.
        seen, chosen = set(), []
        for p in pool:
            if p["item_id"] not in seen:
                seen.add(p["item_id"])
                chosen.append(p)
        for base in chosen[: config["samples"]["probes_per_language"]]:
            for stripped, native in ((True, False), (False, True), (True, True)):
                p = copy.deepcopy(base)
                p.update(
                    {
                        "experiment": "exp3",
                        "baseline_pair_id": base["pair_id"],
                        "condition": f"strip={int(stripped)};native={int(native)}",
                        "prompt_lang": lang if native else "en",
                        "rubric_validation": "draft_unvalidated" if native else "english",
                        "pair_id": f"{base['pair_id']}:strip={int(stripped)};native={int(native)}",
                    }
                )
                if stripped:
                    for side in ("a", "b"):
                        p[side]["text"] = strip_marks(p[side]["text"])
                        p[side]["features"] = features(p[side]["text"])
                        p[side]["correct"] = None
                    # Stripping can change meaning; original gold is not inherited.
                    p["gold"] = None
                output.append(p)
    return output


def plan(config: dict) -> dict:
    langs = len(config["languages"])
    base_items = (config["samples"]["mmlu"] + config["samples"]["mgsm"]) * langs
    max_exp1 = base_items * 2
    traps = config["samples"]["traps_per_language"] * (langs - 1) * 2
    probes = (
        config["samples"]["probes_per_language"] * len(set(config["languages"]) & {"yo", "ig"}) * 3
    )
    return {
        "generation_calls": base_items * len(config["generators"]),
        "foil_calls": traps,
        "maximum_exp1_pairs": max_exp1,
        "maximum_exp2_pairs": traps,
        "maximum_exp3_pairs": probes,
        "maximum_judge_calls": (max_exp1 + traps + probes) * len(config["judges"]) * 2,
        "budget_limit_usd": config["budget_limit_usd"],
        "note": (
            "Upper call bounds, not guaranteed yields or a cost quote. "
            "Experimental controls expand the original pilot."
        ),
    }


async def run(config: dict, data_dir: Path, run_dir: Path, client) -> dict:
    items = read_jsonl(data_dir / "exp1.jsonl")
    translations = read_jsonl(data_dir / "exp2.jsonl")
    jobs = [(item, key) for item in items for key in config["generators"]]

    async def generate(job):
        item, key = job
        return await client.complete(
            key,
            prompts.generation_messages(item),
            {
                "stage": "generation",
                "item_id": item["item_id"],
                "lang": item["lang"],
                "prompt_version": prompts.VERSION,
            },
            config["generation_max_tokens"],
        )

    print(f"Generating candidates: {len(jobs)} requests (cached calls are reused)", flush=True)
    generations = await bounded_map(generate, jobs, config["concurrency"])
    write_jsonl(run_dir / "generations.jsonl", generations)
    pairs, exclusions = verifiable_pairs(config, items, generations)
    write_json(run_dir / "generation_diagnostics.json", exclusions)
    foil_keys = config["generators"][:2]
    jobs = [
        (item, foil_keys[index % len(foil_keys)], condition)
        for index, item in enumerate(translations)
        for condition in ("plain_error", "styled_error")
    ]

    async def make_foil(job):
        item, key, condition = job
        return await client.complete(
            key,
            prompts.foil_messages(item, condition),
            {
                "stage": "foil",
                "item_id": item["item_id"],
                "lang": item["lang"],
                "condition": condition,
                "prompt_version": prompts.VERSION,
            },
            config["generation_max_tokens"],
        )

    print(f"Generating exploratory foils: {len(jobs)} requests", flush=True)
    foils = await bounded_map(make_foil, jobs, config["concurrency"])
    reviews = []
    for (item, key, condition), record in zip(jobs, foils, strict=True):
        if record["status"] != "success":
            continue
        reference = candidate(item["reference"], "human_translation", "human")
        foil = candidate(record["content"], key, config["models"][key]["family"])
        p = make_pair(
            {
                **item,
                "prompt": (
                    f"Translate accurately into {LANGUAGES[item['lang']]}: {item['en_source']}"
                ),
            },
            reference,
            foil,
            condition,
            None,
            config["seed"],
        )
        p.update(
            {
                "experiment": "exp2",
                "condition": condition,
                "gold_status": "unverified_foil",
                "source": item["source"],
                "reference_provenance": item["reference_provenance"],
            }
        )
        pairs.append(p)
        reviews.append(
            {
                "pair_id": p["pair_id"],
                "content_hash": digest({"prompt": p["prompt"], "a": p["a"], "b": p["b"]}),
                "lang": p["lang"],
                "source": item["en_source"],
                "a": p["a"]["text"],
                "b": p["b"]["text"],
                "gold": None,
                "reviewer": "",
                "notes": "",
            }
        )
    pairs += probe_pairs(config, pairs)
    write_jsonl(run_dir / "pairs.jsonl", pairs)
    # Never overwrite completed human review work on resume.
    if not (run_dir / "foil_review.jsonl").exists():
        write_jsonl(run_dir / "foil_review.jsonl", reviews)
    jobs = [(p, key, order) for p in pairs for key in config["judges"] for order in ("AB", "BA")]

    async def judge(job):
        pair, key, order = job
        rec = await client.complete(
            key,
            prompts.judge_messages(pair, order),
            {
                "stage": "judge",
                "pair_id": pair["pair_id"],
                "order": order,
                "prompt_version": prompts.VERSION,
            },
            config["judge_max_tokens"],
        )
        return {
            "pair_id": pair["pair_id"],
            "judge": key,
            "order": order,
            "request_id": rec["request_id"],
            "verdict": verdict(rec["content"]) if rec["status"] == "success" else "INVALID",
        }

    print(f"Judging all three experiments: {len(pairs)} pairs, {len(jobs)} requests", flush=True)
    raw = await bounded_map(judge, jobs, config["concurrency"])
    write_jsonl(run_dir / "raw_verdicts.jsonl", raw)
    grouped = defaultdict(dict)
    for rec in raw:
        grouped[(rec["pair_id"], rec["judge"])][rec["order"]] = rec["verdict"]
    out = []
    for p in pairs:
        for key in config["judges"]:
            votes = grouped[(p["pair_id"], key)]
            out.append(
                {
                    "pair_id": p["pair_id"],
                    "judge": key,
                    "judge_family": config["models"][key]["family"],
                    "ab": votes.get("AB", "INVALID"),
                    "ba": votes.get("BA", "INVALID"),
                    "winner": reconcile(votes.get("AB", "INVALID"), votes.get("BA", "INVALID")),
                }
            )
    write_jsonl(run_dir / "verdicts.jsonl", out)
    write_json(
        run_dir / "artifacts.json",
        {
            "pairs.jsonl": digest(pairs),
            "verdicts.jsonl": digest(out),
            "raw_verdicts.jsonl": digest(raw),
            "generations.jsonl": digest(generations),
        },
    )
    return {"pairs": len(pairs), "verdicts": len(out)}
