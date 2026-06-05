from __future__ import annotations

import pytest

from pull_cli.errors import PullError
from pull_cli.models import PageSummary, TargetSelection
from pull_cli.resolver import page_id_from_url, resolve_target


class ResolverClient:
    base_url = "https://example.atlassian.net/wiki"
    deployment_type = "cloud"
    api_calls = 0

    def find_page(self, space: str, title: str):
        if title == "One":
            return [PageSummary(page_id="111", title="One", space_key=space)]
        if title == "Many":
            return [
                PageSummary(page_id="111", title="Many", space_key=space),
                PageSummary(page_id="222", title="Many", space_key=space),
            ]
        return []


def test_page_id_from_confluence_url() -> None:
    assert page_id_from_url("https://x.atlassian.net/wiki/spaces/EA/pages/123456/Architecture") == "123456"
    assert page_id_from_url("https://x/wiki/pages/viewpage.action?pageId=789") == "789"


def test_resolution_order_prefers_explicit_page_id() -> None:
    target = resolve_target(
        TargetSelection(
            positional="https://x.atlassian.net/wiki/spaces/EA/pages/999/Wrong",
            page_id="123",
            url="https://x.atlassian.net/wiki/spaces/EA/pages/456/AlsoWrong",
        ),
        ResolverClient(),
    )
    assert target.page_id == "123"


def test_space_title_resolution_and_ambiguous_error() -> None:
    assert resolve_target(TargetSelection(space="EA", title="One"), ResolverClient()).page_id == "111"
    with pytest.raises(PullError) as exc:
        resolve_target(TargetSelection(space="EA", title="Many"), ResolverClient())
    assert exc.value.code == "ERR_VALIDATION_AMBIGUOUS_PAGE"
