#!/usr/bin/env python3
"""Opt-in TypeSafe Jev REST client for bounded Omni routing decisions."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "https://api.typesafe.ai"
MAX_STATE_BYTES = 32 * 1024
TIMEOUT_SECONDS = 10


class JevError(RuntimeError):
    pass


def _enabled() -> bool:
    return os.environ.get("OMNI_JEV") == "1"


def _api_key() -> str:
    value = os.environ.get("JEV_API_KEY", "")
    if not value:
        raise JevError("JEV_API_KEY is not set")
    return value


def _read_limited(stream: Any) -> bytes:
    raw = stream.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise JevError("state exceeds the 32 KiB Omni safety limit")
    return raw


def _read_state(path: Path | None) -> Any:
    if path:
        with path.open("rb") as stream:
            raw = _read_limited(stream)
    else:
        raw = _read_limited(sys.stdin.buffer)
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _request(method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _enabled():
        raise JevError("Jev is disabled; set OMNI_JEV=1 to opt in")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise JevError(f"Jev request failed: {type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise JevError("Jev response is not a JSON object")
    return data


def _questions(kind: str) -> dict[str, Any]:
    if kind == "route-task":
        return {
            "route": {
                "type": "choice",
                "instructions": "Choose the least expensive capable execution path without weakening acceptance criteria.",
                "criteria": {
                    "cheap_worker": "Narrow, repeatable, low-risk lookup or extraction.",
                    "balanced_worker": "Normal engineering or implementation with bounded scope.",
                    "deep_review": "Consequential work that needs stronger independent review.",
                    "escalate": "Exceptional unresolved blocker or critical-risk reasoning.",
                },
            },
            "needs_review": {
                "type": "noul",
                "instructions": "Does this task or proposed result warrant independent review because an error could have material impact?",
            },
        }
    if kind == "retry-strategy":
        return {
            "retry": {
                "type": "choice",
                "instructions": "Choose the next action after the failed attempt using only the supplied evidence.",
                "criteria": {
                    "retry_once": "Transient failure with a concrete reason one retry may succeed.",
                    "change_strategy": "The same attempt is unlikely to help; change approach or context.",
                    "escalate": "A capability or material-risk barrier requires a stronger reviewer or model.",
                    "stop": "Further automated attempts are not justified without new evidence or approval.",
                },
            }
        }
    if kind == "review-gate":
        return {
            "needs_review": {
                "type": "noul",
                "instructions": "Does the supplied change or result require independent review before acceptance?",
                "criteria": {
                    "true": "Material blast radius, security/data integrity risk, ambiguous evidence, or consequential irreversible behavior.",
                    "false": "Bounded reversible work with objective validation and no material unresolved risk.",
                },
            }
        }
    if kind == "completion-check":
        return {
            "complete": {
                "type": "noul",
                "instructions": "Based only on the supplied evidence, is the stated objective actually complete?",
                "criteria": {
                    "true": "All stated acceptance criteria have direct supporting evidence and no known blocker remains.",
                    "false": "A required criterion is unverified, failed, blocked, or contradicted by the evidence.",
                },
            }
        }
    raise JevError(f"unsupported decision kind: {kind}")


def build_payload(kind: str, model: str, state: Any) -> dict[str, Any]:
    if not model:
        raise JevError("model is required; discover it with the models command")
    return {"state": state, "model": model, "questions": _questions(kind)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["doctor", "models", "route-task",
                                           "retry-strategy", "review-gate",
                                           "completion-check"])
    parser.add_argument("--model")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.action == "doctor":
            print(json.dumps({
                "enabled": _enabled(),
                "api_key_present": bool(os.environ.get("JEV_API_KEY")),
                "base_url": BASE_URL,
                "network_checked": False,
                "notice": "No credentials are printed and no network request is made.",
            }, indent=2))
            return 0

        if args.action == "models":
            print(json.dumps(_request("GET", "/v1/models"), indent=2))
            return 0

        state = _read_state(args.state_file)
        payload = build_payload(args.action, args.model or "", state)
        if args.dry_run:
            print(json.dumps(payload, indent=2))
            return 0
        print(json.dumps(_request("POST", "/v1/systemone", payload=payload), indent=2))
        return 0
    except (OSError, UnicodeError, JevError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
