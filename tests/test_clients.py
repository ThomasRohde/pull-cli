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

    def get_page_comments(self, **kwargs):
        self.calls.append(("get_page_comments", str(kwargs.get("content_id")), kwargs))
        start = int(kwargs.get("start") or 0)
        location = kwargs.get("location")
        if location == "inline":
            results = [_comment_payload("comment-inline", location="inline"), _comment_payload("comment-0")]
        elif start == 0:
            results = [_comment_payload(f"comment-{index}") for index in range(100)]
        elif start == 100:
            results = [_comment_payload("comment-100")]
        else:
            results = []
        return {"results": results}

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


def test_data_center_client_fetches_paginated_footer_and_inline_comments() -> None:
    api = FakeAtlassianConfluence()
    client = DataCenterClient(Config(base_url="https://confluence.example.com/confluence"), api=api)  # type: ignore[arg-type]

    comments = client.list_comments("123")

    assert len(comments) == 102
    assert comments[0].comment_id == "comment-0"
    assert comments[0].location == "footer"
    assert comments[0].author == "Comment Author"
    assert comments[0].body_html == "<p>Comment body comment-0</p>"
    assert comments[-1].comment_id == "comment-inline"
    assert comments[-1].location == "inline"
    comment_calls = [call for call in api.calls if call[0] == "get_page_comments"]
    assert comment_calls[0][2]["start"] == 0
    assert comment_calls[0][2]["limit"] == 100
    assert comment_calls[0][2]["depth"] == "all"
    assert comment_calls[1][2]["start"] == 100
    assert comment_calls[-1][2]["location"] == "inline"


def _comment_payload(comment_id: str, *, location: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": comment_id,
        "type": "comment",
        "status": "current",
        "body": {"view": {"value": f"<p>Comment body {comment_id}</p>"}},
        "version": {"number": 1, "when": "2026-06-05T08:05:00Z"},
        "history": {
            "createdDate": "2026-06-05T08:00:00Z",
            "createdBy": {"displayName": "Comment Author"},
        },
        "extensions": {"resolution": {"status": "open"}},
    }
    if location:
        payload["extensions"] = {"location": location, "resolution": {"status": "open"}}
    return payload
