from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any

import yaml

from .errors import EXIT_VALIDATION, PullError
from .html_normalizer import normalize_html
from .markdown_writer import rendered_html_to_markdown
from .models import (
    AssetRecord,
    CommentRecord,
    ExtractionResult,
    PageArtifact,
    PullOptions,
    WarningRecord,
)
from .paths import as_posix, markdown_link_target, relative_path, slugify
from .security import (
    SECRET_KEY_PATTERN,
    redact_source_url_text,
    redact_text,
    redact_value,
    sanitize_url,
)

BUNDLE_LINK_RE = re.compile(r"(!?\[[^\]]*]\()([^)]+)(\))")
WRITE_ORIENTED_SNAPSHOT_KEYS = {
    "draft",
    "draftid",
    "edit",
    "editui",
    "edituiv2",
    "isactiveliveeditsession",
    "operations",
    "permissions",
}
REDACTED_SNAPSHOT_KEYS = {
    "draftversion",
    "restrictions",
    "schedulepublishdate",
    "schedulepublishinfo",
}
REDACTED_LINK_KEYS = {
    "base",
    "context",
    "self",
    "tinyui",
    "webui",
}


def prepare_output_dir(output: Path, *, force: bool, clean: bool) -> None:
    if output.exists() and clean:
        shutil.rmtree(output)
    if output.exists() and any(output.iterdir()) and not force and not clean:
        raise PullError(
            code="ERR_VALIDATION_OUTPUT_EXISTS",
            message=f"Output directory already exists and is not empty: {output}",
            exit_code=EXIT_VALIDATION,
            suggested_action="Use --force to add/overwrite files or --clean to replace the directory.",
        )
    output.mkdir(parents=True, exist_ok=True)
    (output / "pages").mkdir(exist_ok=True)
    (output / "diagnostics").mkdir(exist_ok=True)


def write_page_artifact(output: Path, artifact: PageArtifact, *, options: PullOptions) -> None:
    page_dir = output / artifact.page_dir
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "assets").mkdir(exist_ok=True)
    (output / artifact.index_md).write_text(artifact.markdown, encoding="utf-8")
    if options.write_html and artifact.index_html:
        (output / artifact.index_html).write_text(
            _sanitize_snapshot(artifact.html, redact_source_urls=options.redact_source_urls),
            encoding="utf-8",
        )
    if options.write_source and artifact.source_path and artifact.page.body_storage:
        (output / artifact.source_path).write_text(
            _sanitize_snapshot(artifact.page.body_storage, redact_source_urls=options.redact_source_urls),
            encoding="utf-8",
        )
    page_json_data = {
        "page": _sanitize_snapshot(artifact.page.raw, redact_source_urls=options.redact_source_urls),
        "metadata": {
            "page_id": artifact.page.page_id,
            "title": artifact.page.title,
            "space_key": artifact.page.space_key,
            "version": artifact.page.version,
            "url": sanitize_url(artifact.page.url, redact_source_url=options.redact_source_urls),
            "labels": artifact.page.labels,
        },
        "representations": {
            "has_rendered_html": bool(artifact.page.body_view or artifact.page.body_export_view),
            "has_storage": bool(artifact.page.body_storage),
            "has_adf": bool(artifact.page.body_adf),
        },
        "warnings": [warning.to_dict() for warning in artifact.warnings],
    }
    (output / artifact.page_json).write_text(
        json.dumps(
            redact_value(page_json_data, redact_source_urls=options.redact_source_urls),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    if artifact.comments_path and artifact.comments:
        (output / artifact.comments_path).write_text(
            _comments_markdown(artifact, options=options),
            encoding="utf-8",
        )


def write_manifest(result: ExtractionResult, *, options: PullOptions, root_page_id: str, base_url: str, deployment_type: str) -> None:
    manifest = build_manifest(
        result,
        options=options,
        root_page_id=root_page_id,
        base_url=base_url,
        deployment_type=deployment_type,
    )
    result.manifest_path.write_text(
        yaml.safe_dump(
            redact_value(manifest, redact_source_urls=options.redact_manifest),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    write_ai_manifests(result, options=options)


def build_manifest(
    result: ExtractionResult,
    *,
    options: PullOptions,
    root_page_id: str,
    base_url: str,
    deployment_type: str,
) -> dict[str, Any]:
    ai_paths = _ai_manifest_paths(result)
    pages = []
    for artifact in result.pages:
        paths = {
            "dir": artifact.page_dir,
            "markdown": artifact.index_md,
            "html": artifact.index_html,
            "source": artifact.source_path,
            "metadata": artifact.page_json,
        }
        page_entry = {
            "order": artifact.order,
            "page_id": artifact.page.page_id,
            "title": artifact.page.title,
            "space_key": artifact.page.space_key,
            "parent_id": artifact.page.parent_id,
            "depth": artifact.page.depth,
            "version": artifact.page.version,
            "url": artifact.page.url,
            "paths": paths,
            "assets": [asset.asset_id for asset in artifact.assets],
            "warnings": [warning.to_dict() for warning in artifact.warnings],
            "macro_records": [macro.macro_id for macro in artifact.macros],
        }
        if artifact.comments_path and artifact.comments:
            paths["comments"] = artifact.comments_path
            page_entry["comments"] = {
                "count": len(artifact.comments),
                "locations": _comment_locations(artifact.comments, options=options),
            }
        pages.append(page_entry)
    return {
        "schema_version": "1.0",
        "tool": {"name": "pull-cli", "version": _tool_version()},
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "base_url": base_url,
            "deployment_type": deployment_type,
        },
        "root": {"page_id": root_page_id},
        "path_base": {
            "kind": "package_root",
            "root": ".",
            "rule": "All relative paths in this manifest are relative to the output package root.",
        },
        "options": options.manifest_dict(),
        "paths": {
            "manifest": "manifest.yaml",
            "ai_manifest": ai_paths["manifest"],
            "ai_entry": ai_paths["entry"],
            "bundle": as_posix(result.bundle_path.relative_to(result.output_dir)) if result.bundle_path else None,
            "chunks": "chunks.jsonl" if options.write_chunks else None,
            "warnings": "diagnostics/warnings.jsonl",
            "unresolved_links": "diagnostics/unresolved-links.md",
        },
        "pages": pages,
        "assets": [asset.to_manifest() for asset in result.assets],
        "links": [asdict(link) for link in result.links],
        "macros": [macro.to_manifest() for macro in result.macros],
        "warnings": [warning.to_dict() for warning in result.warnings],
        "errors": [],
        "completeness": {
            "pages_requested": len(result.pages),
            "pages_written": len(result.pages),
            "assets_downloaded": len(result.assets),
            "warnings": len(result.warnings),
            "rendered_page_first": True,
        },
    }


def write_ai_manifests(result: ExtractionResult, *, options: PullOptions) -> None:
    page_names = _page_names(result.pages)
    ai_paths = _ai_manifest_paths(result, page_names=page_names)
    ai_manifest = build_ai_manifest(result, options=options, page_names=page_names, ai_paths=ai_paths)
    result.ai_manifest_path = result.output_dir / ai_paths["manifest"]
    result.ai_entry_path = result.output_dir / ai_paths["entry"]
    result.ai_manifest_path.write_text(
        yaml.safe_dump(ai_manifest, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    result.ai_entry_path.write_text(
        build_ai_entry_markdown(ai_manifest),
        encoding="utf-8",
    )


def build_ai_manifest(
    result: ExtractionResult,
    *,
    options: PullOptions,
    page_names: dict[str, str] | None = None,
    ai_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    page_names = page_names or _page_names(result.pages)
    ai_paths = ai_paths or _ai_manifest_paths(result, page_names=page_names)
    children_by_parent: dict[str, list[str]] = {}
    for artifact in result.pages:
        parent_id = artifact.page.parent_id
        if parent_id and parent_id in page_names:
            children_by_parent.setdefault(parent_id, []).append(page_names[artifact.page.page_id])

    pages = []
    for artifact in result.pages:
        parent_name = page_names.get(artifact.page.parent_id or "")
        page_assets = [_ai_asset(asset) for asset in artifact.assets]
        page_entry = {
            "name": page_names[artifact.page.page_id],
            "title": artifact.page.title,
            "page_id": artifact.page.page_id,
            "parent": parent_name,
            "depth": artifact.page.depth,
            "markdown": artifact.index_md,
            "children": children_by_parent.get(artifact.page.page_id, []),
            "assets": page_assets,
            "warnings": len(artifact.warnings),
        }
        if artifact.comments_path and artifact.comments:
            page_entry["comments"] = artifact.comments_path
            page_entry["comments_count"] = len(artifact.comments)
        pages.append(page_entry)

    return {
        "schema_version": "1.0",
        "output_mode": options.output_mode,
        "purpose": "Minimal AI navigation manifest for this pulled Confluence package.",
        "start_here": "Read this file first, then open page markdown paths or asset sidecars as needed.",
        "artifact_guidance": _artifact_guidance(result, options=options),
        "path_base": {
            "kind": "package_root",
            "root": ".",
            "rule": "Resolve every relative path in this YAML against the directory containing this YAML file, regardless of the agent shell current working directory.",
            "page_markdown_rule": "After opening a page markdown file, resolve links inside that page relative to that page file.",
            "bundle_rule": "bundle.md is for linear reading and search; its local links are rebased to package_root."
            if result.bundle_path
            else None,
        },
        "root": page_names[result.pages[0].page.page_id] if result.pages else None,
        "entrypoints": {
            "ai_entry": ai_paths["entry"],
            "ai_manifest": ai_paths["manifest"],
            "bundle": as_posix(result.bundle_path.relative_to(result.output_dir))
            if result.bundle_path
            else None,
            "full_manifest": "manifest.yaml",
            "warnings": "diagnostics/warnings.jsonl",
            "unresolved_links": "diagnostics/unresolved-links.md",
            "chunks": "chunks.jsonl" if (result.output_dir / "chunks.jsonl").exists() else None,
        },
        "pages": pages,
        "diagnostics": {
            "warnings": len(result.warnings),
            "warning_codes": _warning_counts(result.warnings),
            "warnings_path": "diagnostics/warnings.jsonl",
            "unresolved_links_path": "diagnostics/unresolved-links.md",
        },
    }


def build_ai_entry_markdown(ai_manifest: dict[str, Any]) -> str:
    simple_mode = ai_manifest.get("output_mode") == "simple"
    entrypoints = ai_manifest.get("entrypoints", {})
    bundle_path = entrypoints.get("bundle") if isinstance(entrypoints, dict) else None
    lines = [
        "# AI Navigation Manifest",
        "",
        str(ai_manifest["start_here"]),
        "",
        f"Root page: `{ai_manifest.get('root')}`",
        "",
        "## Agent Instructions",
        "",
        "1. Set `PACKAGE_ROOT` to the directory containing this file.",
        "2. If you are launched from a repo root or another working directory, keep `PACKAGE_ROOT` as the path base; do not resolve these links against the repo root.",
        "3. Resolve every relative path in this file against `PACKAGE_ROOT`."
        if simple_mode
        else "3. Resolve every relative path in this file and in the YAML manifest against `PACKAGE_ROOT`.",
        "4. Open page Markdown paths under `pages/` for detailed evidence; after opening a page, resolve links inside it relative to that page file.",
        "5. Use the page hierarchy below to choose the smallest relevant page set before reading broad context.",
        _agent_instruction_6(simple_mode=simple_mode, bundle_path=bundle_path),
        "7. Open asset sidecars when present before inferring image, diagram, PDF, or text attachment content.",
        "8. Treat warning counts below as a signal to run validation before making claims about missing content, broken links, macros, or assets."
        if simple_mode
        else "8. Check diagnostics when warning counts are nonzero before making claims about missing content, broken links, macros, or assets.",
        "",
        "## Artifact Guidance",
        "",
        str(ai_manifest.get("artifact_guidance", {}).get("rule", "")),
        "",
        _surfaces_line("Navigation surfaces", ai_manifest.get("artifact_guidance", {}).get("navigation_surfaces")),
        _simple_control_files_line(simple_mode)
        if simple_mode
        else _surfaces_line(
            "Raw reference surfaces",
            ai_manifest.get("artifact_guidance", {}).get("raw_reference_surfaces"),
            suffix="; their links may be redacted and are not evidence of failed local rewriting.",
        ),
        "",
        "## First Checks",
        "",
        "Run `pull validate <PACKAGE_ROOT>` before analysis. If validation fails, inspect the reported file, link, resolution base, candidate path, and diagnostics before trusting generated links or artifacts.",
    ]
    core_file_labels = ("bundle", "chunks") if simple_mode else (
        "ai_manifest",
        "bundle",
        "full_manifest",
        "warnings",
        "unresolved_links",
        "chunks",
    )
    core_file_lines = []
    for label in core_file_labels:
        path = entrypoints.get(label) if isinstance(entrypoints, dict) else None
        if path:
            core_file_lines.append(f"- {label}: [{path}]({markdown_link_target(path)})")
    if core_file_lines:
        lines.extend(["", "## Core Files", "", *core_file_lines])
    lines.extend(["", "## Page Hierarchy", ""])
    _append_page_hierarchy(lines, ai_manifest)
    assets = [
        (page["name"], asset)
        for page in ai_manifest.get("pages", [])
        for asset in page.get("assets", [])
    ]
    if assets:
        lines.extend(["", "## Assets", ""])
        for page_name, asset in assets:
            sidecars = asset.get("sidecars") or []
            sidecar_text = ""
            if sidecars:
                sidecar_links = ", ".join(
                    f"[{sidecar}]({markdown_link_target(sidecar)})" for sidecar in sidecars
                )
                sidecar_text = f"; sidecars: {sidecar_links}"
            lines.append(
                f"- `{page_name}/{asset['name']}`: [{asset['path']}]({markdown_link_target(asset['path'])}){sidecar_text}"
            )
    lines.extend(["", "## Diagnostics", "", f"- warnings: {ai_manifest.get('diagnostics', {}).get('warnings', 0)}"])
    if not simple_mode:
        lines.extend(
            [
                _markdown_link_line("warning records", ai_manifest.get("diagnostics", {}).get("warnings_path")),
                _markdown_link_line(
                    "unresolved links", ai_manifest.get("diagnostics", {}).get("unresolved_links_path")
                ),
            ]
        )
    warning_codes = ai_manifest.get("diagnostics", {}).get("warning_codes", {})
    if isinstance(warning_codes, dict) and warning_codes:
        lines.extend(["", "Warning codes:", ""])
        for code, count in sorted(warning_codes.items()):
            lines.append(f"- `{code}`: {count}")
    return "\n".join(lines).rstrip() + "\n"


def _agent_instruction_6(*, simple_mode: bool, bundle_path: object) -> str:
    if bundle_path:
        return "6. Prefer individual page files for navigation and `bundle.md` for linear reading or search; bundle links are rebased to `PACKAGE_ROOT`."
    if simple_mode:
        return "6. Use individual page files for navigation and reading."
    return "6. Prefer individual page files for navigation; no `bundle.md` was written for this package."


def _surfaces_line(label: str, surfaces: object, *, suffix: str = ".") -> str:
    items = surfaces if isinstance(surfaces, list) else []
    rendered = ", ".join(f"`{item}`" for item in items if isinstance(item, str)) or "none"
    return f"- {label}: {rendered}{suffix}"


def _simple_control_files_line(simple_mode: bool) -> str:
    if simple_mode:
        return "- Control and provenance files are written for tooling but are intentionally not listed as reading targets in simple mode."
    return ""


def _append_page_hierarchy(lines: list[str], ai_manifest: dict[str, Any]) -> None:
    pages = [page for page in ai_manifest.get("pages", []) if isinstance(page, dict)]
    by_name = {page.get("name"): page for page in pages if isinstance(page.get("name"), str)}
    root_name = ai_manifest.get("root")
    roots = [by_name[root_name]] if isinstance(root_name, str) and root_name in by_name else []
    if not roots:
        roots = [page for page in pages if not page.get("parent")]
    if not roots and pages:
        roots = [pages[0]]

    visited: set[str] = set()

    def append_page(page: dict[str, Any], depth: int) -> None:
        name = page.get("name")
        if not isinstance(name, str):
            return
        indent = "  " * depth
        lines.append(f"{indent}- {_page_hierarchy_line(page)}")
        visited.add(name)
        for child_name in page.get("children", []):
            child = by_name.get(child_name)
            if child is None:
                lines.append(f"{indent}  - `{child_name}`: missing from page index")
                continue
            if child_name in visited:
                lines.append(f"{indent}  - `{child_name}`: already listed above")
                continue
            append_page(child, depth + 1)

    for root in roots:
        append_page(root, 0)
    unlisted = [page for page in pages if page.get("name") not in visited]
    if unlisted:
        lines.extend(["", "Unlinked pages:", ""])
        for page in unlisted:
            lines.append(f"- {_page_hierarchy_line(page)}")


def _page_hierarchy_line(page: dict[str, Any]) -> str:
    markdown = page.get("markdown", "")
    comments = ""
    if isinstance(page.get("comments"), str):
        comments = (
            f", comments {page.get('comments_count', 0)} "
            f"([comments.md]({markdown_link_target(page['comments'])}))"
        )
    return (
        f"`{page.get('name')}`: [{page.get('title')}]({markdown_link_target(markdown)}) "
        f"- path `{markdown}`, depth {page.get('depth')}, assets {len(page.get('assets', []))}, warnings {page.get('warnings')}{comments}"
    )


def write_bundle(result: ExtractionResult, *, root_title: str, options: PullOptions) -> None:
    if not result.bundle_path:
        return
    bundle_path = as_posix(result.bundle_path.relative_to(result.output_dir))
    lines = [
        "# Pulled Confluence Bundle",
        "",
        f"Source root: {root_title}",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Pages: {len(result.pages)}",
        f"Assets: {len(result.assets)}",
        f"Warnings: {len(result.warnings)}",
        "Manifest: ./manifest.yaml",
        "",
        "---",
        "",
    ]
    for artifact in result.pages:
        source_url = "<redacted-url>" if options.redact_source_urls else artifact.page.url or ""
        lines.extend(
            [
                f'<!-- pull:page-start id="{artifact.page.page_id}" path="{artifact.index_md}" -->',
                "",
                f"# {artifact.page.title}",
                "",
                f"Source: {source_url}",
                f"Confluence version: {artifact.page.version or 'unknown'}",
                "",
                _rebase_bundle_links(artifact.markdown.strip(), from_file=artifact.index_md, bundle_file=bundle_path),
                "",
                f'<!-- pull:page-end id="{artifact.page.page_id}" -->',
                "",
                "---",
                "",
            ]
        )
    result.bundle_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_diagnostics(output: Path, warnings: list[WarningRecord], unresolved_links: list[dict[str, Any]]) -> None:
    diagnostics = output / "diagnostics"
    diagnostics.mkdir(exist_ok=True)
    warnings_path = diagnostics / "warnings.jsonl"
    warnings_path.write_text(
        "".join(json.dumps(warning.to_dict(), sort_keys=True) + "\n" for warning in warnings),
        encoding="utf-8",
    )
    lines = ["# Unresolved Links", ""]
    if not unresolved_links:
        lines.append("No unresolved local links were recorded.")
    else:
        for link in unresolved_links:
            lines.append(f"- Page `{link.get('source_page_id')}`: `{link.get('original')}` ({link.get('warning')})")
    (diagnostics / "unresolved-links.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def page_markdown_header(artifact: PageArtifact, *, options: PullOptions) -> str:
    source_url = "<redacted-url>" if options.redact_source_urls else artifact.page.url or ""
    lines = [
        "---",
        f'pull_page_id: "{artifact.page.page_id}"',
        f'title: "{artifact.page.title}"',
        f'space: "{artifact.page.space_key or ""}"',
        f"confluence_version: {artifact.page.version or 'null'}",
        f'retrieved_at: "{datetime.now(UTC).isoformat()}"',
        f'source_url: "{source_url}"',
        f"local_assets: {len(artifact.assets)}",
        f"warnings: {len(artifact.warnings)}",
        "---",
        "",
        f"# {artifact.page.title}",
        "",
        f"> Source: Confluence page `{artifact.page.page_id}`, version {artifact.page.version or 'unknown'}.",
        "",
    ]
    if artifact.comments_path and artifact.comments:
        comments_link = relative_path(artifact.index_md, artifact.comments_path)
        lines.extend(
            [
                f"> Comments sidecar: [{len(artifact.comments)} comment(s)]({markdown_link_target(comments_link)}).",
                "",
            ]
        )
    return "\n".join(lines)


def _tool_version() -> str:
    from . import __version__

    return __version__


def _page_names(pages: list[PageArtifact]) -> dict[str, str]:
    names: dict[str, str] = {}
    used: set[str] = set()
    for artifact in pages:
        base = slugify(artifact.page.title, fallback=artifact.page.page_id)
        name = base
        counter = 2
        while name in used:
            name = f"{base}-{counter}"
            counter += 1
        used.add(name)
        names[artifact.page.page_id] = name
    return names


def _ai_manifest_paths(
    result: ExtractionResult, *, page_names: dict[str, str] | None = None
) -> dict[str, str]:
    page_names = page_names or _page_names(result.pages)
    root_name = page_names[result.pages[0].page.page_id] if result.pages else "pulled-confluence"
    reserved = {"manifest", "bundle", "chunks"}
    file_stem = f"{root_name}-ai" if root_name in reserved else root_name
    return {"entry": f"{file_stem}.md", "manifest": f"{file_stem}.yaml"}


def _ai_asset(asset: AssetRecord) -> dict[str, Any]:
    return {
        "name": slugify(Path(asset.filename).stem, fallback=asset.asset_id),
        "filename": asset.filename,
        "path": asset.local_path,
        "media_type": asset.media_type,
        "sidecars": asset.sidecars,
    }


def _warning_counts(warnings: list[WarningRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for warning in warnings:
        counts[warning.code] = counts.get(warning.code, 0) + 1
    return counts


def _comments_markdown(artifact: PageArtifact, *, options: PullOptions) -> str:
    lines = [
        f"# Comments for {artifact.page.title}",
        "",
        f"Page ID: `{artifact.page.page_id}`",
        f"Comment count: {len(artifact.comments)}",
        "",
    ]
    for index, comment in enumerate(artifact.comments, start=1):
        lines.extend(_comment_markdown_block(index, comment, options=options))
    return "\n".join(lines).rstrip() + "\n"


def _comment_markdown_block(index: int, comment: CommentRecord, *, options: PullOptions) -> list[str]:
    lines = [
        f"## Comment {index}: `{_comment_field(comment.comment_id, options=options)}`",
        "",
    ]
    metadata = [
        ("location", comment.location),
        ("status", comment.status),
        ("resolution", comment.resolution),
        ("version", comment.version),
        ("author", comment.author),
        ("created", comment.created_at),
        ("updated", comment.updated_at),
        ("parent", comment.parent_id),
    ]
    for label, value in metadata:
        if value is not None and value != "":
            lines.append(f"- {label}: {_comment_field(value, options=options)}")
    body = _comment_body_markdown(comment, options=options)
    lines.extend(["", body or "_No comment body returned._", ""])
    return lines


def _comment_body_markdown(comment: CommentRecord, *, options: PullOptions) -> str:
    sanitized_html, _warnings = normalize_html(
        comment.body_html,
        source_page_id=comment.page_id,
        redact_source_urls=options.redact_source_urls,
    )
    return rendered_html_to_markdown(sanitized_html).strip()


def _comment_field(value: object, *, options: PullOptions) -> str:
    text = str(_sanitize_snapshot(value, redact_source_urls=options.redact_source_urls) or "")
    return text.replace("\n", " ").strip()


def _comment_locations(comments: list[CommentRecord], *, options: PullOptions) -> list[str]:
    return sorted(
        {
            _comment_field(comment.location, options=options)
            for comment in comments
            if comment.location
        }
    )


def _markdown_link_line(label: str, path: object) -> str:
    if not isinstance(path, str) or not path:
        return f"- {label}: unavailable"
    return f"- {label}: [{path}]({markdown_link_target(path)})"


def _artifact_guidance(result: ExtractionResult, *, options: PullOptions) -> dict[str, Any]:
    navigation_surfaces = ["page index.md files"]
    if result.bundle_path:
        navigation_surfaces.append("bundle.md")
    raw_reference_surfaces = ["page.json"]
    if any(artifact.source_path for artifact in result.pages):
        raw_reference_surfaces.insert(0, "source.storage.xml")
    rendered_reference_surfaces = ["index.html"] if any(artifact.index_html for artifact in result.pages) else []
    if result.bundle_path:
        navigation_rule = "Use page Markdown files and bundle.md for navigation."
    else:
        navigation_rule = "Use page Markdown files for navigation."
    if options.output_mode == "simple":
        rule = (
            f"{navigation_rule} Simple mode keeps control and provenance artifacts available for tooling "
            "without listing them as primary reading targets."
        )
    else:
        rule = (
            f"{navigation_rule} Treat raw reference artifacts as source evidence only; their source links may be "
            "redacted and should not be used to judge rewritten local navigation."
        )
    return {
        "rule": rule,
        "navigation_surfaces": navigation_surfaces,
        "raw_reference_surfaces": raw_reference_surfaces,
        "rendered_reference_surfaces": rendered_reference_surfaces,
    }


def _sanitize_snapshot(value: Any, *, redact_source_urls: bool = False) -> Any:
    if isinstance(value, str):
        if ("<" in value and ">" in value) or ("&lt;" in value and "&gt;" in value):
            text = unescape(value)
            normalized, _warnings = normalize_html(text, source_page_id="", redact_source_urls=redact_source_urls)
            redacted = redact_text(normalized)
            return redact_source_url_text(redacted) if redact_source_urls else redacted
        text = redact_text(value)
        if text.startswith(("http://", "https://")):
            sanitized = sanitize_url(text, redact_source_url=redact_source_urls)
            return sanitized or text
        if redact_source_urls:
            return redact_source_url_text(text)
        return text
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if _is_write_oriented_snapshot_key(key_text):
                continue
            if redact_source_urls and _is_redacted_snapshot_key(key_text):
                continue
            output[key_text] = "<redacted>" if SECRET_KEY_PATTERN.search(key_text) else _sanitize_snapshot(child, redact_source_urls=redact_source_urls)
        return output
    if isinstance(value, list):
        return [_sanitize_snapshot(child, redact_source_urls=redact_source_urls) for child in value]
    return redact_value(value)


def _is_write_oriented_snapshot_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in WRITE_ORIENTED_SNAPSHOT_KEYS


def _is_redacted_snapshot_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return normalized in REDACTED_SNAPSHOT_KEYS or normalized in REDACTED_LINK_KEYS


def _rebase_bundle_links(markdown: str, *, from_file: str, bundle_file: str) -> str:
    def replace(match: re.Match[str]) -> str:
        prefix, raw_target, suffix = match.groups()
        rebased = _rebase_bundle_link_target(raw_target, from_file=from_file, bundle_file=bundle_file)
        return f"{prefix}{rebased}{suffix}"

    return BUNDLE_LINK_RE.sub(replace, markdown)


def _rebase_bundle_link_target(raw_target: str, *, from_file: str, bundle_file: str) -> str:
    leading = raw_target[: len(raw_target) - len(raw_target.lstrip())]
    trailing = raw_target[len(raw_target.rstrip()) :]
    core = raw_target.strip()
    if not core:
        return raw_target

    angle_wrapped = core.startswith("<")
    if angle_wrapped:
        end = core.find(">")
        if end == -1:
            return raw_target
        target = core[1:end]
        trailer = core[end + 1 :]
    else:
        target, trailer = _split_markdown_target(core)

    if _is_external_or_page_local(target):
        return raw_target

    path_part, marker, fragment = target.partition("#")
    if not path_part:
        return raw_target
    rebased_path = relative_path(bundle_file, Path(from_file).parent / path_part)
    if rebased_path.startswith("../"):
        return raw_target
    rebased_target = f"{rebased_path}{marker}{fragment}"
    if angle_wrapped:
        rebased_target = f"<{rebased_target}>{trailer}"
    else:
        rebased_target = f"{rebased_target}{trailer}"
    return f"{leading}{rebased_target}{trailing}"


def _split_markdown_target(core: str) -> tuple[str, str]:
    for marker in (' "', " '", "\t\"", "\t'"):
        if marker in core:
            path, title = core.split(marker, 1)
            return path, f"{marker}{title}"
    return core, ""


def _is_external_or_page_local(target: str) -> bool:
    return target in {"redacted-url", "<redacted-url>"} or target.startswith(("#", "/", "http://", "https://", "mailto:", "jira:"))
