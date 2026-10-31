import asyncio
import importlib.util
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
