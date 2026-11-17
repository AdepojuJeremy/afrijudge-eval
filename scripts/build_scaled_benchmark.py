"""Build the pinned 75- or 300-source Option C benchmark."""

import argparse
import json
from pathlib import Path

from afrijudge.study.benchmark import (
    DOMAIN2_PROFILES,
    TIERS,
    benchmark_path,
    build,
    read_exclusions,
    write_benchmark,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--total-sources", type=int, choices=TIERS, default=300)
    parser.add_argument("--domain2", choices=DOMAIN2_PROFILES, default="mixed")
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/option-c-cache"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--exclude", action="append", type=Path, default=[])
    args = parser.parse_args()
    exclusions = set().union(
        *(read_exclusions(path) for path in [Path("study/excluded_source_ids.json"), *args.exclude])
    )
    data = build(args.cache_dir, args.total_sources, args.seed, exclusions, domain2=args.domain2)
    output = args.output or benchmark_path(args.total_sources, args.domain2)
    write_benchmark(output, data)
    print(
        json.dumps(
            {
                "output": str(output),
                "verified_sources": data["total_sources"],
                "domain2": data["domain2"],
                "eligible_counts": data["eligible_counts"],
                "excluded_source_ids": len(data["excluded_source_ids"]),
                "sha256": data["sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
