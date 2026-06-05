from __future__ import annotations

from pull_cli.models import Config

from .cloud_v2 import CloudV2Client
from .data_center import DataCenterClient


def build_client(config: Config):
    deployment = config.deployment
    if deployment == "cloud" or (
        deployment == "auto" and config.base_url and ".atlassian.net" in config.base_url
    ):
        return CloudV2Client(config)
    return DataCenterClient(config)
