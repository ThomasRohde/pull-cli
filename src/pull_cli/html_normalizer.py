from __future__ import annotations

from bs4 import BeautifulSoup

from .models import WarningRecord


def normalize_html(html: str, *, source_page_id: str) -> tuple[str, list[WarningRecord]]:
    soup = BeautifulSoup(html or "", "lxml")
    warnings: list[WarningRecord] = []
    removed_executable = False
    for tag in soup.find_all(["script", "style", "iframe", "object", "embed"]):
        tag.decompose()
        removed_executable = True
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag.attrs[attr]
                removed_executable = True
        for attr in ("href", "src"):
            value = tag.get(attr)
            if isinstance(value, str) and value.strip().lower().startswith("javascript:"):
                del tag.attrs[attr]
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
