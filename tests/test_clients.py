from __future__ import annotations

from pull_cli.clients.cloud_v2 import CloudV2Client
from pull_cli.clients.data_center import DataCenterClient
from pull_cli.models import AttachmentRecord, Config


class FakeAtlassianConfluence:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get(self, path: str, **kwargs):
        self.calls.append(("get", path, kwargs))
        if path.endswith("/download"):
            return b"attachment-bytes"
        if path == "rest/api/content/123/child/attachment":
            return {
                "results": [
                    {
                        "id": "att456",
                        "title": "file.txt",
                        "metadata": {"mediaType": "text/plain"},
                        "_links": {"download": "/download/attachments/123/file.txt"},
                        "extensions": {"fileSize": 16},
                    }
                ]
            }
        return {"results": []}

    def get_page_by_id(self, page_id: str, expand: str):
        self.calls.append(("get_page_by_id", page_id, {"expand": expand}))
        return {
            "id": page_id,
            "title": "Page",
            "space": {"key": "EA"},
            "version": {"number": 1},
            "body": {"view": {"value": "<p>Rendered</p>"}, "storage": {"value": "<p>Storage</p>"}},
            "_links": {"webui": f"/spaces/EA/pages/{page_id}/Page"},
        }

    def get_page_child_by_type(self, **kwargs):
        self.calls.append(("get_page_child_by_type", "", kwargs))
        return []

    def close(self) -> None:
        self.calls.append(("close", "", {}))


def test_data_center_client_uses_atlassian_api_for_attachments() -> None:
    api = FakeAtlassianConfluence()
    client = DataCenterClient(Config(base_url="https://confluence.example.com/confluence"), api=api)  # type: ignore[arg-type]

    attachments = client.list_attachments("123")

    assert attachments[0].attachment_id == "att456"
    assert api.calls[0] == (
        "get",
        "rest/api/content/123/child/attachment",
        {"params": {"limit": 100, "start": 0, "expand": "version,_links,extensions"}},
    )


def test_cloud_download_attachment_uses_atlassian_api_wiki_rest_endpoint() -> None:
    api = FakeAtlassianConfluence()
    confluence = CloudV2Client(
        Config(base_url="https://example.atlassian.net/wiki", user="u", token="t"),
        api=api,  # type: ignore[arg-type]
    )
    content = confluence.download_attachment(
        AttachmentRecord(
            attachment_id="att456",
            page_id="123",
            filename="file.txt",
            download_url="/download/attachments/123/file.txt",
        )
    )
    assert content == b"attachment-bytes"
    assert api.calls == [
        (
            "get",
            "https://example.atlassian.net/wiki/rest/api/content/123/child/attachment/att456/download",
            {"headers": {"Accept": "*/*"}, "not_json_response": True, "absolute": True},
        )
    ]
