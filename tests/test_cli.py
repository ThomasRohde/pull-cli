from __future__ import annotations

import json

from pull_cli.cli import main


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
