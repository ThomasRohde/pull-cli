from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from pull_cli.clients.base import ConfluenceClient
from pull_cli.models import AttachmentRecord, PageRecord, PageSummary


class FakeConfluenceClient(ConfluenceClient):
    def __init__(
        self,
        *,
        pages: dict[str, PageRecord],
        children: dict[str, list[PageSummary]] | None = None,
        attachments: dict[str, list[AttachmentRecord]] | None = None,
        downloads: dict[str, bytes] | None = None,
        base_url: str = "https://example.atlassian.net/wiki",
        deployment_type: str = "cloud",
    ) -> None:
        self.pages = pages
        self.children = children or {}
        self.attachments = attachments or {}
        self.downloads = downloads or {}
        self.base_url = base_url
        self.deployment_type = deployment_type
        self.api_calls = 0

    def get_page(self, page_id: str) -> PageRecord:
        self.api_calls += 1
        return replace(self.pages[page_id])

    def find_page(self, space: str, title: str) -> list[PageSummary]:
        self.api_calls += 1
        return [
            PageSummary(page_id=page.page_id, title=page.title, space_key=page.space_key, url=page.url)
            for page in self.pages.values()
            if page.space_key == space and page.title == title
        ]

    def get_children(self, page_id: str) -> list[PageSummary]:
        self.api_calls += 1
        return [replace(child) for child in self.children.get(page_id, [])]

    def get_descendants(self, page_id: str, depth: int | None = None) -> list[PageSummary]:
        output: list[PageSummary] = []
        queue = list(self.get_children(page_id))
        while queue:
            item = queue.pop(0)
            if depth is None or item.depth <= depth:
                output.append(item)
            queue.extend(self.get_children(item.page_id))
        return output

    def list_attachments(self, page_id: str) -> list[AttachmentRecord]:
        self.api_calls += 1
        return [replace(attachment) for attachment in self.attachments.get(page_id, [])]

    def download_attachment(self, attachment: AttachmentRecord) -> bytes:
        self.api_calls += 1
        return self.download_url(attachment.download_url or attachment.filename)

    def download_url(self, url: str) -> bytes:
        self.api_calls += 1
        if url in self.downloads:
            return self.downloads[url]
        for key, value in self.downloads.items():
            if url.endswith(key):
                return value
        raise FileNotFoundError(url)

    def close(self) -> None:
        return None


def make_page(
    page_id: str,
    title: str,
    *,
    body_view: str,
    storage: str = "",
    url: str | None = None,
) -> PageRecord:
    return PageRecord(
        page_id=page_id,
        title=title,
        space_key="EA",
        url=url or f"https://example.atlassian.net/wiki/spaces/EA/pages/{page_id}/{title.replace(' ', '+')}",
        version=1,
        body_view=body_view,
        body_storage=storage,
        raw={
            "id": page_id,
            "title": title,
            "_links": {"webui": f"/spaces/EA/pages/{page_id}/{title}"},
            "temporary": "https://example/download?token=secret-token",
        },
    )


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")
