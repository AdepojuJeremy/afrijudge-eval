import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from afrijudge.client import Client, Ledger

SPEC = importlib.util.spec_from_file_location(
    "filtered_launcher", Path(__file__).parents[1] / "scripts/run_paced.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def setup_client(tmp_path, response):
    pacer = launcher.Pacer(0.001, tmp_path / "transport_events.jsonl")
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return response

    class PacedHTTP(httpx.AsyncClient):
        async def post(self, url, **kwargs):
            return await pacer.post(super().post, url, **kwargs)

    http = PacedHTTP(transport=httpx.MockTransport(handler))
    ledger = Ledger(tmp_path / "ledger.sqlite", 1)
    lock = {
        "models": {
            "m": {
                "slug": "test/model",
                "family": "test",
                "provider": "fixed",
                "pricing": {"prompt": 0.000001, "completion": 0.000002},
            }
        }
    }
    client = Client(http, ledger, {"concurrency": 1, "seed": 42}, lock, "secret-key")
    return client, http, ledger, calls


def test_only_structured_filter_code_is_recognized():
    assert launcher.is_content_filter(
        httpx.Response(400, json={"error": {"code": "content_filter"}})
    )
    assert not launcher.is_content_filter(
        httpx.Response(400, json={"error": {"message": "content_filter"}})
    )
    assert not launcher.is_content_filter(
        httpx.Response(429, json={"error": {"code": "content_filter"}})
    )


def test_filter_is_missing_cached_and_budgeted_without_changing_payload(tmp_path):
    async def case():
        response = httpx.Response(
            400,
            json={
                "error": {
                    "message": "Provider returned error",
                    "metadata": {
                        "raw": json.dumps(
                            {"error": {"code": "content_filter", "message": "filtered"}}
                        )
                    },
                }
            },
        )
        client, http, ledger, calls = setup_client(tmp_path, response)
        wrapped = launcher.filter_aware_completion(Client.complete)
        messages = [{"role": "user", "content": "original question"}]
        meta = {"stage": "generation", "lang": "en", "item_id": "mmlu:1"}
        async with http:
            first = await wrapped(client, "m", messages, meta, 20)
            second = await wrapped(client, "m", messages, meta, 20)
        assert first == second
        assert first["status"] == "provider_filtered"
        assert first["content"] == ""
        assert first["generation_id"] is None
        assert first["http_status"] == 400
        assert first["cost_source"] == "reservation_estimate"
        assert ledger.spent > 0
        assert ledger.unresolved() == []
        assert len(calls) == 1
        assert calls[0]["messages"] == messages
        assert calls[0]["provider"]["only"] == ["fixed"]
        assert launcher.FILTER_EVENT.get() is None
        launcher.write_filter_summary(tmp_path)
        summary = json.loads((tmp_path / "provider_filter_summary.json").read_text())
        assert summary["groups"][0]["provider_filtered"] == 1
        ledger.close()

    asyncio.run(case())


def test_other_http_400_still_stops_and_is_not_faked_as_missing(tmp_path):
    async def case():
        client, http, ledger, calls = setup_client(
            tmp_path,
            httpx.Response(
                400, json={"error": {"code": "invalid_parameter", "message": "Bad parameter"}}
            ),
        )
        wrapped = launcher.filter_aware_completion(Client.complete)
        async with http:
            with pytest.raises(RuntimeError, match="HTTP 400"):
                await wrapped(client, "m", [{"role": "user", "content": "original"}], {}, 20)
        assert ledger.records() == []
        assert len(calls) == 1
        ledger.close()

    asyncio.run(case())
