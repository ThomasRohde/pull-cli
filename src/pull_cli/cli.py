from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .clients import build_client
from .config import resolve_config
from .envelope import emit_json, make_envelope, wants_json
from .errors import EXIT_INTERNAL, EXIT_SUCCESS, EXIT_VALIDATION, PullError
from .extractor import extract
from .guide import guide_payload
from .models import PullOptions, TargetSelection
from .resolver import resolve_target
from .security import sanitize_url
from .validator import validate_package

DEFAULT_OUTPUT_DIRNAME = "pulled-confluence"


class PullArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, json_mode: bool = False, command: str = "pull", **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.json_mode = json_mode
        self.command = command

    def error(self, message: str) -> None:
        if self.json_mode:
            error = PullError(
                code="ERR_VALIDATION_INVALID_ARGUMENT",
                message=message,
                exit_code=EXIT_VALIDATION,
                suggested_action="Run pull --help or pull guide --json for valid arguments.",
                details={"argument_error": message},
            )
            emit_json(make_envelope(ok=False, command=self.command, errors=[error]))
            raise SystemExit(EXIT_VALIDATION)
        super().error(message)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    try:
        if args and args[0] == "validate":
            return _main_validate(args[1:])
        if args and args[0] == "guide":
            return _main_guide(args[1:])
        if args and args[0] == "version":
            print(f"pull-cli {__version__}")
            return EXIT_SUCCESS
        return _main_pull(args)
    except PullError as exc:
        if _argv_wants_json(args):
            emit_json(make_envelope(ok=False, command="pull", errors=[exc]))
        else:
            print(f"{exc.code}: {exc.message}", file=sys.stderr)
            if exc.suggested_action:
                print(f"Suggested action: {exc.suggested_action}", file=sys.stderr)
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
        if _argv_wants_json(args):
            emit_json(make_envelope(ok=False, command="pull", errors=[error]))
        else:
            print(f"{error.code}: {error.message}", file=sys.stderr)
        return EXIT_INTERNAL


def _main_pull(argv: Sequence[str]) -> int:
    parser = _pull_parser(json_mode=_argv_wants_json(argv))
    if not argv and not _argv_wants_json(argv):
        parser.print_help()
        return EXIT_SUCCESS
    ns = parser.parse_args(argv)
    json_mode = wants_json(ns.json)
    started = time.perf_counter()
    config = resolve_config(
        base_url=ns.base_url,
        user=ns.user,
        token=ns.token,
        auth_mode=ns.auth,
        cloud_id=ns.cloud_id,
        ssl_verify=ns.ssl_verify,
        config_path=ns.config,
    )
    _suppress_insecure_request_warnings(config.ssl_verify)
    selection = TargetSelection(
        positional=ns.page_ref,
        page_id=ns.page_id,
        url=ns.url,
        space=ns.space,
        title=ns.title,
    )
    options = PullOptions(
        output=_output_path(ns.output),
        force=ns.force,
        clean=ns.clean,
        tree=ns.tree,
        depth=ns.depth,
        max_pages=ns.max_pages,
        layout=ns.layout,
        output_mode=ns.output_mode,
        write_bundle=ns.bundle,
        write_html=ns.html,
        write_source=ns.source,
        write_chunks=ns.chunks,
        asset_policy=ns.assets,
        no_assets=ns.no_assets,
        extract_attachments=ns.extract_attachments,
        comments=ns.comments,
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
        verbose=ns.verbose,
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
            "url": sanitize_url(
                result.pages[0].page.url if result.pages else root.url,
                redact_source_url=options.redact_source_urls,
            ),
        },
        result={
            "output_dir": str(result.output_dir),
            "manifest": str(result.manifest_path),
            "ai_entry": str(result.ai_entry_path) if result.ai_entry_path else None,
            "bundle": str(result.bundle_path) if result.bundle_path else None,
            "output_mode": options.output_mode,
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
        if result.ai_entry_path:
            print(f"AI entry: {result.ai_entry_path.resolve()}")
            print("Give that Markdown file to the agent as the starting point.")
    return EXIT_SUCCESS


def _main_validate(argv: Sequence[str]) -> int:
    parser = PullArgumentParser(
        prog="pull validate",
        description="Validate a pulled Confluence package.",
        json_mode=_argv_wants_json(argv),
        command="validate",
    )
    parser.add_argument("path", nargs="?", metavar="MANIFEST_OR_OUTPUT_DIR")
    parser.add_argument("--json", action="store_true", help="Emit a structured JSON envelope.")
    ns = parser.parse_args(argv)
    json_mode = wants_json(ns.json)
    if not ns.path:
        error = PullError(
            code="ERR_VALIDATION_REQUIRED",
            message="Missing required MANIFEST_OR_OUTPUT_DIR argument.",
            exit_code=EXIT_VALIDATION,
            suggested_action="Pass an output directory or manifest.yaml path.",
        )
        payload = make_envelope(ok=False, command="validate", target={}, errors=[error])
        if json_mode:
            emit_json(payload)
        else:
            print(f"{error.code}: {error.message}", file=sys.stderr)
            print("Usage: pull validate MANIFEST_OR_OUTPUT_DIR [--json]", file=sys.stderr)
        return EXIT_VALIDATION
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
            "validation_warnings": len(validation.warnings),
            "package_warnings": validation.metrics.get("package_warnings", 0),
        },
        warnings=validation.warnings,
        errors=validation.errors,
        metrics=validation.metrics,
    )
    if json_mode:
        emit_json(payload)
    elif validation.ok:
        print(
            f"Validation passed for {validation.manifest_path} "
            f"({validation.metrics.get('pages', 0)} page(s), {validation.metrics.get('assets', 0)} asset(s))."
        )
    else:
        for error in validation.errors:
            print(f"{error['code']}: {error['message']}", file=sys.stderr)
            details = error.get("details", {})
            if details.get("file"):
                print(f"  file: {details['file']}", file=sys.stderr)
            if details.get("link"):
                print(f"  link: {details['link']}", file=sys.stderr)
            if details.get("resolution_base"):
                print(f"  resolution_base: {details['resolution_base']}", file=sys.stderr)
            if details.get("candidate_path"):
                print(f"  candidate_path: {details['candidate_path']}", file=sys.stderr)
        print("Rerun with --json for the structured validation envelope.", file=sys.stderr)
    return 0 if validation.ok else 10


def _main_guide(argv: Sequence[str]) -> int:
    parser = PullArgumentParser(
        prog="pull guide",
        description="Emit agent-readable CLI and output schema.",
        json_mode=_argv_wants_json(argv),
        command="guide",
    )
    parser.add_argument("--json", action="store_true", help="Emit only the guide payload as JSON.")
    ns = parser.parse_args(argv)
    payload = guide_payload()
    if wants_json(ns.json):
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print("pull-cli guide")
        print("Commands: pull PAGE_REF [OPTIONS], pull validate PATH, pull guide --json")
        print("Use --json or LLM=true for stable agent envelopes on pull/validate.")
        print("Recommended agent flow: pull guide --json, pull ... --json, pull validate <output-dir> --json.")
        print("Most common AI use: pull PAGE_URL --tree --comments --clean -o ./pulled-confluence")
        print("Then give the generated <sanitized-root-page-title>.md file to the agent.")
        print("Default output mode is simple: root AI Markdown, page Markdown, assets, and validation control files.")
        print("Default output directory is ./pulled-confluence under your current working directory.")
        print("For Data Center PATs, use --auth bearer or pass --token without --user.")
        print("Use --output-mode full for bundle.md, page HTML snapshots, and source.storage.xml; use --clean to remove stale files when switching modes.")
        print("Start analysis from <sanitized-root-page-title>.md in the output package.")
        print("Manifest and AI manifest paths are package-root-relative; page links are page-file-relative.")
        print("Run pull guide --json for the full machine-readable schema, error codes, and warning codes.")
    return EXIT_SUCCESS


def _pull_parser(*, json_mode: bool = False) -> argparse.ArgumentParser:
    parser = PullArgumentParser(
        prog="pull",
        description="Pull Confluence pages into local AI-consumable evidence packages.",
        epilog=(
            "Commands:\n"
            "  pull PAGE_REF [OPTIONS]\n"
            "  pull validate MANIFEST_OR_OUTPUT_DIR [--json]\n"
            "  pull guide [--json]\n"
            "  pull version\n\n"
            "Most common AI use:\n"
            "  pull PAGE_URL --tree --comments --clean -o ./pulled-confluence\n"
            "  Give ./pulled-confluence/<sanitized-root-page-title>.md to the agent.\n\n"
            "Defaults:\n"
            "  When -o is omitted, output goes to ./pulled-confluence under the current working directory.\n"
            "  Default output mode is simple; use --output-mode full for bundle/html/source artifacts.\n\n"
            "Auth:\n"
            "  Use --auth bearer for Confluence Data Center PATs; explicit --token without --user\n"
            "  will not be paired with PULL_USER or CONFPUB_USER.\n\n"
            "Agent flow:\n"
            "  pull guide --json\n"
            "  pull ... --json\n"
            "  pull validate <output-dir> --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        json_mode=json_mode,
        command="pull",
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

    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory. Default: ./pulled-confluence under the current working directory.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite files in an existing output directory.")
    parser.add_argument("--clean", action="store_true", help="Delete stale files in the output directory first.")
    parser.add_argument("--layout", choices=["auto", "nested", "flat"], default="auto")
    parser.add_argument(
        "--output-mode",
        choices=["simple", "full"],
        default="simple",
        help="Output artifact profile. simple writes quiet agent-facing Markdown by default; full writes all evidence artifacts.",
    )
    parser.add_argument("--bundle", dest="bundle", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--html", dest="html", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--source", dest="source", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--chunks", action="store_true")

    parser.add_argument("--assets", choices=["visible", "page", "all"], default="visible")
    parser.add_argument("--no-assets", action="store_true")
    parser.add_argument("--extract-attachments", action="store_true")
    parser.add_argument("--comments", action="store_true", help="Fetch page and inline comments into page-local comments.md sidecars.")
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
    parser.add_argument(
        "--auth",
        choices=["auto", "bearer", "basic"],
        default="auto",
        help="Authentication mode. auto preserves username+token Basic auth unless --token is passed without --user; bearer forces PAT token auth.",
    )
    parser.add_argument("--cloud-id", help="Optional Confluence Cloud ID.")
    parser.add_argument("--ssl-verify", help="true, false, or path to an enterprise CA bundle.")
    parser.add_argument("--config", help="Optional config YAML path.")

    parser.add_argument("--json", action="store_true", help="Emit a structured JSON object on stdout.")
    parser.add_argument("--version", action="version", version=f"pull-cli {__version__}")
    parser.add_argument("--quiet", action="store_true", help="Accepted but currently no-op; reserved for progress suppression.")
    parser.add_argument("--verbose", action="store_true", help="Emit phase progress and timings to stderr.")
    parser.add_argument("--redact-source-urls", action="store_true")
    parser.add_argument("--redact-manifest", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Treat strict extraction failures as errors.")
    return parser


def _argv_wants_json(argv: Sequence[str]) -> bool:
    return "--json" in argv or wants_json(False)


def _output_path(value: str | None) -> Path:
    if value:
        return Path(value)
    return Path.cwd() / DEFAULT_OUTPUT_DIRNAME


def _suppress_insecure_request_warnings(ssl_verify: bool | str) -> None:
    if ssl_verify is not False:
        return
    try:
        import urllib3
    except Exception:  # noqa: BLE001
        return
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
