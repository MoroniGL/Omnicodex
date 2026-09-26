#!/usr/bin/env python3
"""Opt-in, advisory Jev client: explicit Vercel or direct TypeSafe transport."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

BASE_URL = "https://api.typesafe.ai"  # Direct-provider compatibility.
MAX_STATE_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 30
CONTRACT_VERSION = "omni-jev-advisory/2"
PROVIDERS = {
    "typesafe": {"base_url": BASE_URL, "path": "/v1/systemone"},
    "vercel": {"base_url": "https://ai-gateway.vercel.sh", "path": "/v1/evaluate"},
}
ACTIONS = ("route-task", "retry-strategy", "review-gate", "completion-check")
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class JevError(RuntimeError):
    """Fixed, safe messages only: never include input, key, URL or server body."""
    def __init__(self, code: str, http_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def _require(ok: bool, code: str = "invalid_response") -> None:
    if not ok:
        raise JevError(code)


def _enabled() -> bool:
    return os.environ.get("OMNI_JEV") == "1"


def _provider(provider: str) -> dict[str, str]:
    _require(provider in PROVIDERS, "unknown_provider")
    return PROVIDERS[provider]


def _api_key(provider: str = "typesafe") -> str:
    _provider(provider)
    if provider == "vercel":
        value = os.environ.get("AI_GATEWAY_API_KEY", "")
    else:
        canonical = os.environ.get("TYPESAFE_API_KEY", "")
        legacy = os.environ.get("JEV_API_KEY", "")
        _require(not (canonical and legacy and canonical != legacy), "conflicting_typesafe_keys")
        value = canonical or legacy
        gateway = os.environ.get("AI_GATEWAY_API_KEY", "")
        _require(not (value and gateway and value == gateway), "gateway_key_cannot_use_direct_typesafe")
    _require(bool(value), "missing_api_key_for_selected_provider")
    _require(value.isascii() and all(32 < ord(c) < 127 for c in value), "invalid_api_key_format")
    return value


def check_live_access(provider: str) -> None:
    _provider(provider)
    _require(_enabled(), "jev_disabled_set_OMNI_JEV_1")
    _api_key(provider)


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise JevError("invalid_json_data") from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _bad_constant(_: str) -> None:
    raise JevError("nonfinite_json_number")


def _decode(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                      parse_constant=_bad_constant)


def _read_limited(stream: Any, limit: int = MAX_STATE_BYTES) -> bytes:
    raw = stream.read(limit + 1)
    _require(len(raw) <= limit, "size_limit_exceeded")
    return raw


def _read_state(path: Path | None) -> Any:
    if path:
        with path.open("rb") as stream:
            raw = _read_limited(stream)
    else:
        raw = _read_limited(sys.stdin.buffer)
    try:
        return _decode(raw)
    except json.JSONDecodeError:
        return raw.decode("utf-8-sig")


def _questions(kind: str, provider: str = "typesafe") -> dict[str, Any]:
    _provider(provider)
    boolean_type = "boolean" if provider == "vercel" else "noul"
    if kind == "route-task":
        return {
            "route": {"type": "choice", "instructions": "Choose the least expensive capable path. Do not weaken acceptance criteria or authorize actions.", "criteria": {
                "cheap_worker": "Narrow, repeatable, low-risk lookup or extraction.",
                "balanced_worker": "Ordinary engineering with bounded scope and known constraints.",
                "deep_review": "Consequential change needing independent review, not necessarily an unresolved blocker.",
                "escalate": "A concrete unresolved capability barrier or critical risk requires stronger reasoning.",
                "need_more_evidence": "Insufficient evidence to select a capable path.",
                "human": "Required authorization or a user decision is missing.",
            }},
            "needs_review": {"type": boolean_type, "instructions": "Does this task or result warrant independent review because an error could have material impact?"},
        }
    if kind == "retry-strategy":
        return {"retry": {"type": "choice", "instructions": "Choose the next step based only on the failed attempt and supplied evidence; do not authorize execution.", "criteria": {
            "retry_once": "Transient failure with new evidence that one retry may succeed and budget remaining.",
            "change_strategy": "The same approach is unlikely to work; a different approach is justified.",
            "escalate": "A concrete capability or risk barrier needs stronger reasoning.",
            "stop": "Retry budget exhausted, authorization absent, or no justified next automated attempt.",
        }}}
    if kind == "review-gate":
        return {"needs_review": {"type": boolean_type, "instructions": "Does the supplied change require independent review before acceptance?", "criteria": {
            "true": "Material blast radius, security/data-integrity risk, or consequential unresolved evidence.",
            "false": "Bounded reversible work with objective validation and no material unresolved risk.",
        }}}
    if kind == "completion-check":
        return {"complete": {"type": boolean_type, "instructions": "Does the supplied evidence support every stated acceptance criterion? A self-report is not proof.", "criteria": {
            "true": "Every criterion has direct evidence at the final revision; no blocker remains.",
            "false": "Any required criterion is failed, blocked, unknown, stale, or contradicted.",
        }}}
    raise JevError("unknown_decision_kind")


def build_payload(kind: str, model: str, state: Any,
                  provider: str = "typesafe") -> dict[str, Any]:
    _provider(provider)
    _require(isinstance(model, str) and MODEL_PATTERN.fullmatch(model) is not None, "model_required_or_invalid")
    if provider == "vercel":
        _require(model == "typesafe-ai/jev", "unsupported_vercel_evaluation_model")
    _require(isinstance(state, (str, dict, list)), "invalid_state_type")
    encoded = _json_bytes(state)
    _require(len(encoded) <= MAX_STATE_BYTES, "state_size_limit_exceeded")
    # This only catches the configured credentials, not arbitrary secrets/PII.
    for name in ("AI_GATEWAY_API_KEY", "TYPESAFE_API_KEY", "JEV_API_KEY"):
        key = os.environ.get(name, "")
        if len(key) >= 8:
            _require(_json_bytes(key)[1:-1] not in encoded, "configured_key_in_state")
    return {"model": model, "state": state, "questions": _questions(kind, provider)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        raise JevError("redirect_refused", code)


def _request(method: str, path: str, *, payload: dict[str, Any] | None = None,
             provider: str = "typesafe") -> dict[str, Any]:
    config = _provider(provider)
    check_live_access(provider)
    allowed = {( "POST", config["path"] )}
    if provider == "typesafe":
        allowed.add(("GET", "/v1/models"))
    _require((method, path) in allowed, "endpoint_not_allowed")
    body = None if payload is None else _json_bytes(payload)
    request = urllib.request.Request(config["base_url"] + path, data=body, method=method,
        headers={"Authorization": "Bearer " + _api_key(provider),
                 "Accept": "application/json", "Content-Type": "application/json; charset=utf-8"})
    # No redirects, environment proxies, automatic retry, alternate host or provider fallback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            data = _decode(_read_limited(response, MAX_RESPONSE_BYTES))
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise JevError("http_error", code) from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise JevError("transport_error_no_retry") from None
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise JevError("invalid_response_json") from None
    _require(isinstance(data, dict))
    return data


def _probability(value: Any) -> float:
    _require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1)
    return float(value)


def _usage_count(value: Any) -> int:
    _require(type(value) is int and value >= 0)
    return value


def normalize_response(data: dict[str, Any], payload: dict[str, Any],
                       provider: str) -> dict[str, Any]:
    _provider(provider)
    model = data.get("model")
    _require(isinstance(model, str) and MODEL_PATTERN.fullmatch(model) is not None)
    if provider == "vercel":
        _require(model == payload["model"], "returned_model_mismatch")
    answers = data.get("answers")
    questions = payload["questions"]
    _require(isinstance(answers, dict) and set(answers) == set(questions))
    normalized = {}
    for name, question in questions.items():
        answer = answers[name]
        _require(isinstance(answer, dict) and answer.get("type") == question["type"])
        if question["type"] in ("noul", "boolean"):
            field = "probability" if provider == "vercel" else "noul"
            normalized[name] = {"type": "boolean", "probability": _probability(answer.get(field))}
        else:
            options = question["criteria"]
            probabilities = answer.get("probabilities")
            _require(isinstance(probabilities, dict) and set(probabilities) == set(options))
            probabilities = {key: _probability(val) for key, val in probabilities.items()}
            _require(abs(sum(probabilities.values()) - 1.0) <= 0.02)
            choice = answer.get("choice")
            _require(isinstance(choice, str) and choice in options)
            _require(probabilities[choice] + 1e-6 >= max(probabilities.values()))
            confidence = answer.get("confidence")
            if provider == "typesafe" or "confidence" in answer:
                confidence = _probability(confidence)
            normalized[name] = {"type": "choice", "choice": choice,
                                "probabilities": probabilities, "confidence": confidence}
    usage = data.get("usage")
    _require(isinstance(usage, dict))
    ik, ok = ("inputTokens", "outputTokens") if provider == "vercel" else ("input_tokens", "output_tokens")
    counts = {"input_tokens": _usage_count(usage.get(ik)), "output_tokens": _usage_count(usage.get(ok))}
    cost = None
    if provider == "vercel":
        metadata = data.get("providerMetadata", {})
        _require(isinstance(metadata, dict))
        gateway = metadata.get("gateway", {})
        _require(isinstance(gateway, dict))
        if gateway.get("cost") is not None:
            value = gateway["cost"]
            _require(type(value) in (str, int, float))
            try:
                decimal = Decimal(str(value))
                _require(decimal.is_finite() and decimal >= 0)
                cost = str(decimal)
            except InvalidOperation:
                raise JevError("invalid_cost") from None
    return {"requested_model": payload["model"], "returned_model": model,
            "model_matches_request": model == payload["model"],
            "answers": normalized, "usage": counts, "gateway_cost_usd": cost}


def evaluate(kind: str, state: Any, *, provider: str, model: str) -> dict[str, Any]:
    payload = build_payload(kind, model, state, provider)
    started = time.perf_counter()
    data = _request("POST", _provider(provider)["path"], payload=payload, provider=provider)
    result = normalize_response(data, payload, provider)
    return {"schema_version": 1, "mode": "advisory", "provider": provider,
            "contract": CONTRACT_VERSION + "/" + kind,
            "state_sha256": hashlib.sha256(_json_bytes(state)).hexdigest(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "action_executed": False, "evidence_source": "api_response_not_independent_attestation",
            **result}


def error_record(exc: Exception) -> dict[str, Any]:
    return {"error": exc.code if isinstance(exc, JevError) else "local_input_or_output_error",
            "http_status": exc.http_status if isinstance(exc, JevError) else None,
            "action_executed": False, "fallback": "caller_must_keep_native_policy; no_automatic_retry"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "models", *ACTIONS))
    parser.add_argument("--provider", choices=tuple(PROVIDERS), default=os.environ.get("OMNI_JEV_PROVIDER", "typesafe"))
    parser.add_argument("--model")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = _provider(args.provider)
        if args.action == "doctor":
            credential_error = None
            try:
                _api_key(args.provider)
            except JevError as exc:
                credential_error = exc.code
            report = {"enabled": _enabled(), "provider": args.provider,
                      "api_key_present": credential_error is None,
                      "credential_status": credential_error or "available",
                      "base_url": config["base_url"], "evaluation_path": config["path"],
                      "network_checked": False}
        elif args.action == "models":
            if args.provider == "vercel":
                # Deliberately no authenticated model-list endpoint guess.
                report = {"provider": "vercel", "models": [{"name": "typesafe-ai/jev"}],
                          "source": "documented_configuration", "network_checked": False,
                          "account_access_verified": False}
            elif args.dry_run:
                report = {"method": "GET", "url": BASE_URL + "/v1/models", "network_checked": False}
            else:
                data = _request("GET", "/v1/models", provider=args.provider)
                models = data.get("models")
                _require(isinstance(models, list))
                for item in models:
                    _require(isinstance(item, dict) and isinstance(item.get("name"), str)
                             and MODEL_PATTERN.fullmatch(item["name"]) is not None)
                report = {"provider": args.provider, "models": [{"name": item["name"]} for item in models],
                          "network_checked": True}
        else:
            model = args.model if args.model is not None else ("typesafe-ai/jev" if args.provider == "vercel" else "")
            state = _read_state(args.state_file)
            payload = build_payload(args.action, model, state, args.provider)
            report = payload if args.dry_run else evaluate(args.action, state, provider=args.provider, model=model)
        print(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False))
        return 0
    except (JevError, OSError, UnicodeError, ValueError, RecursionError) as exc:
        print(json.dumps(error_record(exc)), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
