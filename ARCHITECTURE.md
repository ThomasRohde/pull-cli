# Architecture

`pull-cli` is a read-only Confluence extraction CLI optimized for AI analysis packages.
The public contract is the `pull` command, JSON envelope, output package layout, manifest
schema, warning/error codes, and documented environment variables.

## Data Flow

```text
cli.main
  -> config.resolve_config
  -> clients.build_client
  -> resolver.resolve_target
  -> extractor.extract
  -> writer.write_*
  -> envelope.make_envelope / emit_json
```

The pipeline resolves credentials and target selection first, fetches published page data
through the client protocol, converts rendered content and recoverable storage macros,
writes the package, validates paths/links when requested, and returns a structured
envelope for automation.

## Module Responsibilities

| Module | Responsibility |
| --- | --- |
| `cli.py` | Argument parsing, config assembly, JSON/human output, SSL trust setup, top-level error handling. |
| `config.py` | CLI/env/YAML resolution and coercion for auth, SSL, deployment, and retries. |
| `clients/` | Read-only Confluence access through a small protocol; Cloud uses v2 storage-first page fetches. |
| `resolver.py` | Page selector resolution from page ID, URL, or space/title. |
| `crawler.py` | Single-page or descendant traversal with depth and page-count limits. |
| `extractor.py` | Page fetch orchestration, macro conversion, asset/comment/link extraction, metrics. |
| `macros.py` | Storage macro parser and adapter registry. |
| `assets.py` | Asset discovery and download sidecar generation. |
| `links.py` | Local page/asset link rewriting and unresolved-link diagnostics. |
| `html_normalizer.py` | Rendered HTML cleanup, redaction, and unsafe HTML suppression. |
| `markdown_writer.py` | Rendered HTML to Markdown conversion. |
| `writer.py` | Package files, manifests, AI navigation files, diagnostics, bundle, chunks. |
| `validator.py` | Package structure, manifest, local-link, asset, diagnostics, and secret-pattern validation. |
| `security.py` | Token, URL, metadata, and text redaction helpers. |
| `guide.py` | Machine-readable CLI, schema, stability, and troubleshooting guide. |

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `10` | Validation or argument/configuration error. |
| `20` | Authentication or authorization failure. |
| `30` | Source page/body/tree error. |
| `40` | Strict extraction failure. |
| `50` | I/O, network, timeout, or TLS verification failure. |
| `90` | Internal conversion or unexpected error. |

## Client Boundary

`ConfluenceClient` is the internal protocol used by resolver and extractor. The concrete
clients wrap `atlassian-python-api`, but pull-cli owns the package contract above that
library. `_call` in `clients/data_center.py` is the network chokepoint:

- `_call_once` maps Atlassian, requests, HTTP, TLS, and timeout failures to `PullError`.
- `_call` performs bounded retries for retryable errors.
- `PULL_RETRIES` controls retry count from 0 to 10.
- Atlassian library retries are disabled to avoid multiplied attempts and urllib3 2.x
  unbounded connection retry behavior.
- `Retry-After` is honored for retryable HTTP responses and capped.

Cloud behavior subclasses the Data Center client and uses Cloud v2 page/child/attachment
endpoints first, falling back to v1 helpers when needed.

## Macro Registry

`MacroRegistry` parses storage XML and dispatches known macros to adapters. Current
adapters cover:

- panels/admonitions,
- code and noformat,
- status,
- expand,
- tabs,
- layout flattening,
- table of contents placeholders,
- children/page-tree links,
- include/excerpt recovery,
- attachment listings,
- displayed files,
- Jira placeholders,
- diagrams,
- dynamic macro snapshots,
- sanitized HTML.

Unknown macros use an explicit fallback placeholder, warning, or error depending on the
selected unknown-macro policy.

## Output Package Contract

Simple mode is the default agent-facing package:

```text
pulled-confluence/
├── <root-title>.md
├── <root-title>.yaml
├── manifest.yaml
├── pages/*/index.md
├── pages/*/page.json
├── pages/*/assets/
└── diagnostics/
```

Full mode adds `bundle.md`, page `index.html`, and `source.storage.xml` when available.
Comment sidecars are written only when `--comments` is used and comments exist.

All manifest paths are relative to the package root. Root AI Markdown is the primary
navigation surface. Raw/source artifacts are evidence references, not rewritten
navigation proof.

`chunks.jsonl` is experimental: the chunking strategy and record shape may change in minor
releases.

## JSON Envelope

`--json` and `LLM=true` emit exactly one JSON object on stdout. Progress, diagnostics, and
verbose phase timings go to stderr. The envelope has stable top-level fields:

```text
schema_version, request_id, ok, command, target, result, warnings, errors, metrics
```

Errors are structured `PullError` records with code, message, retryable flag, suggested
action, and details.
