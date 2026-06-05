from __future__ import annotations

import json
from pathlib import Path

import yaml

from pull_cli.errors import PullError
from pull_cli.extractor import extract
from pull_cli.models import AttachmentRecord, PageSummary, PullOptions
from pull_cli.validator import validate_package

from .conftest import FakeConfluenceClient, make_page, read


def test_single_page_package_with_image_attachment_macro_and_redaction(tmp_path: Path) -> None:
    output = tmp_path / "pulled"
    page = make_page(
        "100",
        "Architecture Overview",
        body_view="""
        <h1>Architecture Overview</h1>
        <p>Visible rendered content.</p>
        <p><img src="/download/attachments/999/system.png" alt="System"></p>
        <p><a href="/download/attachments/100/requirements.pdf">Requirements</a></p>
        <p><a href="#Missing Section">Broken anchor</a></p>
        <script>window.secret='bad'</script>
        """,
        storage="""
        <root xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource/identifier">
          <ac:structured-macro ac:name="attachments" />
          <ac:structured-macro ac:name="expand">
            <ac:parameter ac:name="title">Details</ac:parameter>
            <ac:rich-text-body><p>Hidden but human-openable detail.</p></ac:rich-text-body>
          </ac:structured-macro>
          <ac:structured-macro ac:name="unknown-vendor">
            <ac:parameter ac:name="mode">x</ac:parameter>
          </ac:structured-macro>
        </root>
        """,
    )
    attachment = AttachmentRecord(
        attachment_id="att-1",
        page_id="100",
        filename="requirements.pdf",
        media_type="application/pdf",
        download_url="/download/attachments/100/requirements.pdf?token=secret",
    )
    client = FakeConfluenceClient(
        pages={"100": page},
        attachments={"100": [attachment]},
        downloads={
            "/download/attachments/999/system.png": b"png-bytes",
            "/download/attachments/100/requirements.pdf?token=secret": b"pdf-bytes",
        },
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="100", title="Architecture Overview"),
        options=PullOptions(output=output, force=True),
    )

    assert (output / "manifest.yaml").exists()
    assert (output / "architecture-overview.yaml").exists()
    assert (output / "architecture-overview.md").exists()
    assert not (output / "ai-manifest.yaml").exists()
    assert not (output / "AI_MANIFEST.md").exists()
    assert (output / "bundle.md").exists()
    markdown = read(output / result.pages[0].index_md)
    assert "Visible rendered content." in markdown
    assert "assets/system.png" in markdown
    assert "assets/requirements.pdf" in markdown
    assert "Hidden but human-openable detail." in markdown
    assert "Unsupported Confluence macro" in markdown
    assert "script" not in markdown
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["paths"]["ai_manifest"] == "architecture-overview.yaml"
    assert manifest["paths"]["ai_entry"] == "architecture-overview.md"
    ai_manifest = yaml.safe_load((output / manifest["paths"]["ai_manifest"]).read_text(encoding="utf-8"))
    assert manifest["assets"][0]["sha256"]
    assert "secret" not in json.dumps(manifest)
    assert ai_manifest["root"] == "architecture-overview"
    assert ai_manifest["path_base"]["kind"] == "package_root"
    assert ai_manifest["path_base"]["root"] == "."
    assert "current working directory" in ai_manifest["path_base"]["rule"]
    assert ai_manifest["entrypoints"]["ai_entry"] == "architecture-overview.md"
    assert ai_manifest["entrypoints"]["ai_manifest"] == "architecture-overview.yaml"
    assert ai_manifest["pages"][0]["name"] == "architecture-overview"
    assert ai_manifest["pages"][0]["parent"] is None
    assert ai_manifest["pages"][0]["markdown"] == result.pages[0].index_md
    assert ai_manifest["pages"][0]["assets"][0]["path"].endswith("assets/system.png")
    assert "source" not in json.dumps(ai_manifest).lower()
    ai_entry = read(output / manifest["paths"]["ai_entry"])
    assert "[architecture-overview.yaml](architecture-overview.yaml)" in ai_entry
    assert "[manifest.yaml](manifest.yaml)" in ai_entry
    assert "[Architecture Overview]" in ai_entry
    assert "Set `PACKAGE_ROOT` to the directory containing this file" in ai_entry
    assert "even if your shell current directory is somewhere else" in ai_entry
    warning_codes = {warning["code"] for warning in manifest["warnings"]}
    assert {"W_SANITIZED_HTML", "W_LINK_ANCHOR_UNRESOLVED", "W_MACRO_UNKNOWN"} <= warning_codes
    validation = validate_package(output)
    assert validation.ok, validation.errors


def test_tree_internal_link_rewriting_and_nested_paths(tmp_path: Path) -> None:
    output = tmp_path / "tree"
    root = make_page(
        "200",
        "Root Page",
        body_view='<h1>Root Page</h1><p><a href="/wiki/spaces/EA/pages/201/Child">Child link</a></p>',
    )
    child = make_page(
        "201",
        "Child",
        body_view='<h1>Child</h1><p><a href="/wiki/spaces/EA/pages/202/Grandchild">Grandchild</a></p>',
    )
    grandchild = make_page("202", "Grandchild", body_view="<h1>Grandchild</h1><p>Leaf.</p>")
    client = FakeConfluenceClient(
        pages={"200": root, "201": child, "202": grandchild},
        children={
            "200": [PageSummary(page_id="201", title="Child")],
            "201": [PageSummary(page_id="202", title="Grandchild")],
        },
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="200", title="Root Page"),
        options=PullOptions(output=output, tree=True, force=True),
    )
    assert len(result.pages) == 3
    assert result.pages[1].index_md.startswith("pages/0001-root-page/0002-child/")
    root_markdown = read(output / result.pages[0].index_md)
    assert "0002-child/index.md" in root_markdown
    bundle = read(output / "bundle.md")
    assert "(pages/0001-root-page/0002-child/index.md)" in bundle
    assert "(pages/0001-root-page/0002-child/0003-grandchild/index.md)" in bundle
    assert "(0002-child/index.md)" not in bundle
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["path_base"]["kind"] == "package_root"
    ai_manifest = yaml.safe_load((output / manifest["paths"]["ai_manifest"]).read_text(encoding="utf-8"))
    assert manifest["paths"]["ai_manifest"] == "root-page.yaml"
    assert manifest["paths"]["ai_entry"] == "root-page.md"
    assert [page["name"] for page in ai_manifest["pages"]] == ["root-page", "child", "grandchild"]
    assert [page["parent"] for page in ai_manifest["pages"]] == [None, "root-page", "child"]
    assert ai_manifest["pages"][0]["children"] == ["child"]
    assert ai_manifest["pages"][1]["children"] == ["grandchild"]
    ai_entry = read(output / manifest["paths"]["ai_entry"])
    assert "- `root-page`: [Root Page]" in ai_entry
    assert "  - `child`: [Child]" in ai_entry
    assert "    - `grandchild`: [Grandchild]" in ai_entry
    assert validate_package(output).ok


def test_validate_rejects_unknown_ai_manifest_child_reference(tmp_path: Path) -> None:
    output = tmp_path / "tree"
    root = make_page("250", "Root", body_view="<h1>Root</h1>")
    child = make_page("251", "Child", body_view="<h1>Child</h1>")
    client = FakeConfluenceClient(
        pages={"250": root, "251": child},
        children={"250": [PageSummary(page_id="251", title="Child")]},
    )
    extract(
        client=client,
        root=PageSummary(page_id="250", title="Root"),
        options=PullOptions(output=output, tree=True, force=True),
    )
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    ai_manifest_path = output / manifest["paths"]["ai_manifest"]
    ai_manifest = yaml.safe_load(ai_manifest_path.read_text(encoding="utf-8"))
    ai_manifest["pages"][0]["children"] = ["missing-child"]
    ai_manifest_path.write_text(yaml.safe_dump(ai_manifest, sort_keys=False), encoding="utf-8")

    validation = validate_package(output)
    assert not validation.ok
    assert validation.errors[-1]["details"] == {"page": "root", "child": "missing-child"}


def test_validate_rejects_unknown_ai_manifest_parent_reference(tmp_path: Path) -> None:
    output = tmp_path / "parent"
    root = make_page("252", "Root", body_view="<h1>Root</h1>")
    child = make_page("253", "Child", body_view="<h1>Child</h1>")
    client = FakeConfluenceClient(
        pages={"252": root, "253": child},
        children={"252": [PageSummary(page_id="253", title="Child")]},
    )
    extract(
        client=client,
        root=PageSummary(page_id="252", title="Root"),
        options=PullOptions(output=output, tree=True, force=True),
    )
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    ai_manifest_path = output / manifest["paths"]["ai_manifest"]
    ai_manifest = yaml.safe_load(ai_manifest_path.read_text(encoding="utf-8"))
    ai_manifest["pages"][1]["parent"] = "missing-parent"
    ai_manifest_path.write_text(yaml.safe_dump(ai_manifest, sort_keys=False), encoding="utf-8")

    validation = validate_package(output)
    assert not validation.ok
    assert validation.errors[-1]["details"] == {"page": "child", "parent": "missing-parent"}


def test_validate_rejects_ai_manifest_without_path_base(tmp_path: Path) -> None:
    output = tmp_path / "path-base"
    page = make_page("255", "Root", body_view="<h1>Root</h1>")
    client = FakeConfluenceClient(pages={"255": page})
    extract(
        client=client,
        root=PageSummary(page_id="255", title="Root"),
        options=PullOptions(output=output, force=True),
    )
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    ai_manifest_path = output / manifest["paths"]["ai_manifest"]
    ai_manifest = yaml.safe_load(ai_manifest_path.read_text(encoding="utf-8"))
    del ai_manifest["path_base"]
    ai_manifest_path.write_text(yaml.safe_dump(ai_manifest, sort_keys=False), encoding="utf-8")

    validation = validate_package(output)
    assert not validation.ok
    assert any("path_base" in error["message"] for error in validation.errors)


def test_ai_manifest_title_filename_avoids_reserved_root_files(tmp_path: Path) -> None:
    output = tmp_path / "reserved"
    page = make_page("260", "Manifest", body_view="<h1>Manifest</h1>")
    client = FakeConfluenceClient(pages={"260": page})
    extract(
        client=client,
        root=PageSummary(page_id="260", title="Manifest"),
        options=PullOptions(output=output, force=True),
    )

    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["paths"]["ai_manifest"] == "manifest-ai.yaml"
    assert manifest["paths"]["ai_entry"] == "manifest-ai.md"
    assert (output / "manifest-ai.yaml").exists()
    assert (output / "manifest-ai.md").exists()
    assert validate_package(output).ok


def test_depth_zero_equals_single_page(tmp_path: Path) -> None:
    page = make_page("300", "Root", body_view="<h1>Root</h1>")
    child = make_page("301", "Child", body_view="<h1>Child</h1>")
    client = FakeConfluenceClient(
        pages={"300": page, "301": child},
        children={"300": [PageSummary(page_id="301", title="Child")]},
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="300", title="Root"),
        options=PullOptions(output=tmp_path / "out", tree=True, depth=0, force=True),
    )
    assert [artifact.page.page_id for artifact in result.pages] == ["300"]


def test_tabs_include_diagram_status_and_code_macro_recovery(tmp_path: Path) -> None:
    page = make_page(
        "400",
        "Macro Page",
        body_view='<h1>Macro Page</h1><p><img src="/download/attachments/400/diagram.png"></p>',
        storage="""
        <root xmlns:ac="http://atlassian.com/content">
          <ac:structured-macro ac:name="tabs">
            <ac:rich-text-body>
              <ac:structured-macro ac:name="tab"><ac:parameter ac:name="title">One</ac:parameter><ac:rich-text-body><p>First tab</p></ac:rich-text-body></ac:structured-macro>
              <ac:structured-macro ac:name="tab"><ac:parameter ac:name="title">Two</ac:parameter><ac:rich-text-body><p>Second tab</p></ac:rich-text-body></ac:structured-macro>
            </ac:rich-text-body>
          </ac:structured-macro>
          <ac:structured-macro ac:name="status"><ac:parameter ac:name="title">Green</ac:parameter><ac:parameter ac:name="colour">Green</ac:parameter></ac:structured-macro>
          <ac:structured-macro ac:name="code"><ac:parameter ac:name="language">python</ac:parameter><ac:plain-text-body>print("hello")</ac:plain-text-body></ac:structured-macro>
          <ac:structured-macro ac:name="excerpt-include"><ac:parameter ac:name="page">Other</ac:parameter></ac:structured-macro>
          <ac:structured-macro ac:name="gliffy"><ac:parameter ac:name="name">System</ac:parameter></ac:structured-macro>
          <ac:structured-macro ac:name="html"><ac:plain-text-body><![CDATA[<b>Safe</b><script>bad()</script>]]></ac:plain-text-body></ac:structured-macro>
        </root>
        """,
    )
    client = FakeConfluenceClient(
        pages={"400": page},
        downloads={"/download/attachments/400/diagram.png": b"diagram"},
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="400", title="Macro Page"),
        options=PullOptions(output=tmp_path / "macros", force=True, diagram_sources=True),
    )
    markdown = read(result.output_dir / result.pages[0].index_md)
    assert "### Tab: One" in markdown
    assert "[STATUS: Green / Green]" in markdown
    assert "```python" in markdown
    assert "Include/excerpt dependency not followed" in markdown
    assert "Diagram macro snapshot: System" in markdown
    assert "Safe" in markdown
    warning_codes = {warning.code for warning in result.warnings}
    assert "W_MACRO_PARTIAL" in warning_codes
    assert "W_ASSET_DIAGRAM_SOURCE_NOT_FOUND" in warning_codes
    assert len(result.macros) >= 6


def test_manifest_validation_failure(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.yaml").write_text("schema_version: '1.0'\npages: []\n", encoding="utf-8")
    validation = validate_package(bad)
    assert not validation.ok
    assert validation.errors


def test_validate_accepts_markdown_title_and_root_relative_web_links(tmp_path: Path) -> None:
    page = make_page(
        "450",
        "Validation Page",
        body_view='<h1>Validation Page</h1><p><a href="/wiki/people/account">Person</a></p>',
    )
    client = FakeConfluenceClient(pages={"450": page})
    result = extract(
        client=client,
        root=PageSummary(page_id="450", title="Validation Page"),
        options=PullOptions(output=tmp_path / "validation-title", force=True),
    )
    md_path = result.output_dir / result.pages[0].index_md
    with md_path.open("a", encoding="utf-8") as handle:
        handle.write('\n[Self](index.md "Download all")\n[Root relative](/wiki/images/icons/wait.gif)\n')
    assert validate_package(result.output_dir).ok


def test_chunks_sidecar_no_assets_warning_and_strict_macro(tmp_path: Path) -> None:
    page = make_page(
        "500",
        "Sidecar Page",
        body_view='<h1>Sidecar Page</h1><p>Chunk me.</p><p><a href="/download/attachments/500/readme.txt">readme</a></p>',
        storage='<root xmlns:ac="http://atlassian.com/content"><ac:structured-macro ac:name="unknown-demo" /></root>',
    )
    attachment = AttachmentRecord(
        attachment_id="txt",
        page_id="500",
        filename="readme.txt",
        media_type="text/plain",
        download_url="/download/attachments/500/readme.txt",
    )
    client = FakeConfluenceClient(
        pages={"500": page},
        attachments={"500": [attachment]},
        downloads={"/download/attachments/500/readme.txt": b"hello sidecar"},
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="500", title="Sidecar Page"),
        options=PullOptions(output=tmp_path / "sidecar", force=True, extract_attachments=True, write_chunks=True),
    )
    assert (result.output_dir / "chunks.jsonl").exists()
    manifest = yaml.safe_load((result.output_dir / "manifest.yaml").read_text(encoding="utf-8"))
    ai_manifest = yaml.safe_load((result.output_dir / manifest["paths"]["ai_manifest"]).read_text(encoding="utf-8"))
    assert ai_manifest["entrypoints"]["chunks"] == "chunks.jsonl"
    assert (result.output_dir / result.assets[0].sidecars[0]).read_text(encoding="utf-8").endswith("hello sidecar\n")
    assert ai_manifest["pages"][0]["assets"][0]["sidecars"] == result.assets[0].sidecars

    no_asset_client = FakeConfluenceClient(pages={"500": page}, attachments={"500": [attachment]})
    no_asset_result = extract(
        client=no_asset_client,
        root=PageSummary(page_id="500", title="Sidecar Page"),
        options=PullOptions(output=tmp_path / "no-assets", force=True, no_assets=True),
    )
    assert "W_ASSET_SKIPPED_BY_POLICY" in {warning.code for warning in no_asset_result.warnings}

    strict_client = FakeConfluenceClient(pages={"500": page}, attachments={"500": [attachment]})
    try:
        extract(
            client=strict_client,
            root=PageSummary(page_id="500", title="Sidecar Page"),
            options=PullOptions(output=tmp_path / "strict", force=True, unknown_macro="error"),
        )
    except PullError as exc:
        assert exc.exit_code == 40
    else:
        raise AssertionError("strict unknown macro policy should fail")
