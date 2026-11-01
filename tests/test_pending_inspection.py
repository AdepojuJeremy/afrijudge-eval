import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest

from afrijudge.client import AmbiguousRequest, Client, Ledger
from afrijudge.prompts import foil_messages, generation_messages, judge_messages

SPEC = importlib.util.spec_from_file_location(
    "inspect_pending", Path(__file__).parents[1] / "scripts/inspect_pending.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def test_pending_hash_matches_real_client_with_reasoning_and_precision(tmp_path):
    item = {"item_id": "mmlu:1", "lang": "yo", "prompt": "Question?"}
    config = {"generators": ["m"], "concurrency": 1, "generation_max_tokens": 768, "seed": 42}
    lock = {
        "models": {
            "m": {
                "slug": "test/model",
                "provider": "test/fp8",
                "quantizations": ["bf16", "fp8"],
                "quantization": "fp8",
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
                "reasoning": {"max_tokens": 128},
                "supported_parameters": ["seed"],
            }
        }
    }
    key, meta = next(helper.generation_requests(config, lock, [item]))

    async def case():
        def timeout(request):
            raise httpx.ReadTimeout("uncertain")

        ledger = Ledger(tmp_path / "ledger.sqlite", 1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
            client = Client(http, ledger, config, lock, "test-key")
            with pytest.raises(AmbiguousRequest):
                await client.complete(
                    "m",
                    generation_messages(item),
                    {k: meta[k] for k in ("stage", "item_id", "lang", "prompt_version")},
                    768,
                )
        assert ledger.unresolved() == [key]
        ledger.close()

    asyncio.run(case())


@pytest.mark.parametrize("stage", ["foil", "judge"])
def test_later_stage_hashes_match_actual_client(tmp_path, stage):
    config = {
        "generators": ["m"],
        "judges": ["m"],
        "concurrency": 1,
        "generation_max_tokens": 768,
        "judge_max_tokens": 256,
        "seed": 42,
    }
    lock = {
        "models": {
            "m": {
                "slug": "test/model",
                "provider": "test/fp8",
                "quantizations": ["bf16", "fp8"],
                "quantization": "fp8",
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
                "supported_parameters": ["seed"],
            }
        }
    }
    if stage == "foil":
        item = {"item_id": "flores:1", "lang": "yo", "en_source": "source"}
        key, details = next(helper.foil_requests(config, lock, [item]))
        meta = {k: details[k] for k in ("stage", "item_id", "lang", "condition", "prompt_version")}
        messages, max_tokens = foil_messages(item, "plain_error"), 768
    else:
        pair = {
            "pair_id": "yo:mmlu:1",
            "item_id": "mmlu:1",
            "lang": "yo",
            "prompt": "original",
            "a": {"text": "one"},
            "b": {"text": "two"},
        }
        key, details = next(helper.judge_requests(config, lock, [pair]))
        meta = {k: details[k] for k in ("stage", "pair_id", "order", "prompt_version")}
        messages, max_tokens = judge_messages(pair, "AB"), 256

    async def case():
        def timeout(request):
            raise httpx.ReadTimeout("uncertain")

        ledger = Ledger(tmp_path / "ledger.sqlite", 1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
            client = Client(http, ledger, config, lock, "test-key")
            with pytest.raises(AmbiguousRequest):
                await client.complete("m", messages, meta, max_tokens)
        assert ledger.unresolved() == [key]
        ledger.close()

    asyncio.run(case())
