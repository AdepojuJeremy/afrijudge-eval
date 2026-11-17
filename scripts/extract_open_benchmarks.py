"""Extract the open benchmark pools with verified language alignment and checksums."""

import argparse
import json
from pathlib import Path

from afrijudge.io import write_json, write_jsonl
from afrijudge.study.benchmark import (
    afriqa,
    belebele,
    flores,
    mgsm,
    mmlu,
    read_exclusions,
    sib200,
    xnli,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/option-c-cache"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/open-benchmarks"))
    parser.add_argument("--exclude", action="append", type=Path, default=[])
    args = parser.parse_args()
    paths = [Path("study/excluded_source_ids.json"), *args.exclude]
    exclusions = set().union(*(read_exclusions(path) for path in paths))
    origin, counts = [], {}
    for name, loader in (
        ("belebele", belebele),
        ("afrimmlu", mmlu),
        ("afrimgsm", mgsm),
        ("afrixnli", xnli),
        ("sib200", sib200),
        ("flores_sib200", flores),
        ("afriqa", afriqa),
    ):
        if name in ("afrimmlu", "afrimgsm"):
            rows = loader(args.cache_dir, origin, exclusions)
        else:
            rows = loader(args.cache_dir, origin)
        available = [r for r in rows if r.get("source_id", r.get("topic_id")) not in exclusions]
        write_jsonl(args.output_dir / f"{name}.jsonl", available)
        counts[name] = len(available)
    write_json(
        args.output_dir / "manifest.json",
        {
            "counts": counts,
            "upstream": list({row["url"]: row for row in origin}.values()),
            "excluded_source_ids": sorted(exclusions),
        },
    )
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
