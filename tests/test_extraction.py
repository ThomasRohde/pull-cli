from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from pull_cli.errors import PullError
from pull_cli.extractor import extract
from pull_cli.models import AttachmentRecord, CommentRecord, PageSummary, PullOptions
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
    assert (output / result.pages[0].page_json).exists()
    assert (output / "diagnostics" / "warnings.jsonl").exists()
    assert (output / "diagnostics" / "unresolved-links.md").exists()
    assert not (output / "bundle.md").exists()
    assert result.bundle_path is None
    assert result.pages[0].index_html is None
    assert result.pages[0].source_path is None
    assert result.pages[0].comments_path is None
    assert client.comment_calls == []
    assert not (output / "pages" / "0001-architecture-overview" / "comments.md").exists()
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
    assert manifest["paths"]["bundle"] is None
    assert manifest["options"]["output_mode"] == "simple"
    assert manifest["options"]["write_bundle"] is False
    assert manifest["options"]["write_html"] is False
    assert manifest["options"]["write_source"] is False
    ai_manifest = yaml.safe_load((output / manifest["paths"]["ai_manifest"]).read_text(encoding="utf-8"))
    assert manifest["assets"][0]["sha256"]
    assert "secret" not in json.dumps(manifest)
    assert ai_manifest["output_mode"] == "simple"
    assert ai_manifest["root"] == "architecture-overview"
    assert ai_manifest["path_base"]["kind"] == "package_root"
    assert ai_manifest["path_base"]["root"] == "."
    assert "current working directory" in ai_manifest["path_base"]["rule"]
    assert ai_manifest["entrypoints"]["ai_entry"] == "architecture-overview.md"
    assert ai_manifest["entrypoints"]["ai_manifest"] == "architecture-overview.yaml"
    assert ai_manifest["entrypoints"]["bundle"] is None
    assert ai_manifest["diagnostics"]["warning_codes"]["W_LINK_ANCHOR_UNRESOLVED"] == 1
    assert ai_manifest["pages"][0]["name"] == "architecture-overview"
    assert ai_manifest["pages"][0]["parent"] is None
    assert ai_manifest["pages"][0]["markdown"] == result.pages[0].index_md
    assert ai_manifest["pages"][0]["assets"][0]["path"].endswith("assets/system.png")
    assert ai_manifest["artifact_guidance"]["navigation_surfaces"] == ["page index.md files"]
    assert ai_manifest["artifact_guidance"]["raw_reference_surfaces"] == ["page.json"]
    assert ai_manifest["artifact_guidance"]["rendered_reference_surfaces"] == []
    assert "https://example.atlassian.net" not in json.dumps(ai_manifest)
    ai_entry = read(output / manifest["paths"]["ai_entry"])
    assert "[architecture-overview.yaml](architecture-overview.yaml)" not in ai_entry
    assert "[manifest.yaml](manifest.yaml)" not in ai_entry
    assert "[diagnostics/warnings.jsonl](diagnostics/warnings.jsonl)" not in ai_entry
    assert "[diagnostics/unresolved-links.md](diagnostics/unresolved-links.md)" not in ai_entry
    assert "[Architecture Overview]" in ai_entry
    assert "Set `PACKAGE_ROOT` to the directory containing this file" in ai_entry
    assert "do not resolve these links against the repo root" in ai_entry
    assert "Run `pull validate <PACKAGE_ROOT>` before analysis" in ai_entry
    assert "Control and provenance files are written for tooling" in ai_entry
    assert "Raw reference surfaces" not in ai_entry
    assert "`W_LINK_ANCHOR_UNRESOLVED`: 1" in ai_entry
    warning_codes = {warning["code"] for warning in manifest["warnings"]}
    assert {"W_SANITIZED_HTML", "W_LINK_ANCHOR_UNRESOLVED", "W_MACRO_UNKNOWN"} <= warning_codes
    validation = validate_package(output)
    assert validation.ok, validation.errors
    assert validation.metrics["package_warnings"] == len(result.warnings)
    ai_entry_validation = validate_package(output / manifest["paths"]["ai_entry"])
    assert not ai_entry_validation.ok
    assert "AI Markdown entrypoint" in ai_entry_validation.errors[0]["message"]


def test_comments_option_writes_markdown_sidecar_and_agent_links(tmp_path: Path) -> None:
    output = tmp_path / "comments"
    page = make_page("120", "Commented Page", body_view="<h1>Commented Page</h1><p>Body.</p>")
    comments = [
        CommentRecord(
            comment_id="c-1",
            page_id="120",
            location="footer",
            status="current",
            version=1,
            author="Thomas Rohde",
            created_at="2026-06-05T08:00:00Z",
            updated_at="2026-06-05T08:05:00Z",
            body_html='<p>Footer comment with <a href="https://example.atlassian.net/wiki/comment?token=secret">source</a>.</p>',
        ),
        CommentRecord(
            comment_id="c-1",
            page_id="120",
            location="footer",
            body_html="<p>Duplicate should be omitted.</p>",
        ),
        CommentRecord(
            comment_id="c-2",
            page_id="120",
            location="inline",
            status="resolved",
            version=2,
            author="Inline Author",
            parent_id="c-1",
            resolution="resolved",
            body_html="<p>Inline reply body.</p>",
        ),
    ]
    client = FakeConfluenceClient(pages={"120": page}, comments={"120": comments})

    result = extract(
        client=client,
        root=PageSummary(page_id="120", title="Commented Page"),
        options=PullOptions(
            output=output,
            force=True,
            comments=True,
            redact_source_urls=True,
            redact_manifest=True,
        ),
    )

    assert client.comment_calls == ["120"]
    assert result.pages[0].comments_path == "pages/0001-commented-page/comments.md"
    comments_path = output / result.pages[0].comments_path
    comments_markdown = read(comments_path)
    assert "Footer comment with [source](<redacted-url>)." in comments_markdown
    assert "Inline reply body." in comments_markdown
    assert "Duplicate should be omitted" not in comments_markdown
    assert "- location: footer" in comments_markdown
    assert "- location: inline" in comments_markdown
    assert "- author: Thomas Rohde" in comments_markdown
    assert "- parent: c-1" in comments_markdown
    assert "token=secret" not in comments_markdown
    assert "https://example.atlassian.net" not in comments_markdown

    page_markdown = read(output / result.pages[0].index_md)
    assert "Comments sidecar: [2 comment(s)](comments.md)" in page_markdown
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["options"]["comments"] is True
    assert manifest["pages"][0]["paths"]["comments"] == result.pages[0].comments_path
    assert manifest["pages"][0]["comments"] == {"count": 2, "locations": ["footer", "inline"]}
    ai_manifest = yaml.safe_load((output / manifest["paths"]["ai_manifest"]).read_text(encoding="utf-8"))
    assert ai_manifest["pages"][0]["comments"] == result.pages[0].comments_path
    assert ai_manifest["pages"][0]["comments_count"] == 2
    ai_entry = read(output / manifest["paths"]["ai_entry"])
    assert "comments 2 ([comments.md](pages/0001-commented-page/comments.md))" in ai_entry
    assert validate_package(output).ok


def test_comments_fetch_failure_warns_without_sidecar(tmp_path: Path) -> None:
    output = tmp_path / "comments-failed"
    page = make_page("121", "Comment Failure", body_view="<h1>Comment Failure</h1>")
    client = FakeConfluenceClient(pages={"121": page}, comment_errors={"121"})

    result = extract(
        client=client,
        root=PageSummary(page_id="121", title="Comment Failure"),
        options=PullOptions(output=output, force=True, comments=True),
    )

    assert client.comment_calls == ["121"]
    assert result.pages[0].comments_path is None
    assert "W_COMMENTS_FETCH_FAILED" in {warning.code for warning in result.warnings}
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert "comments" not in manifest["pages"][0]["paths"]
    assert validate_package(output).ok


def test_full_mode_writes_current_evidence_artifacts_and_links_control_files(tmp_path: Path) -> None:
    output = tmp_path / "full"
    page = make_page(
        "125",
        "Full Evidence",
        body_view="<h1>Full Evidence</h1><p>Visible.</p>",
        storage="<p>Storage evidence.</p>",
    )
    client = FakeConfluenceClient(pages={"125": page})
    result = extract(
        client=client,
        root=PageSummary(page_id="125", title="Full Evidence"),
        options=PullOptions(output=output, force=True, output_mode="full"),
    )

    assert (output / "bundle.md").exists()
    assert result.bundle_path == output / "bundle.md"
    assert result.pages[0].index_html == "pages/0001-full-evidence/index.html"
    assert result.pages[0].source_path == "pages/0001-full-evidence/source.storage.xml"
    assert (output / result.pages[0].index_html).exists()
    assert (output / result.pages[0].source_path).exists()
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["options"]["output_mode"] == "full"
    assert manifest["options"]["write_bundle"] is True
    assert manifest["options"]["write_html"] is True
    assert manifest["options"]["write_source"] is True
    ai_manifest = yaml.safe_load((output / manifest["paths"]["ai_manifest"]).read_text(encoding="utf-8"))
    assert ai_manifest["output_mode"] == "full"
    assert ai_manifest["artifact_guidance"]["navigation_surfaces"] == ["page index.md files", "bundle.md"]
    assert ai_manifest["artifact_guidance"]["raw_reference_surfaces"] == ["source.storage.xml", "page.json"]
    assert ai_manifest["artifact_guidance"]["rendered_reference_surfaces"] == ["index.html"]
    ai_entry = read(output / manifest["paths"]["ai_entry"])
    assert "[full-evidence.yaml](full-evidence.yaml)" in ai_entry
    assert "[manifest.yaml](manifest.yaml)" in ai_entry
    assert "[diagnostics/warnings.jsonl](diagnostics/warnings.jsonl)" in ai_entry
    assert validate_package(output).ok


def test_render_mode_storage_prefers_storage_body(tmp_path: Path) -> None:
    output = tmp_path / "storage-mode"
    page = make_page(
        "130",
        "Storage Mode",
        body_view="<h1>Rendered Body</h1><p>Rendered only.</p>",
        storage="<h1>Storage Body</h1><p>Storage only.</p>",
    )
    client = FakeConfluenceClient(pages={"130": page})

    result = extract(
        client=client,
        root=PageSummary(page_id="130", title="Storage Mode"),
        options=PullOptions(output=output, force=True, render_mode="storage"),
    )

    markdown = read(output / result.pages[0].index_md)
    assert "Storage only." in markdown
    assert "Rendered only." not in markdown


def test_attachment_macro_ui_is_sanitized_and_replaced_with_read_only_listing(tmp_path: Path) -> None:
    output = tmp_path / "attachments"
    page = make_page(
        "150",
        "Attachment UI",
        body_view="""
        <h1>Attachment UI</h1>
        <p><a href="/download/attachments/150/readme.txt">Readme</a></p>
        <div class="plugin_attachments_upload_container">
          <form method="POST">
            <input type="hidden" name="atl_token" value="super-secret-token">
            <input type="file" name="file_0">
            <label>Upload file</label>
          </form>
        </div>
        <div class="attachment-buttons">
          <a class="editAttachmentLink" href="/pages/editattachment.action">Properties</a>
          <a class="removeAttachmentLink" href="/pages/confirmattachmentremoval.action">Delete</a>
        </div>
        <a class="download-all-link" href="/download/all_attachments?pageId=150">Download All</a>
        <div class="plugin_attachments_container">
          <div class="plugin_attachments_table_container">
            <table class="attachments">
              <tr><th>File</th><th>Modified</th></tr>
              <tr>
                <td>Labels - No labels <a href="/download/attachments/150/readme.txt" title="Download">readme.txt</a></td>
                <td>about 3 hours ago by <a href="/wiki/people/account">Thomas Rohde</a></td>
              </tr>
            </table>
          </div>
        </div>
        """,
    )
    attachment = AttachmentRecord(
        attachment_id="att-150",
        page_id="150",
        filename="readme.txt",
        media_type="text/plain",
        download_url="/download/attachments/150/readme.txt",
    )
    client = FakeConfluenceClient(
        pages={"150": page},
        attachments={"150": [attachment]},
        downloads={"/download/attachments/150/readme.txt": b"read only"},
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="150", title="Attachment UI"),
        options=PullOptions(output=output, force=True, output_mode="full", extract_attachments=True),
    )

    markdown = read(output / result.pages[0].index_md)
    html = read(output / result.pages[0].index_html)
    page_json = read(output / result.pages[0].page_json)
    bundle = read(output / "bundle.md")
    combined = "\n".join([markdown, html, page_json, bundle])
    assert "atl_token" not in combined
    assert "super-secret-token" not in combined
    assert "Upload file" not in markdown
    assert "Properties" not in markdown
    assert "Delete" not in markdown
    assert "Download All" not in markdown
    assert "Labels - No labels" not in markdown
    assert "Modified" not in markdown
    assert "Thomas Rohde" not in markdown
    assert "## Attachments" in markdown
    assert "| readme.txt | `pages/0001-attachment-ui/assets/readme.txt` ([open](assets/readme.txt))" in markdown
    assert validate_package(output).ok


def test_asset_filenames_with_spaces_and_parentheses_validate(tmp_path: Path) -> None:
    output = tmp_path / "asset-parentheses"
    page = make_page(
        "160",
        "Asset Parentheses",
        body_view="""
        <h1>Asset Parentheses</h1>
        <p><img src="/download/attachments/160/Fees domain(To-Be).png" alt="Fees domain(To-Be)"></p>
        """,
    )
    client = FakeConfluenceClient(
        pages={"160": page},
        downloads={"/download/attachments/160/Fees domain(To-Be).png": b"png-bytes"},
    )

    result = extract(
        client=client,
        root=PageSummary(page_id="160", title="Asset Parentheses"),
        options=PullOptions(output=output, force=True),
    )

    markdown = read(output / result.pages[0].index_md)
    assert "assets/Fees%20domain%28To-Be%29.png" in markdown
    assert (output / "pages" / "0001-asset-parentheses" / "assets" / "Fees domain(To-Be).png").exists()
    assert validate_package(output).ok


def test_redact_source_urls_applies_to_page_json_html_and_source(tmp_path: Path) -> None:
    output = tmp_path / "redacted"
    page = make_page(
        "175",
        "Redaction",
        body_view="""
        <h1>Redaction</h1>
        <p><img src="https://example.atlassian.net/wiki/images/image.png?token=secret" data-image-src="https://example.atlassian.net/wiki/images/image.png?token=secret" data-base-url="https://example.atlassian.net/wiki"></p>
        <p><img src="https://example.atlassian.net/wiki/images/labeled.png?token=secret" alt="Useful redacted diagram"></p>
        <p>Literal source URL: https://example.atlassian.net/wiki/spaces/EA/pages/175/Redaction</p>
        <p><a href="/download/attachments/175/readme.txt?token=secret">Readme</a></p>
        <p><a href="https://example.atlassian.net/wiki/spaces/EA/pages/999/Outside">Outside</a></p>
        """,
        storage='<p><a href="https://example.atlassian.net/wiki/download/attachments/175/source.txt?token=secret">Source</a> and literal https://example.atlassian.net/wiki/display/EA/Redaction</p>',
    )
    page.raw["body"] = {
        "view": {"value": page.body_view},
        "storage": {"value": page.body_storage},
    }
    page.raw["_links"] = {
        "webui": "/spaces/EA/pages/175/Redaction",
        "tinyui": "/x/abc",
        "base": "https://example.atlassian.net/wiki",
        "context": "/wiki",
        "self": "https://example.atlassian.net/wiki/rest/api/content/175",
        "editui": "/pages/resumedraft.action?draftId=175",
        "edituiv2": "/spaces/EA/pages/edit-v2/175",
    }
    page.raw["_expandable"] = {"operations": "", "permissions": ""}
    page.raw["extensions"] = {
        "draftVersion": 2,
        "isActiveLiveEditSession": False,
        "restrictions": {"read": True},
        "schedulePublishDate": "2026-06-05",
        "schedulePublishInfo": {"enabled": False},
    }
    attachment = AttachmentRecord(
        attachment_id="readme",
        page_id="175",
        filename="readme.txt",
        media_type="text/plain",
        download_url="/download/attachments/175/readme.txt?token=secret",
    )
    client = FakeConfluenceClient(
        pages={"175": page},
        attachments={"175": [attachment]},
        downloads={"/download/attachments/175/readme.txt?token=secret": b"redacted download"},
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="175", title="Redaction"),
        options=PullOptions(
            output=output,
            force=True,
            output_mode="full",
            redact_source_urls=True,
            redact_manifest=True,
        ),
    )

    html = read(output / result.pages[0].index_html)
    page_json = read(output / result.pages[0].page_json)
    markdown = read(output / result.pages[0].index_md)
    source = read(output / result.pages[0].source_path)
    manifest_text = read(output / "manifest.yaml")
    combined = "\n".join([html, page_json, source, manifest_text])
    assert "https://example.atlassian.net" not in combined
    assert "https://example.atlassian.net" not in markdown
    assert "/download/attachments/175/readme.txt" not in combined
    assert "token=secret" not in combined
    assert "editui" not in page_json
    assert "edituiv2" not in page_json
    assert "webui" not in page_json
    assert "tinyui" not in page_json
    assert "resumedraft" not in page_json
    assert "operations" not in page_json
    assert "permissions" not in page_json
    assert "draftVersion" not in page_json
    assert "isActiveLiveEditSession" not in page_json
    assert "restrictions" not in page_json
    assert "schedulePublishDate" not in page_json
    assert "schedulePublishInfo" not in page_json
    assert '"title": "Redaction"' in page_json
    assert '"has_rendered_html": true' in page_json
    assert "![](<redacted-url>)" not in markdown
    assert "![Useful redacted diagram](<redacted-url>)" in markdown
    assert "<redacted-url>" in combined
    assert len(result.assets) == 1
    assert (output / result.assets[0].local_path).exists()
    assert "W_ASSET_DOWNLOAD_FAILED" not in {warning.code for warning in result.warnings}
    assert validate_package(output).ok


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
    sibling = make_page("203", "Sibling", body_view="<h1>Sibling</h1><p>Peer.</p>")
    grandchild = make_page(
        "202",
        "Grandchild",
        body_view='<h1>Grandchild</h1><p>Leaf.</p><p><a href="/wiki/spaces/EA/pages/203/Sibling">Sibling</a></p>',
    )
    client = FakeConfluenceClient(
        pages={"200": root, "201": child, "202": grandchild, "203": sibling},
        children={
            "200": [PageSummary(page_id="201", title="Child"), PageSummary(page_id="203", title="Sibling")],
            "201": [PageSummary(page_id="202", title="Grandchild")],
        },
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="200", title="Root Page"),
        options=PullOptions(output=output, tree=True, force=True, output_mode="full"),
    )
    assert len(result.pages) == 4
    assert result.pages[1].index_md.startswith("pages/0001-root-page/0002-child/")
    root_markdown = read(output / result.pages[0].index_md)
    assert "0002-child/index.md" in root_markdown
    grandchild_markdown = read(output / result.pages[3].index_md)
    assert "../../0003-sibling/index.md" in grandchild_markdown
    bundle = read(output / "bundle.md")
    assert "(pages/0001-root-page/0002-child/index.md)" in bundle
    assert "(pages/0001-root-page/0002-child/0004-grandchild/index.md)" in bundle
    assert "(pages/0001-root-page/0003-sibling/index.md)" in bundle
    assert "(0002-child/index.md)" not in bundle
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["path_base"]["kind"] == "package_root"
    ai_manifest = yaml.safe_load((output / manifest["paths"]["ai_manifest"]).read_text(encoding="utf-8"))
    assert manifest["paths"]["ai_manifest"] == "root-page.yaml"
    assert manifest["paths"]["ai_entry"] == "root-page.md"
    assert [page["name"] for page in ai_manifest["pages"]] == ["root-page", "child", "sibling", "grandchild"]
    assert [page["parent"] for page in ai_manifest["pages"]] == [None, "root-page", "root-page", "child"]
    assert ai_manifest["pages"][0]["children"] == ["child", "sibling"]
    assert ai_manifest["pages"][1]["children"] == ["grandchild"]
    ai_entry = read(output / manifest["paths"]["ai_entry"])
    assert "- `root-page`: [Root Page]" in ai_entry
    assert "  - `child`: [Child]" in ai_entry
    assert "  - `sibling`: [Sibling]" in ai_entry
    assert "    - `grandchild`: [Grandchild]" in ai_entry
    assert validate_package(output).ok


def test_redacted_tree_preserves_local_markdown_and_bundle_links(tmp_path: Path) -> None:
    output = tmp_path / "redacted-tree"
    root = make_page(
        "210",
        "Root Page",
        body_view="""
        <h1>Root Page</h1>
        <p><a href="/wiki/spaces/EA/pages/211/Child">Child link</a></p>
        <p><a href="https://example.atlassian.net/wiki/spaces/EA/pages/999/External">External link</a></p>
        """,
    )
    child = make_page("211", "Child", body_view="<h1>Child</h1><p>Child body.</p>")
    client = FakeConfluenceClient(
        pages={"210": root, "211": child},
        children={"210": [PageSummary(page_id="211", title="Child")]},
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="210", title="Root Page"),
        options=PullOptions(
            output=output,
            tree=True,
            force=True,
            output_mode="full",
            redact_source_urls=True,
            redact_manifest=True,
        ),
    )

    root_markdown = read(output / result.pages[0].index_md)
    root_html = read(output / result.pages[0].index_html)
    bundle = read(output / "bundle.md")
    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    assert "[Child link](0002-child/index.md)" in root_markdown
    assert '[External link](<redacted-url>)' in root_markdown
    assert 'href="0002-child/index.md"' in root_html
    assert "(pages/0001-root-page/0002-child/index.md)" in bundle
    assert manifest["links"][0]["rewritten"] == "0002-child/index.md"
    assert validate_package(output).ok


def test_validate_rejects_redacted_placeholder_for_rewritten_links(tmp_path: Path) -> None:
    output = tmp_path / "redacted-placeholder"
    root = make_page(
        "220",
        "Root Page",
        body_view='<h1>Root Page</h1><p><a href="/wiki/spaces/EA/pages/221/Child">Child link</a></p>',
    )
    child = make_page("221", "Child", body_view="<h1>Child</h1>")
    client = FakeConfluenceClient(
        pages={"220": root, "221": child},
        children={"220": [PageSummary(page_id="221", title="Child")]},
    )
    result = extract(
        client=client,
        root=PageSummary(page_id="220", title="Root Page"),
        options=PullOptions(output=output, tree=True, force=True, redact_source_urls=True, redact_manifest=True),
    )
    root_markdown_path = output / result.pages[0].index_md
    root_markdown_path.write_text(
        root_markdown_path.read_text(encoding="utf-8").replace("(0002-child/index.md)", "(<redacted-url>)", 1),
        encoding="utf-8",
    )

    validation = validate_package(output)
    assert not validation.ok
    assert any(error["code"] == "ERR_VALIDATION_REDACTED_REWRITTEN_LINK" for error in validation.errors)


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
        options=PullOptions(output=output, force=True, output_mode="full"),
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


def test_tree_discovery_failure_does_not_create_output_scaffold(tmp_path: Path) -> None:
    output = tmp_path / "early-failure"
    page = make_page("410", "Early Failure", body_view="<h1>Early Failure</h1>")

    class FailingTreeClient(FakeConfluenceClient):
        def get_children(self, page_id: str) -> list[PageSummary]:
            raise RuntimeError("tree discovery failed")

    client = FailingTreeClient(pages={"410": page})

    with pytest.raises(RuntimeError):
        extract(
            client=client,
            root=PageSummary(page_id="410", title="Early Failure"),
            options=PullOptions(output=output, tree=True, force=True),
        )

    assert not output.exists()


def test_validate_rejects_secret_marker_in_html(tmp_path: Path) -> None:
    output = tmp_path / "secret-html"
    page = make_page("425", "Secret HTML", body_view="<h1>Secret HTML</h1>")
    client = FakeConfluenceClient(pages={"425": page})
    result = extract(
        client=client,
        root=PageSummary(page_id="425", title="Secret HTML"),
        options=PullOptions(output=output, force=True, output_mode="full"),
    )
    html_path = output / result.pages[0].index_html
    html_path.write_text('<input type="hidden" name="atl_token" value="abc123">', encoding="utf-8")

    validation = validate_package(output)
    assert not validation.ok
    assert validation.errors[-1]["code"] == "ERR_VALIDATION_SECRET_PATTERN"
    assert validation.errors[-1]["details"]["line"] == 1
    assert validation.errors[-1]["details"]["term"] == "name=atl_token"


def test_validate_does_not_reject_plain_pat_word(tmp_path: Path) -> None:
    output = tmp_path / "plain-pat"
    page = make_page("426", "Plain PAT", body_view="<h1>Plain PAT</h1>")
    client = FakeConfluenceClient(pages={"426": page})
    result = extract(
        client=client,
        root=PageSummary(page_id="426", title="Plain PAT"),
        options=PullOptions(output=output, force=True),
    )
    markdown_path = output / result.pages[0].index_md
    markdown_path.write_text(
        markdown_path.read_text(encoding="utf-8") + "\nPAT is an acronym in this paragraph.\n",
        encoding="utf-8",
    )

    assert validate_package(output).ok


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
