from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

from .attachment_extractors import extract_text_sidecar, write_extracted_markdown
from .clients.base import ConfluenceClient
from .models import AssetRecord, AssetReference, AttachmentRecord, PullOptions, WarningRecord
from .paths import safe_filename, unique_name
from .security import sanitize_url

ATTACHMENT_PATH_RE = re.compile(r"/download/attachments/(?P<page_id>[^/]+)/(?P<filename>[^?#]+)")


@dataclass
class AssetCandidate:
    original: str
    role: str
    html_attribute: str
    attachment: AttachmentRecord | None = None
    filename: str | None = None


def discover_asset_candidates(
    html: str,
    *,
    page_id: str,
    attachments: list[AttachmentRecord],
    options: PullOptions,
) -> list[AssetCandidate]:
    if options.no_assets:
        return []
    soup = BeautifulSoup(html or "", "lxml")
    attachment_by_name = {attachment.filename.lower(): attachment for attachment in attachments}
    attachment_by_url = {
        _normalize_url(attachment.download_url): attachment
        for attachment in attachments
        if attachment.download_url
    }
    candidates: list[AssetCandidate] = []
    seen: set[tuple[str, str]] = set()

    for tag in soup.find_all("img"):
        src = tag.get("src")
        if not isinstance(src, str) or _is_external(src) or _is_confluence_chrome_asset(src):
            continue
        attachment = attachment_by_url.get(_normalize_url(src)) or attachment_by_name.get(_filename_from_url(src).lower())
        _add_candidate(
            candidates,
            seen,
            AssetCandidate(src, "visible-image", "src", attachment, _filename_from_url(src)),
        )

    for tag in soup.find_all("a"):
        href = tag.get("href")
        if not isinstance(href, str):
            continue
        filename = _filename_from_url(href)
        attachment = attachment_by_url.get(_normalize_url(href)) or attachment_by_name.get(filename.lower())
        if attachment or ATTACHMENT_PATH_RE.search(href):
            _add_candidate(candidates, seen, AssetCandidate(href, "linked-attachment", "href", attachment, filename))

    if options.asset_policy in {"page", "all"}:
        for attachment in attachments:
            _add_candidate(
                candidates,
                seen,
                AssetCandidate(
                    attachment.download_url or attachment.web_url or attachment.filename,
                    "page-attachment",
                    "attachment",
                    attachment,
                    attachment.filename,
                ),
            )

    return candidates


def download_assets(
    candidates: list[AssetCandidate],
    *,
    page_id: str,
    page_assets_dir: Path,
    page_assets_path: str,
    client: ConfluenceClient,
    extract_attachments: bool = False,
) -> tuple[list[AssetRecord], list[WarningRecord]]:
    assets: list[AssetRecord] = []
    warnings: list[WarningRecord] = []
    used_names: set[str] = set()
    page_assets_dir.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(candidates, start=1):
        filename = safe_filename(candidate.attachment.filename if candidate.attachment else candidate.filename or "asset")
        filename = unique_name(filename, used_names)
        try:
            content = (
                client.download_attachment(candidate.attachment)
                if candidate.attachment
                else client.download_url(candidate.original)
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                WarningRecord(
                    code="W_ASSET_DOWNLOAD_FAILED",
                    message=f"Could not download asset {filename}.",
                    source_page_id=page_id,
                    details={"source_url": sanitize_url(candidate.original), "reason": str(exc)},
                )
            )
            continue
        target = page_assets_dir / filename
        target.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        media_type = candidate.attachment.media_type if candidate.attachment else mimetypes.guess_type(filename)[0]
        sidecars: list[str] = []
        if extract_attachments:
            try:
                extracted = extract_text_sidecar(target)
                if extracted:
                    sidecar = write_extracted_markdown(target, extracted)
                    sidecars.append(f"{page_assets_path}/{sidecar.name}")
            except Exception as exc:  # noqa: BLE001
                warnings.append(
                    WarningRecord(
                        code="W_ATTACHMENT_TEXT_EXTRACTION_FAILED",
                        message=f"Could not extract text sidecar for {filename}.",
                        source_page_id=page_id,
                        details={"reason": str(exc), "filename": filename},
                    )
                )
        assets.append(
            AssetRecord(
                asset_id=f"asset-{page_id}-{index}",
                source_page_id=page_id,
                attachment_id=candidate.attachment.attachment_id if candidate.attachment else None,
                filename=filename,
                media_type=media_type,
                local_path=f"{page_assets_path}/{filename}",
                sha256=digest,
                role=candidate.role,
                source_url=sanitize_url(candidate.attachment.download_url if candidate.attachment else candidate.original),
                references=[
                    AssetReference(
                        page_id=page_id,
                        html_attribute=candidate.html_attribute,
                        original=sanitize_url(candidate.original) or candidate.original,
                    )
                ],
                sidecars=sidecars,
            )
        )
    return assets, warnings


def skipped_asset_warnings(html: str, *, page_id: str) -> list[WarningRecord]:
    soup = BeautifulSoup(html or "", "lxml")
    warnings: list[WarningRecord] = []
    for tag in soup.find_all("img"):
        src = tag.get("src")
        if isinstance(src, str):
            warnings.append(
                WarningRecord(
                    code="W_ASSET_SKIPPED_BY_POLICY",
                    message="Image asset download was skipped by --no-assets.",
                    source_page_id=page_id,
                    details={"source_url": sanitize_url(src)},
                )
            )
    for tag in soup.find_all("a"):
        href = tag.get("href")
        if isinstance(href, str) and ATTACHMENT_PATH_RE.search(href):
            warnings.append(
                WarningRecord(
                    code="W_ASSET_SKIPPED_BY_POLICY",
                    message="Attachment download was skipped by --no-assets.",
                    source_page_id=page_id,
                    details={"source_url": sanitize_url(href)},
                )
            )
    return warnings


def _add_candidate(
    candidates: list[AssetCandidate], seen: set[tuple[str, str]], candidate: AssetCandidate
) -> None:
    key_value = (
        f"attachment:{candidate.attachment.attachment_id}"
        if candidate.attachment
        else _normalize_url(candidate.original)
    )
    key = (key_value, "asset")
    if key in seen:
        return
    seen.add(key)
    candidates.append(candidate)


def _filename_from_url(url: str) -> str:
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    match = ATTACHMENT_PATH_RE.search(path)
    if match:
        return unquote(match.group("filename"))
    return Path(path).name or "asset"


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlsplit(url)
    return unquote(parsed.path).lower()


def _is_external(url: str) -> bool:
    return url.startswith(("http://", "https://")) and "/download/attachments/" not in url


def _is_confluence_chrome_asset(url: str) -> bool:
    parsed = urlsplit(url)
    return any(
        marker in parsed.path
        for marker in (
            "/images/icons/",
            "/s/",
            "/download/resources/",
            "/plugins/servlet/",
        )
    )
