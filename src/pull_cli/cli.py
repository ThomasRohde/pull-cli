from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .clients import build_client
from .config import resolve_config
from .envelope import emit_json, make_envelope, wants_json
from .errors import EXIT_INTERNAL, EXIT_SUCCESS, PullError
from .extractor import extract
from .guide import guide_payload
from .models import PullOptions, TargetSelection
from .resolver import resolve_target
from .validator import validate_package


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    try:
        if args and args[0] == "validate":
            return _main_validate(args[1:])
        if args and args[0] == "guide":
            return _main_guide(args[1:])
        return _main_pull(args)
    except PullError as exc:
        emit_json(make_envelope(ok=False, command="pull", errors=[exc]))
        return exc.exit_code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        error = PullError(
            code="ERR_INTERNAL_CONVERSION",
            message="An internal error occurred.",
            exit_code=EXIT_INTERNAL,
            details={"reason": str(exc)},
        )
        emit_json(make_envelope(ok=False, command="pull", errors=[error]))
        return EXIT_INTERNAL


def _main_pull(argv: Sequence[str]) -> int:
    parser = _pull_parser()
    ns = parser.parse_args(argv)
    json_mode = wants_json(ns.json)
    started = time.perf_counter()
    config = resolve_config(
        base_url=ns.base_url,
        user=ns.user,
        token=ns.token,
        cloud_id=ns.cloud_id,
        ssl_verify=ns.ssl_verify,
        config_path=ns.config,
    )
    selection = TargetSelection(
        positional=ns.page_ref,
        page_id=ns.page_id,
        url=ns.url,
        space=ns.space,
        title=ns.title,
    )
    options = PullOptions(
        output=Path(ns.output),
        force=ns.force,
        clean=ns.clean,
        tree=ns.tree,
        depth=ns.depth,
        max_pages=ns.max_pages,
        layout=ns.layout,
        write_bundle=ns.bundle,
        write_html=ns.html,
        write_source=ns.source,
        write_chunks=ns.chunks,
        asset_policy=ns.assets,
        no_assets=ns.no_assets,
        extract_attachments=ns.extract_attachments,
        diagram_sources=ns.diagram_sources,
        render_mode=ns.render_mode,
        macro_policy=ns.macro_policy,
        unknown_macro=ns.unknown_macro,
        rewrite_links=ns.rewrite_links,
        follow_includes=ns.follow_includes,
        follow_links=ns.follow_links,
        include_non_page_children=ns.include_non_page_children,
        redact_source_urls=ns.redact_source_urls,
        redact_manifest=ns.redact_manifest,
        strict=ns.strict,
    )
    client = build_client(config)
    try:
        root = resolve_target(selection, client)
        result = extract(client=client, root=root, options=options)
    finally:
        client.close()
    duration_ms = int((time.perf_counter() - started) * 1000)
    result.metrics["duration_ms"] = duration_ms
    payload = make_envelope(
        ok=True,
        command="pull",
        target={
            "page_id": result.pages[0].page.page_id if result.pages else root.page_id,
            "url": result.pages[0].page.url if result.pages else root.url,
        },
        result={
            "output_dir": str(result.output_dir),
            "manifest": str(result.manifest_path),
            "bundle": str(result.bundle_path) if result.bundle_path else None,
            "pages": len(result.pages),
            "assets": len(result.assets),
            "warnings": len(result.warnings),
        },
        warnings=result.warnings,
        metrics=result.metrics,
    )
    if json_mode:
        emit_json(payload)
    else:
        print(
            f"Pulled {len(result.pages)} page(s), {len(result.assets)} asset(s), "
            f"{len(result.warnings)} warning(s) into {result.output_dir}"
        )
    return EXIT_SUCCESS


def _main_validate(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="pull validate", description="Validate a pulled Confluence package.")
    parser.add_argument("path", metavar="MANIFEST_OR_OUTPUT_DIR")
    parser.add_argument("--json", action="store_true", help="Emit a structured JSON envelope.")
    ns = parser.parse_args(argv)
    validation = validate_package(Path(ns.path))
    payload = make_envelope(
        ok=validation.ok,
        command="validate",
        target={"path": ns.path},
        result={
            "manifest": str(validation.manifest_path),
            "output_dir": str(validation.output_dir),
            "errors": len(validation.errors),
            "warnings": len(validation.warnings),
        },
        warnings=validation.warnings,
        errors=validation.errors,
        metrics=validation.metrics,
    )
    if wants_json(ns.json):
        emit_json(payload)
    elif validation.ok:
        print(
            f"Validation passed for {validation.manifest_path} "
            f"({validation.metrics.get('pages', 0)} page(s), {validation.metrics.get('assets', 0)} asset(s))."
        )
    else:
        for error in validation.errors:
            print(f"{error['code']}: {error['message']}", file=sys.stderr)
        print(json.dumps(payload, indent=2), file=sys.stderr)
    return 0 if validation.ok else 10


def _main_guide(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="pull guide", description="Emit agent-readable CLI and output schema.")
    parser.add_argument("--json", action="store_true", help="Emit only the guide payload as JSON.")
    ns = parser.parse_args(argv)
    payload = guide_payload()
    if wants_json(ns.json):
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print("pull-cli guide")
        print("Commands: pull PAGE_REF [OPTIONS], pull validate PATH, pull guide --json")
        print("Use --json or LLM=true for stable agent envelopes on pull/validate.")
    return EXIT_SUCCESS


def _pull_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pull",
        description="Pull Confluence pages into local AI-consumable evidence packages.",
    )
    parser.add_argument("page_ref", nargs="?", metavar="PAGE_REF", help="Confluence page ID or page URL.")
    parser.add_argument("--page-id", dest="page_id", help="Confluence page/content ID.")
    parser.add_argument("--url", help="Confluence page URL.")
    parser.add_argument("--space", help="Confluence space key, used with --title.")
    parser.add_argument("--title", help="Confluence page title, used with --space.")

    parser.add_argument("--tree", action="store_true", help="Pull descendant page hierarchy.")
    parser.add_argument("--depth", type=int, help="Tree depth limit; 0 equals single page.")
    parser.add_argument("--max-pages", type=int, default=500, help="Safety cap for tree pulls.")
    parser.add_argument("--include-non-page-children", action="store_true")

    parser.add_argument("-o", "--output", default="pulled-confluence", help="Output directory.")
    parser.add_argument("--force", action="store_true", help="Overwrite files in an existing output directory.")
    parser.add_argument("--clean", action="store_true", help="Delete stale files in the output directory first.")
    parser.add_argument("--layout", choices=["auto", "nested", "flat"], default="auto")
    parser.add_argument("--bundle", dest="bundle", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--html", dest="html", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--source", dest="source", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--chunks", action="store_true")

    parser.add_argument("--assets", choices=["visible", "page", "all"], default="visible")
    parser.add_argument("--no-assets", action="store_true")
    parser.add_argument("--extract-attachments", action="store_true")
    parser.add_argument("--diagram-sources", action="store_true")

    parser.add_argument("--render-mode", choices=["hybrid", "view", "export-view", "styled-view", "storage"], default="hybrid")
    parser.add_argument("--macro-policy", choices=["expand", "placeholder", "strict"], default="expand")
    parser.add_argument("--unknown-macro", choices=["warn", "error", "ignore"], default="warn")

    parser.add_argument("--rewrite-links", dest="rewrite_links", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--follow-includes", action="store_true")
    parser.add_argument("--follow-links", choices=["same-tree", "same-space", "none"], default="none")

    parser.add_argument("--base-url", help="Confluence base URL.")
    parser.add_argument("--user", help="Confluence username/email.")
    parser.add_argument("--token", help="Confluence API token or PAT. Prefer env vars.")
    parser.add_argument("--cloud-id", help="Optional Confluence Cloud ID.")
    parser.add_argument("--ssl-verify", help="true, false, or path to an enterprise CA bundle.")
    parser.add_argument("--config", help="Optional config YAML path.")

    parser.add_argument("--json", action="store_true", help="Emit a structured JSON object on stdout.")
    parser.add_argument("--quiet", action="store_true", help="Reserved for progress suppression.")
    parser.add_argument("--verbose", action="store_true", help="Reserved for extra diagnostics.")
    parser.add_argument("--redact-source-urls", action="store_true")
    parser.add_argument("--redact-manifest", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Treat strict extraction failures as errors.")
    return parser
