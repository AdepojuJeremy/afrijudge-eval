"""Explicitly synthetic offline plumbing exercise, never a source of research results."""

import copy
import json
from pathlib import Path

from afrijudge.io import digest, write_json, write_jsonl
from afrijudge.pipeline import run
from afrijudge.stats import analyze
from afrijudge.text import answer


class DemoClient:
    def __init__(self, config):
        self.config = config

    async def complete(self, key, messages, meta, max_tokens):
        if meta["stage"] == "generation":
            correct = self.config["generators"].index(key) % 2 == 0
            value = (
                ("B" if correct else "C")
                if meta["item_id"].startswith("mmlu")
                else ("4" if correct else "5")
            )
            text = f"Ìdáhùn àpẹẹrẹ. Ọmụmaatụ. <answer>{value}</answer>"
        elif meta["stage"] == "foil":
            text = "Ìdáhùn àpẹẹrẹ tí kò tọ́. Ọmụmaatụ na-ezighi ezi."
        else:
            data = json.loads(messages[-1]["content"])
            task = "mmlu" if "mmlu" in meta["pair_id"] else "mgsm"
            correct = "B" if task == "mmlu" else "4"
            if "RESPONSE_1" in data:
                winner = (
                    "RESPONSE_1" if answer(data["RESPONSE_1"], task) == correct else "RESPONSE_2"
                )
                text = json.dumps({"verdict": winner, "reasoning": "SYNTHETIC DEMO ONLY"})
            else:
                winner = "A" if answer(data["A"], task) == correct else "B"
                text = json.dumps({"reasoning": "SYNTHETIC DEMO ONLY", "verdict": winner})
        return {
            "status": "success",
            "finish_reason": "stop",
            "content": text,
            "meta": meta,
            "model_key": key,
            "request_id": digest({"messages": messages, "meta": meta, "key": key}),
        }


async def demo(directory: Path, config: dict):
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Demo requires a new empty run directory")
    config = copy.deepcopy(config)
    config["samples"] = dict.fromkeys(config["samples"], 1)
    data_dir = directory / "synthetic_data"
    items = [
        {
            "item_id": f"{task}:demo",
            "lang": lang,
            "task": task,
            "prompt": "SYNTHETIC: 2 + 2? A) 3 B) 4 C) 5 D) 6",
            "gold": "B" if task == "mmlu" else "4",
        }
        for lang in config["languages"]
        for task in ("mmlu", "mgsm")
    ]
    translations = [
        {
            "item_id": "demo:reference",
            "lang": lang,
            "en_source": "DEMO ONLY",
            "reference": "Àpẹẹrẹ. Ọmụmaatụ.",
            "source": {"type": "SYNTHETIC"},
            "reference_provenance": "SYNTHETIC_NOT_HUMAN",
        }
        for lang in config["languages"]
        if lang != "en"
    ]
    write_jsonl(data_dir / "exp1.jsonl", items)
    write_jsonl(data_dir / "exp2.jsonl", translations)
    write_json(directory / "manifest.json", {"mode": "synthetic_demo", "config": config})
    await run(config, data_dir, directory, DemoClient(config))
    report = analyze(directory, config)
    report["status"] = "SYNTHETIC_DEMO_NOT_RESEARCH_RESULTS"
    write_json(directory / "report.json", report)
    print(f"Offline demo complete: {directory / 'report.json'} (not research results)")
