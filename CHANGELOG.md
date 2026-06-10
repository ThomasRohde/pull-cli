# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-06-10

### Added
- Functional `--quiet` mode for silent human-mode success output.
- Bounded pull-cli-owned retry policy with `PULL_RETRIES`.
- Windows and macOS CI smoke coverage alongside the Linux Python matrix.
- Linux coverage reporting and a coverage gate.
- `CONTRIBUTING.md`, `ARCHITECTURE.md`, and a documented stability policy.

### Changed
- `--quiet` now overrides `--verbose` instead of acting as a no-op.
- Retry behavior is owned by pull-cli instead of atlassian-python-api.
- Package classifier is now `Development Status :: 5 - Production/Stable`.
- `--chunks` is explicitly experimental and excluded from the stability policy.

### Fixed
- Potential unbounded connection-error retry loops under urllib3 2.x.
- Retry-After handling for retryable HTTP responses.

## [0.2.3] - 2026-06-10

### Fixed
- Empty, unreadable, or non-certificate `--ssl-verify` CA bundle paths fail fast with `ERR_TLS_VERIFY`.
- TLS setup `OSError` cases are translated to `ERR_TLS_VERIFY`.

## [0.2.2] - 2026-06-09

### Added
- Default operating-system trust store support through `truststore`.
- `ERR_TLS_VERIFY` guidance for corporate TLS interception.

### Fixed
- TLS certificate verification failures fail fast instead of surfacing as generic connection errors.

## [0.2.1] - 2026-06-09

### Added
- Atlassian Cloud v2 storage-first page fetches.
- Verbose phase progress to stderr.
- Fast-fail guidance for Atlassian Cloud `ATAT` tokens used as Bearer auth.

### Fixed
- `--render-mode storage` now uses storage content for Markdown conversion.
- Page selector parsing remains order-independent with other flags.

## [0.2.0] - 2026-06-08

### Added
- `--output-mode simple|full` with simple mode as the default.
- Optional comment sidecars with `--comments`.
- Explicit `--auth auto|bearer|basic` behavior.
- Improved CLI help, guide output, default output directory guidance, and Data Center PAT handling.

### Fixed
- JSON stdout remains parseable when `--ssl-verify false` suppresses urllib3 warnings.
- Asset filenames with punctuation round-trip through Markdown writing and validation.
- Redacted package metadata is leaner and avoids distracting source-navigation fields.

## [0.1.0] - 2026-06-05

### Added
- Initial read-only Confluence evidence package extractor.
- Page/tree extraction to Markdown, manifests, diagnostics, assets, and optional full evidence artifacts.
- Macro conversion registry and storage macro parsing across platforms.
- Package validation and JSON envelope output.

[1.0.0]: https://github.com/ThomasRohde/pull-cli/compare/v0.2.3...v1.0.0
[0.2.3]: https://github.com/ThomasRohde/pull-cli/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/ThomasRohde/pull-cli/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/ThomasRohde/pull-cli/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/ThomasRohde/pull-cli/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ThomasRohde/pull-cli/releases/tag/v0.1.0
