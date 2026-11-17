"""Extract open benchmarks into portable per-source JSONL records."""

import argparse
import json
from pathlib import Path

from afrijudge.io import digest, write_json, write_jsonl
from afrijudge.study.benchmark import (
    CATEGORIES,
    PINNED,
    afriqa,
    belebele,
    flores,
    mgsm,
    mmlu,
    read_exclusions,
    sib200,
    source_aliases,
    xnli,
)

POOLS = {
    "belebele": (belebele, "belebele", "belebele", "CC-BY-SA-4.0"),
    "afrimmlu": (mmlu, "mmlu", "conceptual", "Apache-2.0"),
    "afrimgsm": (mgsm, "mgsm", "arithmetic", "Apache-2.0"),
    "afrixnli": (xnli, "xnli", "logical", "Apache-2.0"),
    "sib200": (sib200, "sib200", "explanatory", "CC-BY-SA-4.0"),
    "flores_sib200": (flores, "sib200", "explanatory", "CC-BY-SA-4.0"),
    "afriqa": (afriqa, "afriqa", "open_qa", "CC-BY-SA-4.0"),
}


def _afriqa_row(row):
    return {
        **{key: val for key, val in row.items() if key != "topic_id"},
        "language_sources": {
            row["original_lang"]: {
                "question": row["question"],
                "answer": row["answer"],
                "provenance": "human_authored",
            },
            "en": {
                "question": row["english_question"],
                "answers": row["english_answers"],
                "passage": row["passage"],
                "provenance": "human_translation",
            },
        },
    }


def format_row(name: str, row: dict) -> dict:
    """Return dataset fields separately from the internal runner's model prompts."""
    _, pin, domain, license_name = POOLS[name]
    result = {
        "source_id": row.get("source_id") or row["topic_id"],
        "domain": domain,
        "dataset": row.get("dataset", PINNED[pin][0]),
        "license": license_name,
    }
    if name == "afriqa":
        return {**result, **_afriqa_row(row)}
    fields = {
        "belebele": ("passage", "question", "choices", "gold_text", "foil_text"),
        "afrimmlu": ("question", "choices", "gold_text", "foil_text"),
        "afrimgsm": ("question",),
        "afrixnli": ("premise", "hypothesis", "label"),
        "flores_sib200": ("passage", "question", "choices", "gold_category", "foil_category"),
    }
    result["language_sources"] = variants = {}
    for lang, v in row["language_sources"].items():
        if name == "sib200":
            cat = v["category"]
            foil = next(other for other in CATEGORIES if other != cat)
            variants[lang] = {"passage": v["text"], "gold_category": cat, "foil_category": foil}
        else:
            variants[lang] = {k: v[k] for k in fields[name]}
        if name == "afrimgsm":
            variants[lang].update(
                gold_int=int(v["gold"]),
                foil_int=int(v["foil"]),
                question_words=v["prompt"],
            )
        if name == "afrimmlu":
            variants[lang]["subject"] = row["subject"]
    if name == "afrimgsm":
        en = variants["en"]
        result.update(gold=en["gold_int"], foil=en["foil_int"])
    for key in ("article", "question_number", "sentence_rows", "sib200_sentences"):
        if key in row:
            result[key] = row[key]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/option-c-cache"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/open-benchmarks"))
    parser.add_argument("--exclude", action="append", type=Path, default=[])
    args = parser.parse_args()
    paths = [Path("study/excluded_source_ids.json"), *args.exclude]
    exclusions = set().union(*(read_exclusions(path) for path in paths))
    origin, counts, hashes = [], {}, {}
    for name, (loader, _, _, _) in POOLS.items():
        if name in ("afrimmlu", "afrimgsm"):
            rows = loader(args.cache_dir, origin, exclusions)
        else:
            rows = loader(args.cache_dir, origin)
        available = [format_row(name, row) for row in rows if not exclusions & source_aliases(row)]
        write_jsonl(args.output_dir / f"{name}.jsonl", available)
        counts[name], hashes[name] = len(available), digest(available)
    write_json(
        args.output_dir / "manifest.json",
        {
            "schema": 2,
            "counts": counts,
            "hashes": hashes,
            "upstream": list({row["url"]: row for row in origin}.values()),
            "excluded_source_ids": sorted(exclusions),
        },
    )
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
