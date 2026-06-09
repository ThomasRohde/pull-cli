from __future__ import annotations

from pull_cli.errors import EXIT_AUTH, PullError
from pull_cli.models import Config

from .cloud_v2 import CloudV2Client
from .data_center import DataCenterClient


def build_client(config: Config):
    deployment = config.deployment
    is_cloud = deployment == "cloud" or (
        deployment == "auto" and config.base_url and ".atlassian.net" in config.base_url
    )
    if is_cloud:
        _reject_cloud_bearer_api_token(config)
        return CloudV2Client(config)
    return DataCenterClient(config)


def _reject_cloud_bearer_api_token(config: Config) -> None:
    token_prefix = (config.token or "")[:4].upper()
    token_only = bool(config.token) and not config.user
    bearer_auth = config.auth_mode == "bearer" or (config.auth_mode == "auto" and token_only)
    if token_prefix != "ATAT" or not bearer_auth:
        return
    raise PullError(
        code="ERR_AUTH_REQUIRED",
        message="Atlassian Cloud API tokens require Basic auth with an account email.",
        exit_code=EXIT_AUTH,
        suggested_action="Set --user to the account email and use --auth basic with the Cloud API token.",
        details={"auth_mode": config.auth_mode, "deployment_type": "cloud"},
    )
