from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

AssetPolicy = Literal["visible", "page", "all"]
RenderMode = Literal["hybrid", "view", "export-view", "styled-view", "storage"]
MacroPolicy = Literal["expand", "placeholder", "strict"]
UnknownMacroPolicy = Literal["warn", "error", "ignore"]


@dataclass
class PullOptions:
    output: Path
    force: bool = False
    clean: bool = False
    tree: bool = False
    depth: int | None = None
    max_pages: int = 500
    layout: Literal["auto", "nested", "flat"] = "auto"
    write_bundle: bool = True
    write_html: bool = True
    write_source: bool = True
    write_chunks: bool = False
    asset_policy: AssetPolicy = "visible"
    no_assets: bool = False
    extract_attachments: bool = False
    diagram_sources: bool = False
    render_mode: RenderMode = "hybrid"
    macro_policy: MacroPolicy = "expand"
    unknown_macro: UnknownMacroPolicy = "warn"
    rewrite_links: bool = True
    follow_includes: bool = False
    follow_links: Literal["same-tree", "same-space", "none"] = "none"
    include_non_page_children: bool = False
    redact_source_urls: bool = False
    redact_manifest: bool = False
    strict: bool = False

    def manifest_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["output"] = str(self.output)
        return data


@dataclass
class Config:
    base_url: str | None = None
    user: str | None = None
    token: str | None = None
    cloud_id: str | None = None
    ssl_verify: bool | str = True
    deployment: Literal["auto", "cloud", "data_center"] = "auto"
    config_path: Path | None = None

    @property
    def has_auth(self) -> bool:
        return bool(self.token)


@dataclass
class TargetSelection:
    positional: str | None = None
    page_id: str | None = None
    url: str | None = None
    space: str | None = None
    title: str | None = None


@dataclass
class PageSummary:
    page_id: str
    title: str
    space_key: str | None = None
    url: str | None = None
    parent_id: str | None = None
    depth: int = 0
    order: int = 0


@dataclass
class PageRecord(PageSummary):
    version: int | None = None
    body_view: str | None = None
    body_export_view: str | None = None
    body_storage: str | None = None
    body_adf: dict[str, Any] | None = None
    labels: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class AttachmentRecord:
    attachment_id: str
    page_id: str
    filename: str
    media_type: str | None = None
    download_url: str | None = None
    web_url: str | None = None
    file_size: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WarningRecord:
    code: str
    message: str
    source_page_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssetReference:
    page_id: str
    html_attribute: str
    original: str


@dataclass
class AssetRecord:
    asset_id: str
    source_page_id: str | None
    attachment_id: str | None
    filename: str
    media_type: str | None
    local_path: str
    sha256: str | None
    role: str
    source_url: str | None = None
    references: list[AssetReference] = field(default_factory=list)
    sidecars: list[str] = field(default_factory=list)

    def to_manifest(self) -> dict[str, Any]:
        data = asdict(self)
        data["references"] = [asdict(ref) for ref in self.references]
        return data


@dataclass
class LinkRecord:
    original: str
    normalized: str
    kind: str
    source_page_id: str
    target_page_id: str | None = None
    target_asset_id: str | None = None
    rewritten: str | None = None
    status: Literal["rewritten", "preserved", "unresolved", "skipped"] = "preserved"
    warning: str | None = None


@dataclass
class MacroRecord:
    macro_id: str
    name: str
    adapter: str
    source_page_id: str
    status: Literal["converted", "placeholder", "ignored", "error"] = "converted"
    markdown: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    warnings: list[WarningRecord] = field(default_factory=list)

    def to_manifest(self) -> dict[str, Any]:
        data = asdict(self)
        data["warnings"] = [warning.to_dict() for warning in self.warnings]
        return data


@dataclass
class PageArtifact:
    page: PageRecord
    order: int
    page_dir: str
    index_md: str
    index_html: str | None
    source_path: str | None
    page_json: str
    markdown: str
    html: str
    assets: list[AssetRecord] = field(default_factory=list)
    links: list[LinkRecord] = field(default_factory=list)
    macros: list[MacroRecord] = field(default_factory=list)
    warnings: list[WarningRecord] = field(default_factory=list)


@dataclass
class ExtractionResult:
    output_dir: Path
    manifest_path: Path
    bundle_path: Path | None
    pages: list[PageArtifact]
    assets: list[AssetRecord]
    warnings: list[WarningRecord]
    links: list[LinkRecord]
    macros: list[MacroRecord]
    metrics: dict[str, Any] = field(default_factory=dict)
