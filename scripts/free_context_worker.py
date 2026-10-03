#!/usr/bin/env python3
"""Capture approved context locally and obtain compact evidence via Gemini Direct."""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import efficiency, offload_scope as scope
from scripts.providers.gemini import GeminiProvider
from scripts.providers.base import ProviderError

MANIFEST = ROOT / "integrations" / "efficiency.json"
OUTPUT_SCHEMA = ROOT / "schemas" / "evidence-pack.schema.json"
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_ARTIFACT_BYTES = 524_288
MAX_TIMEOUT_SECONDS = 300.0
# Require at least 20% reduction, including exact ranges the premium parent reopens.
MAX_HANDOFF_FRACTION = 0.8


def _load_local(name: str) -> Any:
    return importlib.import_module("scripts." + name)


def _environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    values = dict(os.environ if environment is None else environment)
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in values.items()):
        raise ValueError("Worker environment must contain strings")
    return values


def _is_link_or_reparse(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        reparse and getattr(info, "st_file_attributes", 0) & reparse
    )


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _artifact_directory(requested: Path | None, workspace: Path) -> Path:
    workspace_resolved = workspace.resolve(strict=True)
    if requested is None:
        destination = Path(tempfile.mkdtemp(prefix="omnicodex-offload-"))
        if _inside(destination.resolve(strict=True), workspace_resolved):
            destination.rmdir()
            raise ValueError("Temporary artifact directory resolved inside the workspace")
        os.chmod(destination, 0o700)
        return destination
    destination = requested.absolute()
    if destination.exists() or _inside(destination.resolve(strict=False), workspace_resolved):
        raise ValueError("Artifact directory must be fresh and outside the workspace")
    parent = destination.parent.resolve(strict=True)
    if _inside(parent, workspace_resolved):
        raise ValueError("Artifact directory must be outside the workspace")
    for candidate in (parent, *parent.parents):
        if _is_link_or_reparse(candidate.lstat()):
            raise ValueError("Artifact parent cannot be a link or reparse point")
    os.mkdir(destination, 0o700)
    return destination


def _write_json_new(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact exceeds size limit")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                raise OSError("Artifact write failed")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _captured_metrics(request: dict[str, Any], captured: Any,
                      provider_available: bool) -> dict[str, Any]:
    metrics = dict(request["metrics"])
    total_bytes = sum(len(entry.data) for entry in captured.entries)
    total_lines = sum(len(entry.data.splitlines()) for entry in captured.entries)
    metrics.update({
        "estimated_chars": total_bytes,
        "file_count": len(captured.entries),
        "diff_lines": total_lines,
        "log_bytes": total_bytes,
    })
    metrics["provider_available"] = provider_available
    return metrics


def _gate(request: dict[str, Any], captured: Any, profile: str,
          provider_available: bool, efficiency: Any,
          manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = _captured_metrics(request, captured, provider_available)
    plan = efficiency.make_offload_plan(manifest, metrics, profile)
    return metrics, plan


def _fallback(plan: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    reasons = list(plan["reason_codes"])
    if reason is not None and reason not in reasons:
        reasons.append(reason)
    return {
        "schema_version": 1,
        "status": "fallback",
        "route": "native",
        "reason_codes": reasons,
        "estimated_raw_tokens": plan["estimated_raw_tokens"],
        "quota_fallback": False,
        "runtime_model_verified": False,
    }


def _verification_evidence_bytes(pack: dict[str, Any], captured: Any) -> int:
    entries = {entry.path: entry.data.splitlines(keepends=True) for entry in captured.entries}
    intervals: dict[str, list[tuple[int, int]]] = {}
    for finding in pack["findings"]:
        for evidence in finding["evidence"]:
            intervals.setdefault(evidence["path"], []).append(
                (evidence["start_line"] - 1, evidence["end_line"]))
    total = 0
    for path, ranges in intervals.items():
        merged: list[list[int]] = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        total += sum(len(b"".join(entries[path][start:end])) for start, end in merged)
    return total


def _validate_pack(pack: dict[str, Any], request: dict[str, Any], captured: Any,
                   plan: dict[str, Any], manifest: dict[str, Any]) -> tuple[int, int]:
    efficiency.validate_evidence_pack(pack)
    if pack["task_kind"] != request["task_kind"] or pack["snapshot"] != captured.fingerprint:
        raise ValueError("EvidencePack identity mismatch")
    approved = {entry.path for entry in captured.entries}
    if not set(pack["relevant_files"]).issubset(approved):
        raise ValueError("EvidencePack references files outside the captured scope")
    references = [item for finding in pack["findings"] for item in finding["evidence"]]
    scope.validate_captured_references(captured, references)
    # Reject common instruction injection. All remaining prose is still untrusted;
    # parent acceptance requires opening exact source ranges, never executing prose.
    instruction = re.compile(
        r"\b(?:ignore (?:all |previous |prior )?instructions|"
        r"run (?:shell|powershell|bash|cmd|commands)|execute (?:commands|code)|"
        r"delete (?:files|the workspace)|system prompt)\b", re.IGNORECASE)
    if instruction.search(json.dumps(pack, ensure_ascii=False)):
        raise ValueError("EvidencePack contains operational instructions")
    pack_tokens = efficiency.estimate_pack_tokens(manifest, pack)
    if pack_tokens > plan["max_pack_tokens"]:
        raise ValueError("EvidencePack exceeds the profile budget")
    divisor = manifest["token_offload"]["chars_per_token"]
    evidence_bytes = _verification_evidence_bytes(pack, captured)
    evidence_tokens = (evidence_bytes + divisor - 1) // divisor
    if pack_tokens + evidence_tokens > int(plan["estimated_raw_tokens"] * MAX_HANDOFF_FRACTION):
        raise ValueError("Compact handoff would not meaningfully reduce premium context")
    return pack_tokens, evidence_tokens


def _scope_unchanged(workspace: Path, captured: Any,
                     approved_paths: list[str] | None = None) -> tuple[bool, str | None]:
    try:
        if approved_paths is not None:
            # Check directory membership by metadata without opening newly added files.
            current_paths = scope._collect_approved_scope(workspace, approved_paths)
            if current_paths != [entry.path for entry in captured.entries]:
                return False, None
        # Never expand directories again: only files approved in the immutable capture.
        current = scope.capture_scope(workspace, [entry.path for entry in captured.entries])
    except (OSError, ValueError, UnicodeError):
        return False, None
    return current.fingerprint == captured.fingerprint, current.fingerprint


def _receipt(metrics: dict[str, Any], plan: dict[str, Any], profile: str,
             captured: Any, telemetry: dict[str, Any], reason: str,
             snapshot_after: str | None, pack: dict[str, Any] | None = None,
             pack_tokens: int | None = None, evidence_tokens: int | None = None) -> dict[str, Any]:
    compact = pack_tokens + evidence_tokens if pack_tokens is not None and evidence_tokens is not None else None
    avoided = plan["estimated_raw_tokens"] - compact if compact is not None else None
    receipt = {
        "schema_version": 1, "mode": "live_token_offload_receipt", "profile": profile,
        "task_kind": metrics["task_kind"], "route": "free_context_worker",
        "provider": "gemini_direct", "requested_provider": "gemini_direct",
        "requested_model": telemetry.get("requested_model"),
        "worker_outcome": reason or "completed", "worker_exit_status": None,
        "failure_reason": reason or None, "elapsed_ms": telemetry.get("elapsed_ms"),
        "estimated_raw_tokens": plan["estimated_raw_tokens"],
        "captured_raw_bytes": sum(len(entry.data) for entry in captured.entries),
        "estimated_evidence_pack_tokens": pack_tokens,
        "estimated_verification_evidence_tokens": evidence_tokens,
        "estimated_compact_handoff_tokens": compact,
        "estimated_premium_context_avoided": avoided,
        "estimated_reduction_fraction": round(avoided / plan["estimated_raw_tokens"], 4) if avoided is not None else None,
        "validation_result": "rejected" if reason else "accepted",
        "evidence_pack_status": pack["status"] if pack else None,
        "evidence_trust": "untrusted_until_premium_source_verification",
        "native_fallback_recommended": bool(reason),
        "snapshot_before": captured.fingerprint, "snapshot_after": snapshot_after,
        "snapshot_scope": "captured_files_only",
        "actual_premium_parent_usage": None, "billing_verified": False,
        "subscription_allowance_verified": False, "quota_fallback": False,
        "artifacts": {"receipt": "receipt.json", "evidence_pack": "evidence-pack.json" if not reason else None},
    }
    for field in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
                  "served_model", "retry_count"):
        receipt[field] = telemetry.get(field)
    receipt["served_provider"] = None
    receipt["fallback_count"] = 0  # This implementation never retries another route/provider.
    return receipt


def run_action(action: str, workspace: Path | None, request_path: Path | None,
               profile: str, artifacts: Path | None, timeout_seconds: float,
               *, environment: Mapping[str, str] | None = None,
               transport: Any | None = None) -> tuple[dict[str, Any], int]:
    """Execute an offline doctor/gate or one direct provider request."""
    if action not in {"doctor", "dry-run", "run"}:
        raise ValueError("Unknown worker action")
    if profile not in efficiency.PROFILES:
        raise ValueError("Unknown profile")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or
            not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise ValueError("Invalid worker timeout")
    env = _environment(environment)
    provider = GeminiProvider(environment=env, transport=transport)
    settings = provider.status()
    if action == "doctor":
        return ({"schema_version": 1, "mode": "free_context_worker_doctor",
                 "native_status": "READY", "provider": settings["provider"],
                 "model": settings["model"], "key_configured": bool(env.get("GEMINI_API_KEY")),
                 "free_context_offload": "READY" if settings["configured"] else "NOT CONFIGURED",
                 "connectivity_verified": False, "runtime_model_verified": False,
                 "quota_fallback": False,
                 "notice": "Offline configuration check; use validate_gemini.py for connectivity."}, 0)
    if workspace is None or request_path is None:
        raise ValueError("Workspace and request are required")
    manifest = efficiency.read_json(MANIFEST)
    efficiency.validate_manifest(manifest)
    request = efficiency.read_json(request_path)
    scope.validate_worker_request(request)  # Privacy checks precede any workspace file open.
    captured = scope.capture_scope(workspace, request["approved_paths"])
    expected = request.get("expected_snapshot")
    if expected is not None and expected != captured.fingerprint:
        return ({"schema_version": 1, "status": "failed", "route": "native",
                 "reason_code": "snapshot_mismatch", "native_fallback_recommended": True,
                 "quota_fallback": False}, 3)
    metrics, plan = _gate(request, captured, profile, settings["configured"], efficiency, manifest)
    if not settings["configured"]:
        _, eligible_plan = _gate(request, captured, profile, True, efficiency, manifest)
        if eligible_plan["route"] != "free_context_worker":
            return _fallback(eligible_plan), 0
        return _fallback(plan, "missing_key" if not env.get("GEMINI_API_KEY") else "provider_not_configured"), 0
    if plan["route"] != "free_context_worker":
        return _fallback(plan), 0
    if action == "dry-run":
        return ({"schema_version": 1, "status": "ready", "route": "free_context_worker",
                 "reason_codes": plan["reason_codes"], "snapshot": captured.fingerprint,
                 "approved_files": [entry.path for entry in captured.entries],
                 "estimated_raw_tokens": plan["estimated_raw_tokens"],
                 "target_pack_tokens": plan["target_pack_tokens"], "max_pack_tokens": plan["max_pack_tokens"],
                 "requested_provider": settings["provider"], "requested_model": settings["model"],
                 "network_requests": 0, "quota_fallback": False, "runtime_model_verified": False}, 0)
    artifact_dir = _artifact_directory(artifacts, workspace)
    started = time.monotonic()
    telemetry = {"requested_model": settings["model"], "retry_count": 0}
    pack = None
    pack_tokens = evidence_tokens = None
    reason = ""
    try:
        result = provider.generate_evidence_pack(
            {"task_kind": request["task_kind"], "objective": request["objective"]},
            captured, efficiency.read_json(OUTPUT_SCHEMA),
            {"timeout_seconds": timeout_seconds, "target_pack_tokens": plan["target_pack_tokens"],
             "max_output_tokens": min(16384, plan["max_pack_tokens"] * 2 + 512)})
        telemetry = result.telemetry
        pack = result.pack
        pack_tokens, evidence_tokens = _validate_pack(pack, request, captured, plan, manifest)
    except ProviderError as error:
        reason = error.reason_code
        telemetry.update(error.telemetry)
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError, KeyError):
        reason = "invalid_pack"
    unchanged, snapshot_after = _scope_unchanged(workspace, captured, request["approved_paths"])
    if not unchanged:
        reason = "workspace_mutated"
    receipt = _receipt(metrics, plan, profile, captured, telemetry, reason, snapshot_after,
                       pack if not reason else None,
                       pack_tokens if not reason else None, evidence_tokens if not reason else None)
    receipt["orchestration_elapsed_ms"] = int((time.monotonic() - started) * 1000)
    if reason:
        _write_json_new(artifact_dir / "receipt.json", receipt)
        return ({"schema_version": 1, "status": "failed", "route": "native", "reason_code": reason,
                 "native_fallback_recommended": True, "quota_fallback": False,
                 "artifacts": {"directory": str(artifact_dir), "receipt": "receipt.json"}}, 3)
    _write_json_new(artifact_dir / "evidence-pack.json", pack)
    _write_json_new(artifact_dir / "receipt.json", receipt)
    return ({"schema_version": 1, "status": pack["status"], "route": "free_context_worker",
             "snapshot": captured.fingerprint, "estimated_raw_tokens": plan["estimated_raw_tokens"],
             "estimated_evidence_pack_tokens": pack_tokens,
             "estimated_verification_evidence_tokens": evidence_tokens,
             "estimated_compact_handoff_tokens": pack_tokens + evidence_tokens,
             "evidence_trust": "untrusted_until_premium_source_verification",
             "artifacts": {"directory": str(artifact_dir), "receipt": "receipt.json",
                           "evidence_pack": "evidence-pack.json"}, "quota_fallback": False}, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "dry-run", "run"))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--profile", default="balanced", choices=tuple(sorted(efficiency.PROFILES)))
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        result, code = run_action(args.action, args.workspace, args.request, args.profile,
                                  args.artifacts, args.timeout)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError, KeyError):
        print(json.dumps({"error": "ValidationError", "route": "native", "quota_fallback": False,
                          "native_fallback_recommended": True,
                          "action": "Check the approved scope and local provider configuration."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
