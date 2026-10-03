"""Small provider contracts shared by direct evidence generators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


_DIAGNOSTIC_CODES = {
    "provider_error_status": frozenset(("INVALID_ARGUMENT", "FAILED_PRECONDITION",
        "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND", "RESOURCE_EXHAUSTED",
        "INTERNAL", "UNAVAILABLE", "DEADLINE_EXCEEDED")),
    "provider_error_reason": frozenset(("API_KEY_INVALID", "API_KEY_EXPIRED",
        "API_KEY_SERVICE_BLOCKED", "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED",
        "SERVICE_DISABLED", "CONSUMER_INVALID", "BILLING_DISABLED", "RATE_LIMIT_EXCEEDED",
        "QUOTA_EXCEEDED")),
    "transport_error": frozenset(("tls_error", "dns_error", "connection_error",
        "http_protocol_error", "request_encoding_error", "transport_error")),
}


def safe_diagnostics(value: Mapping[str, Any]) -> dict[str, Any]:
    """Retain a numeric HTTP status and fixed codes; never arbitrary provider text."""
    result: dict[str, Any] = {}
    status = value.get("provider_http_status")
    if type(status) is int and 100 <= status <= 599:
        result["provider_http_status"] = status
    for field, allowed in _DIAGNOSTIC_CODES.items():
        item = value.get(field)
        if isinstance(item, str) and item in allowed:
            result[field] = item
    return result


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
