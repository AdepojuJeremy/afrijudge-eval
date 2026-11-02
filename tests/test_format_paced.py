import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from afrijudge.client import Client

SPEC = importlib.util.spec_from_file_location(
    "format_launcher", Path(__file__).parents[1] / "scripts/run_format_paced.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def test_format_launcher_preserves_identity_and_restores_patches(tmp_path, monkeypatch):
    import afrijudge.cli

    before_http, before_complete = httpx.AsyncClient, Client.complete
    original_argv = ["launcher", "--run-dir", str(tmp_path / "diagnostic")]
    monkeypatch.setattr(sys, "argv", original_argv)
    seen = []

    def cli():
        seen.extend(sys.argv)
        assert httpx.AsyncClient is not before_http
        assert Client.complete is not before_complete

    monkeypatch.setattr(afrijudge.cli, "main", cli)
    launcher.main()
    assert seen[:2] == ["afrijudge", "validate-format"]
    assert "--execute" not in seen
    assert seen[seen.index("--run-dir") + 1] == str(tmp_path / "diagnostic")
    assert sys.argv is original_argv
    assert httpx.AsyncClient is before_http and Client.complete is before_complete
    assert not (tmp_path / "diagnostic").exists()


def test_launcher_restores_patches_on_failure(tmp_path, monkeypatch):
    import afrijudge.cli

    before_http, before_complete = httpx.AsyncClient, Client.complete
    monkeypatch.setattr(sys, "argv", ["launcher", "--run-dir", str(tmp_path / "diagnostic")])

    def fail():
        raise RuntimeError("transport ambiguity")

    monkeypatch.setattr(afrijudge.cli, "main", fail)
    with pytest.raises(RuntimeError, match="transport ambiguity"):
        launcher.main()
    assert httpx.AsyncClient is before_http and Client.complete is before_complete


@pytest.mark.parametrize(
    "option,value",
    [
        ("--max-spend-usd", "2"),
        ("--interval-seconds", "nan"),
        ("--rate-limit-cycles", "0"),
        ("--timeout-seconds", "-1"),
    ],
)
def test_launcher_rejects_invalid_limits(monkeypatch, option, value):
    monkeypatch.setattr(sys, "argv", ["launcher", option, value])
    with pytest.raises(SystemExit):
        launcher.main()
