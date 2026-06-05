# Repository Guidance

- Keep `pull` focused on AI analysis of the current rendered Confluence page. Do not turn it into an alias of `confpub page pull`.
- Preserve the stdout/stderr contract: JSON mode writes exactly one JSON object to stdout; progress and diagnostics belong on stderr.
- Do not log or write credentials, tokens, cookies, Authorization headers, or signed download URLs. Route all persisted API data through the redaction helpers.
- Keep Confluence access read-only. Do not add publishing, draft mutation, or permission-bypass behavior.
- Prefer deterministic mocked fixtures for tests. Live Confluence checks are useful smoke tests, not required unit tests.
- When adding macro behavior, implement it through the registry and add a fixture test plus warning/manifest expectations.
- All manifest paths must remain relative to the output root, and `pull validate` should be extended when new output artifacts are added.
