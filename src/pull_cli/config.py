from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .models import Config


def _coerce_ssl_verify(value: str | bool | None) -> bool | str:
    if value is None or value == "":
        return True
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "y", "on"}:
        return True
    if lowered in {"false", "0", "no", "n", "off"}:
        return False
    return value


def _load_config_file(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return data


def resolve_config(
    *,
    base_url: str | None = None,
    user: str | None = None,
    token: str | None = None,
    cloud_id: str | None = None,
    ssl_verify: str | bool | None = None,
    config_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Config:
    env_map = env if env is not None else os.environ
    path = Path(config_path).expanduser() if config_path else None
    file_data = _load_config_file(path)

    resolved = Config(
        base_url=(
            base_url
            or env_map.get("PULL_URL")
            or file_data.get("base_url")
            or env_map.get("CONFPUB_URL")
        ),
        user=(
            user
            or env_map.get("PULL_USER")
            or file_data.get("user")
            or env_map.get("CONFPUB_USER")
        ),
        token=(
            token
            or env_map.get("PULL_TOKEN")
            or file_data.get("token")
            or env_map.get("CONFPUB_TOKEN")
        ),
        cloud_id=cloud_id or env_map.get("PULL_CLOUD_ID") or file_data.get("cloud_id"),
        ssl_verify=_coerce_ssl_verify(
            ssl_verify
            if ssl_verify is not None
            else env_map.get("PULL_SSL_VERIFY")
            or file_data.get("ssl_verify")
            or env_map.get("CONFPUB_SSL_VERIFY")
        ),
        deployment=file_data.get("deployment", "auto"),
        config_path=path,
    )
    if resolved.base_url:
        resolved.base_url = resolved.base_url.rstrip("/")
    return resolved
