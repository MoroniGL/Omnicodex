#!/usr/bin/env python3
"""Run one bounded, read-only FreeLLMAPI context worker for OmniCodex."""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "integrations" / "efficiency.json"
OUTPUT_SCHEMA = ROOT / "schemas" / "evidence-pack.schema.json"
DEFAULT_BASE_URL = "http://127.0.0.1:3001/v1"
DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_ARTIFACT_BYTES = 524_288
MAX_TIMEOUT_SECONDS = 300.0
SECRET_ENV_KEY = "FREELLMAPI_API_KEY"


def _load_local(name: str) -> Any:
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("_free_context_" + name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Required module is unavailable: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _environment(environment: Mapping[str, str] | None) -> dict[str, str]:
    values = dict(os.environ if environment is None else environment)
    if not all(isinstance(key, str) and isinstance(value, str)
               for key, value in values.items()):
        raise ValueError("Worker environment must contain strings")
    return values


def _resolve_codex_prefix(explicit: Sequence[str] | None,
                          environment: Mapping[str, str]) -> tuple[str, ...] | None:
    if explicit is not None:
        if isinstance(explicit, (str, bytes)) or not explicit or not all(
                isinstance(item, str) and item for item in explicit):
            raise ValueError("Invalid Codex executable prefix")
        prefix = tuple(explicit)
    else:
        configured = environment.get("OMNICODEX_CODEX_PATH")
        executable = configured or shutil.which("codex", path=environment.get("PATH", ""))
        if not executable:
            return None
        prefix = (executable,)
    first = Path(prefix[0])
    if first.is_absolute() or first.parent != Path("."):
        return prefix if first.is_file() else None
    return prefix if shutil.which(prefix[0], path=environment.get("PATH", "")) else None


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


def _prompt(request: dict[str, Any], captured: Any, plan: dict[str, Any]) -> str:
    paths = [entry.path for entry in captured.entries]
    return (
        "You are an isolated read-only OmniCodex context worker. Read only the staged "
        "workspace supplied as your current directory. Do not use the web, execute writes, "
        "or modify Git state. Return only an EvidencePack matching the supplied schema. "
        "Keep findings concise and cite exact repo-relative line ranges. Do not include raw "
        "files or full logs.\n"
        f"task_kind={request['task_kind']}\n"
        f"objective={request['objective']}\n"
        f"snapshot={captured.fingerprint}\n"
        f"approved_files={json.dumps(paths, ensure_ascii=False)}\n"
        f"target_pack_tokens={plan['target_pack_tokens']}\n"
        f"max_pack_tokens={plan['max_pack_tokens']}\n"
    )


def _verification_evidence_bytes(pack: dict[str, Any], captured: Any) -> int:
    entries = {entry.path: entry.data.splitlines(keepends=True) for entry in captured.entries}
    intervals: dict[str, list[tuple[int, int]]] = {}
    for finding in pack["findings"]:
        for evidence in finding["evidence"]:
            intervals.setdefault(evidence["path"], []).append(
                (evidence["start_line"] - 1, evidence["end_line"])
            )
    total = 0
    for path, ranges in intervals.items():
        merged: list[list[int]] = []
        for start, end in sorted(ranges):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        lines = entries[path]
        total += sum(len(b"".join(lines[start:end])) for start, end in merged)
    return total


def _validate_pack(pack: dict[str, Any], request: dict[str, Any], captured: Any,
                   workspace: Path, plan: dict[str, Any], efficiency: Any,
                   scope: Any, manifest: dict[str, Any]) -> tuple[int, int]:
    efficiency.validate_evidence_pack(pack)
    if pack["task_kind"] != request["task_kind"] or pack["snapshot"] != captured.fingerprint:
        raise ValueError("EvidencePack identity mismatch")
    approved = [entry.path for entry in captured.entries]
    if not set(pack["relevant_files"]).issubset(approved):
        raise ValueError("EvidencePack references files outside the captured scope")
    references = [item for finding in pack["findings"] for item in finding["evidence"]]
    scope.validate_evidence_references(workspace, approved, references)
    pack_tokens = efficiency.estimate_pack_tokens(manifest, pack)
    if pack_tokens > plan["max_pack_tokens"]:
        raise ValueError("EvidencePack exceeds the profile budget")
    divisor = manifest["token_offload"]["chars_per_token"]
    evidence_bytes = _verification_evidence_bytes(pack, captured)
    evidence_tokens = (evidence_bytes + divisor - 1) // divisor
    if pack_tokens + evidence_tokens >= plan["estimated_raw_tokens"]:
        raise ValueError("Compact handoff would not reduce premium context")
    return pack_tokens, evidence_tokens


def _scope_unchanged(workspace: Path, request: dict[str, Any], captured: Any,
                     scope: Any) -> tuple[bool, str | None]:
    try:
        current = scope.capture_scope(workspace, request["approved_paths"])
    except (OSError, ValueError, UnicodeError):
        return False, None
    return current.fingerprint == captured.fingerprint, current.fingerprint


def _failure_receipt(metrics: dict[str, Any], plan: dict[str, Any], profile: str,
                     captured: Any, execution: dict[str, Any], reason: str,
                     snapshot_after: str | None) -> dict[str, Any]:
    telemetry = execution.get("telemetry", {})
    return {
        "schema_version": 1,
        "mode": "live_token_offload_receipt",
        "profile": profile,
        "task_kind": metrics["task_kind"],
        "route": "free_context_worker",
        "provider": "freellmapi",
        "requested_provider": "freellmapi",
        "requested_model": "auto",
        "worker_outcome": execution.get("outcome", "validation_failed"),
        "worker_exit_status": execution.get("exit_code"),
        "failure_reason": reason,
        "elapsed_ms": execution.get("elapsed_ms"),
        "estimated_raw_tokens": plan["estimated_raw_tokens"],
        "captured_raw_bytes": sum(len(entry.data) for entry in captured.entries),
        "estimated_evidence_pack_tokens": None,
        "estimated_verification_evidence_tokens": None,
        "estimated_compact_handoff_tokens": None,
        "estimated_premium_context_avoided": None,
        "input_tokens": telemetry.get("input_tokens"),
        "cached_input_tokens": telemetry.get("cached_input_tokens"),
        "output_tokens": telemetry.get("output_tokens"),
        "reasoning_output_tokens": telemetry.get("reasoning_output_tokens"),
        "served_model": None,
        "served_provider": None,
        "retry_count": telemetry.get("retry_count"),
        "fallback_count": telemetry.get("fallback_count"),
        "validation_result": "rejected",
        "evidence_pack_status": None,
        "native_fallback_recommended": True,
        "snapshot_before": captured.fingerprint,
        "snapshot_after": snapshot_after,
        "actual_premium_parent_usage": None,
        "billing_verified": False,
        "subscription_allowance_verified": False,
        "quota_fallback": False,
        "artifacts": {"receipt": "receipt.json", "evidence_pack": None},
    }


def _success_receipt(metrics: dict[str, Any], plan: dict[str, Any], profile: str,
                     captured: Any, execution: dict[str, Any], pack: dict[str, Any],
                     pack_tokens: int, evidence_tokens: int,
                     efficiency: Any, manifest: dict[str, Any],
                     snapshot_after: str) -> dict[str, Any]:
    receipt = efficiency.make_offload_receipt(manifest, metrics, pack, profile)
    telemetry = execution["telemetry"]
    receipt.update({
        "mode": "live_token_offload_receipt",
        "requested_provider": "freellmapi",
        "requested_model": "auto",
        "worker_outcome": execution["outcome"],
        "worker_exit_status": execution["exit_code"],
        "elapsed_ms": execution["elapsed_ms"],
        "input_tokens": telemetry["input_tokens"],
        "cached_input_tokens": telemetry["cached_input_tokens"],
        "output_tokens": telemetry["output_tokens"],
        "reasoning_output_tokens": telemetry["reasoning_output_tokens"],
        "served_model": None,
        "served_provider": None,
        "retry_count": telemetry["retry_count"],
        "fallback_count": telemetry["fallback_count"],
        "validation_result": "accepted",
        "evidence_pack_status": pack["status"],
        "native_fallback_recommended": False,
        "snapshot_before": captured.fingerprint,
        "snapshot_after": snapshot_after,
        "actual_premium_parent_usage": None,
        "subscription_allowance_verified": False,
        "artifacts": {"receipt": "receipt.json", "evidence_pack": "evidence-pack.json"},
    })
    # Preserve the locally measured value even if receipt internals evolve.
    receipt["estimated_evidence_pack_tokens"] = pack_tokens
    compact_tokens = pack_tokens + evidence_tokens
    raw_tokens = plan["estimated_raw_tokens"]
    avoided = max(0, raw_tokens - compact_tokens)
    receipt.update({
        "captured_raw_bytes": sum(len(entry.data) for entry in captured.entries),
        "estimated_verification_evidence_tokens": evidence_tokens,
        "estimated_compact_handoff_tokens": compact_tokens,
        "estimated_premium_context_avoided": avoided,
        "estimated_reduction_fraction": round(avoided / raw_tokens, 4) if raw_tokens else 0.0,
    })
    return receipt


def run_action(action: str, workspace: Path | None, request_path: Path | None,
               profile: str, codex_prefix: Sequence[str] | None,
               artifacts: Path | None, timeout_seconds: float,
               *, environment: Mapping[str, str] | None = None) -> tuple[dict[str, Any], int]:
    """Execute doctor, dry-run, or one live worker invocation."""
    if action not in {"doctor", "dry-run", "run"}:
        raise ValueError("Unknown worker action")
    if action != "doctor" and (
            not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or
            not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise ValueError("Invalid worker timeout")
    env = _environment(environment)
    scope = _load_local("offload_scope")
    endpoint = scope.validate_endpoint(env.get("FREELLMAPI_BASE_URL", DEFAULT_BASE_URL))
    prefix = _resolve_codex_prefix(codex_prefix, env)
    key_configured = bool(env.get(SECRET_ENV_KEY))
    if action == "doctor":
        return ({
            "schema_version": 1,
            "mode": "free_context_worker_doctor",
            "codex_available": prefix is not None,
            "key_configured": key_configured,
            "endpoint_configured": bool(endpoint),
            "gateway_probed": False,
            "runtime_model_verified": False,
            "quota_fallback": False,
            "notice": "Offline prerequisite check only; no gateway request was made.",
        }, 0)
    if workspace is None or request_path is None:
        raise ValueError("Workspace and request are required")
    workspace = workspace.resolve(strict=True)
    request_path = request_path.resolve(strict=True)
    efficiency = _load_local("efficiency")
    manifest = efficiency.read_json(MANIFEST)
    efficiency.validate_manifest(manifest)
    request = efficiency.read_json(request_path)
    scope.validate_worker_request(request)
    captured = scope.capture_scope(workspace, request["approved_paths"])
    expected = request.get("expected_snapshot")
    if expected is not None and expected != captured.fingerprint:
        return ({
            "schema_version": 1, "status": "failed", "route": "native",
            "reason_code": "snapshot_mismatch", "native_fallback_recommended": True,
            "quota_fallback": False,
        }, 3)
    provider_available = key_configured and prefix is not None
    metrics, plan = _gate(
        request, captured, profile, provider_available, efficiency, manifest
    )
    if not provider_available:
        # Preserve the cost-gate reason for genuinely small work while still
        # recording real provider availability in the production plan.
        _, eligible_plan = _gate(request, captured, profile, True, efficiency, manifest)
        if eligible_plan["route"] != "free_context_worker":
            return _fallback(eligible_plan), 0
        missing = "missing_key" if not key_configured else "codex_unavailable"
        return _fallback(plan, missing), 0
    if plan["route"] != "free_context_worker":
        return _fallback(plan), 0
    adapter = _load_local("codex_exec_adapter")
    preview_argv = adapter.build_codex_exec_argv(
        prefix, Path("<staged-workspace>"), OUTPUT_SCHEMA, Path("<worker-output.json>"),
        endpoint=endpoint,
    )
    if action == "dry-run":
        return ({
            "schema_version": 1,
            "status": "ready",
            "route": "free_context_worker",
            "reason_codes": plan["reason_codes"],
            "snapshot": captured.fingerprint,
            "approved_files": [entry.path for entry in captured.entries],
            "estimated_raw_tokens": plan["estimated_raw_tokens"],
            "target_pack_tokens": plan["target_pack_tokens"],
            "max_pack_tokens": plan["max_pack_tokens"],
            "requested_model": "auto",
            "command_preview_windows": adapter.format_command(preview_argv, platform="windows"),
            "command_preview_posix": adapter.format_command(preview_argv, platform="posix"),
            "network_requests": 0,
            "quota_fallback": False,
            "runtime_model_verified": False,
        }, 0)

    artifact_dir = _artifact_directory(artifacts, workspace)
    output_path = artifact_dir / "worker-output.json"
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="omnicodex-stage-") as stage_parent_name:
        stage_parent = Path(stage_parent_name)
        stage, staged = scope.stage_captured_scope(captured, stage_parent)
        if staged.fingerprint != captured.fingerprint:
            raise ValueError("Staged snapshot mismatch")
        argv = adapter.build_codex_exec_argv(
            prefix, stage, OUTPUT_SCHEMA, output_path, endpoint=endpoint
        )
        execution = adapter.execute_codex_exec(
            argv, _prompt(request, captured, plan), timeout_seconds=timeout_seconds,
            environment=env,
        )
    unchanged, snapshot_after = _scope_unchanged(workspace, request, captured, scope)
    if not unchanged:
        reason = "workspace_mutated"
    elif execution["outcome"] != "completed":
        if execution["outcome"] == "timeout":
            reason = "worker_timeout"
        elif execution["outcome"] in {"missing_output", "stale_output"}:
            reason = "invalid_pack"
        else:
            reason = "worker_failed"
    else:
        reason = ""
    pack: dict[str, Any] | None = None
    pack_tokens: int | None = None
    evidence_tokens: int | None = None
    if not reason:
        try:
            pack = execution["final_message"]
            pack_tokens, evidence_tokens = _validate_pack(
                pack, request, captured, workspace, plan, efficiency, scope, manifest
            )
            unchanged, snapshot_after = _scope_unchanged(workspace, request, captured, scope)
            if not unchanged:
                reason = "workspace_mutated"
        except (OSError, ValueError, UnicodeError, TypeError, AttributeError, KeyError):
            reason = "invalid_pack"
    if reason:
        receipt = _failure_receipt(
            metrics, plan, profile, captured, execution, reason, snapshot_after
        )
        receipt["orchestration_elapsed_ms"] = int((time.monotonic() - started) * 1000)
        _write_json_new(artifact_dir / "receipt.json", receipt)
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        return ({
            "schema_version": 1,
            "status": "failed",
            "route": "native",
            "reason_code": reason,
            "native_fallback_recommended": True,
            "artifacts": {"directory": str(artifact_dir), "receipt": "receipt.json"},
            "quota_fallback": False,
        }, 3)
    if pack is None or pack_tokens is None or evidence_tokens is None or snapshot_after is None:
        raise ValueError("Accepted EvidencePack state is incomplete")
    receipt = _success_receipt(
        metrics, plan, profile, captured, execution, pack, pack_tokens, evidence_tokens,
        efficiency, manifest, snapshot_after,
    )
    receipt["orchestration_elapsed_ms"] = int((time.monotonic() - started) * 1000)
    _write_json_new(artifact_dir / "evidence-pack.json", pack)
    _write_json_new(artifact_dir / "receipt.json", receipt)
    try:
        output_path.unlink()
    except FileNotFoundError:
        pass
    return ({
        "schema_version": 1,
        "status": pack["status"],
        "route": "free_context_worker",
        "snapshot": captured.fingerprint,
        "estimated_raw_tokens": plan["estimated_raw_tokens"],
        "estimated_evidence_pack_tokens": pack_tokens,
        "estimated_verification_evidence_tokens": evidence_tokens,
        "estimated_compact_handoff_tokens": pack_tokens + evidence_tokens,
        "artifacts": {
            "directory": str(artifact_dir),
            "receipt": "receipt.json",
            "evidence_pack": "evidence-pack.json",
        },
        "quota_fallback": False,
    }, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "dry-run", "run"))
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--profile", default="balanced",
                        choices=("auto", "economy", "balanced", "quality", "max"))
    parser.add_argument("--codex", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        result, code = run_action(
            args.action, args.workspace, args.request, args.profile,
            (str(args.codex),) if args.codex else None,
            args.artifacts, args.timeout,
        )
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError, KeyError):
        print(json.dumps({
            "error": "ValidationError",
            "action": "Check the bounded worker inputs and local prerequisites.",
        }), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
