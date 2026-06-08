from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote


def slugify(value: str, *, fallback: str = "page") -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = lowered.strip("-")
    return lowered[:80] or fallback


def safe_filename(value: str, *, fallback: str = "asset") -> str:
    name = Path(value).name.strip()
    name = re.sub(r"[\x00-\x1f<>:\"|?*\\/]+", "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:180] or fallback


def unique_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    path = Path(name)
    stem = path.stem or "asset"
    suffix = path.suffix
    counter = 2
    while True:
        candidate = f"{stem}-{counter}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def as_posix(path: str | Path) -> str:
    return Path(path).as_posix()


def relative_path(from_file: str | Path, to_file: str | Path) -> str:
    from_path = Path(from_file)
    to_path = Path(to_file)
    return Path(os.path.relpath(to_path, start=from_path.parent)).as_posix()


def markdown_link_target(target: str | Path) -> str:
    value = str(target).replace("\\", "/")
    if not value or value in {"<redacted-url>", "redacted-url"}:
        return value
    if value.startswith(("#", "/", "http://", "https://", "mailto:", "jira:")):
        return value
    path_part, marker, fragment = value.partition("#")
    encoded = quote(path_part, safe="/%._-~")
    if marker:
        encoded += marker + quote(fragment, safe="%._-~")
    return encoded
