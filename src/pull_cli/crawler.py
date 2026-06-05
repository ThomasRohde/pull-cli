from __future__ import annotations

from collections import deque

from .clients.base import ConfluenceClient
from .errors import EXIT_SOURCE, PullError
from .models import PageSummary


def crawl_pages(
    client: ConfluenceClient,
    root: PageSummary,
    *,
    tree: bool,
    depth: int | None,
    max_pages: int,
) -> list[PageSummary]:
    root.depth = 0
    root.parent_id = None
    ordered: list[PageSummary] = [root]
    if not tree or depth == 0:
        root.order = 1
        return ordered

    queue: deque[PageSummary] = deque([root])
    seen = {root.page_id}
    while queue:
        parent = queue.popleft()
        if depth is not None and parent.depth >= depth:
            continue
        children = client.get_children(parent.page_id)
        for child in children:
            if child.page_id in seen:
                continue
            if len(ordered) >= max_pages:
                raise PullError(
                    code="ERR_SOURCE_TREE_TOO_LARGE",
                    message=f"Tree extraction exceeded the max page cap of {max_pages}.",
                    exit_code=EXIT_SOURCE,
                    suggested_action="Use --max-pages with a higher value or reduce --depth.",
                    details={"max_pages": max_pages},
                )
            child.parent_id = parent.page_id
            child.depth = parent.depth + 1
            seen.add(child.page_id)
            ordered.append(child)
            queue.append(child)

    for index, summary in enumerate(ordered, start=1):
        summary.order = index
    return ordered
