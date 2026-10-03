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
    "provider_finish_reason": frozenset(("STOP", "MAX_TOKENS", "SAFETY", "RECITATION",
        "LANGUAGE", "OTHER", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII",
        "MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS")),
    "provider_output_issue": frozenset(("invalid_response_json", "invalid_usage",
        "invalid_candidates", "non_stop_finish", "invalid_content_parts",
        "invalid_pack_json", "non_object_pack")),
    "pack_validation_issue": frozenset(("schema", "task_kind_mismatch", "snapshot_mismatch",
        "unapproved_file", "citations", "operational_instructions", "pack_budget", "handoff_reduction")),
    "pack_schema_issue": frozenset(("version", "status", "task", "snapshot", "summary", "unknown_field",
        "file_list", "findings", "empty_findings", "finding", "evidence", "evidence_shape",
        "evidence_reference", "missing_relevant_citation", "line_range", "risk_unknown_list",
        "validation", "validation_item")),
}

_REQUEST_HINT_TERMS = {
    "json_schema": ("responsejsonschema", "response_json_schema"),
    "response_format": ("responseformat", "response_format", "responsemimetype", "response_mime_type"),
    "schema_enum": ("enum",),
    "schema_complexity": ("nesting depth", "too complex", "too many states", "schema complexity"),
    "schema_type": ("type_string", "type_number", "invalid type", "expected type"),
    "schema_array_bounds": ("maxitems", "minitems", "max_items", "min_items"),
    "output_token_limit": ("maxoutputtokens", "max_output_tokens"),
    "api_key": ("api key", "api_key"),
    "model": ("model",),
    "unsupported_field": ("unknown name", "unsupported field", "unrecognized field"),
}


def request_error_hints(message: Any) -> dict[str, Any]:
    """Return fixed lexical hints, never a message excerpt or a diagnosis."""
    if not isinstance(message, str) or len(message) > 8192:
        return {}
    lowered = message.lower()
    hints = [code for code, terms in _REQUEST_HINT_TERMS.items() if any(term in lowered for term in terms)]
    return {"provider_error_hints": hints} if hints else {}


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
    hints = value.get("provider_error_hints")
    if isinstance(hints, list) and len(hints) <= len(_REQUEST_HINT_TERMS):
        recognized = list(dict.fromkeys(item for item in hints
                          if isinstance(item, str) and item in _REQUEST_HINT_TERMS))
        if recognized:
            result["provider_error_hints"] = recognized
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
