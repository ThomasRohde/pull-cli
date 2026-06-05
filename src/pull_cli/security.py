from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SECRET_KEY_PATTERN = re.compile(
    r"(^|[_\-.])(authorization|cookie|token|password|secret|signature|session|jwt|pat|access[_-]?key)([_\-.]|$)",
    re.IGNORECASE,
)
SECRET_TEXT_PATTERNS = [
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bBasic\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(?i)(access_token|api_token|jwt|token|signature|atl_token)=([^&\s]+)"),
    re.compile(r"(?i)\bname=[\"']?(atl_token|token|signature|jwt|password|secret)[\"']?"),
]
SECRET_HTML_INPUT_PATTERN = re.compile(
    r"(?is)<input\b(?=[^>]*\bname=[\"']?(?:atl_token|token|signature|jwt|password|secret)[\"']?)[^>]*>"
)
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_token",
    "atl_token",
    "auth",
    "authorization",
    "downloadtoken",
    "expires",
    "jwt",
    "signature",
    "sig",
    "token",
    "x-amz-algorithm",
    "x-amz-credential",
    "x-amz-date",
    "x-amz-expires",
    "x-amz-security-token",
    "x-amz-signature",
    "x-amz-signedheaders",
}


def redact_text(value: str) -> str:
    redacted = SECRET_HTML_INPUT_PATTERN.sub("<input name=<redacted> value=<redacted>>", value)
    for pattern in SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(lambda match: match.group(0).split("=", 1)[0] + "=<redacted>" if "=" in match.group(0) else "<redacted-auth>", redacted)
    return redacted


def sanitize_url(url: str | None, *, redact_source_url: bool = False) -> str | None:
    if not url:
        return url
    if redact_source_url:
        return "<redacted-url>"
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact_text(url)
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS or SECRET_KEY_PATTERN.search(key):
            query_pairs.append((key, "<redacted>"))
        else:
            query_pairs.append((key, redact_text(value)))
    sanitized = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query_pairs), parts.fragment)
    )
    return redact_text(sanitized)


def redact_value(value: Any, *, redact_source_urls: bool = False) -> Any:
    if isinstance(value, str):
        if value.startswith(("http://", "https://", "/wiki/", "/download/")):
            return sanitize_url(value, redact_source_url=redact_source_urls)
        return redact_text(value)
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if SECRET_KEY_PATTERN.search(key_text):
                output[key_text] = "<redacted>"
            else:
                output[key_text] = redact_value(child, redact_source_urls=redact_source_urls)
        return output
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_value(child, redact_source_urls=redact_source_urls) for child in value]
    return value


def contains_secret_text(value: str) -> bool:
    if SECRET_KEY_PATTERN.search(value):
        return True
    for pattern in SECRET_TEXT_PATTERNS:
        for match in pattern.finditer(value):
            if "<redacted>" not in match.group(0) and "<redacted-auth>" not in match.group(0):
                return True
    return False
