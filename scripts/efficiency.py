#!/usr/bin/env python3
"""Offline capability diagnostics and advisory plans. No installs or tool execution."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "integrations" / "efficiency.json"
MAX_INPUT_BYTES = 262144
MAX_PACK_BYTES = 524288
PROVIDERS = {"context-mode", "codebase-memory-mcp"}
PROFILES = {"economy", "balanced", "quality", "max", "auto"}
TASKS = {"structural", "large-output", "implementation", "review"}
OFFLOAD_TASKS = {"repo_scout", "bulk_file_read", "log_distill", "diff_analysis", "long_doc_digest"}
DATA_CLASSES = {"public", "approved_private", "sensitive"}
PACK_STATUSES = {"completed", "blocked", "needs_review"}
EVIDENCE_KINDS = {"source", "log", "diff", "doc"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def parse_bounded_json(raw: bytes | str, limit: int = MAX_INPUT_BYTES,
                       max_depth: int = 32) -> Any:
    """Reject ambiguous, nonfinite, oversized or deeply nested JSON before allocation."""
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            require(key not in value, "Duplicate JSON key")
            value[key] = item
        return value

    def reject_constant(value: str) -> Any:
        raise ValueError("Nonfinite JSON constant")

    def finite_float(value: str) -> float:
        parsed = float(value)
        require(math.isfinite(parsed), "Nonfinite JSON number")
        return parsed

    try:
        require(isinstance(raw, (bytes, str)), "JSON must be text")
        require(len(raw if isinstance(raw, bytes) else raw.encode("utf-8")) <= limit,
                "JSON exceeds byte limit")
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        depth, quoted, escaped = 0, False, False
        for character in text:
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in "[{":
                depth += 1
                require(depth <= max_depth, "JSON nesting exceeds limit")
            elif character in "]}":
                depth -= 1
        return json.loads(text, object_pairs_hook=unique, parse_constant=reject_constant,
                          parse_float=finite_float)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise ValueError("Invalid bounded JSON") from None


def read_json(path: Path, limit: int = MAX_INPUT_BYTES) -> dict[str, Any]:
    # Bound allocation even if a file grows while being read. Never echo its contents.
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "JSON file exceeds the configured input limit")
    data = parse_bounded_json(raw, limit)
    require(isinstance(data, dict), "JSON root must be an object")
    return data


def validate_manifest(data: dict[str, Any]) -> None:
    require(type(data.get("schema_version")) is int and data["schema_version"] == 1,
            "Unsupported manifest schema")
    require(set(data.get("profiles", {})) == PROFILES, "Manifest profile mismatch")
    require(set(data.get("providers", {})) == PROVIDERS, "Manifest provider mismatch")
    for settings in data["profiles"].values():
        words = settings.get("handoff_target_words")
        require(type(words) is int and 50 <= words <= 2000, "Invalid handoff target")
    for settings in data["providers"].values():
        tools = settings.get("required_tools")
        require(isinstance(tools, list) and bool(tools), "Required tool list missing")
        require(all(isinstance(tool, str) and tool for tool in tools), "Invalid tool name")
    policy = data.get("policy", {})
    for key in ("explicit_opt_in", "one_output_compressor", "native_fallback",
                "raw_evidence_required"):
        require(policy.get(key) is True, "Required safety policy disabled")
    require(policy.get("automatic_installation") is False, "Automatic installation forbidden")
    offload = data.get("token_offload", {})
    require(offload.get("provider") == "gemini_direct", "Token offload provider mismatch")
    require(isinstance(offload.get("model_selector"), str) and offload["model_selector"],
            "Token offload model selector missing")
    require(offload.get("read_only_default") is True, "Token offload must default read-only")
    require(type(offload.get("chars_per_token")) is int and 1 <= offload["chars_per_token"] <= 16,
            "Invalid token estimator")
    require(set(offload.get("supported_tasks", {})) == OFFLOAD_TASKS,
            "Token offload task set mismatch")
    for gate in offload["supported_tasks"].values():
        require(gate.get("secondary_metric") in
                {"file_count", "diff_lines", "log_bytes", "search_hits", "estimated_chars"},
                "Invalid token offload secondary metric")
        require(type(gate.get("secondary_min")) is int and gate["secondary_min"] > 0,
                "Invalid token offload secondary threshold")
        fraction = gate.get("min_token_fraction")
        require(isinstance(fraction, (int, float)) and not isinstance(fraction, bool)
                and 0 < float(fraction) <= 1, "Invalid token offload fraction")
    for key in ("workspace_opt_in_required", "sensitive_externalization_forbidden",
                "root_acceptance_required", "raw_evidence_retrieval_required"):
        require(offload.get(key) is True, "Required token offload policy disabled")
    require(offload.get("quota_fallback") is False, "Quota fallback must stay disabled")
    require(offload.get("automatic_installation") is False,
            "Token offload automatic installation forbidden")
    for settings in data["profiles"].values():
        for key in ("offload_min_estimated_tokens", "offload_target_pack_tokens",
                    "offload_max_pack_tokens"):
            require(type(settings.get(key)) is int and settings[key] > 0,
                    "Invalid profile token offload budget")
        require(settings["offload_target_pack_tokens"] <= settings["offload_max_pack_tokens"],
                "Invalid profile pack budget order")


def validate_inventory(data: dict[str, Any]) -> None:
    require(type(data.get("schema_version")) is int and data["schema_version"] == 1,
            "Unsupported inventory schema")
    require(isinstance(data.get("session_id"), str) and bool(data["session_id"]),
            "Inventory needs a nonempty session_id")
    providers = data.get("providers")
    require(isinstance(providers, dict), "Inventory providers must be an object")
    require(set(providers) <= PROVIDERS, "Unknown inventory provider")
    for state in providers.values():
        require(isinstance(state, dict), "Provider state must be an object")
        require(type(state.get("probe_ok", False)) is bool, "probe_ok must be a boolean")
        tools = state.get("tools", [])
        require(isinstance(tools, list), "tools must be a list of server-local names")
        require(all(isinstance(tool, str) and tool for tool in tools), "Invalid tool name")
        require(len(set(tools)) == len(tools), "Duplicate tool names")
        if "index_snapshot" in state:
            require(isinstance(state["index_snapshot"], str), "Invalid index_snapshot")


def availability(manifest: dict[str, Any], inventory: dict[str, Any] | None,
                 session_id: str | None) -> dict[str, dict[str, Any]]:
    result = {}
    for name, config in manifest["providers"].items():
        state = (inventory or {}).get("providers", {}).get(name, {})
        missing = sorted(set(config["required_tools"]) - set(state.get("tools", [])))
        same_session = bool(session_id and inventory and
                            inventory["session_id"] == session_id)
        result[name] = {
            "usable_from_supplied_evidence": bool(same_session and
                                                    state.get("probe_ok") is True and
                                                    not missing),
            "session_matches": same_session,
            "missing_tools": missing,
            "probe_reported_ok": state.get("probe_ok") is True,
        }
    return result


def make_plan(manifest: dict[str, Any], inventory: dict[str, Any] | None,
              profile: str, task: str, enabled: set[str], session_id: str | None,
              snapshot: str | None) -> dict[str, Any]:
    validate_manifest(manifest)
    if inventory is not None:
        validate_inventory(inventory)
    require(profile in PROFILES and task in TASKS, "Unknown profile or task")
    require(enabled <= PROVIDERS, "Unknown requested provider")
    available = availability(manifest, inventory, session_id)
    provider = "native"
    reason = "Use targeted native tools; no suitable opted-in provider is evidenced."
    if task == "structural" and "codebase-memory-mcp" in enabled:
        name = "codebase-memory-mcp"
        state = (inventory or {}).get("providers", {}).get(name, {})
        if available[name]["usable_from_supplied_evidence"] and snapshot and \
                state.get("index_snapshot") == snapshot:
            provider = name
            reason = "Matching supplied graph snapshot; verify relevant source before decisions."
        else:
            reason = "Graph unavailable or snapshot unconfirmed/stale: use native search and reads."
    elif task == "large-output" and "context-mode" in enabled:
        if available["context-mode"]["usable_from_supplied_evidence"]:
            provider = "context-mode"
            reason = "Retrieve bounded evidence through the opted-in context provider."
    return {
        "schema_version": 1,
        "mode": "advisory_dry_run",
        "profile": profile,
        "task": task,
        "provider": provider,
        "reason": reason,
        "output_compressor": "context-mode" if provider == "context-mode" else "none",
        "handoff_target_words": manifest["profiles"][profile]["handoff_target_words"],
        "handoff_target_is_soft": True,
        "quality_checks_required": True,
        "raw_evidence_required": True,
        "runtime_model_verified": False,
        "model_switch_performed": False,
        "evidence": "Supplied inventory only; this script does not probe live MCP servers.",
        "availability": available,
    }



def validate_offload_metrics(data: dict[str, Any], require_provider_available: bool = True) -> None:
    require(type(data.get("schema_version")) is int and data["schema_version"] == 1,
            "Unsupported offload metrics schema")
    require(data.get("task_kind") in OFFLOAD_TASKS, "Unknown offload task")
    require(data.get("data_classification") in DATA_CLASSES, "Unknown data classification")
    require(type(data.get("external_offload_approved")) is bool, "Approval must be boolean")
    if require_provider_available:
        require(type(data.get("provider_available")) is bool,
                "Provider availability must be boolean")
    elif "provider_available" in data:
        require(type(data["provider_available"]) is bool,
                "Provider availability must be boolean")
    for key in ("estimated_chars", "file_count", "diff_lines", "log_bytes", "search_hits"):
        require(type(data.get(key)) is int and 0 <= data[key] <= 10_000_000_000,
                "Invalid offload metric")
    units = data.get("independent_units", 1)
    require(type(units) is int and 1 <= units <= 1000, "Invalid independent unit count")


def _estimated_raw_tokens(manifest: dict[str, Any], metrics: dict[str, Any]) -> int:
    chars = metrics["estimated_chars"] or metrics["log_bytes"]
    return (chars + manifest["token_offload"]["chars_per_token"] - 1) // \
        manifest["token_offload"]["chars_per_token"]


def make_offload_plan(manifest: dict[str, Any], metrics: dict[str, Any],
                      profile: str) -> dict[str, Any]:
    validate_manifest(manifest)
    validate_offload_metrics(metrics)
    require(profile in PROFILES, "Unknown profile")
    raw_tokens = _estimated_raw_tokens(manifest, metrics)
    reasons: list[str] = []
    if metrics["data_classification"] == "sensitive":
        reasons.append("sensitive_data")
    if not metrics["external_offload_approved"]:
        reasons.append("workspace_not_opted_in")
    if not metrics["provider_available"]:
        reasons.append("provider_not_available")
    settings = manifest["profiles"][profile]
    offload = manifest["token_offload"]
    route = "native"
    if not reasons:
        threshold = settings["offload_min_estimated_tokens"]
        if raw_tokens >= threshold:
            reasons.append("estimated_context_over_profile_threshold")
            route = "free_context_worker"
        else:
            gate = offload["supported_tasks"][metrics["task_kind"]]
            secondary = metrics[gate["secondary_metric"]]
            floor = int(threshold * float(gate["min_token_fraction"]) + 0.999999)
            if secondary >= gate["secondary_min"] and raw_tokens >= floor:
                reasons.extend(("task_volume_threshold",
                                "metric:" + gate["secondary_metric"]))
                route = "free_context_worker"
    if not reasons:
        reasons.append("context_below_offload_threshold")
    enabled = route == "free_context_worker"
    return {
        "schema_version": 1,
        "mode": "advisory_offload_plan",
        "profile": profile,
        "task_kind": metrics["task_kind"],
        "route": route,
        "provider": offload["provider"] if enabled else None,
        "model_selector": offload["model_selector"] if enabled else None,
        "read_only_worker": bool(enabled and offload["read_only_default"]),
        "parallel_read_only_ok": bool(
            enabled and metrics.get("independent_units", 1) > 1 and
            metrics["task_kind"] in {"repo_scout", "bulk_file_read", "long_doc_digest"}
        ),
        "estimated_raw_tokens": raw_tokens,
        "target_pack_tokens": settings["offload_target_pack_tokens"] if enabled else None,
        "max_pack_tokens": settings["offload_max_pack_tokens"] if enabled else None,
        "reason_codes": reasons,
        "root_acceptance_required": True,
        "quota_fallback": False,
        "network_requests": 0,
        "runtime_verified": False,
        "note": "Advisory only; deterministic tools should narrow scope before any external offload.",
    }


def _repo_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 4096:
        return False
    if "\\" in value or "\x00" in value or value.startswith("/") or \
            (len(value) >= 3 and value[1:3] == ":/"):
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _bounded_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit and "\x00" not in value


def validate_evidence_pack(pack: dict[str, Any]) -> None:
    require(isinstance(pack, dict) and type(pack.get("schema_version")) is int and
            pack["schema_version"] == 1, "Unsupported EvidencePack schema")
    require(pack.get("status") in PACK_STATUSES, "Invalid EvidencePack status")
    require(pack.get("task_kind") in OFFLOAD_TASKS, "Invalid EvidencePack task")
    require(_bounded_text(pack.get("snapshot"), 512), "Invalid EvidencePack snapshot")
    require(_bounded_text(pack.get("summary"), 4000), "Invalid EvidencePack summary")
    allowed = {"schema_version", "status", "task_kind", "snapshot", "summary",
               "relevant_files", "findings", "risks", "unknowns", "validation"}
    require(set(pack) <= allowed, "Unknown EvidencePack field")
    files = pack.get("relevant_files")
    require(isinstance(files, list) and len(files) <= 128 and
            all(_repo_relative_path(path) for path in files) and
            len(set(files)) == len(files), "Invalid EvidencePack file list")
    findings = pack.get("findings")
    require(isinstance(findings, list) and len(findings) <= 64, "Invalid EvidencePack findings")
    if pack["status"] == "completed":
        require(bool(findings), "Completed EvidencePack needs findings")
    for finding in findings:
        require(isinstance(finding, dict) and set(finding) == {"claim", "evidence"} and
                _bounded_text(finding["claim"], 2000), "Invalid EvidencePack finding")
        evidence = finding["evidence"]
        require(isinstance(evidence, list) and 1 <= len(evidence) <= 8,
                "Invalid EvidencePack evidence")
        for item in evidence:
            require(isinstance(item, dict) and
                    set(item) == {"path", "start_line", "end_line", "kind"},
                    "Invalid EvidencePack evidence shape")
            require(_repo_relative_path(item["path"]) and item["kind"] in EVIDENCE_KINDS,
                    "Invalid EvidencePack evidence reference")
            require(item["path"] in files, "EvidencePack citation missing from relevant files")
            require(type(item["start_line"]) is int and type(item["end_line"]) is int and
                    1 <= item["start_line"] <= item["end_line"] and
                    item["end_line"] - item["start_line"] <= 500,
                    "Invalid EvidencePack line range")
    for key in ("risks", "unknowns"):
        values = pack.get(key)
        require(isinstance(values, list) and len(values) <= 32 and
                all(_bounded_text(value, 1500) for value in values),
                "Invalid EvidencePack risk/unknown list")
    validation = pack.get("validation")
    require(isinstance(validation, list) and len(validation) <= 32,
            "Invalid EvidencePack validation")
    for item in validation:
        require(isinstance(item, dict) and
                set(item) == {"check", "status", "reference"} and
                _bounded_text(item["check"], 1000) and
                item["status"] in {"passed", "failed", "not_run"} and
                isinstance(item["reference"], str) and len(item["reference"]) <= 2000,
                "Invalid EvidencePack validation item")


def estimate_pack_tokens(manifest: dict[str, Any], pack: dict[str, Any]) -> int:
    validate_evidence_pack(pack)
    raw = json.dumps(pack, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    raw_bytes = raw.encode("utf-8")
    require(len(raw_bytes) <= MAX_PACK_BYTES, "EvidencePack too large")
    divisor = manifest["token_offload"]["chars_per_token"]
    return (len(raw_bytes) + divisor - 1) // divisor


def make_offload_receipt(manifest: dict[str, Any], metrics: dict[str, Any],
                         pack: dict[str, Any], profile: str) -> dict[str, Any]:
    plan = make_offload_plan(manifest, metrics, profile)
    require(plan["route"] == "free_context_worker", "Receipt needs an offload route")
    validate_evidence_pack(pack)
    require(pack["task_kind"] == metrics["task_kind"], "EvidencePack task mismatch")
    pack_tokens = estimate_pack_tokens(manifest, pack)
    raw_tokens = plan["estimated_raw_tokens"]
    avoided = max(0, raw_tokens - pack_tokens)
    return {
        "schema_version": 1,
        "mode": "estimated_token_offload_receipt",
        "profile": profile,
        "task_kind": metrics["task_kind"],
        "route": plan["route"],
        "provider": plan["provider"],
        "model_selector": plan["model_selector"],
        "estimated_raw_tokens": raw_tokens,
        "estimated_evidence_pack_tokens": pack_tokens,
        "estimated_premium_context_avoided": avoided,
        "estimated_reduction_fraction": round(avoided / raw_tokens, 4) if raw_tokens else 0.0,
        "within_pack_budget": pack_tokens <= plan["max_pack_tokens"],
        "billing_verified": False,
        "runtime_verified": False,
        "quota_fallback": False,
        "note": "Routing telemetry only; compare live root and worker usage when available.",
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=[
        "doctor", "plan", "offload-plan", "validate-pack", "offload-receipt"
    ])
    parser.add_argument("--inventory", type=Path,
                        help="Sanitized, current-session capability inventory JSON")
    parser.add_argument("--session", help="Current session ID; must match the inventory")
    parser.add_argument("--snapshot", help="Current workspace fingerprint, including dirty files")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="balanced")
    parser.add_argument("--task", choices=sorted(TASKS), default="implementation")
    parser.add_argument("--enable", action="append", choices=sorted(PROVIDERS), default=[])
    parser.add_argument("--metrics", type=Path, help="Sanitized token-offload metrics JSON")
    parser.add_argument("--pack", type=Path, help="EvidencePack JSON")
    args = parser.parse_args(argv)
    try:
        manifest = read_json(MANIFEST)
        validate_manifest(manifest)
        inventory = read_json(args.inventory) if args.inventory else None
        if inventory is not None:
            validate_inventory(inventory)
        if args.action == "doctor":
            report = {
                "mode": "read_only_diagnostics",
                "manifest_valid": True,
                "binaries_on_path": {name: shutil.which(name) is not None for name in
                                     ("codex", "claude", "context-mode",
                                      "codebase-memory-mcp", "rtk")},
                "availability": availability(manifest, inventory, args.session),
                "token_offload_provider": manifest["token_offload"]["provider"],
                "token_offload_quota_fallback": False,
                "live_mcp_checked": False,
                "hooks_checked": False,
                "runtime_model_verified": False,
                "notice": "Binary presence is not MCP/provider availability, permission, or compatibility.",
            }
        elif args.action == "plan":
            report = make_plan(manifest, inventory, args.profile, args.task,
                               set(args.enable), args.session, args.snapshot)
        elif args.action == "offload-plan":
            require(args.metrics is not None, "Metrics are required")
            report = make_offload_plan(manifest, read_json(args.metrics), args.profile)
        elif args.action == "validate-pack":
            require(args.pack is not None, "EvidencePack is required")
            pack = read_json(args.pack, MAX_PACK_BYTES)
            validate_evidence_pack(pack)
            report = {
                "mode": "evidence_pack_validation",
                "valid": True,
                "estimated_pack_tokens": estimate_pack_tokens(manifest, pack),
                "runtime_model_verified": False,
            }
        else:
            require(args.metrics is not None and args.pack is not None,
                    "Metrics and EvidencePack are required")
            report = make_offload_receipt(
                manifest, read_json(args.metrics),
                read_json(args.pack, MAX_PACK_BYTES), args.profile
            )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError, KeyError):
        print(json.dumps({"error": "ValidationError",
                          "action": "Check the documented input schema."}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
