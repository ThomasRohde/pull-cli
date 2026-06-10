from __future__ import annotations

from pull_cli.config import resolve_config


def test_explicit_token_without_user_ignores_legacy_user_env() -> None:
    config = resolve_config(
        base_url="https://confluence.example.com",
        token="dc-pat",
        env={
            "CONFPUB_USER": "legacy-user",
            "CONFPUB_TOKEN": "legacy-token",
        },
    )

    assert config.token == "dc-pat"
    assert config.user is None
    assert config.auth_mode == "auto"


def test_explicit_token_with_user_keeps_basic_auth_inputs() -> None:
    config = resolve_config(
        base_url="https://confluence.example.com",
        user="explicit-user",
        token="dc-pat",
        env={"CONFPUB_USER": "legacy-user"},
    )

    assert config.user == "explicit-user"
    assert config.token == "dc-pat"


def test_bearer_auth_mode_ignores_user_fallbacks() -> None:
    config = resolve_config(
        base_url="https://confluence.example.com",
        token="dc-pat",
        auth_mode="bearer",
        env={
            "PULL_USER": "pull-user",
            "CONFPUB_USER": "legacy-user",
        },
    )

    assert config.auth_mode == "bearer"
    assert config.user is None
    assert config.token == "dc-pat"


def test_basic_auth_mode_can_use_legacy_user_fallback() -> None:
    config = resolve_config(
        base_url="https://confluence.example.com",
        token="dc-pat",
        auth_mode="basic",
        env={"CONFPUB_USER": "legacy-user"},
    )

    assert config.auth_mode == "basic"
    assert config.user == "legacy-user"
    assert config.token == "dc-pat"


def test_legacy_env_auth_still_pairs_user_and_token_by_default() -> None:
    config = resolve_config(
        base_url="https://confluence.example.com",
        env={
            "CONFPUB_USER": "legacy-user",
            "CONFPUB_TOKEN": "legacy-token",
        },
    )

    assert config.user == "legacy-user"
    assert config.token == "legacy-token"
    assert config.auth_mode == "auto"


def test_retries_resolve_from_env_and_can_disable() -> None:
    config = resolve_config(
        base_url="https://confluence.example.com",
        env={"PULL_RETRIES": "0"},
    )

    assert config.retries == 0


def test_retries_resolve_from_yaml_and_clamp(tmp_path) -> None:
    config_path = tmp_path / "pull.yaml"
    config_path.write_text("retries: 99\n", encoding="utf-8")

    config = resolve_config(
        base_url="https://confluence.example.com",
        config_path=config_path,
        env={},
    )

    assert config.retries == 10


def test_retries_env_overrides_yaml(tmp_path) -> None:
    config_path = tmp_path / "pull.yaml"
    config_path.write_text("retries: 7\n", encoding="utf-8")

    config = resolve_config(
        base_url="https://confluence.example.com",
        config_path=config_path,
        env={"PULL_RETRIES": "2"},
    )

    assert config.retries == 2
