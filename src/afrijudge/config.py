"""Configuration validation shared by planning and execution."""

import math
from pathlib import Path

import yaml

from afrijudge.io import digest

LANGUAGES = {"en": "English", "ha": "Hausa", "yo": "Yoruba", "ig": "Igbo", "sw": "Swahili"}


def load_config(path: str | Path) -> dict:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Expected schema_version: 1")
    if not config.get("languages") or set(config["languages"]) - LANGUAGES.keys():
        raise ValueError("Unsupported or empty languages")
    if "en" not in config["languages"]:
        raise ValueError("English parallel control is required")
    for key in ("budget_limit_usd", "concurrency", "generation_max_tokens", "judge_max_tokens"):
        if not math.isfinite(float(config[key])) or config[key] <= 0:
            raise ValueError(f"{key} must be finite and positive")
    for key in ("concurrency", "generation_max_tokens", "judge_max_tokens", "seed"):
        if type(config[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    for role in ("generators", "judges"):
        keys = config[role]
        if not keys or len(keys) != len(set(keys)):
            raise ValueError(f"Empty or duplicate {role}")
        for key in keys:
            model = config["models"][key]
            if "/" not in model["slug"] or not model["family"]:
                raise ValueError(f"Invalid model: {key}")
            if model.get("quantizations") and not set(model["quantizations"]) <= {
                "bf16",
                "fp16",
                "fp8",
            }:
                raise ValueError("Explicit precision configuration required")
        if len({config["models"][key]["family"] for key in keys}) != len(keys):
            raise ValueError(f"{role} must contain distinct families for this pilot")
    for key, size in config["samples"].items():
        if type(size) is not int or size < 0:
            raise ValueError(f"Invalid sample size: {key}")
    for source in config["datasets"].values():
        revision = source.get("revision", source.get("sha256", ""))
        expected = 40 if "revision" in source else 64
        if len(revision) != expected or any(c not in "0123456789abcdef" for c in revision):
            raise ValueError(
                "Datasets require immutable commit hashes or archive SHA-256 checksums"
            )
    config["config_hash"] = digest(config)
    return config
