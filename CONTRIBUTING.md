# Contributing

## Setup

Use `uv` and install all optional development dependencies:

```bash
uv sync --all-extras
```

Common checks:

```bash
uv run ruff check .
uv run pytest
uv run pytest --cov=pull_cli --cov-report=term-missing
uv build
```

## Fixtures

Prefer deterministic tests with `FakeConfluenceClient` or small mocked Atlassian client
fixtures. Live Confluence smoke tests are useful before releases, but unit and regression
tests must not require live credentials.

When package fixture output intentionally changes, regenerate it with:

```bash
uv run python tests/generate_fixture_output.py .tmp/generated-fixture
uv run pull validate .tmp/generated-fixture
```

Commit only deliberate fixture changes. Do not commit credentials, cookies,
Authorization headers, signed download URLs, or live tenant-specific content.

## Contracts

Follow `AGENTS.md` when changing behavior:

- Keep `pull` read-only.
- Preserve JSON mode: exactly one JSON object on stdout.
- Send progress and diagnostics to stderr.
- Persist API-derived data only after redaction.
- Keep manifest paths relative to the output root.
- Extend `pull validate` when adding output artifacts.

## Macro Adapters

Macro behavior belongs in the registry in `src/pull_cli/macros.py`. Add or update an
adapter when a Confluence macro needs special conversion, then add fixture coverage for:

- converted Markdown or placeholder output,
- warnings and manifest expectations,
- strict/unknown macro behavior when relevant.

Unknown macros should remain explainable placeholders unless the selected policy says to
ignore or error.

## Releases

See `RELEASING.md` for versioning, trusted publishing, and release commands. The PyPI
workflow only publishes when a GitHub Release is published.
