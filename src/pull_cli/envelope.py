from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict
from typing import Any

from .errors import PullError
from .models import WarningRecord
from .security import redact_value

SCHEMA_VERSION = "1.0"


def wants_json(explicit: bool) -> bool:
    return explicit or os.environ.get("LLM", "").lower() == "true"


def request_id() -> str:
    return time.strftime("req_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]


def make_envelope(
    *,
    ok: bool,
    command: str,
    target: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    warnings: list[WarningRecord | dict[str, Any]] | None = None,
    errors: list[PullError | dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
    request_id_value: str | None = None,
) -> dict[str, Any]:
    warning_records = [
        warning.to_dict() if isinstance(warning, WarningRecord) else warning
        for warning in (warnings or [])
    ]
    error_records = [error.to_record() if isinstance(error, PullError) else error for error in errors or []]
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id_value or request_id(),
        "ok": ok,
        "command": command,
        "target": target or {},
        "result": result if ok else None,
        "warnings": warning_records,
        "errors": error_records,
        "metrics": metrics or {},
    }


def emit_json(data: dict[str, Any]) -> None:
    print(json.dumps(redact_value(data), ensure_ascii=False, separators=(",", ":")))


def dataclass_dict(value: Any) -> dict[str, Any]:
    return asdict(value)
