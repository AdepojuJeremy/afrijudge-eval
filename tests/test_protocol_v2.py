import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from afrijudge.config import load_config
from afrijudge.demo import demo
from afrijudge.format_validation import select_pairs, source_spend, summarize, validate
from afrijudge.io import digest, read_jsonl, write_json, write_jsonl
from afrijudge.judge_v2 import messages, parse, parse_record
from afrijudge.prompts import judge_messages, judge_version
from afrijudge.text import reconcile, verdict

ROOT = Path(__file__).parents[1]


def pair(lang="en", index=0):
    return {
        "pair_id": f"{lang}:mmlu:{index}:both_incorrect",
        "lang": lang,
        "item_id": f"mmlu:{index}",
        "experiment": "exp1",
        "prompt_lang": "en",
        "prompt": "Q? A) x B) y C) z D) w",
        "a": {"text": "one"},
        "b": {"text": "two"},
    }


@pytest.mark.parametrize(
    "label,expected", [("RESPONSE_1", "A"), ("RESPONSE_2", "B"), ("TIE", "TIE")]
)
def test_v2_labels_and_order_mapping(label, expected):
    assert parse(json.dumps({"verdict": label, "reasoning": "A short reason."})) == (
        expected,
        "valid",
    )
    a = json.loads(messages(pair(), "AB")[-1]["content"])
    b = json.loads(messages(pair(), "BA")[-1]["content"])
    assert a["RESPONSE_1"] == b["RESPONSE_2"] == "one"
    assert "A" not in a
    assert reconcile("A", "A") == "ORDER_UNSTABLE"
    assert reconcile("TIE", "A") == "ORDER_UNSTABLE"


@pytest.mark.parametrize(
    "text",
    [
        '{"verdict":"Both are wrong","reasoning":"x"}',
        '{"verdict":"C","reasoning":"x"}',
        '{"verdict":"A","reasoning":"x"}',
        '{"verdict":"RESPONSE_1","verdict":"RESPONSE_2","reasoning":"x"}',
        'Example {"verdict":"RESPONSE_1","reasoning":"x"}',
        '{"reasoning":"x","verdict":"RESPONSE_1"}',
        '{"verdict":"RESPONSE_1","reasoning":"x","extra":1}',
        '{"verdict":["RESPONSE_1"],"reasoning":"x"}',
        '{"verdict":"RESPONSE_1","reasoning":""}',
    ],
)
def test_v2_rejects_ambiguous_or_noncompliant_outputs(text):
    assert parse(text)[0] == "INVALID"


def test_truncation_and_word_limit_remain_invalid():
    text = json.dumps({"verdict": "RESPONSE_1", "reasoning": "word " * 41})
    assert parse(text) == ("INVALID", "reasoning_word_limit")
    text = '{"verdict":"RESPONSE_1","reasoning":"short"}'
    assert (
        parse_record({"status": "invalid_completion", "finish_reason": "length", "content": text})[
            0
        ]
        == "INVALID"
    )
    assert parse_record({"status": "success", "content": text})[0] == "INVALID"


def test_old_protocol_stays_default_and_parser_is_not_relaxed():
    config = load_config(ROOT / "config/pilot_budget.yaml")
    assert judge_version(config) == "1"
    assert "A" in json.loads(judge_messages(pair(), "AB")[-1]["content"])
    assert verdict('Preamble {"verdict":"A"}') == "INVALID"
    revised = load_config(ROOT / "config/pilot_revision_v2.yaml")
    assert judge_version(revised) == "2"
    assert set(revised["judges"]) == set(config["judges"])
    assert "mmlu:398" in revised["excluded_source_items"]


def test_v2_demo_runs_all_conditions(tmp_path):
    config = load_config(ROOT / "config/pilot_revision_v2.yaml")
    asyncio.run(demo(tmp_path / "demo", config))
    raw = read_jsonl(tmp_path / "demo/raw_verdicts.jsonl")
    assert raw and all(r["parse_diagnostic"] == "valid" for r in raw)
    assert all(r["prompt_version"] == "2" for r in raw)


def test_stratified_selection_ignores_input_order_and_excludes_sources():
    config = load_config(ROOT / "config/pilot_revision_v2.yaml")
    pairs = [pair(lang, i) for lang in config["languages"] for i in [1, 2, 3, 398]]
    a = select_pairs(pairs, config, 10)
    assert a == select_pairs(list(reversed(pairs)), config, 10)
    assert len(a) == 10 and {p["lang"] for p in a} == set(config["languages"])
    assert all(p["item_id"] != "mmlu:398" for p in a)


def test_validation_dry_run_makes_no_requests_or_output_directory(tmp_path, monkeypatch):
    import httpx

    async def forbid(*args, **kwargs):
        raise AssertionError("Dry run contacted API")

    monkeypatch.setattr(httpx.AsyncClient, "post", forbid)
    monkeypatch.setattr(httpx.AsyncClient, "get", forbid)
    cfg = load_config(ROOT / "config/pilot_revision_v2.yaml")
    source = tmp_path / "original"
    source.mkdir()
    write_jsonl(
        source / "pairs.jsonl", [pair(lang, i) for lang in cfg["languages"] for i in range(4)]
    )
    write_json(source / "models.lock.json", {"models": cfg["models"]})
    args = SimpleNamespace(
        source_run=source,
        run_dir=tmp_path / "validation",
        items=10,
        max_spend_usd=1.0,
        interval_seconds=12,
        execute=False,
    )
    result = asyncio.run(validate(args, cfg))
    assert result["judge_calls"] == 120
    assert not args.run_dir.exists()


def test_read_only_source_accounting_includes_uncertain_reservations(tmp_path):
    from afrijudge.client import Ledger

    ledger = Ledger(tmp_path / "ledger.sqlite", 45)
    ledger.reserve("uncertain", 0.1)
    assert source_spend(tmp_path) == 0.1
    assert ledger.unresolved() == ["uncertain"]
    ledger.close()


def test_format_report_separates_truncation_from_quality_tie():
    p = pair()
    recs = [
        {
            "model_key": "m",
            "meta": {"pair_id": p["pair_id"], "order": order},
            "status": "success",
            "finish_reason": "stop",
            "content": '{"verdict":"TIE","reasoning":"Equal quality."}',
        }
        for order in ["AB", "BA"]
    ]
    report = summarize(recs, [p], ["m"])
    assert report["reconciled_counts"] == {"TIE": 1}
    recs[0].update(status="invalid_completion", finish_reason="length")
    assert summarize(recs, [p], ["m"])["reconciled_counts"] == {"INVALID": 1}


@pytest.mark.parametrize("excluded", [["bad:1"], ["mgsm:x"], ["mgsm:1", "mgsm:1"], "mmlu:1"])
def test_bad_exclusion_configuration_rejected(tmp_path, excluded):
    import yaml

    cfg = copy.deepcopy(load_config(ROOT / "config/pilot_budget.yaml"))
    cfg.pop("config_hash")
    cfg["excluded_source_items"] = excluded
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match="excluded_source_items"):
        load_config(path)


def test_exclusion_list_changes_fingerprint():
    a = load_config(ROOT / "config/pilot_budget.yaml")
    b = {**a, "excluded_source_items": ["mmlu:398"]}
    assert digest({k: a[k] for k in ("datasets", "languages", "samples", "seed")}) != digest(
        {k: b[k] for k in ("datasets", "languages", "samples", "seed", "excluded_source_items")}
    )


def test_mock_validation_keeps_pilot_ledger_and_reuses_cache(tmp_path, monkeypatch):
    import httpx

    from afrijudge.client import Ledger

    cfg = load_config(ROOT / "config/pilot_revision_v2.yaml")
    source = tmp_path / "pilot"
    source.mkdir()
    write_jsonl(source / "pairs.jsonl", [pair()])
    models = copy.deepcopy(cfg["models"])
    for model in models.values():
        model.update(
            provider="test/provider", pricing={"prompt": "0.000001", "completion": "0.000002"}
        )
    write_json(source / "models.lock.json", {"models": models})
    write_json(source / "manifest.json", {"config": {"budget_limit_usd": 45}})
    old = Ledger(source / "ledger.sqlite", 45)
    old.reserve("original", 14)
    old.finish("original", 13.80, {"status": "success", "content": "pilot remains"})
    old.close()
    calls = []

    def handle(request):
        calls.append(request)
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "model": payload["model"],
                "provider": "test/provider",
                "choices": [
                    {
                        "message": {"content": '{"verdict":"TIE","reasoning":"Equal."}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"cost": 0.0001},
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )

    async def no_wait(*args):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-secret")
    args = SimpleNamespace(
        source_run=source,
        run_dir=tmp_path / "validation",
        items=1,
        max_spend_usd=0.05,
        interval_seconds=12,
        execute=True,
    )
    for _ in range(2):
        result = asyncio.run(validate(args, cfg))
        assert result["completed_response_records"] == 12
        assert result["reconciled_counts"] == {"TIE": 6}
    assert len(calls) == 12  # Second invocation sends no POSTs.
    assert source_spend(source) == 13.8
    assert "test-only-secret" not in (args.run_dir / "requests.jsonl").read_text()
    assert json.loads((source / "manifest.json").read_text()) == {
        "config": {"budget_limit_usd": 45}
    }


def test_quarantine_cannot_reenter_through_duplicate_source_text():
    from afrijudge.data import eligible_parallel_indices

    tables = {
        lang: [
            {"item_id": f"mmlu:{i}", "prompt": f"{lang}:{text}"}
            for i, text in enumerate(["defective", "defective", "good"])
        ]
        for lang in ["en", "ha"]
    }
    assert eligible_parallel_indices(tables, "mmlu", []) == [0, 2]
    assert eligible_parallel_indices(tables, "mmlu", ["mmlu:0"]) == [2]
    with pytest.raises(ValueError, match="Unknown excluded"):
        eligible_parallel_indices(tables, "mmlu", ["mmlu:999"])
