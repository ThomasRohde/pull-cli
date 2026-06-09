from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

import pytest
import urllib3

import pull_cli
import pull_cli.cli as cli
from pull_cli.cli import main

from .conftest import FakeConfluenceClient, make_page


def test_guide_json_is_plain_json(capsys) -> None:
    assert main(["guide", "--json"]) == 0
    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["schema_version"] == "1.0"
    assert "pull" in payload["commands"]
    assert payload["output_schema"]["default_mode"] == "simple"
    assert "--output-mode simple|full" in payload["commands"]["pull"]["options"]["output"]
    assert "--auth auto|bearer|basic" in payload["commands"]["pull"]["options"]["auth"]
    assert payload["auth"]["mode_default"] == "auto"


def test_pull_json_failure_envelope_without_target(capsys, monkeypatch) -> None:
    monkeypatch.delenv("PULL_URL", raising=False)
    monkeypatch.delenv("CONFPUB_URL", raising=False)
    assert main(["--json"]) == 10
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["result"] is None
    assert payload["errors"][0]["code"] == "ERR_VALIDATION_REQUIRED"


def test_pull_without_arguments_displays_help(capsys, monkeypatch) -> None:
    monkeypatch.delenv("LLM", raising=False)
    monkeypatch.delenv("PULL_URL", raising=False)
    monkeypatch.delenv("CONFPUB_URL", raising=False)
    assert main([]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "usage: pull" in captured.out
    assert "Most common AI use:" in captured.out
    assert "./pulled-confluence/<sanitized-root-page-title>.md" in captured.out


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
    assert capsys.readouterr().out == f"pull-cli {pull_cli.__version__}\n"
    assert main(["version"]) == 0
    assert capsys.readouterr().out == f"pull-cli {pull_cli.__version__}\n"
    assert version("pull-cli") == pull_cli.__version__


def test_help_mentions_agent_commands(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    stdout = capsys.readouterr().out
    assert "pull validate MANIFEST_OR_OUTPUT_DIR" in stdout
    assert "pull guide [--json]" in stdout
    assert "--output-mode" in stdout
    assert "Agent flow:" in stdout
    assert "Most common AI use:" in stdout
    assert "current working directory" in stdout


def test_human_guide_mentions_path_rules(capsys) -> None:
    assert main(["guide"]) == 0
    stdout = capsys.readouterr().out
    assert "Recommended agent flow:" in stdout
    assert "Most common AI use:" in stdout
    assert "package-root-relative" in stdout
    assert "Default output mode is simple" in stdout
    assert "./pulled-confluence" in stdout
    assert "--output-mode full" in stdout


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


def test_pull_json_reports_simple_default_and_ai_entry(capsys, monkeypatch, tmp_path: Path) -> None:
    page = make_page("901", "CLI Simple", body_view="<h1>CLI Simple</h1>", storage="<p>Source</p>")
    client = FakeConfluenceClient(pages={"901": page})
    monkeypatch.setattr(cli, "build_client", lambda _config: client)
    output = tmp_path / "cli-simple"

    assert main(["--page-id", "901", "--output", str(output), "--clean", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["result"]["output_mode"] == "simple"
    assert payload["result"]["ai_entry"].endswith("cli-simple.md")
    assert (output / "cli-simple.md").exists()
    assert not (output / "bundle.md").exists()
    assert not any((output / "pages").rglob("index.html"))
    assert not any((output / "pages").rglob("source.storage.xml"))


def test_pull_human_success_prints_ai_entry(capsys, monkeypatch, tmp_path: Path) -> None:
    page = make_page("904", "CLI Human", body_view="<h1>CLI Human</h1>")
    client = FakeConfluenceClient(pages={"904": page})
    monkeypatch.setattr(cli, "build_client", lambda _config: client)
    output = tmp_path / "cli-human"

    assert main(["--page-id", "904", "--output", str(output), "--clean"]) == 0

    captured = capsys.readouterr()
    assert "Pulled 1 page(s)" in captured.out
    assert "AI entry:" in captured.out
    assert str((output / "cli-human.md").resolve()) in captured.out
    assert "Give that Markdown file to the agent" in captured.out


def test_pull_default_output_is_current_working_directory(capsys, monkeypatch, tmp_path: Path) -> None:
    page = make_page("905", "CLI Default Output", body_view="<h1>CLI Default Output</h1>")
    client = FakeConfluenceClient(pages={"905": page})
    monkeypatch.setattr(cli, "build_client", lambda _config: client)
    monkeypatch.chdir(tmp_path)

    assert main(["--page-id", "905", "--base-url", "https://example.atlassian.net/wiki"]) == 0

    output = tmp_path / "pulled-confluence"
    assert output.exists()
    assert (output / "cli-default-output.md").exists()
    captured = capsys.readouterr()
    assert str(output) in captured.out
    assert str((output / "cli-default-output.md").resolve()) in captured.out


def test_output_mode_artifact_flags_override_defaults(capsys, monkeypatch, tmp_path: Path) -> None:
    simple_page = make_page("902", "CLI Override Simple", body_view="<h1>Simple</h1>", storage="<p>Source</p>")
    simple_client = FakeConfluenceClient(pages={"902": simple_page})
    monkeypatch.setattr(cli, "build_client", lambda _config: simple_client)
    simple_output = tmp_path / "simple-overrides"

    assert (
        main(
            [
                "--page-id",
                "902",
                "--output",
                str(simple_output),
                "--clean",
                "--bundle",
                "--html",
                "--source",
                "--json",
            ]
        )
        == 0
    )
    simple_payload = json.loads(capsys.readouterr().out)
    assert simple_payload["result"]["output_mode"] == "simple"
    assert (simple_output / "bundle.md").exists()
    assert any((simple_output / "pages").rglob("index.html"))
    assert any((simple_output / "pages").rglob("source.storage.xml"))
    simple_ai_entry = (simple_output / "cli-override-simple.md").read_text(encoding="utf-8")
    assert "[bundle.md](bundle.md)" in simple_ai_entry
    assert "[manifest.yaml](manifest.yaml)" not in simple_ai_entry
    assert "[diagnostics/warnings.jsonl](diagnostics/warnings.jsonl)" not in simple_ai_entry

    full_page = make_page("903", "CLI Override Full", body_view="<h1>Full</h1>", storage="<p>Source</p>")
    full_client = FakeConfluenceClient(pages={"903": full_page})
    monkeypatch.setattr(cli, "build_client", lambda _config: full_client)
    full_output = tmp_path / "full-overrides"

    assert (
        main(
            [
                "--page-id",
                "903",
                "--output-mode",
                "full",
                "--output",
                str(full_output),
                "--clean",
                "--no-bundle",
                "--no-html",
                "--no-source",
                "--json",
            ]
        )
        == 0
    )
    full_payload = json.loads(capsys.readouterr().out)
    assert full_payload["result"]["output_mode"] == "full"
    assert full_payload["result"]["bundle"] is None
    assert not (full_output / "bundle.md").exists()
    assert not any((full_output / "pages").rglob("index.html"))
    assert not any((full_output / "pages").rglob("source.storage.xml"))


def test_cli_token_without_user_ignores_legacy_user_env(capsys, monkeypatch, tmp_path: Path) -> None:
    page = make_page("906", "CLI Bearer", body_view="<h1>CLI Bearer</h1>")
    client = FakeConfluenceClient(pages={"906": page})
    captured = {}

    def build_client(config):
        captured["config"] = config
        return client

    monkeypatch.setenv("CONFPUB_USER", "legacy-user")
    monkeypatch.setenv("CONFPUB_TOKEN", "legacy-token")
    monkeypatch.setattr(cli, "build_client", build_client)

    assert (
        main(
            [
                "--page-id",
                "906",
                "--base-url",
                "https://confluence.example.com",
                "--token",
                "explicit-pat",
                "--output",
                str(tmp_path / "cli-bearer"),
                "--clean",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    config = captured["config"]
    assert config.token == "explicit-pat"
    assert config.user is None
    assert config.auth_mode == "auto"


def test_cli_auth_basic_can_use_legacy_user_env(capsys, monkeypatch, tmp_path: Path) -> None:
    page = make_page("907", "CLI Basic", body_view="<h1>CLI Basic</h1>")
    client = FakeConfluenceClient(pages={"907": page})
    captured = {}

    def build_client(config):
        captured["config"] = config
        return client

    monkeypatch.setenv("CONFPUB_USER", "legacy-user")
    monkeypatch.setattr(cli, "build_client", build_client)

    assert (
        main(
            [
                "--page-id",
                "907",
                "--base-url",
                "https://confluence.example.com",
                "--token",
                "explicit-pat",
                "--auth",
                "basic",
                "--output",
                str(tmp_path / "cli-basic"),
                "--clean",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    config = captured["config"]
    assert config.token == "explicit-pat"
    assert config.user == "legacy-user"
    assert config.auth_mode == "basic"


def test_cli_page_id_after_json_and_other_flags_is_resolved(capsys, monkeypatch, tmp_path: Path) -> None:
    page = make_page("908", "CLI Ordered", body_view="<h1>CLI Ordered</h1>")
    client = FakeConfluenceClient(pages={"908": page})
    monkeypatch.setattr(cli, "build_client", lambda _config: client)

    assert (
        main(
            [
                "--auth",
                "basic",
                "--no-assets",
                "--json",
                "--page-id",
                "908",
                "-o",
                str(tmp_path / "cli-ordered"),
                "--clean",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["target"]["page_id"] == "908"


def test_cli_verbose_progress_goes_to_stderr(capsys, monkeypatch, tmp_path: Path) -> None:
    page = make_page("909", "CLI Verbose", body_view="<h1>CLI Verbose</h1>")
    client = FakeConfluenceClient(pages={"909": page})
    monkeypatch.setattr(cli, "build_client", lambda _config: client)

    assert (
        main(
            [
                "--page-id",
                "909",
                "--output",
                str(tmp_path / "cli-verbose"),
                "--clean",
                "--verbose",
                "--json",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    json.loads(captured.out)
    assert "[pull:crawl]" in captured.err
    assert "[pull:page]" in captured.err


def test_ssl_verify_false_suppresses_urllib3_warning(monkeypatch) -> None:
    called = {}

    def disable_warnings(category=None):
        called["category"] = category

    monkeypatch.setattr(urllib3, "disable_warnings", disable_warnings)

    cli._suppress_insecure_request_warnings(False)

    assert called["category"] is urllib3.exceptions.InsecureRequestWarning
