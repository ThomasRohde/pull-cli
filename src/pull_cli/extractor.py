from __future__ import annotations

from pathlib import Path

from .assets import discover_asset_candidates, download_assets, skipped_asset_warnings
from .clients.base import ConfluenceClient
from .crawler import crawl_pages
from .errors import EXIT_STRICT_PARTIAL, PullError
from .html_normalizer import normalize_html
from .links import rewrite_html_links
from .macros import MacroContext, MacroRegistry
from .markdown_writer import rendered_html_to_markdown
from .models import ExtractionResult, PageArtifact, PageSummary, PullOptions
from .paths import slugify
from .writer import (
    page_markdown_header,
    prepare_output_dir,
    write_bundle,
    write_diagnostics,
    write_manifest,
    write_page_artifact,
)


def extract(
    *,
    client: ConfluenceClient,
    root: PageSummary,
    options: PullOptions,
) -> ExtractionResult:
    prepare_output_dir(options.output, force=options.force, clean=options.clean)
    summaries = crawl_pages(
        client,
        root,
        tree=options.tree,
        depth=options.depth,
        max_pages=options.max_pages,
    )
    page_paths = _page_paths(summaries, options=options)
    pages_by_id = {summary.page_id: summary for summary in summaries}
    registry = MacroRegistry()
    result = ExtractionResult(
        output_dir=options.output,
        manifest_path=options.output / "manifest.yaml",
        bundle_path=options.output / "bundle.md" if options.write_bundle else None,
        pages=[],
        assets=[],
        warnings=[],
        links=[],
        macros=[],
    )
    for summary in summaries:
        page = client.get_page(summary.page_id)
        page.order = summary.order
        page.depth = summary.depth
        page.parent_id = summary.parent_id
        page.title = page.title or summary.title
        page.url = page.url or summary.url
        page_dir = page_paths[page.page_id].removesuffix("/index.md")
        index_md = f"{page_dir}/index.md"
        index_html = f"{page_dir}/index.html" if options.write_html else None
        source_path = f"{page_dir}/source.storage.xml" if options.write_source and page.body_storage else None
        page_json = f"{page_dir}/page.json"
        rendered = _select_rendered_body(page.body_view, page.body_export_view, page.body_storage)
        normalized_html, html_warnings = normalize_html(rendered, source_page_id=page.page_id)
        attachments = client.list_attachments(page.page_id)
        candidates = discover_asset_candidates(
            normalized_html,
            page_id=page.page_id,
            attachments=attachments,
            options=options,
        )
        assets, asset_warnings = download_assets(
            candidates,
            page_id=page.page_id,
            page_assets_dir=options.output / page_dir / "assets",
            page_assets_path=f"{page_dir}/assets",
            client=client,
            extract_attachments=options.extract_attachments,
        )
        if options.no_assets:
            asset_warnings.extend(skipped_asset_warnings(normalized_html, page_id=page.page_id))
        rewritten_html, links, link_warnings = rewrite_html_links(
            normalized_html,
            page=page,
            page_index_path=index_md,
            pages_by_id=pages_by_id,
            page_paths=page_paths,
            assets=assets,
            rewrite_links=options.rewrite_links,
        )
        macro_context = MacroContext(
            page_id=page.page_id,
            attachments=attachments,
            options=options,
            child_links=_child_links(page, summaries, page_paths),
        )
        macros = registry.convert_all(page.body_storage, macro_context)
        _enforce_strict_macros(macros, options=options)
        macro_warnings = [warning for macro in macros for warning in macro.warnings]
        visible_markdown = rendered_html_to_markdown(rewritten_html)
        macro_markdown = _macro_recovery_markdown(macros)
        artifact = PageArtifact(
            page=page,
            order=page.order,
            page_dir=page_dir,
            index_md=index_md,
            index_html=index_html,
            source_path=source_path,
            page_json=page_json,
            markdown="",
            html=rewritten_html,
            assets=assets,
            links=links,
            macros=macros,
            warnings=[*html_warnings, *asset_warnings, *link_warnings, *macro_warnings],
        )
        artifact.markdown = (
            page_markdown_header(artifact, options=options)
            + visible_markdown
            + ("\n\n## Macro Recovery\n\n" + macro_markdown + "\n" if macro_markdown else "")
        )
        write_page_artifact(options.output, artifact, options=options)
        result.pages.append(artifact)
        result.assets.extend(assets)
        result.links.extend(links)
        result.macros.extend(macros)
        result.warnings.extend(artifact.warnings)

    unresolved = [
        link.__dict__
        for link in result.links
        if link.status == "unresolved" or link.warning == "W_LINK_ANCHOR_UNRESOLVED"
    ]
    write_bundle(result, root_title=result.pages[0].page.title if result.pages else root.title, options=options)
    if options.write_chunks:
        _write_chunks(result)
    write_diagnostics(options.output, result.warnings, unresolved)
    write_manifest(
        result,
        options=options,
        root_page_id=root.page_id,
        base_url=client.base_url,
        deployment_type=client.deployment_type,
    )
    result.metrics["api_calls"] = client.api_calls
    result.metrics["pages"] = len(result.pages)
    result.metrics["assets"] = len(result.assets)
    return result


def _select_rendered_body(view: str | None, export_view: str | None, storage: str | None) -> str:
    return view or export_view or storage or ""


def _macro_recovery_markdown(macros) -> str:
    blocks = [macro.markdown.strip() for macro in macros if macro.markdown and macro.status != "ignored"]
    return "\n\n".join(block for block in blocks if block)


def _enforce_strict_macros(macros, *, options: PullOptions) -> None:
    strict = options.macro_policy == "strict" or options.unknown_macro == "error"
    if not strict:
        return
    failures = [
        {
            "macro_id": macro.macro_id,
            "name": macro.name,
            "status": macro.status,
            "warnings": [warning.code for warning in macro.warnings],
        }
        for macro in macros
        if macro.status in {"placeholder", "error"} or macro.warnings
    ]
    if failures:
        raise PullError(
            code="ERR_INTERNAL_CONVERSION",
            message="Strict macro policy rejected one or more partial macro conversions.",
            exit_code=EXIT_STRICT_PARTIAL,
            suggested_action="Use --macro-policy expand or --unknown-macro warn to allow placeholders.",
            details={"macros": failures},
        )


def _page_paths(summaries: list[PageSummary], *, options: PullOptions) -> dict[str, str]:
    layout = options.layout
    if layout == "auto":
        layout = "nested" if options.tree else "flat"
    paths: dict[str, str] = {}
    by_id = {summary.page_id: summary for summary in summaries}
    for summary in summaries:
        segment = f"{summary.order:04d}-{slugify(summary.title, fallback=summary.page_id)}"
        if layout == "nested" and summary.parent_id and summary.parent_id in paths:
            parent_dir = str(Path(paths[summary.parent_id]).parent).replace("\\", "/")
            paths[summary.page_id] = f"{parent_dir}/{segment}/index.md"
        elif layout == "nested" and summary.parent_id and summary.parent_id in by_id:
            paths[summary.page_id] = f"pages/{segment}/index.md"
        else:
            paths[summary.page_id] = f"pages/{segment}/index.md"
    return paths


def _child_links(
    page: PageSummary, summaries: list[PageSummary], page_paths: dict[str, str]
) -> list[tuple[str, str]]:
    links = []
    source_index = page_paths.get(page.page_id, "")
    for summary in summaries:
        if summary.parent_id == page.page_id:
            from .paths import relative_path

            links.append((summary.title, relative_path(source_index, page_paths[summary.page_id])))
    return links


def _write_chunks(result: ExtractionResult) -> None:
    import json

    chunks_path = result.output_dir / "chunks.jsonl"
    records = []
    for artifact in result.pages:
        paragraphs = [block.strip() for block in artifact.markdown.split("\n\n") if block.strip()]
        for index, paragraph in enumerate(paragraphs, start=1):
            records.append(
                {
                    "schema_version": "1.0",
                    "chunk_id": f"{artifact.page.page_id}-{index:04d}",
                    "page_id": artifact.page.page_id,
                    "title": artifact.page.title,
                    "source_path": artifact.index_md,
                    "order": artifact.order,
                    "text": paragraph,
                }
            )
    chunks_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
