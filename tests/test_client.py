import asyncio
import copy
import json

import httpx
import pytest

from afrijudge.client import AmbiguousRequest, BudgetExceeded, Client, Ledger, bounded_map, catalog


def settings():
    return {"concurrency": 2, "seed": 42}


def model_lock():
    return {
        "models": {
            "m": {
                "slug": "vendor/model",
                "family": "vendor",
                "provider": "provider/tag",
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                "quantizations": ["bf16"],
                "supported_parameters": ["seed"],
            }
        }
    }


def response(content="OK", cost=0.0001):
    return {
        "id": "gen-id",
        "provider": "provider",
        "model": "vendor/model",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"cost": cost, "prompt_tokens": 10, "completion_tokens": 10},
    }


def test_cache_full_payload_and_no_secret_in_ledger(tmp_path):
    seen = []

    async def case():
        def handler(request):
            payload = json.loads(request.content)
            seen.append(payload)
            assert payload["provider"]["allow_fallbacks"] is False
            assert payload["provider"]["quantizations"] == ["bf16"]
            return httpx.Response(200, json=response())

        ledger = Ledger(tmp_path / "ledger.sqlite", 1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = Client(http, ledger, settings(), model_lock(), "secret-test-value")
            for message in ("one", "one", "two"):
                await client.complete(
                    "m", [{"role": "user", "content": message}], {"same": "metadata"}, 20
                )
        assert len(seen) == 2
        assert len(ledger.records()) == 2
        assert "secret-test-value" not in json.dumps(ledger.records())
        ledger.close()

    asyncio.run(case())


def test_budget_reservations_persist_and_share_stages(tmp_path):
    path = tmp_path / "ledger.sqlite"
    ledger = Ledger(path, 0.01)
    ledger.reserve("generation", 0.008)
    with pytest.raises(BudgetExceeded):
        ledger.reserve("judge", 0.003)
    ledger.close()
    recovered = Ledger(path, 0.01)
    assert recovered.spent == 0.008
    with pytest.raises(AmbiguousRequest):
        recovered.cached("generation")
    recovered.close()


def test_transport_failure_never_blindly_replayed(tmp_path):
    calls = []

    async def case():
        def handler(request):
            calls.append(1)
            raise httpx.ReadTimeout("timeout")

        ledger = Ledger(tmp_path / "ledger.sqlite", 1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = Client(http, ledger, settings(), model_lock(), "key")
            for _ in range(2):
                with pytest.raises(AmbiguousRequest):
                    await client.complete("m", [{"role": "user", "content": "x"}], {}, 20)
        assert len(calls) == 1
        assert len(ledger.unresolved()) == 1
        ledger.close()

    asyncio.run(case())


def test_clear_rejection_releases_reservation(tmp_path):
    async def case():
        ledger = Ledger(tmp_path / "ledger.sqlite", 1)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        ) as http:
            client = Client(http, ledger, settings(), model_lock(), "key")
            with pytest.raises(RuntimeError, match="HTTP 404"):
                await client.complete("m", [{"role": "user", "content": "x"}], {}, 20)
        assert ledger.spent == 0
        ledger.close()

    asyncio.run(case())


def test_length_truncation_is_cached_but_invalid(tmp_path):
    async def case():
        payload = response()
        payload["choices"][0]["finish_reason"] = "length"
        ledger = Ledger(tmp_path / "ledger.sqlite", 1)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        ) as http:
            client = Client(http, ledger, settings(), model_lock(), "key")
            record = await client.complete("m", [{"role": "user", "content": "x"}], {}, 20)
        assert record["status"] == "invalid_completion"
        assert ledger.spent > 0
        ledger.close()

    asyncio.run(case())


def test_catalog_does_not_drop_precision_filter():
    async def case():
        def handler(request):
            if request.url.path.endswith("/endpoints"):
                return httpx.Response(
                    200,
                    json={
                        "data": {
                            "endpoints": [
                                {
                                    "tag": "bad",
                                    "quantization": "int4",
                                    "pricing": {"prompt": "0", "completion": "0"},
                                }
                            ]
                        }
                    },
                )
            return httpx.Response(200, json={"data": [{"id": "vendor/model"}]})

        config = {
            "generators": ["m"],
            "judges": ["m"],
            "models": {"m": model_lock()["models"]["m"]},
        }
        config["models"]["m"].pop("provider")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(ValueError, match="No eligible"):
                await catalog(http, config)

    asyncio.run(case())


def test_bounded_workers_drain_inflight_on_failure():
    async def case():
        completed = []

        async def job(i):
            if i == 1:
                raise ValueError("stop")
            await asyncio.sleep(0.01)
            completed.append(i)
            return i

        with pytest.raises(ValueError):
            await bounded_map(job, list(range(50)), 2)
        assert completed == [0]

    asyncio.run(case())


def test_catalog_rejects_missing_model():
    async def case():
        config = {
            "generators": ["m"],
            "judges": ["m"],
            "models": copy.deepcopy(model_lock()["models"]),
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []}))
        ) as http:
            with pytest.raises(ValueError, match="Unavailable model"):
                await catalog(http, config)

    asyncio.run(case())


def test_embedded_provider_error_cannot_be_silently_reused(tmp_path):
    async def case():
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(
                200, json={"error": {"message": "upstream failure"}, "usage": {"cost": 0.0001}}
            )

        ledger = Ledger(tmp_path / "ledger.sqlite", 1)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = Client(http, ledger, settings(), model_lock(), "key")
            for _ in range(2):
                with pytest.raises(RuntimeError, match="[Pp]rovider error|Provider returned"):
                    await client.complete("m", [{"role": "user", "content": "x"}], {}, 20)
        assert len(calls) == 1
        assert ledger.records()[0]["status"] == "provider_error"
        assert ledger.spent > 0
        ledger.close()

    asyncio.run(case())
