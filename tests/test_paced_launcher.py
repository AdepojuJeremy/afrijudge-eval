import asyncio
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from afrijudge.cli import code_hash

SPEC = importlib.util.spec_from_file_location(
    "run_paced", Path(__file__).parents[1] / "scripts/run_paced.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_retry_after_numeric_date_and_invalid():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    assert launcher.retry_after_seconds("75", now) == 75
    assert launcher.retry_after_seconds("Sat, 31 Oct 2026 12:02:00 GMT", now) == 120
    for value in (None, "invalid", "NaN", "Infinity", "-12"):
        assert launcher.retry_after_seconds(value, now) == 0


def test_error_logging_redacts_credentials():
    response = httpx.Response(429, json={"error": {"message": "Limit secretkey sk-or-v1-test"}})
    result = launcher.safe_error(response, {"Authorization": "Bearer secretkey"})
    assert "secretkey" not in result
    assert "sk-or-v1-test" not in result


def test_nested_400_details_are_logged_without_credentials():
    response = httpx.Response(
        400,
        json={
            "error": {
                "message": "Provider returned error",
                "metadata": {
                    "raw": json.dumps(
                        {
                            "error": {
                                "code": "invalid_parameter",
                                "message": "bad setting secret-key",
                            }
                        }
                    )
                },
            }
        },
    )
    result = launcher.safe_error(response, {"Authorization": "Bearer secret-key"})
    assert "invalid_parameter" in result
    assert "bad setting" in result
    assert "secret-key" not in result
    assert (
        launcher.safe_error(httpx.Response(400, text="not-json"), {})
        == "HTTP 400 (non-JSON response)"
    )


def test_400_diagnostics_do_not_change_request_or_retry(tmp_path):
    async def case():
        payload = {"model": "test/model", "provider": {"only": ["fixed-provider"]}}
        original = json.dumps(payload, sort_keys=True)
        calls = []
        response = httpx.Response(400, json={"error": {"message": "specific error"}})

        async def send(url, **kwargs):
            calls.append(kwargs)
            return response

        pacer = launcher.Pacer(6, tmp_path / "events.jsonl")
        result = await pacer.post(
            send, "https://openrouter.ai/api/v1/chat/completions", json=payload
        )
        assert result is response
        assert len(calls) == 1
        assert json.dumps(payload, sort_keys=True) == original
        event = json.loads((tmp_path / "events.jsonl").read_text())
        assert event["status_code"] == 400
        assert event["message"] == "specific error"

    asyncio.run(case())


def test_pacing_serializes_posts_and_respects_cooldown(tmp_path):
    async def case():
        clock = [0.0]
        starts, active = [], [0]

        async def sleep(seconds):
            clock[0] += seconds

        async def send(url, **kwargs):
            active[0] += 1
            assert active[0] == 1
            starts.append(clock[0])
            await asyncio.sleep(0)
            active[0] -= 1
            if len(starts) == 1:
                return httpx.Response(
                    429, headers={"retry-after": "90"}, json={"error": {"message": "provider busy"}}
                )
            return httpx.Response(200, json={})

        pacer = launcher.Pacer(6, tmp_path / "events.jsonl", clock=lambda: clock[0], sleep=sleep)
        before = code_hash()
        payload = {"model": "test/model", "provider": {"only": ["test"]}}
        await asyncio.gather(
            *(
                pacer.post(send, "https://openrouter.ai/api/v1/chat/completions", json=payload)
                for _ in range(3)
            )
        )
        assert starts == [0, 90, 96]
        assert payload == {"model": "test/model", "provider": {"only": ["test"]}}
        assert code_hash() == before

    asyncio.run(case())
