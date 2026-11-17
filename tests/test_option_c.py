import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest
import yaml

from afrijudge.io import digest
from afrijudge.study.analysis import analyze
from afrijudge.study.benchmark import LANGUAGES, open_benchmark
from afrijudge.study.cli import judge_jobs, plan
from afrijudge.study.execution import dispatch
from afrijudge.study.num2words_afri import MATH_SYMBOL, number_text
from afrijudge.study.stimuli import (
    STYLES,
    Job,
    audit_sample,
    compile_pairs,
    h2_prompt_jobs,
    neutral_prose,
)

ROOT = Path(__file__).resolve().parents[1]


def _load(total=300):
    return open_benchmark(ROOT / "study" / f"benchmark-{total}.json.gz")


@pytest.mark.parametrize("total,calls", ((75, 7920), (300, 31680)))
def test_published_benchmark(total, calls):
    data = _load(total)
    p = plan(total, 6, 1024, 256)
    assert p["total_judge_calls"] == calls
    assert len({row["source_id"] for row in data["sources"]}) == total
    topics = [row for row in data["sources"] if "h2" in row]
    assert len(topics) == total // 5
    assert sum(len(h2_prompt_jobs(row, data["sha256"])) for row in topics) == 6 * len(topics)
    assert Counter(row["h2"]["original_lang"] for row in topics) == {
        lang: len(topics) // 3 for lang in LANGUAGES[1:]
    }
    if total == 300:
        assert Counter(row["dataset"] for row in data["sources"]) == {
            "facebook/belebele": 75,
            "masakhane/afrimmlu": 45,
            "masakhane/afrixnli": 30,
            "masakhane/afrimgsm": 75,
            "Davlan/sib200 + FLORES-200": 75,
        }
    xnli_groups = [r["group"] for r in data["sources"] if r["source_id"].startswith("xnli:")]
    assert len(xnli_groups) == len(set(xnli_groups))
    for group in data["sources"]:
        if group["domain"] == "flores":
            assert group["gold_category"] != group["foil_category"]
            assert group["sib200_sentences"]
        if group["domain"] == "mgsm":
            for v in group["language_sources"].values():
                assert not MATH_SYMBOL.search(v["prompt"])
    for lang in LANGUAGES:
        forms = {number_text(n, lang) for n in range(10001)}
        assert len(forms) == 10001
        assert all(not MATH_SYMBOL.search(text) for text in forms)


def test_math_answer_metadata_is_removed_and_checked():
    row = next(row for row in _load()["sources"] if row["domain"] == "mgsm")
    sample = row["language_sources"]["en"]
    out = {
        "correct": (
            f"The needed amount is {sample['gold_text']}. The values in the question show how "
            f"the amount was calculated. <answer>{sample['gold']}</answer>"
        ),
        "foil": (
            f"The needed amount is {sample['foil_text']}. The values used in the explanation "
            f"lead to the stated amount. <answer>{sample['foil']}</answer>"
        ),
    }
    prose = neutral_prose(json.dumps(out), row, "en")
    assert "<answer>" not in prose["correct"]
    out["correct"] = out["correct"].replace(sample["gold_text"], sample["gold"])
    with pytest.raises(ValueError, match="digit or an operator"):
        neutral_prose(json.dumps(out), row, "en")


def _protocol_pairs(data):
    """Exercise the full schedule offline with explicitly unit-test-only responses."""
    neutral, shortcuts, questions, passages, answers = {}, {}, {}, {}, {}
    for row in data["sources"]:
        for lang in LANGUAGES:
            sid = row["source_id"]
            v = row["language_sources"][lang]
            neutral[sid, lang] = {"correct": v["gold_text"], "foil": v["foil_text"]}
            if row["split"] == "test":
                shortcuts[sid, lang] = f"# {v['foil_text']}"
            if "h2" in row:
                passages[sid, lang] = row["h2"]["passage"]
                for style in STYLES:
                    questions[sid, lang, style] = row["h2"]["question"]
                    for model in row["h2_matchup"]:
                        answers[sid, lang, style, model] = row["h2"]["answer"]
    return compile_pairs(data, neutral, shortcuts, questions, passages, answers)


def test_full_schedule_position_mapping_report_and_audit():
    cfg = yaml.safe_load((ROOT / "config/option_c.yaml").read_text())
    data = _load()
    pairs = _protocol_pairs(data)
    assert len(audit_sample(pairs, cfg["seed"])) == 264
    jobs = judge_jobs(pairs, cfg["judges"], data["sha256"])
    assert len(jobs) == 31680
    assert len({digest(job) for job in jobs}) == len(jobs)
    records = []
    for job in jobs:
        order = job.meta["order"]
        visible = json.loads(job.messages[1]["content"])
        assert set(visible) == {"question", "RESPONSE_1", "RESPONSE_2"}
        label = "RESPONSE_1" if order == "AB" else "RESPONSE_2"
        records.append(
            {
                "meta": job.meta,
                "model_key": job.model,
                "status": "success",
                "finish_reason": "stop",
                "content": json.dumps({"verdict": label, "reasoning": "Checked."}),
            }
        )
    report = analyze(pairs, records, cfg)
    assert report["judge_calls"] == 31680
    assert report["invalid_judge_calls"] == 0
    assert report["pairs_by_dataset"]["masakhane/afrixnli"] == 216
    assert report["pairs_by_dataset"]["masakhane/afriqa"] == 480
    assert report["h3"]["overall"]["six_judge_majority"]["correct"] == 1920
    assert report["h2"]["paired_topic_contrasts"]["en_formal_minus_idiomatic"]["estimate"] == 0


def test_rate_limit_cooldown_keeps_other_route_moving(monkeypatch):
    from afrijudge.client import RateLimitExhausted
    from afrijudge.study import execution

    class Client:
        models = {name: {"slug": name, "provider": "deepinfra"} for name in ("first", "second")}

        def __init__(self):
            self.calls = []

        async def complete(self, model, messages, meta, max_tokens):
            self.calls.append(model)
            if self.calls == ["first"]:
                raise RateLimitExhausted("rate limit")
            return model

    client = Client()
    monkeypatch.setattr(execution, "RATE_LIMIT_COOLDOWNS", (0,))
    result = asyncio.run(
        dispatch(
            client,
            [Job(model, [], {}) for model in client.models],
            256,
            progress="test",
        )
    )
    assert client.calls == ["first", "second", "first"]
    assert result == ["first", "second"]


def test_original_domain2_profile_and_open_explanatory_prompts():
    data = open_benchmark(ROOT / "study/benchmark-300-afrimmlu.json.gz")
    assert data["domain2"] == "afrimmlu"
    assert Counter(r["dataset"] for r in data["sources"] if r["domain"] == "mmlu") == {
        "masakhane/afrimmlu": 75,
    }
    for item in data["sources"]:
        if item["domain"] == "flores":
            for row in item["language_sources"].values():
                assert "\nA)" not in row["prompt"] and "\nB)" not in row["prompt"]


def test_numeric_reference_checks_every_intermediate():
    from afrijudge.study.benchmark import checked_quantities

    assert checked_quantities(["5+7=12", "(5+7)/2=6"]) == {2, 5, 6, 7, 12}
    for steps in (["2-5+6=3"], ["(5/2)*2=5"], ["1000+1-1=1000"], ["4*2=9"]):
        with pytest.raises(ValueError):
            checked_quantities(steps)


def test_conclusion_style_and_sentence_gates():
    from afrijudge.study.stimuli import h2_output, shortcut_prose

    row = {
        "domain": "mmlu",
        "language_sources": {
            "en": {"gold": "A", "foil": "B", "gold_text": "soil erosion", "foil_text": "rainfall"},
        },
    }
    neutral = {
        "correct": (
            "The underlying issue here is runoff that removes the fertile layer over time. "
            "The observed change fits the predicted outcome. <answer>A</answer>"
        ),
        "foil": (
            "The underlying issue here is rainfall that accumulates in the area over time. "
            "The observed change fits the predicted outcome. <answer>B</answer>"
        ),
    }
    with pytest.raises(ValueError, match="omitted its designated conclusion"):
        neutral_prose(json.dumps(neutral), row, "en")
    neutral["correct"] = neutral["correct"].replace("runoff", "soil erosion")
    parsed = neutral_prose(json.dumps(neutral), row, "en")
    explanation = (
        "The source clearly shows rainfall as the explanation. "
        "This explanation relies on the details from the described event. "
        "The change appears across the area over time. "
        "The explanation connects the measured changes with the proposed cause in the question. "
        "It also considers how the observation applies across the area described in the passage."
    )
    raw = json.dumps({"shortcut": "# Summary\n" + explanation + " <answer>B</answer>"})
    with pytest.raises(ValueError, match="required formal transition"):
        shortcut_prose(raw, row, "en", parsed)
    raw = raw.replace(
        "The source clearly shows", "In accordance with the source, the evidence shows"
    )
    assert shortcut_prose(raw, row, "en", parsed).startswith("# Summary")
    sentences = [
        "Rainfall is the phenomenon mentioned in the study.",
        "The description explains its effect across the area.",
        "The changes appear over the same interval in the evidence.",
    ]
    assert h2_output(json.dumps({"sentences": sentences}), "answer", "en")
    with pytest.raises(ValueError, match="three to four complete sentences"):
        h2_output(json.dumps({"sentences": sentences + sentences}), "answer", "en")


def test_automatic_launch_freezes_pairs_and_audit_before_judging(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from afrijudge.study import analysis, cli

    cfg = yaml.safe_load((ROOT / "config/option_c.yaml").read_text())
    data = _load(75)
    pairs = _protocol_pairs(data)
    args = SimpleNamespace(
        command="study-run",
        auto_approve_programmatic=True,
        gen_max_tokens=1024,
        judge_max_tokens=256,
        interval_seconds=4,
    )

    async def catalog(http, config):
        return {"models": {}}

    async def assemble(client, data, cap):
        assert cap == 1024
        return pairs

    async def dispatch(client, jobs, cap, *, progress):
        assert (tmp_path / "pairs.json").is_file()
        assert (tmp_path / "review" / "stratified_audit.csv").read_text().count("PENDING") == 66
        assert cap == 256
        return [{}] * len(jobs)

    monkeypatch.setattr(cli, "catalog", catalog)
    monkeypatch.setattr(cli, "_assemble", assemble)
    monkeypatch.setattr(cli, "dispatch", dispatch)
    monkeypatch.setattr(analysis, "analyze", lambda pairs, records, config: {})
    result = asyncio.run(cli._locked_paid(args, tmp_path, data, cfg, plan(75, 6, 1024, 256), 1, ""))
    assert result["mode"] == "complete" and result["judge_calls"] == 7920
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["approval"] == {"method": "programmatic", "audit_pairs": 66}
