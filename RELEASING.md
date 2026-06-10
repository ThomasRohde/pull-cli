# Releasing

## Versioning

`pull-cli` uses SemVer-style public versions: `MAJOR.MINOR.PATCH`.

The single source of truth is `src/pull_cli/__init__.py`:

```python
__version__ = "1.0.0"
```

`pyproject.toml` reads that value dynamically through Hatch, and the CLI reports the same value through:

```bash
uv run pull --version
uv run pull version
```

Bump versions with Hatch:

```bash
uv run hatch version patch
uv run hatch version minor
uv run hatch version major
```

Use patch for backwards-compatible fixes, minor for backwards-compatible features, and major for intentional breaking changes.

## PyPI Trusted Publisher

Configure the PyPI trusted publisher with these values:

```text
PyPI Project Name: pull-cli
Owner: ThomasRohde
Repository name: pull-cli
Workflow name: publish.yml
Environment name: pypi
```

The publishing workflow is `.github/workflows/publish.yml`. It uses the `pypi` GitHub environment and PyPI trusted publishing, so no PyPI API token is stored in GitHub.

## Release Flow

1. Update `CHANGELOG.md` for the release.

2. Bump the version:

   ```bash
   uv run hatch version patch
   ```

3. Sync and verify locally:

   ```bash
   uv sync --all-extras
   uv run pull --version
   uv run ruff check .
   uv run pytest
   uv run pytest --cov=pull_cli --cov-report=term-missing
   uv build
   uvx --from twine twine check dist/*
   ```

4. Commit the version bump:

   ```bash
   git add src/pull_cli/__init__.py
   git commit -m "Release v$(uv run hatch version)"
   ```

5. Push the commit, create a GitHub release tagged `vX.Y.Z`, and publish that release.

The `publish.yml` workflow only runs when a GitHub release is published. It checks that the release tag, after removing a leading `v`, matches `pull_cli.__version__` before building and uploading distributions to PyPI.

The CI gate runs Python 3.11, 3.12, and 3.13 on Ubuntu, plus Python 3.13 on Windows and macOS. Linux jobs run the coverage threshold; Windows and macOS run the plain test suite to avoid platform-specific coverage variance.
