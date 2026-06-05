from __future__ import annotations

from markdownify import markdownify as html_to_markdown


def rendered_html_to_markdown(html: str) -> str:
    markdown = html_to_markdown(
        html or "",
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
    )
    lines = [line.rstrip() for line in markdown.splitlines()]
    compact: list[str] = []
    blank_count = 0
    for line in lines:
        if line:
            blank_count = 0
            compact.append(line)
        else:
            blank_count += 1
            if blank_count <= 2:
                compact.append("")
    return "\n".join(compact).strip() + "\n" if compact else ""
