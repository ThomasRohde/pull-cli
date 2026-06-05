from __future__ import annotations

import json
from pathlib import Path

import pytest

import pull_cli.cli as cli
from pull_cli.cli import main

from .conftest import FakeConfluenceClient, make_page


def test_guide_json_is_plain_json(capsys) -> None:
    assert main(["guide", "--json"]) == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["schema_version"] == "1.0"
    assert "pull" in payload["commands"]


def test_pull_json_failure_envelope_without_target(capsys, monkeypatch) -> None:
    monkeypatch.delenv("PULL_URL", raising=False)
    monkeypatch.delenv("CONFPUB_URL", raising=False)
    assert main(["--json"]) == 10
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["result"] is None
    assert payload["errors"][0]["code"] == "ERR_VALIDATION_REQUIRED"


def test_pull_human_failure_without_target_uses_stderr(capsys, monkeypatch) -> None:
    monkeypatch.delenv("LLM", raising=False)
    monkeypatch.delenv("PULL_URL", raising=False)
    monkeypatch.delenv("CONFPUB_URL", raising=False)
    assert main([]) == 10
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ERR_VALIDATION_REQUIRED" in captured.err
    assert "Suggested action:" in captured.err


def test_pull_json_failure_envelope_for_invalid_argument(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--bogus", "--json"])
    assert exc_info.value.code == 10
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "ERR_VALIDATION_INVALID_ARGUMENT"
    assert "--bogus" in payload["errors"][0]["message"]


def test_validate_json_failure_envelope_without_path(capsys) -> None:
    assert main(["validate", "--json"]) == 10
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["ok"] is False
    assert payload["command"] == "validate"
    assert payload["errors"][0]["code"] == "ERR_VALIDATION_REQUIRED"
    assert "MANIFEST_OR_OUTPUT_DIR" in payload["errors"][0]["message"]


def test_version_commands(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out.startswith("pull-cli ")
    assert main(["version"]) == 0
    assert capsys.readouterr().out.startswith("pull-cli ")


def test_help_mentions_agent_commands(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    stdout = capsys.readouterr().out
    assert "pull validate MANIFEST_OR_OUTPUT_DIR" in stdout
    assert "pull guide [--json]" in stdout
    assert "Agent flow:" in stdout


def test_human_guide_mentions_path_rules(capsys) -> None:
    assert main(["guide"]) == 0
    stdout = capsys.readouterr().out
    assert "Recommended agent flow:" in stdout
    assert "package-root-relative" in stdout


def test_redacted_pull_json_redacts_target_url(capsys, monkeypatch, tmp_path: Path) -> None:
    page = make_page("900", "JSON Redaction", body_view="<h1>JSON Redaction</h1>")
    client = FakeConfluenceClient(pages={"900": page})
    monkeypatch.setattr(cli, "build_client", lambda _config: client)

    assert (
        main(
            [
                "--page-id",
                "900",
                "--base-url",
                "https://example.atlassian.net/wiki",
                "--output",
                str(tmp_path / "json-redacted"),
                "--clean",
                "--redact-source-urls",
                "--json",
            ]
        )
        == 0
    )

    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["target"]["url"] == "<redacted-url>"
    assert "https://example.atlassian.net" not in stdout
