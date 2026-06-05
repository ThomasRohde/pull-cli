from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from .markdown_writer import rendered_html_to_markdown
from .models import AttachmentRecord, MacroRecord, PullOptions, WarningRecord


@dataclass
class MacroInstance:
    macro_id: str
    name: str
    params: dict[str, str]
    body: str
    raw: str


@dataclass
class MacroContext:
    page_id: str
    attachments: list[AttachmentRecord]
    options: PullOptions
    child_links: list[tuple[str, str]] = field(default_factory=list)


class MacroAdapter:
    names: set[str] = set()
    adapter_name = "unknown"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        return unknown_macro(macro, context)


class PanelAdapter(MacroAdapter):
    names = {"info", "note", "tip", "warning", "panel"}
    adapter_name = "panel"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        label = macro.name.upper() if macro.name != "panel" else "PANEL"
        title = macro.params.get("title") or macro.params.get("name") or label.title()
        body = storage_fragment_to_markdown(macro.body)
        quoted = "\n".join(f"> {line}" if line else ">" for line in body.splitlines())
        markdown = f"> [!{label}] {title}\n{quoted}".strip()
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=markdown,
            params=macro.params,
        )


class CodeAdapter(MacroAdapter):
    names = {"code", "noformat"}
    adapter_name = "code"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        language = macro.params.get("language") or macro.params.get("lang") or ""
        code = plain_text(macro.body).strip("\n")
        fence_language = re.sub(r"[^A-Za-z0-9_+.-]", "", language)
        markdown = f"```{fence_language}\n{code}\n```"
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=markdown,
            params=macro.params,
        )


class StatusAdapter(MacroAdapter):
    names = {"status"}
    adapter_name = "status"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        text = macro.params.get("title") or macro.params.get("text") or plain_text(macro.body).strip()
        color = macro.params.get("colour") or macro.params.get("color") or macro.params.get("subtle") or "default"
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=f"[STATUS: {text} / {color}]",
            params=macro.params,
        )


class ExpandAdapter(MacroAdapter):
    names = {"expand"}
    adapter_name = "expand"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        title = macro.params.get("title") or macro.params.get("name") or "Expand"
        body = storage_fragment_to_markdown(macro.body)
        markdown = f"### Expand: {title}\n\n{body}".strip()
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=markdown,
            params=macro.params,
        )


class TabsAdapter(MacroAdapter):
    names = {"tabs", "tab-group", "tabgroup", "composition-setup"}
    adapter_name = "tabs"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        nested = parse_macros(macro.body, top_level_only=True)
        tab_blocks: list[str] = []
        for index, tab in enumerate(nested, start=1):
            if tab.name not in {"tab", "tab-pane", "aui-tab", "composition-tab"}:
                continue
            title = tab.params.get("title") or tab.params.get("name") or f"Tab {index}"
            body = storage_fragment_to_markdown(tab.body)
            tab_blocks.append(f"### Tab: {title}\n\n{body}".strip())
        if not tab_blocks:
            body = storage_fragment_to_markdown(macro.body)
            tab_blocks.append(f"### Tabs\n\n{body}".strip())
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown="\n\n".join(tab_blocks),
            params=macro.params,
        )


class FlattenAdapter(MacroAdapter):
    names = {"section", "column", "layout", "layout-section", "layout-cell"}
    adapter_name = "layout"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=storage_fragment_to_markdown(macro.body),
            params=macro.params,
        )


class TocAdapter(MacroAdapter):
    names = {"toc"}
    adapter_name = "toc"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            status="placeholder",
            markdown="[Table of contents macro omitted: headings are present in the page Markdown.]",
            params=macro.params,
        )


class ChildrenAdapter(MacroAdapter):
    names = {"children", "pagetree", "page-tree"}
    adapter_name = "children"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        if context.child_links:
            items = "\n".join(f"- [{title}]({link})" for title, link in context.child_links)
            markdown = f"### Child Pages\n\n{items}"
        else:
            markdown = "[Children/page tree macro: no in-scope child pages were available in this pull.]"
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=markdown,
            params=macro.params,
        )


class IncludeAdapter(MacroAdapter):
    names = {"include", "excerpt-include", "multi-excerpt-include", "excerpt"}
    adapter_name = "include"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        target = macro.params.get("page") or macro.params.get("name") or macro.params.get("default-parameter-value") or "unknown"
        warnings: list[WarningRecord] = []
        if context.options.follow_includes:
            body = storage_fragment_to_markdown(macro.body)
            markdown = body or f"[Include/excerpt target {target!r} requested for follow, but no inline body was available.]"
            warnings.append(
                WarningRecord(
                    code="W_MACRO_PARTIAL",
                    message="Include/excerpt follow was requested but only inline source content was available.",
                    source_page_id=context.page_id,
                    details={"target": target},
                )
            )
        else:
            markdown = f"[Include/excerpt dependency not followed: {target}]"
            warnings.append(
                WarningRecord(
                    code="W_MACRO_PARTIAL",
                    message="Include/excerpt macro was represented as a dependency placeholder.",
                    source_page_id=context.page_id,
                    details={"target": target},
                )
            )
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            status="placeholder" if not context.options.follow_includes else "converted",
            markdown=markdown,
            params=macro.params,
            warnings=warnings,
        )


class AttachmentsAdapter(MacroAdapter):
    names = {"attachments"}
    adapter_name = "attachments"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        if context.attachments:
            items = "\n".join(f"- {attachment.filename}" for attachment in context.attachments)
            markdown = f"### Attachments\n\n{items}"
        else:
            markdown = "[Attachments macro: no attachments were returned by Confluence.]"
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=markdown,
            params=macro.params,
        )


class ViewFileAdapter(MacroAdapter):
    names = {"view-file", "office-excel", "office-powerpoint", "office-word", "viewpdf", "pdf"}
    adapter_name = "view-file"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        filename = macro.params.get("name") or macro.params.get("filename") or _attachment_name(macro.raw) or "file"
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=f"[Displayed file attachment: {filename}]",
            params=macro.params,
        )


class JiraAdapter(MacroAdapter):
    names = {"jira", "jiraissues", "jiraportlet"}
    adapter_name = "jira"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        query = macro.params.get("jqlQuery") or macro.params.get("key") or macro.params.get("url") or "unavailable"
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            status="placeholder",
            markdown=f"[Jira macro snapshot placeholder: {query}]",
            params=macro.params,
        )


class DiagramAdapter(MacroAdapter):
    names = {
        "gliffy",
        "drawio",
        "draw.io",
        "mermaid",
        "plantuml",
        "plantumlrender",
        "diagram",
    }
    adapter_name = "diagram"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        title = macro.params.get("name") or macro.params.get("title") or macro.name
        body = plain_text(macro.body).strip()
        markdown = f"[Diagram macro snapshot: {title}]"
        if body:
            markdown += f"\n\n```text\n{body}\n```"
        warnings: list[WarningRecord] = []
        if context.options.diagram_sources and not body:
            warnings.append(
                WarningRecord(
                    code="W_ASSET_DIAGRAM_SOURCE_NOT_FOUND",
                    message="Diagram source was requested but was not discoverable in storage.",
                    source_page_id=context.page_id,
                    details={"macro": macro.name, "title": title},
                )
            )
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=markdown,
            params=macro.params,
            warnings=warnings,
        )


class DynamicAdapter(MacroAdapter):
    names = {"recently-updated", "contentbylabel", "content-by-label", "task-report", "roadmap"}
    adapter_name = "dynamic"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        warning = WarningRecord(
            code="W_DYNAMIC_MACRO_SNAPSHOT",
            message="Dynamic macro is represented as a pull-time rendered snapshot where available.",
            source_page_id=context.page_id,
            details={"macro": macro.name},
        )
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            status="placeholder",
            markdown=f"[Dynamic macro snapshot: {macro.name}]",
            params=macro.params,
            warnings=[warning],
        )


class HtmlAdapter(MacroAdapter):
    names = {"html"}
    adapter_name = "html"

    def convert(self, macro: MacroInstance, context: MacroContext) -> MacroRecord:
        soup = BeautifulSoup(macro.body, "lxml")
        sanitized = False
        for tag in soup.find_all(["script", "iframe", "object", "embed"]):
            tag.decompose()
            sanitized = True
        markdown = rendered_html_to_markdown(str(soup)).strip() or "[HTML macro had no visible text.]"
        warnings = []
        if sanitized:
            warnings.append(
                WarningRecord(
                    code="W_SANITIZED_HTML",
                    message="Executable content was stripped from an HTML macro.",
                    source_page_id=context.page_id,
                )
            )
        return MacroRecord(
            macro_id=macro.macro_id,
            name=macro.name,
            adapter=self.adapter_name,
            source_page_id=context.page_id,
            markdown=markdown,
            params=macro.params,
            warnings=warnings,
        )


class MacroRegistry:
    def __init__(self) -> None:
        adapters: list[MacroAdapter] = [
            PanelAdapter(),
            CodeAdapter(),
            StatusAdapter(),
            ExpandAdapter(),
            TabsAdapter(),
            FlattenAdapter(),
            TocAdapter(),
            ChildrenAdapter(),
            IncludeAdapter(),
            AttachmentsAdapter(),
            ViewFileAdapter(),
            JiraAdapter(),
            DiagramAdapter(),
            DynamicAdapter(),
            HtmlAdapter(),
        ]
        self._adapters = {name: adapter for adapter in adapters for name in adapter.names}

    def convert_all(self, storage: str | None, context: MacroContext) -> list[MacroRecord]:
        records: list[MacroRecord] = []
        for macro in parse_macros(storage or "", top_level_only=True):
            adapter = self._adapters.get(macro.name)
            if adapter:
                records.append(adapter.convert(macro, context))
            elif context.options.unknown_macro == "ignore":
                records.append(
                    MacroRecord(
                        macro_id=macro.macro_id,
                        name=macro.name,
                        adapter="unknown",
                        source_page_id=context.page_id,
                        status="ignored",
                        params=macro.params,
                    )
                )
            else:
                records.append(unknown_macro(macro, context))
        return records


def parse_macros(storage: str, *, top_level_only: bool = False) -> list[MacroInstance]:
    if not storage:
        return []
    soup = _storage_soup(storage)
    tags = [tag for tag in soup.find_all(True) if _is_macro_tag(tag)]
    if top_level_only:
        tags = [tag for tag in tags if not any(_is_macro_tag(parent) for parent in tag.parents if isinstance(parent, Tag))]
    macros = []
    for index, tag in enumerate(tags, start=1):
        name = _attr(tag, "ac:name", "name") or "unknown"
        raw = str(tag)
        macro_id = hashlib.sha1(f"{name}:{index}:{raw[:100]}".encode()).hexdigest()[:12]
        macros.append(
            MacroInstance(
                macro_id=macro_id,
                name=name.lower(),
                params=_parameters(tag),
                body=_body(tag),
                raw=raw,
            )
        )
    return macros


def storage_fragment_to_markdown(fragment: str) -> str:
    if not fragment:
        return ""
    soup = _storage_soup(fragment)
    for macro_tag in soup.find_all(True):
        if _is_macro_tag(macro_tag):
            macro_tag.replace_with(f"[Nested macro: {_attr(macro_tag, 'ac:name', 'name') or 'unknown'}]")
    root = _storage_root(soup)
    html_fragment = "".join(str(child) for child in root.contents)
    return rendered_html_to_markdown(html_fragment).strip()


def plain_text(fragment: str) -> str:
    if not fragment:
        return ""
    return _storage_root(_storage_soup(fragment)).get_text("\n")


def unknown_macro(macro: MacroInstance, context: MacroContext) -> MacroRecord:
    warning = WarningRecord(
        code="W_MACRO_UNKNOWN",
        message=f"Unsupported macro {macro.name!r} was represented as a placeholder.",
        source_page_id=context.page_id,
        details={"macro": macro.name, "params": macro.params},
    )
    status = "error" if context.options.unknown_macro == "error" else "placeholder"
    return MacroRecord(
        macro_id=macro.macro_id,
        name=macro.name,
        adapter="unknown",
        source_page_id=context.page_id,
        status=status,
        markdown=f"[Unsupported Confluence macro: {macro.name}; params={macro.params}]",
        params=macro.params,
        warnings=[warning],
    )


def _is_macro_tag(tag: Tag) -> bool:
    return tag.name.endswith("structured-macro") or tag.name.endswith("macro")


def _attr(tag: Tag, *names: str) -> str | None:
    for name in names:
        value = tag.attrs.get(name)
        if isinstance(value, str):
            return value
    return None


def _parameters(tag: Tag) -> dict[str, str]:
    params: dict[str, str] = {}
    for parameter in tag.find_all(True):
        if not parameter.name.endswith("parameter"):
            continue
        name = _attr(parameter, "ac:name", "name")
        if not name:
            continue
        params[name] = parameter.get_text(" ", strip=True)
    return params


def _body(tag: Tag) -> str:
    for child in tag.find_all(True, recursive=False):
        if child.name.endswith("rich-text-body") or child.name.endswith("plain-text-body"):
            return "".join(str(part) for part in child.contents)
    bodies = [child for child in tag.find_all(True) if child.name.endswith("rich-text-body") or child.name.endswith("plain-text-body")]
    if bodies:
        return "".join(str(part) for part in bodies[0].contents)
    return ""


def _attachment_name(raw: str) -> str | None:
    soup = _storage_soup(raw)
    attachment = next((tag for tag in _storage_root(soup).find_all(True) if tag.name.endswith("attachment")), None)
    if not attachment:
        return None
    return _attr(attachment, "ri:filename", "filename")


def _storage_soup(fragment: str) -> BeautifulSoup:
    return BeautifulSoup(f"<pull-root>{fragment}</pull-root>", "xml")


def _storage_root(soup: BeautifulSoup) -> Tag | BeautifulSoup:
    return soup.find("pull-root") or soup.body or soup
