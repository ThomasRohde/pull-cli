# pull-cli

`pull-cli` installs the `pull` command, a read-only Confluence extractor for AI-consumable evidence packages. It is rendered-page-first: page Markdown, and the optional Markdown bundle in full mode, are based on the current published page as visible to the authenticated user, while storage XML is kept for macro recovery, provenance, and fallback.

The default output mode is `simple`: a quiet agent-facing package with the root AI Markdown file, per-page Markdown files, assets/sidecars, and validation control files. Use `--output-mode full` when you also want `bundle.md`, page HTML snapshots, and storage-source sidecars.

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
pull --page-id 123456 --auth bearer -o pulled-confluence
```

`CONFPUB_URL`, `CONFPUB_USER`, `CONFPUB_TOKEN`, and `CONFPUB_SSL_VERIFY` are accepted as compatibility fallbacks after `PULL_*` variables.

For the most common AI handoff, pull the whole page tree and point the agent at the generated root Markdown file:

```bash
pull "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture" --tree --comments --clean -o pulled-confluence
```

Then give the agent `pulled-confluence/<sanitized-root-page-title>.md`.

Running `pull` without arguments prints help. If `-o/--output` is omitted, output is written to `./pulled-confluence` under the current working directory.

## CLI Examples

```bash
pull 123456 -o pulled
pull "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture" -o pulled
pull --space EA --title "Architecture Overview" -o pulled
pull --page-id 123456 --tree --depth 3 --max-pages 100 -o tree
pull "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture" --tree --comments --clean -o pulled-confluence
pull --page-id 123456 --tree --assets all --extract-attachments -o offline
pull --page-id 123456 --tree --comments -o with-comments
pull --page-id 123456 --output-mode full -o full-evidence
pull --page-id 123456 --output-mode simple --bundle -o simple-with-bundle
pull --page-id 123456 --auth bearer --token "$token" --ssl-verify false -o data-center-pat
pull --page-id 123456 --json -o pulled
pull validate pulled
pull guide --json
```

Selector resolution order is: explicit `--page-id`, explicit `--url`, positional URL, positional numeric page ID, then `--space` plus `--title`.

## Output Package

Default `simple` mode:

```text
pulled-confluence/
├── page-title.md
├── page-title.yaml
├── manifest.yaml
├── pages/
│   └── 0001-page-slug/
│       ├── index.md
│       ├── page.json
│       ├── comments.md        # with --comments, only when comments exist
│       └── assets/
└── diagnostics/
    ├── warnings.jsonl
    └── unresolved-links.md
```

`page-title.md` is named from the sanitized root page title and is the recommended first file to give another AI agent. In simple mode it links only the reading/navigation surface: page Markdown paths, assets, sidecars, and explicitly requested agent-facing extras such as `bundle.md` or `chunks.jsonl`. Warning counts are shown, but control files are not linked from the root AI Markdown.

`page-title.yaml` is the machine-readable version of that AI navigation manifest, also named from the sanitized root page title. It intentionally omits noisy provenance and raw API details; use `manifest.yaml` when you need full validation/provenance data. The exact generated filenames are recorded in `manifest.yaml` under `paths.ai_entry` and `paths.ai_manifest`. AI navigation paths are package-root-relative: resolve them against the directory containing the root AI Markdown/YAML file, not the caller's shell working directory.

`manifest.yaml`, `page.json`, and diagnostics files are still written in simple mode so `pull validate <output-dir>` and provenance checks work. `--force` never deletes stale files from earlier runs; use `--clean` when switching modes if you need the physical tree to contain only files from the new mode.

`--output-mode full` adds the full evidence artifacts:

```text
pulled-confluence/
├── bundle.md
└── pages/
    └── 0001-page-slug/
        ├── index.html
        └── source.storage.xml
```

`bundle.md` concatenates pages in page/tree order with stable delimiters for AI use; local links embedded in the bundle are rebased to the package root. `index.html` and `source.storage.xml` are raw/reference artifacts, not the primary navigation surface.

For tree pulls, nested page paths are the default. The manifest always carries stable numeric ordering.

## Auth and Config

Resolution order:

1. CLI flags such as `--base-url`, `--user`, `--token`, `--ssl-verify`.
2. `PULL_*` environment variables.
3. Optional YAML config from `--config`.
4. `CONFPUB_*` compatibility environment variables.

`--ssl-verify` accepts `true`, `false`, or a CA bundle path.

`--auth` accepts `auto`, `bearer`, or `basic`. The default `auto` mode preserves username+token Basic auth when a user and token are both resolved. If you pass `--token` without an explicit `--user`, `pull` treats that as token-only auth and does not pair the token with `PULL_USER` or `CONFPUB_USER` from the environment. This makes Data Center PATs work with `Authorization: Bearer <PAT>` even on machines that still have `CONFPUB_USER` set for other tools.

Use `--auth bearer` to force PAT/Bearer token auth and ignore user fallbacks. Use `--auth basic` when your instance expects username/password or username/API-token Basic auth; it requires a resolved user and token.

If a Data Center pull returns `ERR_AUTH_REQUIRED` while a direct request with `Authorization: Bearer <PAT>` succeeds, retry with `--auth bearer` or pass only `--token` and no explicit `--user`. If Basic auth is intended, pass `--auth basic --user <name> --token <token>`.

When `--ssl-verify false` is used intentionally, `pull` suppresses urllib3 `InsecureRequestWarning` so JSON mode remains parseable on stdout.

## Macro, Asset, and Link Behavior

The extractor uses a macro adapter registry. Current adapters cover panels/admonitions, code/noformat, status, expand, tabs, layout flattening, TOC placeholders, children/page tree links when in scope, include/excerpt placeholders or inline source when available, attachments, displayed files, Jira placeholders, diagram snapshots, dynamic snapshots, HTML macro sanitization, and unknown macro placeholders.

Asset policy defaults to `visible`: rendered images, visible attachment links, file macros, and rendered diagram images where discoverable. `--assets page` downloads all page attachments. `--assets all` includes visible/referenced assets plus all page attachments and macro-listed files where discoverable. `--no-assets` skips downloads and preserves source links with warnings.

Local links to pages in the pulled tree are rewritten to relative `index.md` paths. Downloaded asset links are rewritten to local files. External, mailto, Jira, and out-of-scope Confluence links are preserved. Same-page anchors are normalized where possible; unresolved anchors become diagnostics.

## Comments

Comments are skipped by default. Use `--comments` to fetch page-level and inline comments for each pulled page. When comments exist, `pull` writes a page-local `comments.md` sidecar with agent-readable metadata and Markdown-converted comment bodies.

Comment sidecars are agent-facing reading surfaces: the root AI Markdown page hierarchy links them in simple mode, the page `index.md` header links the local sidecar, and the AI YAML includes the optional comments path and count. If one page's comments cannot be fetched, the pull continues with `W_COMMENTS_FETCH_FAILED` and validation can still pass for the partial package.

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

Validation checks manifest shape, AI navigation manifest paths, relative paths, page files, optional comment sidecars, asset checksums, diagnostics JSONL, Markdown local links, and token-like markers in text outputs.

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

## Releasing

Versions are managed from `src/pull_cli/__init__.py` through Hatch. Use `uv run hatch version patch`, `uv run hatch version minor`, or `uv run hatch version major`; `pull --version`, built package metadata, and GitHub release tags are expected to match. See [RELEASING.md](RELEASING.md) for the PyPI trusted publisher setup and release flow.

## License

MIT. See [LICENSE](LICENSE).
