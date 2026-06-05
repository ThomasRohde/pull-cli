from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EXIT_SUCCESS = 0
EXIT_VALIDATION = 10
EXIT_AUTH = 20
EXIT_SOURCE = 30
EXIT_STRICT_PARTIAL = 40
EXIT_IO = 50
EXIT_INTERNAL = 90


@dataclass
class PullError(Exception):
    code: str
    message: str
    exit_code: int = EXIT_INTERNAL
    retryable: bool = False
    suggested_action: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "suggested_action": self.suggested_action,
            "details": self.details,
        }


def validation_error(
    code: str,
    message: str,
    *,
    suggested_action: str | None = None,
    details: dict[str, Any] | None = None,
) -> PullError:
    return PullError(
        code=code,
        message=message,
        exit_code=EXIT_VALIDATION,
        suggested_action=suggested_action,
        details=details or {},
    )
