# pull-cli

`pull-cli` installs the `pull` command, a read-only Confluence extractor for AI-consumable evidence packages. It is rendered-page-first: the Markdown bundle is based on the current published page as visible to the authenticated user, while storage XML is kept for macro recovery, provenance, and fallback.

Confluence access is implemented through `atlassian-python-api` behind a small `pull_cli.clients` protocol. The extraction, redaction, manifest, asset, link, and validation contracts remain owned by `pull-cli`.

## Install

```bash
uvx pull-cli --help
uv tool install pull-cli
pip install pull-cli
```

The package name is `pull-cli`. The import package is `pull_cli`. Console scripts are `pull` and `pull-cli`.

## Quickstart

Cloud:

```bash
set PULL_URL=https://example.atlassian.net/wiki
set PULL_USER=you@example.com
set PULL_TOKEN=your-api-token
pull 123456 -o pulled-confluence
```

Data Center or Server:

```bash
set PULL_URL=https://confluence.example.com/confluence
set PULL_TOKEN=your-personal-access-token
pull --page-id 123456 -o pulled-confluence
```

`CONFPUB_URL`, `CONFPUB_USER`, `CONFPUB_TOKEN`, and `CONFPUB_SSL_VERIFY` are accepted as compatibility fallbacks after `PULL_*` variables.

## CLI Examples

```bash
pull 123456 -o pulled
pull "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture" -o pulled
pull --space EA --title "Architecture Overview" -o pulled
pull --page-id 123456 --tree --depth 3 --max-pages 100 -o tree
pull --page-id 123456 --tree --assets all --extract-attachments -o offline
pull --page-id 123456 --json -o pulled
pull validate pulled
pull guide --json
```

Selector resolution order is: explicit `--page-id`, explicit `--url`, positional URL, positional numeric page ID, then `--space` plus `--title`.

## Output Package

```text
pulled-confluence/
├── page-title.md
├── page-title.yaml
├── manifest.yaml
├── bundle.md
├── pages/
│   └── 0001-page-slug/
│       ├── index.md
│       ├── index.html
│       ├── source.storage.xml
│       ├── page.json
│       └── assets/
└── diagnostics/
    ├── warnings.jsonl
    └── unresolved-links.md
```

`page-title.md` is named from the sanitized root page title and is the recommended first file to give another AI agent. It contains explicit agent instructions, package-root path rules, a hierarchical page index with sanitized title-based page names, page Markdown paths, assets, extracted sidecars, and diagnostics links.

`page-title.yaml` is the machine-readable version of that AI navigation manifest, also named from the sanitized root page title. It intentionally omits noisy provenance and raw API details; use `manifest.yaml` when you need full validation/provenance data. The exact generated filenames are recorded in `manifest.yaml` under `paths.ai_entry` and `paths.ai_manifest`. AI navigation paths are package-root-relative: resolve them against the directory containing the root AI Markdown/YAML file, not the caller's shell working directory.

`manifest.yaml` is mandatory and records source metadata, options, page order, local relative paths, assets, SHA-256 checksums, link rewrites, macro conversions, warnings, and extraction completeness. `bundle.md` concatenates pages in page/tree order with stable delimiters for AI use; local links embedded in the bundle are rebased to the package root.

For tree pulls, nested page paths are the default. The manifest always carries stable numeric ordering.

## Auth and Config

Resolution order:

1. CLI flags such as `--base-url`, `--user`, `--token`, `--ssl-verify`.
2. `PULL_*` environment variables.
3. Optional YAML config from `--config`.
4. `CONFPUB_*` compatibility environment variables.

`--ssl-verify` accepts `true`, `false`, or a CA bundle path.

## Macro, Asset, and Link Behavior

The extractor uses a macro adapter registry. Current adapters cover panels/admonitions, code/noformat, status, expand, tabs, layout flattening, TOC placeholders, children/page tree links when in scope, include/excerpt placeholders or inline source when available, attachments, displayed files, Jira placeholders, diagram snapshots, dynamic snapshots, HTML macro sanitization, and unknown macro placeholders.

Asset policy defaults to `visible`: rendered images, visible attachment links, file macros, and rendered diagram images where discoverable. `--assets page` downloads all page attachments. `--assets all` includes visible/referenced assets plus all page attachments and macro-listed files where discoverable. `--no-assets` skips downloads and preserves source links with warnings.

Local links to pages in the pulled tree are rewritten to relative `index.md` paths. Downloaded asset links are rewritten to local files. External, mailto, Jira, and out-of-scope Confluence links are preserved. Same-page anchors are normalized where possible; unresolved anchors become diagnostics.

## JSON Mode

With `--json` or `LLM=true`, stdout is exactly one JSON object with:

```json
{
  "schema_version": "1.0",
  "request_id": "req_...",
  "ok": true,
  "command": "pull",
  "target": {},
  "result": {},
  "warnings": [],
  "errors": [],
  "metrics": {}
}
```

Progress, retries, warnings, and debug output belong on stderr.

## Security

`pull` is read-only. It does not mutate Confluence, fetch drafts by default, bypass permissions, or call LLM services. Tokens, Authorization headers, cookies, signed download query parameters, and token-like strings are redacted before JSON envelopes, manifests, page metadata, and diagnostics are written.

Rendered HTML snapshots are sanitized by removing executable tags and event attributes. HTML macro content is made inert before conversion.

## Validation

```bash
pull validate pulled-confluence
pull validate pulled-confluence/manifest.yaml --json
```

Validation checks manifest shape, AI navigation manifest paths, relative paths, page files, asset checksums, diagnostics JSONL, Markdown local links, and token-like markers in text outputs.

## Development

```bash
uv sync --all-extras
uv run ruff check .
uv run pytest
uv build
uv run pull --help
uv run pull guide --json
uv run python tests/generate_fixture_output.py .tmp/generated-fixture
uv run pull validate .tmp/generated-fixture
```

Live smoke testing requires a readable Confluence page and credentials through `PULL_*` or `CONFPUB_*`.
