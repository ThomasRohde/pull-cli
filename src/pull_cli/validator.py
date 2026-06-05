from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import WarningRecord
from .security import contains_secret_text

LOCAL_LINK_RE = re.compile(r"\[[^\]]*]\(([^)]+)\)")


@dataclass
class ValidationResult:
    ok: bool
    manifest_path: Path
    output_dir: Path
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[WarningRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def validate_package(path: Path) -> ValidationResult:
    manifest_path = path / "manifest.yaml" if path.is_dir() else path
    output_dir = manifest_path.parent
    result = ValidationResult(ok=True, manifest_path=manifest_path, output_dir=output_dir)
    if not manifest_path.exists():
        return _error(result, "ERR_VALIDATION_REQUIRED", "Manifest file does not exist.", {"path": str(manifest_path)})
    if manifest_path.is_file() and manifest_path.suffix.lower() == ".md":
        text = manifest_path.read_text(encoding="utf-8", errors="ignore")
        if text.lstrip().startswith("# AI Navigation Manifest"):
            return _error(
                result,
                "ERR_VALIDATION_REQUIRED",
                "This is the AI Markdown entrypoint; validate its parent directory or adjacent manifest.yaml.",
                {"path": str(manifest_path), "suggested_path": str(manifest_path.parent)},
            )
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return _error(result, "ERR_VALIDATION_REQUIRED", "Manifest YAML could not be parsed.", {"reason": str(exc)})
    if not isinstance(manifest, dict):
        return _error(result, "ERR_VALIDATION_REQUIRED", "Manifest root must be a mapping.", {})
    _check_required(result, manifest, ["schema_version", "tool", "source", "root", "pages", "paths"])
    if manifest.get("path_base") is not None:
        _check_path_base(result, manifest.get("path_base"), "manifest.path_base")
    manifest_paths = manifest.get("paths") if isinstance(manifest.get("paths"), dict) else {}
    if manifest_paths.get("bundle"):
        _check_relative_file(result, output_dir, manifest_paths.get("bundle"), "paths.bundle")
        bundle_path = output_dir / str(manifest_paths.get("bundle"))
        if bundle_path.exists():
            _check_markdown_links(result, bundle_path, output_dir)
    if manifest_paths.get("ai_manifest"):
        _check_relative_file(result, output_dir, manifest_paths.get("ai_manifest"), "paths.ai_manifest")
        _check_ai_manifest(result, output_dir, output_dir / str(manifest_paths.get("ai_manifest")))
    if manifest_paths.get("ai_entry"):
        _check_relative_file(result, output_dir, manifest_paths.get("ai_entry"), "paths.ai_entry")
        ai_entry_path = output_dir / str(manifest_paths.get("ai_entry"))
        if ai_entry_path.exists():
            _check_markdown_links(result, ai_entry_path, output_dir)
    pages = manifest.get("pages") if isinstance(manifest.get("pages"), list) else []
    assets = manifest.get("assets") if isinstance(manifest.get("assets"), list) else []
    result.metrics.update({"pages": len(pages), "assets": len(assets)})
    if not pages:
        _error(result, "ERR_VALIDATION_REQUIRED", "Manifest contains no pages.", {})

    for page in pages:
        if not isinstance(page, dict):
            _error(result, "ERR_VALIDATION_REQUIRED", "Page manifest entry is not a mapping.", {})
            continue
        paths = page.get("paths") if isinstance(page.get("paths"), dict) else {}
        for key in ("markdown", "metadata"):
            _check_relative_file(result, output_dir, paths.get(key), f"page.{key}")
        for optional in ("html", "source", "comments"):
            if paths.get(optional):
                _check_relative_file(result, output_dir, paths.get(optional), f"page.{optional}")
                if optional == "comments":
                    comments_path = output_dir / str(paths.get(optional))
                    if comments_path.exists():
                        _check_markdown_links(result, comments_path, output_dir)
        markdown_path = output_dir / str(paths.get("markdown", ""))
        if markdown_path.exists():
            _check_markdown_links(result, markdown_path, output_dir)
    _check_redacted_rewritten_links(result, output_dir, pages, manifest.get("links"))

    for asset in assets:
        if not isinstance(asset, dict):
            _error(result, "ERR_VALIDATION_REQUIRED", "Asset manifest entry is not a mapping.", {})
            continue
        local_path = asset.get("local_path")
        asset_path = output_dir / str(local_path or "")
        _check_relative_file(result, output_dir, local_path, "asset.local_path")
        if asset_path.exists() and asset.get("sha256"):
            digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
            if digest != asset["sha256"]:
                _error(
                    result,
                    "ERR_VALIDATION_REQUIRED",
                    "Asset checksum does not match manifest.",
                    {"asset": local_path},
                )

    warning_path = output_dir / "diagnostics" / "warnings.jsonl"
    package_warning_count = 0
    if warning_path.exists():
        for line_number, line in enumerate(warning_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            package_warning_count += 1
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                _error(
                    result,
                    "ERR_VALIDATION_REQUIRED",
                    "warnings.jsonl contains invalid JSON.",
                    {"line": line_number, "reason": str(exc)},
                )
    result.metrics["package_warnings"] = package_warning_count

    _scan_for_secret_markers(result, output_dir)
    result.ok = not result.errors
    return result


def _check_required(result: ValidationResult, manifest: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        if key not in manifest:
            _error(result, "ERR_VALIDATION_REQUIRED", f"Manifest is missing required key {key!r}.", {})


def _check_relative_file(
    result: ValidationResult, output_dir: Path, relative: object, label: str
) -> None:
    if not isinstance(relative, str) or not relative:
        _error(result, "ERR_VALIDATION_REQUIRED", f"Missing relative path for {label}.", {})
        return
    rel_path = Path(relative)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        _error(result, "ERR_VALIDATION_REQUIRED", f"Path for {label} must be relative to output root.", {"path": relative})
        return
    if not (output_dir / rel_path).exists():
        _error(result, "ERR_VALIDATION_REQUIRED", f"Referenced file for {label} does not exist.", {"path": relative})


def _check_markdown_links(result: ValidationResult, markdown_path: Path, output_dir: Path) -> None:
    text = markdown_path.read_text(encoding="utf-8")
    for match in LOCAL_LINK_RE.finditer(text):
        target = _markdown_link_destination(match.group(1))
        if not target or target in {"redacted-url", "<redacted-url>"} or target.startswith(("#", "/", "http://", "https://", "mailto:", "jira:")):
            continue
        target_path = target.split("#", 1)[0]
        resolution_base = markdown_path.parent.resolve()
        candidate_path = (markdown_path.parent / target_path).resolve()
        details = {
            "link": target,
            "file": str(markdown_path),
            "resolution_base": str(resolution_base),
            "candidate_path": str(candidate_path),
        }
        if not candidate_path.is_relative_to(output_dir.resolve()):
            _error(result, "ERR_VALIDATION_REQUIRED", "Markdown link escapes output directory.", details)
            continue
        if not candidate_path.exists():
            _error(result, "ERR_VALIDATION_REQUIRED", "Markdown local link target does not exist.", details)


def _check_redacted_rewritten_links(
    result: ValidationResult, output_dir: Path, pages: list[Any], links: object
) -> None:
    if not isinstance(links, list):
        return
    rewritten_links_by_page: dict[str, int] = {}
    rewritten_assets_by_page: dict[str, int] = {}
    redacted_link_allowance_by_page: dict[str, int] = {}
    redacted_asset_allowance_by_page: dict[str, int] = {}
    for link in links:
        if not isinstance(link, dict):
            continue
        source_page_id = link.get("source_page_id")
        if not isinstance(source_page_id, str) or not source_page_id:
            continue
        kind = link.get("kind")
        if link.get("status") == "rewritten" and link.get("rewritten"):
            if kind == "asset":
                rewritten_assets_by_page[source_page_id] = rewritten_assets_by_page.get(source_page_id, 0) + 1
            else:
                rewritten_links_by_page[source_page_id] = rewritten_links_by_page.get(source_page_id, 0) + 1
        elif kind == "asset":
            redacted_asset_allowance_by_page[source_page_id] = redacted_asset_allowance_by_page.get(source_page_id, 0) + 1
        elif kind not in {"anchor", "mailto"}:
            redacted_link_allowance_by_page[source_page_id] = redacted_link_allowance_by_page.get(source_page_id, 0) + 1

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("page_id")
        if not isinstance(page_id, str):
            continue
        has_rewritten_links = rewritten_links_by_page.get(page_id, 0) > 0
        has_rewritten_assets = rewritten_assets_by_page.get(page_id, 0) > 0
        if not has_rewritten_links and not has_rewritten_assets:
            continue
        paths = page.get("paths") if isinstance(page.get("paths"), dict) else {}
        markdown = paths.get("markdown")
        if not isinstance(markdown, str) or not markdown:
            continue
        markdown_path = output_dir / markdown
        if not markdown_path.exists():
            continue
        redacted_links = _redacted_markdown_link_lines(markdown_path)
        redacted_page_links = [link for link in redacted_links if link["kind"] == "link"]
        redacted_asset_links = [link for link in redacted_links if link["kind"] == "image"]
        link_allowance = redacted_link_allowance_by_page.get(page_id, 0)
        asset_allowance = redacted_asset_allowance_by_page.get(page_id, 0) + _asset_warning_allowance(page)
        if has_rewritten_links and len(redacted_page_links) > link_allowance:
            _error(
                result,
                "ERR_VALIDATION_REDACTED_REWRITTEN_LINK",
                "Markdown contains redacted link placeholders although the manifest has rewritten local links for this page.",
                {
                    "page_id": page_id,
                    "file": str(markdown_path),
                    "redacted_links": len(redacted_page_links),
                    "non_rewritten_link_allowance": link_allowance,
                    "rewritten_links": rewritten_links_by_page[page_id],
                    "examples": redacted_page_links[:5],
                },
            )
        if has_rewritten_assets and len(redacted_asset_links) > asset_allowance:
            _error(
                result,
                "ERR_VALIDATION_REDACTED_REWRITTEN_LINK",
                "Markdown contains redacted image placeholders although the manifest has rewritten local assets for this page.",
                {
                    "page_id": page_id,
                    "file": str(markdown_path),
                    "redacted_images": len(redacted_asset_links),
                    "non_rewritten_asset_allowance": asset_allowance,
                    "rewritten_assets": rewritten_assets_by_page[page_id],
                    "examples": redacted_asset_links[:5],
                },
            )


def _redacted_markdown_link_lines(markdown_path: Path) -> list[dict[str, Any]]:
    examples = []
    for line_number, line in enumerate(markdown_path.read_text(encoding="utf-8").splitlines(), start=1):
        for match in LOCAL_LINK_RE.finditer(line):
            if _markdown_link_destination(match.group(1)) == "redacted-url":
                kind = "image" if match.start() > 0 and line[match.start() - 1] == "!" else "link"
                examples.append({"line": line_number, "kind": kind, "text": line.strip()})
    return examples


def _asset_warning_allowance(page: dict[str, Any]) -> int:
    warnings = page.get("warnings") if isinstance(page.get("warnings"), list) else []
    return sum(
        1
        for warning in warnings
        if isinstance(warning, dict) and warning.get("code") in {"W_ASSET_DOWNLOAD_FAILED", "W_ASSET_SKIPPED_BY_POLICY"}
    )


def _check_ai_manifest(result: ValidationResult, output_dir: Path, path: Path) -> None:
    if not path.exists():
        return
    try:
        ai_manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        _error(result, "ERR_VALIDATION_REQUIRED", "AI manifest YAML could not be parsed.", {"reason": str(exc)})
        return
    if not isinstance(ai_manifest, dict):
        _error(result, "ERR_VALIDATION_REQUIRED", "AI manifest root must be a mapping.", {})
        return
    _check_required(result, ai_manifest, ["schema_version", "path_base", "root", "entrypoints", "pages", "diagnostics"])
    _check_path_base(result, ai_manifest.get("path_base"), "ai_manifest.path_base")
    entrypoints = ai_manifest.get("entrypoints") if isinstance(ai_manifest.get("entrypoints"), dict) else {}
    for label, entrypoint in entrypoints.items():
        if entrypoint:
            _check_relative_file(result, output_dir, entrypoint, f"ai_manifest.entrypoints.{label}")
    pages = ai_manifest.get("pages") if isinstance(ai_manifest.get("pages"), list) else []
    seen_names: set[str] = set()
    page_children: list[tuple[str, list[Any]]] = []
    page_parents: list[tuple[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            _error(result, "ERR_VALIDATION_REQUIRED", "AI manifest page entry is not a mapping.", {})
            continue
        name = page.get("name")
        if not isinstance(name, str) or not name:
            _error(result, "ERR_VALIDATION_REQUIRED", "AI manifest page is missing a name.", {})
        elif name in seen_names:
            _error(result, "ERR_VALIDATION_REQUIRED", "AI manifest page names must be unique.", {"name": name})
        else:
            seen_names.add(name)
        children = page.get("children") if isinstance(page.get("children"), list) else []
        if isinstance(name, str) and name:
            page_children.append((name, children))
            page_parents.append((name, page.get("parent")))
        _check_relative_file(result, output_dir, page.get("markdown"), "ai_manifest.page.markdown")
        if page.get("comments"):
            _check_relative_file(result, output_dir, page.get("comments"), "ai_manifest.page.comments")
        assets = page.get("assets") if isinstance(page.get("assets"), list) else []
        for asset in assets:
            if not isinstance(asset, dict):
                _error(result, "ERR_VALIDATION_REQUIRED", "AI manifest asset entry is not a mapping.", {})
                continue
            _check_relative_file(result, output_dir, asset.get("path"), "ai_manifest.asset.path")
            sidecars = asset.get("sidecars") if isinstance(asset.get("sidecars"), list) else []
            for sidecar in sidecars:
                _check_relative_file(result, output_dir, sidecar, "ai_manifest.asset.sidecar")
    for name, children in page_children:
        for child in children:
            if not isinstance(child, str) or child not in seen_names:
                _error(
                    result,
                    "ERR_VALIDATION_REQUIRED",
                    "AI manifest child reference does not match a page name.",
                    {"page": name, "child": child},
                )
    for name, parent in page_parents:
        if parent is not None and (not isinstance(parent, str) or parent not in seen_names):
            _error(
                result,
                "ERR_VALIDATION_REQUIRED",
                "AI manifest parent reference does not match a page name.",
                {"page": name, "parent": parent},
            )


def _check_path_base(result: ValidationResult, path_base: object, label: str) -> None:
    if not isinstance(path_base, dict):
        _error(result, "ERR_VALIDATION_REQUIRED", f"{label} must be a mapping.", {})
        return
    if path_base.get("kind") != "package_root":
        _error(
            result,
            "ERR_VALIDATION_REQUIRED",
            f"{label}.kind must be 'package_root'.",
            {"kind": path_base.get("kind")},
        )
    if path_base.get("root") != ".":
        _error(
            result,
            "ERR_VALIDATION_REQUIRED",
            f"{label}.root must be '.'.",
            {"root": path_base.get("root")},
        )
    rule = path_base.get("rule")
    if not isinstance(rule, str) or (label == "ai_manifest.path_base" and "directory containing" not in rule):
        _error(result, "ERR_VALIDATION_REQUIRED", f"{label}.rule must explain the package-root base.", {})


def _markdown_link_destination(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<"):
        end = target.find(">")
        return target[1:end] if end != -1 else target.strip("<>")
    for marker in (' "', " '", "\t\"", "\t'"):
        if marker in target:
            return target.split(marker, 1)[0].strip()
    return target


def _scan_for_secret_markers(result: ValidationResult, output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml", ".json", ".jsonl", ".md", ".html", ".xml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if contains_secret_text(text):
            _error(
                result,
                "ERR_VALIDATION_SECRET_PATTERN",
                "A secret-like marker was found in a text output file.",
                {"path": str(path.relative_to(output_dir))},
            )


def _error(
    result: ValidationResult, code: str, message: str, details: dict[str, Any]
) -> ValidationResult:
    result.ok = False
    result.errors.append(
        {
            "code": code,
            "message": message,
            "retryable": False,
            "suggested_action": "Regenerate the package or inspect the referenced file.",
            "details": details,
        }
    )
    return result
