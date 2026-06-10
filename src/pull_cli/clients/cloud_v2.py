from __future__ import annotations

from typing import Any

from atlassian import Confluence

from pull_cli.models import AttachmentRecord, Config, PageRecord, PageSummary
from pull_cli.security import redact_value

from .data_center import REQUEST_TIMEOUT_SECONDS, DataCenterClient, _auth_kwargs


class CloudV2Client(DataCenterClient):
    """Confluence Cloud adapter backed by atlassian-python-api.

    The installed atlassian-python-api package exposes the legacy `Confluence`
    class in this environment. We use its public helpers for v1 content endpoints
    and its low-level `get` method for Cloud v2 endpoints until the documented
    `ConfluenceCloud` class is available in the package index.
    """

    deployment_type = "cloud"

    def __init__(self, config: Config, *, api: Confluence | None = None) -> None:
        super().__init__(config, api=api)
        self._site_url = self.base_url.removesuffix("/wiki")

    def _build_api(self, config: Config) -> Confluence:
        kwargs = {
            "url": self.base_url,
            "verify_ssl": config.ssl_verify,
            "timeout": REQUEST_TIMEOUT_SECONDS,
            "cloud": True,
            "backoff_and_retry": False,
        }
        kwargs.update(_auth_kwargs(config))
        return Confluence(**kwargs)

    def _v2_url(self, *parts: str) -> str:
        return self._site_url + "/" + "/".join(["wiki", "api", "v2", *parts])

    def _cloud_v2_get(self, *parts: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        data = self._call(
            self._api.get,
            self._v2_url(*parts),
            params=params,
            absolute=True,
        )
        return data if isinstance(data, dict) else {}

    def get_page(self, page_id: str) -> PageRecord:
        data = self._cloud_v2_get("pages", page_id, params={"body-format": "storage"})
        if data:
            return self._parse_cloud_page(data, page_id)
        return super().get_page(page_id)

    def _parse_cloud_page(self, data: dict[str, Any], page_id: str) -> PageRecord:
        links = data.get("_links") if isinstance(data.get("_links"), dict) else {}
        return PageRecord(
            page_id=str(data.get("id") or page_id),
            title=str(data.get("title") or "Untitled"),
            space_key=_space_key(data),
            url=self._absolute_url(str(links.get("webui") or "")) if links else None,
            version=_version_number(data),
            body_storage=_body_storage(data),
            raw=redact_value(data),
        )

    def get_children(self, page_id: str) -> list[PageSummary]:
        data = self._cloud_v2_get("pages", page_id, "children", params={"limit": 100})
        results = data.get("results") if isinstance(data, dict) else None
        if isinstance(results, list):
            summaries = [
                PageSummary(
                    page_id=str(item.get("id")),
                    title=str(item.get("title") or "Untitled"),
                    space_key=_space_key(item),
                    url=self._absolute_url(str(item.get("_links", {}).get("webui", "")))
                    if isinstance(item.get("_links"), dict)
                    else None,
                    parent_id=page_id,
                )
                for item in results
                if isinstance(item, dict) and item.get("id")
            ]
            if summaries:
                return summaries
        return super().get_children(page_id)

    def list_attachments(self, page_id: str) -> list[AttachmentRecord]:
        data = self._cloud_v2_get("pages", page_id, "attachments", params={"limit": 250})
        results = data.get("results") if isinstance(data, dict) else None
        if isinstance(results, list):
            attachments = [
                AttachmentRecord(
                    attachment_id=str(item.get("id")),
                    page_id=page_id,
                    filename=str(item.get("title") or item.get("filename") or "attachment"),
                    media_type=str(item.get("mediaType") or "") or None,
                    download_url=self._absolute_url(str(item.get("downloadLink") or ""))
                    if item.get("downloadLink")
                    else None,
                    web_url=self._absolute_url(str(item.get("_links", {}).get("webui", "")))
                    if isinstance(item.get("_links"), dict)
                    else None,
                    file_size=int(item["fileSize"]) if isinstance(item.get("fileSize"), int) else None,
                    raw=redact_value(item),
                )
                for item in results
                if isinstance(item, dict) and item.get("id")
            ]
            if attachments:
                return attachments
        return super().list_attachments(page_id)

    def download_attachment(self, attachment: AttachmentRecord) -> bytes:
        return self._call(
            self._api.get,
            f"{self._site_url}/wiki/rest/api/content/{attachment.page_id}/child/attachment/{attachment.attachment_id}/download",
            headers={"Accept": "*/*"},
            not_json_response=True,
            absolute=True,
        )


def _space_key(item: dict[str, Any]) -> str | None:
    space = item.get("space") if isinstance(item.get("space"), dict) else {}
    return str(space.get("key") or item.get("spaceKey") or "") or None


def _body_storage(data: dict[str, Any]) -> str | None:
    body = data.get("body") if isinstance(data.get("body"), dict) else {}
    storage = body.get("storage") if isinstance(body.get("storage"), dict) else {}
    value = storage.get("value")
    return value if isinstance(value, str) else None


def _version_number(data: dict[str, Any]) -> int | None:
    version = data.get("version") if isinstance(data.get("version"), dict) else {}
    return int(version["number"]) if isinstance(version.get("number"), int) else None
