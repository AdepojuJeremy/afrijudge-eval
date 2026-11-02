import asyncio
import importlib.util
from pathlib import Path

import httpx
import pytest

from afrijudge.client import AmbiguousRequest, BudgetExceeded, Client, Ledger

SPEC = importlib.util.spec_from_file_location(
    "retry_launcher", Path(__file__).parents[1] / "scripts/run_paced.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)
RATE_ERROR = "Rate limit exhausted; retry this run later"


def test_retries_same_request_after_explicit_exhaustion_only():
    async def case():
        calls, sleeps, events = [], [], []
        messages, meta = [{"role": "user", "content": "unchanged"}], {"stage": "judge"}

        async def original(client, model, msgs, metadata, cap):
            calls.append((model, msgs, metadata, cap))
            if len(calls) < 3:
                raise RuntimeError(RATE_ERROR)
            return {"status": "success", "content": "saved response"}

        async def sleep(seconds):
            sleeps.append(seconds)

        retry = launcher.retry_rate_limits(
            original, cycles=3, delay=180, sleep=sleep, log=events.append
        )
        result = await retry(None, "m", messages, meta, 512)
        assert result["status"] == "success"
        assert calls == [("m", messages, meta, 512)] * 3
        assert sleeps == [180, 180]
        assert [e["completed_batch"] for e in events] == [1, 2]

    asyncio.run(case())


def test_retries_are_bounded():
    async def case():
        attempts = []

        async def fail(*args):
            attempts.append(1)
            raise RuntimeError(RATE_ERROR)

        async def sleep(seconds):
            pass

        retry = launcher.retry_rate_limits(fail, cycles=2, delay=0, sleep=sleep)
        with pytest.raises(RuntimeError, match="Rate limit exhausted"):
            await retry(None, "m", [], {}, 20)
        assert len(attempts) == 2

    asyncio.run(case())


@pytest.mark.parametrize(
    "error",
    [
        BudgetExceeded("ceiling reached"),
        AmbiguousRequest("Transport failure; reservation retained"),
        RuntimeError("Cached provider error; recover before resuming"),
        RuntimeError("OpenRouter rejected model: HTTP 400"),
    ],
)
def test_other_errors_are_never_retried(error):
    async def case():
        attempts = []

        async def fail(*args):
            attempts.append(1)
            raise error

        retry = launcher.retry_rate_limits(fail, cycles=8)
        with pytest.raises(type(error)) as caught:
            await retry(None, "m", [], {}, 20)
        assert caught.value is error
        assert len(attempts) == 1

    asyncio.run(case())


def test_real_client_releases_rejected_batch_before_retry(tmp_path, monkeypatch):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr("afrijudge.client.asyncio.sleep", no_sleep)

    async def case():
        requests = []

        def handler(request):
            requests.append(request.content)
            if len(requests) <= 4:
                return httpx.Response(429)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"cost": 0.0001},
                },
            )

        ledger = Ledger(tmp_path / "ledger.sqlite", 1)
        lock = {
            "models": {
                "m": {
                    "slug": "test/model",
                    "provider": "fixed",
                    "pricing": {"prompt": 0.000001, "completion": 0.000002},
                }
            }
        }
        retry = launcher.retry_rate_limits(Client.complete, cycles=2, delay=180, sleep=no_sleep)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = Client(http, ledger, {"concurrency": 1, "seed": 42}, lock, "test-key")
            result = await retry(client, "m", [{"role": "user", "content": "same"}], {}, 20)
        assert result["content"] == "ok"
        assert len(requests) == 5
        assert len(set(requests)) == 1
        assert ledger.spent == 0.0001
        assert ledger.unresolved() == []
        assert len(ledger.records()) == 1
        ledger.close()

    asyncio.run(case())
