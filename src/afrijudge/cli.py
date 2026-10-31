"""Command-line entry points; paid execution is always explicit."""

import argparse
import asyncio
import contextlib
import fcntl
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import httpx

from afrijudge import __version__
from afrijudge.client import Client, Ledger, catalog
from afrijudge.config import load_config
from afrijudge.data import prepare
from afrijudge.io import digest, write_json, write_jsonl
from afrijudge.pipeline import plan, run
from afrijudge.stats import analyze


def code_hash() -> str:
    return digest({p.name: p.read_text() for p in sorted(Path(__file__).parent.glob("*.py"))})


@contextlib.contextmanager
def run_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another process is using this run directory") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


async def execute(args, config: dict):
    directory, data_dir = Path(args.run_dir), Path(args.data)
    if not args.execute:
        print(json.dumps(plan(config), indent=2))
        print("Planning only. Add --execute to make paid API calls.")
        return
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "Set OPENROUTER_API_KEY locally in your environment; never put it in config"
        )
    with run_lock(directory):
        data_manifest = prepare(config, data_dir)
        manifest_path = directory / "manifest.json"
        identity = {
            "config_hash": config["config_hash"],
            "data_hash": digest(data_manifest),
            "code_hash": code_hash(),
            "mode": "real_api",
        }
        if manifest_path.exists():
            old = json.loads(manifest_path.read_text())
            if old["identity"] != identity:
                raise ValueError("Run configuration, data, or code changed; use a new --run-dir")
        else:
            try:
                commit = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
                ).strip()
            except (subprocess.CalledProcessError, FileNotFoundError):
                commit = None
            write_json(
                manifest_path,
                {
                    "identity": identity,
                    "config": config,
                    "version": __version__,
                    "git_commit": commit,
                    "python": platform.python_version(),
                    "dependencies": {
                        name: importlib.metadata.version(name)
                        for name in ("httpx", "numpy", "PyYAML")
                    },
                },
            )
        ledger = Ledger(directory / "ledger.sqlite", config["budget_limit_usd"])
        try:
            if ledger.unresolved():
                raise RuntimeError(
                    "Unresolved potentially billed requests; inspect with afrijudge status"
                )
            async with httpx.AsyncClient(
                timeout=config["timeout_seconds"], follow_redirects=False
            ) as http:
                lock_path = directory / "models.lock.json"
                if lock_path.exists():
                    model_lock = json.loads(lock_path.read_text())
                else:
                    model_lock = await catalog(http, config)
                    write_json(lock_path, model_lock)
                manifest = json.loads(manifest_path.read_text())
                locked_hash = digest(model_lock)
                if manifest.get("model_lock_hash", locked_hash) != locked_hash:
                    raise ValueError("Model lock changed within a run; use a new run directory")
                manifest["model_lock_hash"] = locked_hash
                write_json(manifest_path, manifest)
                client = Client(http, ledger, config, model_lock, api_key)
                await run(config, data_dir, directory, client)
            report = analyze(directory, config)
            report["spend_usd"] = ledger.spent
            report["model_lock_hash"] = digest(model_lock)
            write_json(directory / "report.json", report)
        finally:
            write_jsonl(directory / "requests.jsonl", ledger.records())
            ledger.close()
    print(f"Completed. Read {directory / 'report.json'}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="AfriJudge-Eval reproducible pilot suite")
    subs = root.add_subparsers(dest="command", required=True)
    for name in ("plan", "prepare", "preflight", "run", "analyze", "status", "demo"):
        sub = subs.add_parser(name)
        sub.add_argument("--config", default="config/pilot_config.yaml")
        sub.add_argument("--data", default="data/pilot")
        sub.add_argument("--run-dir", default="runs/pilot")
        if name == "run":
            sub.add_argument("--execute", action="store_true", help="Enable paid API calls")
        if name in ("run", "prepare", "plan", "preflight"):
            sub.add_argument(
                "--smoke",
                action="store_true",
                help="Small REAL-data subset; use separate data/run dirs",
            )
    return root


def main():
    args = parser().parse_args()
    try:
        config = load_config(args.config)
        if getattr(args, "smoke", False):
            config["samples"] = dict.fromkeys(config["samples"], 1)
            config.pop("config_hash")
            config["config_hash"] = digest(config)
        if args.command == "plan":
            print(json.dumps(plan(config), indent=2))
        elif args.command == "prepare":
            print(json.dumps(prepare(config, Path(args.data)), indent=2))
        elif args.command == "preflight":

            async def check():
                async with httpx.AsyncClient(timeout=60) as http:
                    return await catalog(http, config)

            result = asyncio.run(check())
            print(json.dumps(result, indent=2))
        elif args.command == "run":
            asyncio.run(execute(args, config))
        elif args.command == "analyze":
            # Analyze using the actual run config, including smoke overrides.
            directory = Path(args.run_dir)
            manifest = json.loads((directory / "manifest.json").read_text())
            analyze(directory, manifest["config"])
            print(f"Updated {directory / 'report.json'}")
        elif args.command == "status":
            ledger = Ledger(Path(args.run_dir) / "ledger.sqlite", config["budget_limit_usd"])
            try:
                print(
                    json.dumps(
                        {
                            "spent_or_reserved_usd": ledger.spent,
                            "unresolved": ledger.unresolved(),
                            "completed_requests": len(ledger.records()),
                        },
                        indent=2,
                    )
                )
            finally:
                ledger.close()
        elif args.command == "demo":
            from afrijudge.demo import demo

            asyncio.run(demo(Path(args.run_dir), config))
    except (ValueError, RuntimeError, OSError, KeyError, httpx.HTTPError) as exc:
        # Never dump an HTTP request or its Authorization header on failure.
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
