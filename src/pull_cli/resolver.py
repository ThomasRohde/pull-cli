from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

from .clients.base import ConfluenceClient
from .errors import EXIT_SOURCE, PullError, validation_error
from .models import PageSummary, TargetSelection

PAGE_URL_RE = re.compile(r"/pages/(?:viewpage\.action\?pageId=)?(?P<id>\d+)|[?&]pageId=(?P<query_id>\d+)")
NUMERIC_ID_RE = re.compile(r"^\d+$")


def is_url(value: str | None) -> bool:
    return bool(value and value.startswith(("http://", "https://")))


def page_id_from_url(url: str) -> str | None:
    parsed = urlsplit(url)
    query_id = parse_qs(parsed.query).get("pageId")
    if query_id:
        return query_id[0]
    path = unquote(parsed.path)
    match = PAGE_URL_RE.search(path)
    if match:
        return match.group("id") or match.group("query_id")
    return None


def resolve_target(selection: TargetSelection, client: ConfluenceClient) -> PageSummary:
    if selection.page_id:
        return PageSummary(page_id=selection.page_id, title=selection.page_id)
    if selection.url:
        return _summary_from_url(selection.url)
    if selection.positional and is_url(selection.positional):
        return _summary_from_url(selection.positional)
    if selection.positional and NUMERIC_ID_RE.match(selection.positional):
        return PageSummary(page_id=selection.positional, title=selection.positional)
    if selection.space and selection.title:
        matches = client.find_page(selection.space, selection.title)
        if not matches:
            raise PullError(
                code="ERR_SOURCE_PAGE_NOT_FOUND",
                message=f"No Confluence page matched space {selection.space!r} and title {selection.title!r}.",
                exit_code=EXIT_SOURCE,
                suggested_action="Check the space key/title or use --page-id.",
            )
        if len(matches) > 1:
            raise validation_error(
                "ERR_VALIDATION_AMBIGUOUS_PAGE",
                "Multiple Confluence pages matched the requested title.",
                suggested_action="Use --page-id or --url for an exact page.",
                details={"candidates": [match.__dict__ for match in matches]},
            )
        return matches[0]
    raise validation_error(
        "ERR_VALIDATION_REQUIRED",
        "A page selector is required.",
        suggested_action="Pass PAGE_REF, --page-id, --url, or --space with --title.",
    )


def _summary_from_url(url: str) -> PageSummary:
    page_id = page_id_from_url(url)
    if not page_id:
        raise validation_error(
            "ERR_VALIDATION_INVALID_URL",
            "The URL does not look like a Confluence page URL with a page ID.",
            suggested_action="Use a canonical Confluence page URL or --page-id.",
            details={"url": url},
        )
    return PageSummary(page_id=page_id, title=page_id, url=url)
