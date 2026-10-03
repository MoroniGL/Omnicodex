"""Small provider contracts shared by direct evidence generators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class GenerationResult:
    """A validated provider response and only directly evidenced telemetry."""

    pack: dict[str, Any]
    telemetry: dict[str, Any]


class ProviderError(ValueError):
    """A deliberately non-diagnostic provider error safe to persist or display."""

    def __init__(self, reason_code: str, telemetry: Mapping[str, Any] | None = None):
        safe_codes = frozenset((
            "provider_not_configured", "provider_timeout", "provider_failed",
            "invalid_pack", "credential_leak",
        ))
        self.reason_code = reason_code if reason_code in safe_codes else "provider_failed"
        self.telemetry = dict(telemetry or {})
        super().__init__(self.reason_code)


class EvidencePackProvider(Protocol):
    def status(self) -> dict[str, Any]: ...

    def generate_evidence_pack(
        self,
        task: Mapping[str, Any],
        captured_scope: Any,
        evidence_schema: Mapping[str, Any],
        limits: Mapping[str, Any],
    ) -> GenerationResult: ...
