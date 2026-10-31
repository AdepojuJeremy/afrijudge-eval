import asyncio
import json
from pathlib import Path

import pytest

from afrijudge.config import load_config
from afrijudge.data import parse_verifiable
from afrijudge.demo import demo
from afrijudge.io import read_jsonl
from afrijudge.pipeline import candidate, make_pair, probe_pairs
from afrijudge.stats import analyze


@pytest.fixture
def config():
    return load_config(Path(__file__).parents[1] / "config/pilot_config.yaml")


def test_real_source_schema_and_missing_gold_fail():
    raw = "question\tchoices\tanswer\tsubject\nQ?\t['x', 'y', 'z', 'w']\tB\tmath\n"
    assert parse_verifiable(raw, "mmlu")[0]["gold"] == "B"
    with pytest.raises(ValueError):
        parse_verifiable(raw.replace("\tB\t", "\t\t"), "mmlu")


def test_both_candidates_changed_and_gold_cleared(config):
    base = make_pair(
        {"lang": "yo", "item_id": "mmlu:1", "prompt": "q"},
        candidate("ẹ́", "g1", "one", True),
        candidate("ọ̀", "g2", "two", False),
        "correct_vs_incorrect",
        "A",
        42,
    )
    probes = probe_pairs(config, [base])
    assert len(probes) == 3
    for p in probes:
        if p["condition"].startswith("strip=1"):
            assert p["gold"] is None
            assert p["a"]["text"] != base["a"]["text"]
            assert p["b"]["text"] != base["b"]["text"]
            assert p["a"]["features"]["utf8_bytes"] == len(p["a"]["text"].encode())


def test_nonchanging_unicode_is_not_probe(config):
    base = make_pair(
        {"lang": "yo", "item_id": "i", "prompt": "q"},
        candidate("plain", "a", "one"),
        candidate("ascii", "b", "two"),
        "both_incorrect",
        None,
        42,
    )
    assert probe_pairs(config, [base]) == []


def test_all_three_experiments_end_to_end_and_annotation_guard(tmp_path, config):
    directory = tmp_path / "demo"
    asyncio.run(demo(directory, config))
    report = json.loads((directory / "report.json").read_text())
    assert report["status"] == "SYNTHETIC_DEMO_NOT_RESEARCH_RESULTS"
    assert {p["experiment"] for p in read_jsonl(directory / "pairs.jsonl")} == {
        "exp1",
        "exp2",
        "exp3",
    }
    assert all(
        g["validity"]["n_gold_pairs"] == 0 for g in report["groups"] if g["experiment"] == "exp2"
    )
    reviews = read_jsonl(directory / "foil_review.jsonl")
    reviews[0].update(
        {"gold": "A", "reviewer": "reviewer", "notes": "checked", "content_hash": "wrong"}
    )
    (directory / "foil_review.jsonl").write_text("\n".join(json.dumps(r) for r in reviews))
    with pytest.raises(ValueError, match="hash mismatch"):
        analyze(directory, config)
