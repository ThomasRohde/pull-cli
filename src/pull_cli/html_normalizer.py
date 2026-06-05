from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString

from .models import WarningRecord
from .security import SECRET_KEY_PATTERN, redact_source_url_text, redact_text, sanitize_url

WRITE_UI_SELECTORS = (
    ".plugin_attachments_container",
    ".plugin_attachments_upload_container",
    ".plugin_attachments_table_container",
    ".attachments-table-drop-zone",
    ".download-all-link",
    ".attachment-buttons",
    "table.attachments",
    ".labels-edit-container",
    ".show-labels-editor",
    ".editAttachmentLink",
    ".removeAttachmentLink",
)


def normalize_html(
    html: str, *, source_page_id: str, redact_source_urls: bool = False
) -> tuple[str, list[WarningRecord]]:
    soup = BeautifulSoup(html or "", "lxml")
    warnings: list[WarningRecord] = []
    removed_executable = False
    for tag in soup.find_all(["script", "style", "iframe", "object", "embed", "form"]):
        tag.decompose()
        removed_executable = True
    for selector in WRITE_UI_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()
            removed_executable = True
    for tag in soup.find_all("input"):
        input_type = str(tag.get("type") or "").lower()
        input_name = str(tag.get("name") or "")
        if input_type == "hidden" or input_type == "file" or SECRET_KEY_PATTERN.search(input_name):
            tag.decompose()
            removed_executable = True
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            attr_lower = attr.lower()
            if attr_lower.startswith("on") or SECRET_KEY_PATTERN.search(attr_lower):
                del tag.attrs[attr]
                removed_executable = True
                continue
            value = tag.attrs.get(attr)
            if isinstance(value, str):
                redacted = (
                    sanitize_url(value, redact_source_url=redact_source_urls)
                    if _is_source_url(value)
                    else redact_text(value)
                )
                if redacted != value:
                    tag.attrs[attr] = redacted
                    removed_executable = True
        for attr in ("href", "src", "data-file-src"):
            value = tag.get(attr)
            if isinstance(value, str) and value.strip().lower().startswith("javascript:"):
                del tag.attrs[attr]
                removed_executable = True
                continue
            if isinstance(value, str) and _is_source_url(value):
                sanitized = sanitize_url(value, redact_source_url=redact_source_urls)
                if sanitized != value:
                    tag.attrs[attr] = sanitized
                    removed_executable = True
    if redact_source_urls:
        for node in soup.find_all(string=True):
            if isinstance(node, NavigableString):
                redacted = redact_source_url_text(str(node))
                if redacted != str(node):
                    node.replace_with(redacted)
                    removed_executable = True
        for tag in soup.find_all("img"):
            src = tag.get("src")
            if isinstance(src, str) and _is_redacted_url(src) and not _has_accessible_label(tag):
                tag.decompose()
                removed_executable = True
    if removed_executable:
        warnings.append(
            WarningRecord(
                code="W_SANITIZED_HTML",
                message="Executable or active HTML content was stripped from the rendered page snapshot.",
                source_page_id=source_page_id,
            )
        )
    body = soup.body or soup
    return str(body), warnings


def soup_from_html(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def _is_source_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://", "//", "/wiki/", "/download/"))


def _is_redacted_url(value: str) -> bool:
    return value.strip().lower() in {"<redacted-url>", "&lt;redacted-url&gt;"}


def _has_accessible_label(tag) -> bool:
    for attr in ("alt", "title", "aria-label"):
        value = tag.get(attr)
        if isinstance(value, str) and value.strip():
            return True
    return False
