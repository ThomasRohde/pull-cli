from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .assets import ATTACHMENT_PATH_RE
from .models import AssetRecord, LinkRecord, PageSummary, WarningRecord
from .paths import relative_path
from .resolver import page_id_from_url

HEADING_CHARS_RE = re.compile(r"[^a-z0-9 -]")


def rewrite_html_links(
    html: str,
    *,
    page: PageSummary,
    page_index_path: str,
    pages_by_id: dict[str, PageSummary],
    page_paths: dict[str, str],
    assets: list[AssetRecord],
    rewrite_links: bool,
) -> tuple[str, list[LinkRecord], list[WarningRecord]]:
    soup = BeautifulSoup(html or "", "lxml")
    links: list[LinkRecord] = []
    warnings: list[WarningRecord] = []
    asset_by_original = _asset_lookup(assets)
    anchors = _heading_anchors(soup)

    for tag in soup.find_all("img"):
        src = tag.get("src")
        if not isinstance(src, str):
            continue
        asset = asset_by_original.get(_asset_key(src))
        if asset and rewrite_links:
            rewritten = relative_path(page_index_path, asset.local_path)
            tag["src"] = rewritten
            links.append(
                LinkRecord(
                    original=src,
                    normalized=_asset_key(src),
                    kind="asset",
                    source_page_id=page.page_id,
                    target_asset_id=asset.asset_id,
                    rewritten=rewritten,
                    status="rewritten",
                )
            )

    for tag in soup.find_all("a"):
        href = tag.get("href")
        if not isinstance(href, str):
            continue
        record = _rewrite_href(
            href,
            page=page,
            page_index_path=page_index_path,
            pages_by_id=pages_by_id,
            page_paths=page_paths,
            asset_by_original=asset_by_original,
            anchors=anchors,
            rewrite_links=rewrite_links,
        )
        links.append(record)
        if record.rewritten and rewrite_links:
            tag["href"] = record.rewritten
        if record.warning:
            warnings.append(
                WarningRecord(
                    code=record.warning,
                    message=f"Link could not be fully rewritten: {href}",
                    source_page_id=page.page_id,
                    details={"href": href},
                )
            )
    return str(soup.body or soup), links, warnings


def markdown_anchor(text: str) -> str:
    value = text.strip().lower().replace("_", "-")
    value = HEADING_CHARS_RE.sub("", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value


def _rewrite_href(
    href: str,
    *,
    page: PageSummary,
    page_index_path: str,
    pages_by_id: dict[str, PageSummary],
    page_paths: dict[str, str],
    asset_by_original: dict[str, AssetRecord],
    anchors: set[str],
    rewrite_links: bool,
) -> LinkRecord:
    if href.startswith("mailto:"):
        return LinkRecord(href, href, "mailto", page.page_id, status="preserved")
    if _is_jira(href):
        return LinkRecord(href, href, "jira", page.page_id, status="preserved")
    if href.startswith("#"):
        anchor = markdown_anchor(href[1:])
        status = "rewritten" if anchor in anchors else "unresolved"
        warning = None if anchor in anchors else "W_LINK_ANCHOR_UNRESOLVED"
        rewritten = f"#{anchor}" if anchor and rewrite_links else href
        return LinkRecord(href, anchor, "anchor", page.page_id, rewritten=rewritten, status=status, warning=warning)

    asset = asset_by_original.get(_asset_key(href))
    if asset:
        rewritten = relative_path(page_index_path, asset.local_path)
        return LinkRecord(
            href,
            _asset_key(href),
            "attachment",
            page.page_id,
            target_asset_id=asset.asset_id,
            rewritten=rewritten,
            status="rewritten",
        )

    target_page_id = page_id_from_url(href)
    if target_page_id and target_page_id in pages_by_id:
        anchor = urlsplit(href).fragment
        rewritten = relative_path(page_index_path, page_paths[target_page_id])
        if anchor:
            rewritten += f"#{markdown_anchor(anchor)}"
        return LinkRecord(
            href,
            target_page_id,
            "page",
            page.page_id,
            target_page_id=target_page_id,
            rewritten=rewritten,
            status="rewritten",
        )
    if ATTACHMENT_PATH_RE.search(href):
        return LinkRecord(
            href,
            _asset_key(href),
            "attachment",
            page.page_id,
            status="unresolved",
            warning="W_LINK_UNRESOLVED",
        )
    if href.startswith(("http://", "https://")):
        return LinkRecord(href, href, "external", page.page_id, status="preserved")
    return LinkRecord(href, href, "unknown", page.page_id, status="preserved")


def _heading_anchors(soup: BeautifulSoup) -> set[str]:
    anchors: set[str] = set()
    for tag in soup.find_all(re.compile("^h[1-6]$")):
        if tag.get("id"):
            anchors.add(markdown_anchor(str(tag["id"])))
        text = tag.get_text(" ", strip=True)
        if text:
            anchors.add(markdown_anchor(text))
    for tag in soup.find_all(attrs={"name": True}):
        anchors.add(markdown_anchor(str(tag["name"])))
    return anchors


def _asset_lookup(assets: list[AssetRecord]) -> dict[str, AssetRecord]:
    lookup: dict[str, AssetRecord] = {}
    for asset in assets:
        for ref in asset.references:
            lookup[_asset_key(ref.original)] = asset
        if asset.source_url:
            lookup[_asset_key(asset.source_url)] = asset
        lookup[Path(asset.filename).name.lower()] = asset
    return lookup


def _asset_key(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.path:
        return parsed.path.lower()
    return url.lower()


def _is_jira(href: str) -> bool:
    return bool(re.search(r"/browse/[A-Z][A-Z0-9]+-\d+", href)) or href.startswith("jira:")
