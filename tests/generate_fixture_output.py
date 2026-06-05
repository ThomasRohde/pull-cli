from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from pull_cli.extractor import extract  # noqa: E402
from pull_cli.models import AttachmentRecord, PageSummary, PullOptions  # noqa: E402
from tests.conftest import FakeConfluenceClient, make_page  # noqa: E402


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".tmp" / "generated-fixture"
    if output.exists():
        shutil.rmtree(output)
    page = make_page(
        "900",
        "Generated Fixture",
        body_view='<h1>Generated Fixture</h1><p>Fixture text.</p><p><a href="/download/attachments/900/file.txt">file</a></p>',
        storage='<root xmlns:ac="http://atlassian.com/content"><ac:structured-macro ac:name="info"><ac:rich-text-body><p>Info body</p></ac:rich-text-body></ac:structured-macro></root>',
    )
    attachment = AttachmentRecord(
        attachment_id="file",
        page_id="900",
        filename="file.txt",
        media_type="text/plain",
        download_url="/download/attachments/900/file.txt",
    )
    client = FakeConfluenceClient(
        pages={"900": page},
        attachments={"900": [attachment]},
        downloads={"/download/attachments/900/file.txt": b"hello"},
    )
    extract(
        client=client,
        root=PageSummary(page_id="900", title="Generated Fixture"),
        options=PullOptions(output=output, force=True),
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
