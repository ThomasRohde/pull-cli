# Design Document: `pull` — AI-Optimized Confluence Extraction CLI

**Package:** `pull-cli`  
**Command:** `pull`  
**Status:** Design draft  
**Date:** 2026-06-05  
**Audience:** implementers, maintainers, and AI agents that need reliable Confluence context packages

---

## 1. Executive summary

`pull` is a Python command-line tool for extracting Confluence pages and page hierarchies into a local, AI-consumable evidence package. It is deliberately different from `confpub page pull`.

`confpub` is optimized for high-fidelity round-tripping between Markdown and Confluence. `pull` is optimized for a different job: capturing what a human reader would currently see on the published Confluence page, including rendered macro output, images, diagrams, attachment references, and page-tree relationships, while making that content easy for a large language model to read, cite, chunk, and inspect.

The default output mode is `simple`: root AI Markdown, page Markdown, assets/sidecars, and validation control files. `--output-mode full` writes the broader evidence package:

```text
pulled-confluence/
├── manifest.yaml
├── bundle.md
├── pages/
│   └── 0001-architecture-overview/
│       ├── index.md
│       ├── index.html
│       ├── source.storage.xml
│       ├── page.json
│       ├── comments.md
│       └── assets/
│           ├── system-context.png
│           ├── system-context.gliffy
│           └── system-context.extracted.md
├── assets/
│   └── shared/
└── diagnostics/
    ├── warnings.jsonl
    └── unresolved-links.md
```

The design goal is simple: an AI agent should be able to start from the root AI Markdown file, then inspect linked page, comment, and asset files as needed, without guessing where content came from or whether links/assets/macros were lost. Full mode keeps `manifest.yaml` and `bundle.md` useful for deeper validation, search, and provenance work.

---

## 2. Problem statement

A Confluence page can contain much more than plain text:

- rendered macros;
- tabs, expanders, panels, excerpts, includes, page properties, reports, Jira macros, page trees, children lists, and attachments macros;
- images hosted as page attachments, images referenced from other pages, and external images;
- diagram apps such as Gliffy, draw.io, Mermaid, PlantUML, or app-specific renderers;
- Office/PDF/image attachments that are not text but still matter for understanding;
- links to sibling pages, child pages, anchors, attachments, external sites, Jira issues, and Smart Links.

A round-trip puller usually optimizes for editable source representation. That is not the same as preserving the current reading experience. For AI analysis, the current reading experience matters more than edit fidelity.

`pull` therefore treats Confluence as a rendered knowledge source, not as a publishing target.

---

## 3. Design principles

### 3.1 Rendered-page-first

The authoritative source for AI content is the rendered page as visible to the authenticated user on the current published page. Storage format is still collected, but mostly for provenance, macro recovery, asset discovery, and fallback conversion.

### 3.2 Preserve meaning over authoring syntax

The output should preserve what the reader can understand. For example, a tabbed macro should become serialized sections, not an opaque macro block. A collapsed expand section should be included because a human can open it. A rendered attachment list should become a local file list with working links.

### 3.3 Never silently lose content

Unsupported macros, missing assets, failed downloads, permission-denied pages, and ambiguous links must be recorded in the manifest and diagnostics. A partial result is acceptable; silent omission is not.

### 3.4 Local links must work

Links between pulled pages, links to headings/anchors, and links to downloaded assets should be rewritten to relative local paths. External links should remain external and be marked as external.

### 3.5 AI-friendly without hiding provenance

Markdown should be concise and readable, but every page and asset must retain source metadata: Confluence page ID, version, source URL, retrieval time, content representation used, and warnings.

### 3.6 Deterministic output

Repeated pulls of the same page/version should produce stable paths, stable manifests, stable bundle ordering, and stable diagnostic codes, unless the source content changes.

### 3.7 Read-only and safe by default

`pull` must not mutate Confluence. It must not fetch drafts unless explicitly requested. It must not attempt to bypass page restrictions. It only extracts what the authenticated user can view.

---

## 4. Relationship to `confpub`

`confpub` should remain the publishing and round-trip tool. `pull` should become the AI-ingestion tool.

Relevant existing `confpub` ideas to reuse:

- agent-first CLI design;
- structured JSON envelope on stdout;
- progress and diagnostics on stderr;
- stable error codes;
- deterministic config/auth resolution;
- Cloud and Data Center support;
- existing Confluence API wrapper concepts;
- manifest/lockfile discipline;
- asset discovery and URL rewriting patterns.

Important differences:

| Area | `confpub page pull` | `pull` |
|---|---|---|
| Primary goal | editable Markdown for round-trip | AI evidence package |
| Fidelity target | Confluence storage/edit model | current visible published page |
| Macro handling | reverse-convert to Markdown | render, serialize, extract, annotate |
| Attachments | support page attachments | collect visible/referenced assets, cross-page assets, macro-listed attachments, diagram source where possible |
| Manifest | round-trip publishing manifest | provenance, local links, assets, warnings, extraction metadata |
| Output | Markdown files | Markdown, rendered HTML snapshot, source sidecars, asset sidecars, bundle, manifest, diagnostics |
| Mutation | read-only pull | strictly read-only |

Do **not** implement `pull` as a thin alias over `confpub page pull`. The internal API client and config model can be shared or copied, but the extraction pipeline must be separate.

---

## 5. Product requirements

### 5.1 Package and command

- PyPI package name: `pull-cli`.
- Console command: `pull`.
- Optional secondary console alias: `pull-cli` for discoverability.
- Python package import name: `pull_cli` or `pullconfluence`; prefer `pull_cli` to align with PyPI.

### 5.2 Pull scope

- Default: pull a single page.
- `--tree`: pull the page and its descendant page hierarchy.
- `--depth N`: optional tree depth limit. `--depth 0` equals single page. `--tree` without `--depth` means full descendant tree, subject to `--max-pages`.
- `--max-pages N`: safety cap for large spaces.
- `--include-non-page-children`: optional handling for Cloud whiteboards, databases, embeds, folders, and Smart Links where APIs expose them as children.

### 5.3 Page selection

Support all common selectors:

```bash
pull --url "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture"
pull --page-id 123456
pull --space EA --title "Architecture Overview"
pull 123456
pull "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture"
```

Resolution order:

1. explicit `--page-id`;
2. explicit `--url`;
3. positional URL;
4. positional numeric page ID;
5. `--space` + `--title`.

If multiple pages match a title, return `ERR_VALIDATION_AMBIGUOUS_PAGE` with candidate IDs and URLs.

### 5.4 Output formats

`--output-mode simple` is the default. It writes the root AI Markdown/YAML files, `manifest.yaml`, diagnostics, page `index.md`, page `page.json`, optional `comments.md` sidecars, and assets/sidecars. `--output-mode full` additionally writes `bundle.md`, page `index.html`, and `source.storage.xml` where available. Artifact flags such as `--bundle`, `--html`, and `--source` override the selected mode defaults.

For each page:

- `index.md`: AI-optimized Markdown derived from rendered page and macro adapters.
- `index.html`: cleaned rendered HTML snapshot with local asset links.
- `source.storage.xml`: original storage format or ADF JSON sidecar, when available.
- `page.json`: raw metadata and selected raw API representations.
- `comments.md`: optional page-local comment sidecar written only with `--comments` when comments exist.
- `assets/`: page-local assets.

For the whole pull:

- `manifest.yaml`: canonical manifest.
- `bundle.md`: concatenated AI-readable bundle in page-tree order.
- `diagnostics/warnings.jsonl`: machine-readable warnings.
- `diagnostics/unresolved-links.md`: human-readable unresolved link report.
- Optional `chunks.jsonl`: chunked RAG-ready records.

### 5.5 Link rewriting

- Links to pages included in the pull are rewritten to relative local Markdown paths.
- Links to anchors/headings are rewritten to local Markdown anchors where possible.
- Links to attachments/assets included in the pull are rewritten to relative local file paths.
- Links to Confluence pages outside the pulled scope remain absolute unless `--follow-links` is explicitly set.
- Links to included/excerpted pages are recorded as dependencies, even if not pulled as standalone pages.
- Link rewrites must be recorded in `manifest.yaml`.

### 5.6 Asset and attachment capture

By default, `pull` should capture:

- images visible in rendered page HTML;
- attachments linked from visible page content;
- attachments displayed by an Attachments macro;
- diagram render images visible on the page;
- original diagram/source attachment where discoverable, for example `.gliffy`, `.drawio`, `.svg`, `.mmd`, `.puml`, or JSON source;
- cross-page attachments when the rendered page refers to an attachment hosted on another page and the user has permission to download it.

Options:

```bash
--assets visible        # default: visible/referenced assets only
--assets page           # all attachments on pulled pages
--assets all            # visible/referenced + all page attachments + macro-listed files
--no-assets             # text only; keep original links and warnings
--extract-attachments   # create text sidecars for PDF/DOCX/XLSX/PPTX/SVG where possible
--diagram-sources       # try harder to download original diagram source files
--comments              # fetch page and inline comments into comments.md sidecars
```

### 5.7 Macro conversion

`pull` must have a macro adapter registry. The default behavior is:

1. use rendered output if it contains meaningful visible content;
2. use storage/ADF to recover macro parameters and hidden bodies;
3. serialize interactive/multi-body content into linear Markdown;
4. record unsupported or lossy conversions.

Examples:

- tabs → ordered sections;
- expand/collapse → included section with title;
- include/excerpt → inline rendered content, with source dependency recorded;
- attachments macro → local attachment list;
- page tree/children display → local page links when in scope;
- status macro → text lozenge representation;
- Jira macro → rendered issue table or issue/JQL placeholder with link;
- Gliffy/draw.io/diagram macros → rendered image plus source attachment if found;
- unknown macro → rendered text if any, plus macro placeholder and diagnostic.

### 5.8 Manifest

A YAML manifest is mandatory, even for single-page pulls.

It must contain:

- source Confluence site and deployment type;
- root page information;
- tool version and retrieval timestamp;
- options used;
- every pulled page with local paths;
- every downloaded asset with local paths, media type, checksum, source URL, and references;
- link rewrite records;
- macro conversion records;
- warnings and errors;
- extraction completeness summary.

### 5.9 AI processing

The output must be optimized for AI processing:

- no base64 blobs in Markdown;
- no raw CSS/JS noise in primary Markdown unless content-bearing;
- stable source delimiters in `bundle.md`;
- local links to page and asset files;
- extracted text sidecars for documents and diagrams where feasible;
- compact macro annotations;
- source/version metadata near each page heading;
- optional chunk output for RAG.

---

## 6. Non-goals

- Publishing back to Confluence.
- High-fidelity edit round-trip.
- Reconstructing exact browser CSS/layout.
- Bypassing permissions.
- Fetching drafts by default.
- Mutating pages to simplify extraction.
- Calling an LLM service inside the CLI by default.
- Embedding binary files directly in Markdown.

Optional future plugins may perform LLM-based image captioning or diagram summarization, but the core CLI should not require an LLM provider.

---

## 7. CLI design

### 7.1 Basic commands

Keep the CLI intentionally small. The command itself performs the pull.

```bash
pull PAGE_REF [OPTIONS]
```

Examples:

```bash
# Pull one page by ID into ./pulled
pull 123456 -o pulled

# Pull one page by URL
pull "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture" -o architecture-context

# Pull a hierarchy
pull --page-id 123456 --tree -o architecture-tree

# Pull only three levels
pull --page-id 123456 --tree --depth 3 -o architecture-tree

# Pull with all page attachments and extracted text sidecars
pull --page-id 123456 --tree --assets all --extract-attachments -o architecture-tree

# Generate a RAG chunk file
pull --page-id 123456 --tree --chunks -o architecture-tree
```

### 7.2 Core options

```text
Target selection:
  PAGE_REF                     Page ID or Confluence page URL
  --url TEXT                   Confluence page URL
  --page-id TEXT               Confluence page ID/content ID
  --space TEXT                 Space key, used with --title
  --title TEXT                 Page title, used with --space

Scope:
  --tree                       Pull descendants as a hierarchy
  --depth INTEGER              Limit descendant depth
  --max-pages INTEGER          Stop before accidental large pulls; default 500
  --include-non-page-children  Include metadata for whiteboards/databases/embeds/folders where supported

Output:
  -o, --output PATH            Output directory; default ./pulled-confluence
  --force                      Overwrite existing output directory
  --clean                      Delete stale files in output directory before writing
  --layout nested|flat         Default nested for --tree, flat for single page
  --output-mode simple|full    Default simple; full writes bundle/html/source artifacts
  --bundle / --no-bundle       Write bundle.md; default mode-dependent
  --html / --no-html           Write cleaned rendered HTML; default mode-dependent
  --source / --no-source       Write source.storage.xml or source.adf.json; default mode-dependent
  --chunks                     Write chunks.jsonl
  --comments                   Fetch page and inline comments into comments.md sidecars

Assets:
  --assets visible|page|all    Asset policy; default visible
  --no-assets                  Skip downloads; keep links and warnings
  --extract-attachments        Extract text sidecars where possible
  --diagram-sources            Try to download original diagram source attachments

Rendering/conversion:
  --render-mode hybrid|view|export-view|styled-view|storage
                              Default hybrid
  --macro-policy expand|placeholder|strict
                              Default expand
  --unknown-macro warn|error|ignore
                              Default warn

Links:
  --rewrite-links / --no-rewrite-links
                              Default true
  --follow-includes            Pull include/excerpt source pages as dependencies
  --follow-links same-tree|same-space|none
                              Default none beyond selected tree

Auth/config:
  --base-url TEXT              Confluence base URL
  --user TEXT                  Email/username for Cloud/basic auth
  --token TEXT                 API token or PAT
  --cloud-id TEXT              Optional Cloud ID for api.atlassian.com mode
  --ssl-verify true|false|PATH SSL verification setting
  --config PATH                Optional config file

Behavior:
  --json                       Emit structured JSON envelope; default when LLM=true
  --quiet                      Suppress progress output
  --verbose                    More diagnostics
  --redact-source-urls         Redact source URLs in bundle; keep full URLs in manifest unless --redact-manifest too
  --redact-manifest            Redact source URLs and account IDs in manifest
```

### 7.3 Environment variables

Primary variables:

```text
PULL_URL
PULL_USER
PULL_TOKEN
PULL_CLOUD_ID
PULL_SSL_VERIFY
PULL_OUTPUT
PULL_PROFILE
```

Compatibility fallback:

```text
CONFPUB_URL
CONFPUB_USER
CONFPUB_TOKEN
CONFPUB_SSL_VERIFY
```

Resolution order:

1. CLI flags;
2. `PULL_*` env vars;
3. config file;
4. OS keychain, if configured;
5. `CONFPUB_*` env vars as compatibility fallback.

### 7.4 Stdout/stderr contract

For agent use, stdout should be JSON only when `--json` or `LLM=true` is set:

```json
{
  "schema_version": "1.0",
  "request_id": "req_20260605_141530_7f3a",
  "ok": true,
  "command": "pull",
  "target": {
    "page_id": "123456",
    "url": "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture"
  },
  "result": {
    "output_dir": "pulled-confluence",
    "manifest": "pulled-confluence/manifest.yaml",
    "bundle": "pulled-confluence/bundle.md",
    "pages": 12,
    "assets": 38,
    "warnings": 3
  },
  "warnings": [],
  "errors": [],
  "metrics": {
    "duration_ms": 12782,
    "api_calls": 61
  }
}
```

Progress, download status, and debug logs go to stderr.

---

## 8. Output package design

### 8.1 Single-page output

```text
pulled-confluence/
├── manifest.yaml
├── bundle.md
├── pages/
│   └── 0001-architecture-overview/
│       ├── index.md
│       ├── index.html
│       ├── source.storage.xml
│       ├── page.json
│       ├── comments.md
│       └── assets/
│           ├── diagram.png
│           ├── diagram.gliffy
│           └── requirements.pdf
└── diagnostics/
    ├── warnings.jsonl
    └── unresolved-links.md
```

### 8.2 Tree output

```text
pulled-confluence/
├── manifest.yaml
├── bundle.md
├── pages/
│   ├── 0001-architecture-overview/
│   │   ├── index.md
│   │   ├── index.html
│   │   └── assets/
│   ├── 0002-context/
│   │   └── index.md
│   └── 0003-decisions/
│       └── index.md
├── assets/
│   └── shared/
└── diagnostics/
```

For `--layout nested`, page paths follow the page tree:

```text
pages/
└── architecture-overview/
    ├── index.md
    ├── context/
    │   └── index.md
    └── decisions/
        └── index.md
```

The default should be:

- single page: flat numbered folder;
- tree: nested folder layout;
- always include a stable numeric ordering prefix in manifest, even if path layout is nested.

### 8.3 Page Markdown format

Each `index.md` starts with a compact source header:

```markdown
---
pull_page_id: "123456"
title: "Architecture Overview"
space: "EA"
confluence_version: 42
retrieved_at: "2026-06-05T12:15:30Z"
source_url: "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture"
local_assets: 7
warnings: 1
---

# Architecture Overview

> Source: Confluence page `123456`, version 42, retrieved 2026-06-05T12:15:30Z.

...
```

The front matter is useful for agents, static site tools, and local search.

### 8.4 Bundle format

`bundle.md` concatenates pages in tree order with hard delimiters:

```markdown
# Pulled Confluence Bundle

Source root: Architecture Overview  
Generated: 2026-06-05T12:15:30Z  
Pages: 12  
Assets: 38  
Warnings: 3  
Manifest: ./manifest.yaml

---

<!-- pull:page-start id="123456" path="pages/0001-architecture-overview/index.md" -->

# Architecture Overview

Source: https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture  
Confluence version: 42

...

<!-- pull:page-end id="123456" -->
```

`bundle.md` should avoid embedding huge tables or extracted attachment text by default if it would explode token count. Instead, it should link to sidecar files and include concise summaries such as:

```markdown
[Attachment: requirements.pdf](pages/0001-architecture-overview/assets/requirements.pdf)  
Extracted text: [requirements.extracted.md](pages/0001-architecture-overview/assets/requirements.extracted.md)
```

Optional `--bundle-include-extracted` may inline extracted text sidecars.

---

## 9. Manifest schema

### 9.1 Example

```yaml
schema_version: "1.0"
generated_at: "2026-06-05T12:15:30Z"
tool:
  name: pull
  package: pull-cli
  version: "0.1.0"
  command:
    - pull
    - "123456"
    - "--tree"
    - "--assets"
    - "visible"
source:
  deployment: cloud          # cloud | data_center | server
  base_url: "https://example.atlassian.net/wiki"
  root_page_id: "123456"
  root_title: "Architecture Overview"
  root_url: "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture"
  space_key: EA
  content_state: current_published
options:
  tree: true
  depth: null
  max_pages: 500
  render_mode: hybrid
  asset_policy: visible
  extract_attachments: false
  rewrite_links: true
summary:
  pages_total: 12
  pages_pulled: 12
  assets_downloaded: 38
  links_rewritten: 91
  links_external: 27
  links_unresolved: 2
  macros_converted: 49
  macros_unsupported: 1
  warnings: 3
pages:
  - id: "123456"
    title: "Architecture Overview"
    space_key: EA
    version: 42
    status: current
    web_url: "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture"
    parent_id: null
    depth: 0
    order: 1
    paths:
      markdown: "pages/0001-architecture-overview/index.md"
      html: "pages/0001-architecture-overview/index.html"
      source: "pages/0001-architecture-overview/source.storage.xml"
      metadata: "pages/0001-architecture-overview/page.json"
    children:
      - "123457"
      - "123458"
    assets:
      - asset_id: "att-98765-v3"
        local_path: "pages/0001-architecture-overview/assets/system-context.png"
        role: rendered_diagram
    links:
      - original: "/wiki/spaces/EA/pages/123457/Context"
        rewritten: "../0002-context/index.md"
        kind: page
        target_page_id: "123457"
        status: rewritten
      - original: "https://vendor.example/doc"
        rewritten: "https://vendor.example/doc"
        kind: external
        status: preserved
    macros:
      - macro_id: "macro-1"
        name: "tabs"
        adapter: "tabs.serialize.v1"
        source: rendered_plus_storage
        status: converted
        output_anchor: "tabs-deployment-options"
      - macro_id: "macro-2"
        name: "gliffy"
        adapter: "diagram.gliffy.v1"
        status: converted_with_warning
        assets:
          - "att-98765-v3"
        warnings:
          - "W_ASSET_DIAGRAM_SOURCE_NOT_FOUND"
    warnings:
      - code: "W_LINK_UNRESOLVED"
        message: "Could not resolve anchor #old-heading after heading normalization"
assets:
  - asset_id: "att-98765-v3"
    source:
      page_id: "123456"
      attachment_id: "98765"
      version: 3
      download_url: "https://example.atlassian.net/wiki/download/attachments/123456/system-context.png"
      web_url: "https://example.atlassian.net/wiki/pages/viewpageattachments.action?pageId=123456"
    filename: "system-context.png"
    media_type: "image/png"
    size_bytes: 238910
    sha256: "sha256:..."
    local_path: "pages/0001-architecture-overview/assets/system-context.png"
    extracted_text_path: null
    referenced_by:
      - page_id: "123456"
        context: "image"
        local_page_path: "pages/0001-architecture-overview/index.md"
warnings:
  - code: "W_MACRO_UNKNOWN"
    severity: warning
    page_id: "123456"
    macro_name: "vendor-roadmap"
    message: "Unknown macro rendered no text; placeholder inserted."
```

### 9.2 Required invariants

- All local paths are relative to the output root.
- Every local path referenced by the manifest must exist unless its record status is `missing`, `skipped`, or `failed`.
- Every page has exactly one Markdown path.
- Every downloaded asset has a checksum.
- Every warning has a stable code.
- Manifest records the source Confluence version for each page.
- Manifest records the extraction representation used for each page.

### 9.3 Validation command

Optional but useful:

```bash
pull validate pulled-confluence/manifest.yaml
```

Validation checks:

- all manifest paths exist;
- all rewritten local links resolve;
- all assets have checksums;
- all page IDs are unique;
- all child page references exist or are explicitly marked skipped;
- no unrecorded failed macro conversions.

---

## 10. Extraction pipeline

```text
Resolve target
  ↓
Detect deployment type and API strategy
  ↓
Build page scope: single page or tree
  ↓
Fetch page metadata + rendered body + storage/ADF body
  ↓
Normalize rendered HTML
  ↓
Parse storage/ADF for macro and asset hints
  ↓
Discover visible assets, attachments, diagrams, and cross-page references
  ↓
Download assets and optional source attachments
  ↓
Run macro adapters
  ↓
Convert normalized rendered content to Markdown
  ↓
Rewrite local links
  ↓
Write page files
  ↓
Write bundle, manifest, diagnostics
  ↓
Validate output package
```

### 10.1 Target resolution

Input URL parser must handle:

- Cloud URLs: `/wiki/spaces/{space}/pages/{id}/{title}`;
- older view URLs: `/wiki/pages/viewpage.action?pageId={id}`;
- Data Center context paths: `/confluence/pages/viewpage.action?pageId={id}`;
- short/tiny links where possible by following redirects with authentication;
- title+space lookup.

### 10.2 Deployment detection

Heuristics:

- `*.atlassian.net/wiki` → Cloud.
- Cloud ID configured → Cloud API gateway support.
- otherwise call server info endpoint and detect Server/Data Center.
- allow explicit `--deployment cloud|data-center|server` override.

### 10.3 Body retrieval strategy

Use a hybrid strategy:

1. Fetch metadata and the most useful rendered body representation available.
2. Fetch storage or ADF source representation for macro/asset recovery.
3. When the API body representation is inadequate, use content body conversion endpoints where available.

Recommended strategy by deployment:

| Deployment | Rendered body | Source body | Notes |
|---|---|---|---|
| Confluence Cloud v2 | `GET /wiki/api/v2/pages/{id}?body-format=...` | `storage` or `atlas_doc_format` | v2 has page, attachment, children, descendant APIs. |
| Confluence Cloud v1 | `expand=body.view`, `body.export_view`, or async contentbody convert | `body.storage` | Needed for some conversions and compatibility. |
| Data Center / Server | `/rest/api/content/{id}?expand=body.view,body.export_view,body.storage,version,space` | `body.storage` | Exact support varies by version. |

The implementation should not assume one representation is always correct. It should store all retrieved representations and record which one was used for Markdown.

### 10.4 Render mode definitions

- `hybrid` default: rendered body drives visible content; storage/ADF fills macro bodies, tabs, hidden expanders, asset metadata, and unknown macro placeholders.
- `view`: use normal Confluence rendered view where available.
- `export-view`: use export-oriented rendered HTML when it better expands macros or assets.
- `styled-view`: use styled view where available for richer rendered HTML snapshots.
- `storage`: mostly diagnostic; not recommended for AI output except when rendered APIs fail.

### 10.5 Page scope building

Single page:

- one page only;
- include visible assets and dependencies;
- do not pull child pages unless linked and `--follow-links` allows it.

Tree:

- retrieve descendants top-to-bottom;
- preserve tree order;
- fetch each page independently;
- record skipped pages with reason if permissions, status, type, or cap prevents retrieval;
- support depth and max page limits.

### 10.6 Concurrency and rate limits

- Use bounded async HTTP, e.g., default concurrency 4.
- Separate page fetch concurrency and asset download concurrency.
- Respect `Retry-After`.
- Exponential backoff on 429, 502, 503, 504.
- Persist partial state only after file writes are complete.
- Use temporary files and atomic rename for downloads.

---

## 11. HTML normalization

The rendered HTML should be cleaned before Markdown conversion.

Remove or downrank:

- Confluence UI chrome;
- script tags;
- style tags, unless preserving `index.html` needs them;
- hidden editor artifacts;
- empty wrappers;
- duplicate anchor spans;
- tracking attributes;
- Atlassian-specific classes not useful for AI.

Preserve:

- heading hierarchy;
- table structure;
- lists and task lists;
- link targets before rewriting;
- image alt/caption/title;
- panel/admonition labels;
- status text;
- macro boundaries when detectable;
- data attributes required for asset resolution.

Add structural markers where useful:

```html
<section data-pull-macro="tabs" data-pull-macro-id="..."></section>
```

These markers help adapters produce deterministic Markdown.

---

## 12. Markdown conversion policy

Use Markdown as the primary AI-readable text format, not as a perfect authoring format.

Rules:

- Use ATX headings (`#`, `##`, `###`).
- Convert Confluence panels/admonitions to blockquotes with labels.
- Convert status lozenges to `[STATUS: Done]`.
- Convert task lists to GitHub-style task lists where possible.
- Preserve tables as Markdown if compact; use HTML table fallback for complex rowspan/colspan tables.
- Include image Markdown with local path and alt text.
- Include captions immediately after images.
- Put local attachment links on their own lines.
- Serialize interactive content in reading order.
- Avoid raw HTML in `index.md` unless Markdown would lose meaning.

Example for tabs:

```markdown
## Deployment options

The original page used a tabbed macro. The tabs are serialized below in page order.

### Tab: Kubernetes

...

### Tab: VM deployment

...

### Tab: SaaS

...
```

Example for expand:

```markdown
## Troubleshooting

### Expand: Advanced diagnostics

This content was inside a collapsible section on the original page.

...
```

---

## 13. Macro adapter registry

### 13.1 Adapter interface

```python
class MacroAdapter(Protocol):
    names: set[str]
    priority: int

    def can_handle(self, macro: MacroNode, context: ConversionContext) -> bool: ...

    def convert(self, macro: MacroNode, context: ConversionContext) -> MacroConversionResult: ...
```

`MacroConversionResult`:

```python
class MacroConversionResult(BaseModel):
    status: Literal["converted", "converted_with_warning", "placeholder", "failed"]
    markdown: str
    html: str | None = None
    assets: list[str] = []
    links: list[LinkRecord] = []
    dependencies: list[DependencyRecord] = []
    warnings: list[WarningRecord] = []
    provenance: dict[str, Any] = {}
```

### 13.2 Macro node model

```python
class MacroNode(BaseModel):
    macro_id: str | None
    name: str
    parameters: dict[str, str]
    body_type: Literal["none", "plain-text", "rich-text", "multi-rich-text", "unknown"]
    storage_xml: str | None
    adf_json: dict | None
    rendered_html: str | None
    source_page_id: str
    ordinal: int
```

### 13.3 Built-in macro adapters

| Macro family | Examples | Conversion strategy |
|---|---|---|
| Text formatting | info, note, tip, warning, panel | Markdown blockquote/admonition with title. |
| Code/noformat | code, noformat | fenced code block with language when known. |
| Status | status | `[STATUS: text / color]`. |
| Expand | expand | include body as titled section. |
| Tabs | tabs, tab, tab-group, ui-tabs, ui-tab, deck/card variants | serialize every tab body in order. |
| Layout | section, column, page layout | flatten to logical reading order with section labels where needed. |
| TOC | toc | generate local Markdown TOC from headings or omit with note. |
| Children/page tree | children, pagetree | local tree/list with rewritten links when in scope. |
| Include/excerpt | include, excerpt, excerpt-include, multi-excerpt variants | inline rendered content, record source page dependency. |
| Attachments | attachments | write local attachment list and download files per policy. |
| Office/PDF/View file | view-file, office-word, office-excel, office-powerpoint, pdf | link local file, optional extracted text sidecar. |
| Images/gallery | gallery, ac:image | local image links with captions. |
| Jira | jira, jiraissues, jira-chart | use rendered table/chart if present; otherwise record JQL/key and source link. |
| Drawings/diagrams | gliffy, drawio, mermaid, plantuml | rendered image + source file where discoverable + optional extracted text. |
| Search/dynamic | contentbylabel, livesearch, recently-updated, content-report-table | serialize current rendered snapshot; record query/filter parameters. |
| HTML | html, html-macro, macro-html | preserve visible text; write inert HTML sidecar if useful; strip executable scripts from Markdown. |
| Unknown | any other macro | rendered text if available; otherwise placeholder with parameters and warning. |

### 13.4 Tabs and multi-body macros

Tabs are a first-class use case. The adapter must support several patterns:

1. nested storage macros, e.g., `ui-tabs` containing `ui-tab` children;
2. Composition/Content Formatting macros, e.g., Tab Group + Tab, Deck of Cards + Card;
3. Cloud editor multi-bodied macros using ADF multi-body structures;
4. rendered HTML where only the active tab appears in the rendered body;
5. rendered HTML where all tabs are present but hidden by CSS.

Required behavior:

- extract every tab title;
- extract every tab body;
- preserve tab order;
- include hidden tab bodies, because a human can click the tabs;
- record if only the active tab was available and others could not be recovered.

Output pattern:

```markdown
### Tabs: Supported platforms

The original Confluence page displayed this as tabs. The tabs are serialized below.

#### Tab 1: Cloud

...

#### Tab 2: Data Center

...
```

### 13.5 Dynamic macros

Dynamic macros must be serialized as a snapshot. Example:

```markdown
### Content by label: architecture

This section was generated dynamically by a Confluence macro at pull time.

- [Reference Architecture](../0004-reference-architecture/index.md)
- [Deployment Patterns](../0005-deployment-patterns/index.md)
```

Manifest record:

```yaml
macros:
  - name: contentbylabel
    status: converted
    snapshot: true
    parameters:
      label: architecture
    retrieved_at: "2026-06-05T12:15:30Z"
```

---

## 14. Asset handling design

### 14.1 Discovery sources

Asset discovery must combine:

- rendered HTML `img[src]`, `a[href]`, `object[data]`, `iframe[src]`, and file preview markup;
- Confluence storage image and attachment references;
- page attachment API results;
- macro parameters that name pages/files;
- attachment lists rendered by macros;
- cross-page attachment URLs;
- diagram macro naming conventions.

### 14.2 Asset roles

Every asset gets a role:

```text
visible_image
linked_attachment
macro_attachment
rendered_diagram
diagram_source
page_attachment
external_image
thumbnail
extracted_text
unknown
```

The role matters because it tells an AI agent how to use the asset.

### 14.3 Download strategy

- Download visible images and linked files by default.
- For each asset, prefer authenticated download endpoints over public URLs.
- Follow redirects safely.
- Deduplicate by checksum but preserve page-local aliases where helpful.
- Store large files locally but do not inline them into Markdown.
- Record failed downloads with stable warnings.

### 14.4 Cross-page attachments

Confluence pages may show images or attachments stored on another page. A page-local attachment list alone is insufficient. `pull` must parse the actual rendered/source URLs and resolve the owning page/attachment when possible.

If a referenced attachment is hosted on a page outside the pulled tree:

- download it if the current user has permission and asset policy allows it;
- record `source.page_id` as external to the pulled page set;
- do not pull the owning page unless `--follow-links` or `--follow-includes` says so.

### 14.5 Attachment text extraction

When `--extract-attachments` is enabled, create sidecars:

```text
requirements.pdf
requirements.extracted.md
```

Recommended extractors:

| Type | Extractor | Notes |
|---|---|---|
| PDF | `pypdf` or `pymupdf` optional extra | Text only; no OCR by default. |
| DOCX | `python-docx` | Headings, paragraphs, tables. |
| PPTX | `python-pptx` | Slide text and speaker notes where available. |
| XLSX | `openpyxl` | Sheet names and cell tables; avoid massive sheets unless configured. |
| SVG | XML parser | Extract text nodes, titles, descriptions. |
| HTML | BeautifulSoup | Sanitize, convert visible text. |
| TXT/CSV/JSON/YAML/XML | direct read | Size limit and encoding detection. |

No OCR by default. OCR is expensive, error-prone, and security-sensitive. Provide a future plugin interface for local OCR if needed.

### 14.6 Diagram handling

#### Gliffy

For Gliffy diagrams:

- download the rendered image visible in the page;
- search page attachments for likely original diagram sources;
- preserve `.gliffy`, `.json`, `.svg`, `.png`, and related metadata files where discoverable;
- create a diagram sidecar:

```markdown
# Diagram: System Context

Source page: Architecture Overview  
Rendered image: system-context.png  
Source file: system-context.gliffy  
Alt text: System Context  
Caption: System context diagram

## Text discovered in diagram source

...
```

#### draw.io

- download rendered image;
- download `.drawio`, `.xml`, `.svg`, or embedded source where discoverable;
- extract text from XML/SVG source where possible.

#### Mermaid/PlantUML

- prefer source code from storage/macro body;
- write source file sidecar, e.g., `sequence.mmd` or `deployment.puml`;
- include rendered image if visible.

### 14.7 External images

External images are downloaded only when:

- asset policy allows external downloads; and
- the URL is safe and reachable; and
- `--download-external-assets` is set.

Default behavior: keep external URL, record external asset reference, no download.

---

## 15. Link rewriting design

### 15.1 Link model

```python
class LinkRecord(BaseModel):
    original: str
    normalized: str
    kind: Literal["page", "anchor", "attachment", "asset", "external", "mailto", "jira", "unknown"]
    source_page_id: str
    target_page_id: str | None = None
    target_asset_id: str | None = None
    rewritten: str | None = None
    status: Literal["rewritten", "preserved", "unresolved", "skipped"]
    warning: str | None = None
```

### 15.2 Page links

Input variants:

- absolute page URLs;
- relative `/wiki/...` URLs;
- tiny links;
- `/pages/viewpage.action?pageId=...`;
- storage links with page IDs or content titles;
- anchor links;
- links to pages outside the tree.

Rewrite rule:

```text
if target_page_id in pulled_pages:
    link = relative_path(source_page.index.md, target_page.index.md)
elif same-page anchor:
    link = "#normalized-anchor"
else:
    keep absolute URL and mark external/preserved
```

### 15.3 Anchor links

Anchor normalization must handle:

- Confluence generated heading anchors;
- explicit anchor macros;
- case/space/punctuation normalization;
- duplicate headings;
- non-ASCII characters.

If the target cannot be resolved, preserve the original anchor and record `W_LINK_ANCHOR_UNRESOLVED`.

### 15.4 Attachment links

Rewrite to local downloaded asset paths when downloaded. If the asset was skipped by policy, keep original URL and record policy skip.

### 15.5 Link manifest requirements

All rewritten links must be traceable:

- original URL/ref;
- normalized ref;
- source page;
- target page or asset;
- final local path;
- status.

---

## 16. API strategy

### 16.1 Cloud APIs

Use Cloud REST API v2 for page metadata, page body retrieval, attachments, children, and descendants when available.

Use Cloud REST API v1 content/body conversion where it produces better rendered bodies or when v2 body representation is insufficient.

Important Cloud behaviors to design around:

- v2 page APIs expose `body-format` parameters for page retrieval.
- v2 attachment APIs provide attachment metadata and download links.
- v2 descendants APIs provide tree traversal with pagination and depth.
- content body conversion can be asynchronous and conversion results are time-limited.
- app macros may not render identically across storage, view, export view, and styled view.

### 16.2 Data Center / Server APIs

Use Data Center/Server REST API:

```text
GET /rest/api/content/{id}?expand=body.view,body.export_view,body.storage,version,space,metadata.labels
GET /rest/api/content/{id}/child/page
GET /rest/api/content/{id}/descendant/page
GET /rest/api/content/{id}/child/attachment
```

Support PAT bearer auth for modern Data Center, basic auth where required, and custom context paths such as `/confluence`.

### 16.3 API abstraction

```python
class ConfluenceClient(Protocol):
    async def get_page(self, page_id: str, body_formats: list[str]) -> PageRecord: ...
    async def find_page(self, space: str, title: str) -> list[PageSummary]: ...
    async def get_descendants(self, page_id: str, depth: int | None) -> list[PageSummary]: ...
    async def get_children(self, page_id: str) -> list[ChildSummary]: ...
    async def list_attachments(self, page_id: str) -> list[AttachmentRecord]: ...
    async def download_attachment(self, attachment: AttachmentRecord) -> bytes: ...
    async def convert_body(self, body: str, from_format: str, to_format: str, context_page_id: str) -> str: ...
```

Implementations:

```text
pull_cli.clients.cloud_v2.CloudV2Client
pull_cli.clients.cloud_v1.CloudV1Client
pull_cli.clients.data_center.DataCenterClient
pull_cli.clients.hybrid.HybridConfluenceClient
```

---

## 17. Internal architecture

```text
pull_cli/
├── __init__.py
├── cli.py
├── envelope.py
├── errors.py
├── config.py
├── auth.py
├── clients/
│   ├── base.py
│   ├── cloud_v2.py
│   ├── cloud_v1.py
│   ├── data_center.py
│   └── hybrid.py
├── resolver.py
├── crawler.py
├── fetcher.py
├── representations.py
├── html_normalizer.py
├── markdown_writer.py
├── storage_parser.py
├── adf_parser.py
├── macro_registry.py
├── macro_adapters/
│   ├── base.py
│   ├── panels.py
│   ├── tabs.py
│   ├── expand.py
│   ├── includes.py
│   ├── attachments.py
│   ├── diagrams.py
│   ├── jira.py
│   ├── dynamic.py
│   ├── html.py
│   └── unknown.py
├── assets.py
├── links.py
├── extractor/
│   ├── base.py
│   ├── pdf.py
│   ├── office.py
│   ├── svg.py
│   └── text.py
├── manifest.py
├── bundle.py
├── writer.py
├── validator.py
├── diagnostics.py
└── tests/
```

### 17.1 Main data models

```python
class PullPlan(BaseModel):
    root_page_id: str
    pages: list[PageSummary]
    options: PullOptions

class PageArtifact(BaseModel):
    page: PageRecord
    rendered_html: str
    normalized_html: str
    markdown: str
    assets: list[AssetRecord]
    links: list[LinkRecord]
    macros: list[MacroRecord]
    warnings: list[WarningRecord]

class AssetRecord(BaseModel):
    asset_id: str
    source_page_id: str | None
    attachment_id: str | None
    filename: str
    media_type: str | None
    local_path: str
    sha256: str | None
    role: str
    referenced_by: list[AssetReference]
```

### 17.2 Suggested dependencies

Core:

- `typer` for CLI;
- `httpx` for async HTTP;
- `pydantic` v2 for models;
- `ruamel.yaml` or `PyYAML` for manifest output;
- `beautifulsoup4` + `lxml` for HTML parsing;
- `markdownify` or custom HTML→Markdown converter;
- `tenacity` for retries;
- `orjson` for JSON envelope;
- `platformdirs` for config/cache locations;
- `keyring` optional for credential storage.

Optional extras:

```toml
[project.optional-dependencies]
extract = ["pypdf", "python-docx", "python-pptx", "openpyxl"]
svg = ["defusedxml"]
dev = ["pytest", "pytest-asyncio", "respx", "ruff", "mypy", "types-PyYAML"]
```

---

## 18. Error and warning codes

### 18.1 Exit codes

```text
0   Success
10  Validation/input error
20  Auth/permission error
30  Source content unavailable or ambiguous
40  Partial extraction with strict mode failure
50  I/O or network error
90  Internal error
```

### 18.2 Error codes

```text
ERR_VALIDATION_REQUIRED
ERR_VALIDATION_AMBIGUOUS_PAGE
ERR_VALIDATION_INVALID_URL
ERR_VALIDATION_OUTPUT_EXISTS
ERR_AUTH_REQUIRED
ERR_AUTH_FORBIDDEN
ERR_AUTH_EXPIRED
ERR_SOURCE_PAGE_NOT_FOUND
ERR_SOURCE_BODY_UNAVAILABLE
ERR_SOURCE_TREE_TOO_LARGE
ERR_IO_CONNECTION
ERR_IO_TIMEOUT
ERR_IO_WRITE_FAILED
ERR_INTERNAL_CONVERSION
ERR_INTERNAL_API_RESPONSE
```

### 18.3 Warning codes

```text
W_MACRO_UNKNOWN
W_MACRO_PARTIAL
W_MACRO_RENDER_EMPTY
W_ASSET_DOWNLOAD_FAILED
W_ASSET_SKIPPED_BY_POLICY
W_ASSET_DIAGRAM_SOURCE_NOT_FOUND
W_ATTACHMENT_TEXT_EXTRACTION_FAILED
W_LINK_UNRESOLVED
W_LINK_ANCHOR_UNRESOLVED
W_LINK_EXTERNAL_PRESERVED
W_PAGE_SKIPPED_PERMISSION
W_PAGE_SKIPPED_LIMIT
W_BODY_REPRESENTATION_FALLBACK
W_DYNAMIC_MACRO_SNAPSHOT
W_SANITIZED_HTML
```

Warnings should be both:

- inline in `manifest.yaml`; and
- streamed as JSON lines in `diagnostics/warnings.jsonl`.

---

## 19. Security and compliance considerations

This matters in an enterprise/bank context.

### 19.1 Credentials

- Never write tokens to manifest, page metadata, logs, or diagnostics.
- Redact `Authorization`, cookies, signed download URLs, and temporary media URLs.
- Prefer PAT/API token from env vars, config, or keyring.
- Support `--ssl-verify PATH` for enterprise CA bundles.

### 19.2 Data minimization

Default to current visible page content and visible/referenced assets, not every attachment ever uploaded to a page. `--assets all` is explicit.

### 19.3 Source URL redaction

Provide two redaction levels:

- `--redact-source-urls`: remove source URLs from `bundle.md` and page Markdown, keep page IDs and titles.
- `--redact-manifest`: additionally redact source URLs/account IDs in manifest.

### 19.4 Executable content

- Do not execute scripts from Confluence pages.
- Strip scripts from AI Markdown.
- Preserve HTML macro content in inert sidecar files only.
- Never load external iframes during extraction.

### 19.5 Permissions

- Only retrieve content visible to the authenticated principal.
- Record `403` as skipped/permission warning.
- Do not retry with alternative credentials automatically.

### 19.6 Sensitive content flagging

Optional future feature:

```bash
--classify-sensitive
```

This could run local pattern checks for secrets, API keys, personal data, or banking-specific classification markers before writing a bundle for AI use. Keep out of MVP unless required.

---

## 20. Testing strategy

### 20.1 Unit tests

Create fixture-based tests for:

- URL parsing;
- page ID/title resolution;
- Cloud/DC response parsing;
- HTML normalization;
- storage macro parsing;
- ADF macro parsing;
- each macro adapter;
- link rewriting;
- asset discovery;
- manifest validation.

### 20.2 Golden files

Maintain golden fixtures:

```text
tests/fixtures/pages/
├── simple-page/
├── page-with-images/
├── page-with-cross-page-attachment/
├── page-with-tabs/
├── page-with-expand/
├── page-with-include-excerpt/
├── page-with-gliffy/
├── page-with-attachments-macro/
├── page-with-jira-macro/
└── page-with-unknown-macro/
```

Each fixture should include:

- source storage/ADF;
- rendered HTML;
- expected `index.md`;
- expected manifest fragment;
- expected warnings.

### 20.3 Integration tests

Against a test Confluence instance:

- Cloud single page;
- Cloud tree;
- Data Center single page;
- Data Center tree;
- restricted child page;
- rate limit/backoff simulation;
- large attachment handling.

### 20.4 Acceptance tests

A pull passes acceptance when:

- all pulled pages have Markdown output;
- `manifest.yaml` validates;
- all local asset paths in Markdown exist;
- all local page links resolve;
- unsupported/lossy macros are recorded;
- the bundle can be consumed without Confluence access except for external links;
- no credentials appear in files.

---

## 21. MVP proposal

### MVP scope

Implement enough to make the tool useful quickly:

1. Package skeleton and CLI.
2. Config/auth compatible with `CONFPUB_*` fallback.
3. Cloud and Data Center page fetch by ID/URL/title.
4. Single-page extraction.
5. Tree extraction for pages only.
6. Rendered HTML + storage retrieval.
7. Markdown conversion.
8. Visible image and linked attachment downloads.
9. Local link rewriting for pages in tree and assets.
10. Mandatory manifest.
11. `bundle.md`.
12. Macro adapters for: panels, status, expand, tabs, attachments, include/excerpt, diagrams as image, unknown macro fallback.
13. Stable warnings and JSON envelope.

### Out of MVP but next priority

- Office/PDF text extraction.
- `chunks.jsonl`.
- Jira-specific enrichment.
- draw.io/Gliffy source recovery beyond obvious attachments.
- Cloud non-page children.
- Sensitive content classification.
- Local static HTML browser.

---

## 22. Implementation plan

### Phase 0 — Scaffold

- Create `pull-cli` project with `uv`/`hatchling`.
- Add `pull` and `pull-cli` console scripts.
- Add Typer CLI, Pydantic models, JSON envelope, errors.
- Add config/auth resolution.
- Add basic tests and CI.

### Phase 1 — Single page core

- Resolve page ID from ID/URL/title.
- Fetch metadata, rendered body, storage body.
- Normalize HTML.
- Convert to Markdown.
- Write page files, manifest, and bundle.
- Add `--json` envelope.

### Phase 2 — Assets and link rewriting

- Discover rendered images and links.
- List page attachments.
- Download visible assets.
- Rewrite local asset links.
- Rewrite same-page and same-tree links.
- Add manifest asset/link records.

### Phase 3 — Tree support

- Add descendants/children traversal.
- Preserve hierarchy and order.
- Add `--tree`, `--depth`, `--max-pages`.
- Rewrite page links within tree.
- Add skipped-page records.

### Phase 4 — Macro adapters

- Implement macro registry.
- Parse storage/ADF macro nodes.
- Implement panels/status/code/expand/tabs/attachments/include/excerpt/diagram/unknown adapters.
- Add golden tests.

### Phase 5 — Attachment extraction and diagrams

- Add optional `extract` extra.
- PDF/DOCX/PPTX/XLSX/SVG sidecars.
- Improve Gliffy/draw.io/Mermaid/PlantUML handling.
- Add diagram sidecar Markdown.

### Phase 6 — Validation and hardening

- Add `pull validate`.
- Add strict mode.
- Add redaction options.
- Add rate-limit/backoff tests.
- Add large-tree and partial-failure tests.

---

## 23. Example user workflows

### 23.1 Give an AI a faithful single-page context package

```bash
pull --page-id 123456 -o context
```

Then give the AI:

```text
Read context/manifest.yaml first, then context/bundle.md. Inspect linked assets only when needed.
```

### 23.2 Pull an architecture tree for analysis

```bash
pull --url "https://example.atlassian.net/wiki/spaces/EA/pages/123456/Architecture" \
  --tree \
  --assets visible \
  --diagram-sources \
  -o architecture-pull
```

### 23.3 Pull everything needed for offline review

```bash
pull 123456 \
  --tree \
  --assets all \
  --extract-attachments \
  --diagram-sources \
  --chunks \
  -o architecture-offline
```

### 23.4 Strict CI check for extraction quality

```bash
pull 123456 --tree --unknown-macro error --max-pages 100 -o out --json
pull validate out/manifest.yaml
```

---

## 24. Design choices that should be explicit

### 24.1 Why rendered-first?

A human reader sees macro output, not storage XML. For AI analysis, the visible rendered page is usually the best representation of intent. Storage is still necessary because rendered APIs may hide inactive tabs, macro bodies, attachment metadata, and source diagram hints.

### 24.2 Why not just export HTML?

Raw Confluence HTML is noisy, link-heavy, and often not self-contained. It also lacks a clean inventory of local files, page relationships, macro losses, and provenance. `pull` needs to produce a structured evidence package, not merely a browser export.

### 24.3 Why include source sidecars?

When a macro conversion is disputed, source sidecars allow debugging without re-fetching the page. They also help agents and developers recover content when rendered output is incomplete.

### 24.4 Why no OCR by default?

OCR can be slow, inaccurate, and unsuitable for sensitive enterprise data. The tool should extract text from text-bearing formats and preserve images/diagrams for separate inspection.

### 24.5 Why a mandatory manifest?

AI agents need to know what they are reading, where it came from, which assets exist, what failed, and how links were rewritten. Markdown alone cannot reliably carry that metadata.

---

## 25. Open questions

1. Should `pull` live in the same GitHub organization/repo as `confpub`, or a separate repo?
2. Should `pull` share code with `confpub` through a small common package, or copy the client/config patterns initially?
3. Should JSON envelope be default for all invocations, or only with `--json`/`LLM=true`?
4. Should `bundle.md` inline extracted attachment text by default when small?
5. Should source storage/ADF sidecars be default-on in enterprise contexts, or only with `--source`?
6. Which diagram apps are first-class in the MVP: Gliffy only, or Gliffy + draw.io + Mermaid?
7. Should page comments be supported as an optional `--comments` mode?
8. Should labels, page properties, and version history be included by default in `page.json` only, or summarized in Markdown too?

Recommended answers for MVP:

1. Separate repo, but reuse design conventions from `confpub`.
2. Copy patterns first; extract shared client later if duplication hurts.
3. Default human output in terminal, JSON when `--json` or `LLM=true`.
4. Do not inline extracted attachment text by default; link sidecars.
5. Default `--source` on for debuggability; allow `--no-source`.
6. Gliffy + generic diagram image support in MVP; draw.io/Mermaid next.
7. Exclude comments by default; support opt-in `--comments` sidecars.
8. Include full metadata in `page.json`; summarize only source/version in Markdown.

---

## 26. Reference notes checked during design

- Existing `confpub` repository: https://github.com/ThomasRohde/confpub-cli
- Confluence Cloud REST API v2 documentation: https://developer.atlassian.com/cloud/confluence/rest/v2/
- Confluence Cloud v2 Page API: https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/
- Confluence Cloud v2 Attachment API: https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-attachment/
- Confluence Cloud v2 Children API: https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-children/
- Confluence Cloud v2 Descendants API: https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-descendants/
- Confluence Cloud v1 Content Body conversion API: https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content-body/
- Confluence Data Center REST API: https://developer.atlassian.com/server/confluence/rest/
- Confluence Storage Format: https://confluence.atlassian.com/doc/confluence-storage-format-790796544.html
- Excerpt Include Macro: https://confluence.atlassian.com/doc/excerpt-include-macro-148067.html
- Attachments Macro: https://confluence.atlassian.com/conf95/attachments-macro-1573750558.html
- Gliffy Diagrams for Confluence marketplace entry: https://marketplace.atlassian.com/apps/254/gliffy-diagrams-for-confluence
- Atlassian developer RFC on multi-bodied macros: https://community.developer.atlassian.com/t/rfc-31-introducing-multi-bodied-macros-for-content-formatting-in-confluence-cloud/74219
- Adaptavist/Mosaic tabs documentation: https://docs.adaptavist.com/cfm4cs/latest/mosaic-macros/tabs
- Appfire Composition Tabs migration/differences documentation: https://appfire.atlassian.net/wiki/spaces/CTFCSM/pages/1561201095

---

## 27. Final recommendation

Build `pull` as a new CLI with `confpub` DNA but a separate extraction philosophy.

The most important engineering decision is to make the local package self-describing. The manifest, warnings, page files, asset files, and bundle should make it obvious what a human would have seen, what was downloaded, what was rewritten, and what was not faithfully converted.

The MVP should focus on correctness over breadth:

1. rendered-page-first extraction;
2. reliable local assets;
3. local page/asset link rewriting;
4. strong manifest;
5. tabs/expand/include/attachments/diagram basics;
6. explicit warnings for everything else.

That gives you an AI-ready Confluence puller that is useful immediately, while leaving a clean adapter architecture for the long tail of Confluence macros and marketplace apps.
