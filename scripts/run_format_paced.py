"""Resume the v2 format diagnostic with longer HTTP-429 cooldowns.

Scheduling only: preserve the package code hash, scientific config, selected
pairs, payloads, providers, cached responses and the existing validation ledger.
No paid calls unless --execute is supplied. Ambiguous requests remain fatal.
"""

import argparse
import hashlib
import importlib.util
import math
import sys
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", default="runs/budget")
    parser.add_argument("--run-dir", default="runs/format-v2")
    parser.add_argument("--config", default="config/pilot_revision_v2.yaml")
    parser.add_argument("--items", type=int, default=10)
    parser.add_argument("--max-spend-usd", type=float, default=1)
    parser.add_argument("--interval-seconds", type=float, default=12)
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--rate-limit-cycles", type=int, default=8)
    parser.add_argument("--retry-delay-seconds", type=float, default=180)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be finite and positive")
    if not math.isfinite(args.interval_seconds) or args.interval_seconds < 6:
        parser.error("--interval-seconds must be finite and at least six")
    if not 1 <= args.rate_limit_cycles <= 16:
        parser.error("--rate-limit-cycles must be between 1 and 16")
    if not math.isfinite(args.retry_delay_seconds) or args.retry_delay_seconds < 30:
        parser.error("--retry-delay-seconds must be finite and at least 30")
    if not 0 < args.max_spend_usd <= 1 or not 1 <= args.items <= 10:
        parser.error("Keep the validation at 1–10 comparisons and a positive ceiling up to $1")

    spec = importlib.util.spec_from_file_location(
        "format_pacing_helpers", Path(__file__).with_name("run_paced.py")
    )
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)

    from afrijudge.cli import main as cli_main
    from afrijudge.client import Client

    directory = Path(args.run_dir)
    pacer = helpers.Pacer(args.interval_seconds, directory / "transport_events.jsonl")
    base = httpx.AsyncClient

    class PacedClient(base):
        async def post(self, url, **kwargs):
            kwargs.setdefault("timeout", args.timeout_seconds)
            return await pacer.post(super().post, url, **kwargs)

    previous_argv = sys.argv
    original_complete = Client.complete
    httpx.AsyncClient = PacedClient
    Client.complete = helpers.retry_rate_limits(
        helpers.filter_aware_completion(original_complete),
        cycles=args.rate_limit_cycles,
        delay=args.retry_delay_seconds,
        log=pacer.log,
    )
    sys.argv = [
        "afrijudge",
        "validate-format",
        "--source-run",
        args.source_run,
        "--run-dir",
        args.run_dir,
        "--config",
        args.config,
        "--items",
        str(args.items),
        "--max-spend-usd",
        str(args.max_spend_usd),
        "--interval-seconds",
        str(args.interval_seconds),
    ] + (["--execute"] if args.execute else [])
    try:
        if args.execute:
            pacer.log(
                {
                    "event": "paced_format_start",
                    "interval_seconds": args.interval_seconds,
                    "rate_limit_cycles": args.rate_limit_cycles,
                    "retry_delay_seconds": args.retry_delay_seconds,
                    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                }
            )
        print(
            "Paced format diagnostic: same saved run and $1 maximum ledger ceiling; "
            "longer bounded cooldowns for explicit rate limits only.",
            flush=True,
        )
        cli_main()
    finally:
        httpx.AsyncClient = base
        Client.complete = original_complete
        sys.argv = previous_argv


if __name__ == "__main__":
    main()
