#!/usr/bin/env python3
"""Offline capability diagnostics and advisory plans. No installs or tool execution."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "integrations" / "efficiency.json"
MAX_INPUT_BYTES = 262144
PROVIDERS = {"context-mode", "codebase-memory-mcp"}
PROFILES = {"economy", "balanced", "quality", "max", "auto"}
TASKS = {"structural", "large-output", "implementation", "review"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict[str, Any]:
    # Bound allocation even if a file grows while being read. Never echo its contents.
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    require(len(raw) <= MAX_INPUT_BYTES, "JSON file exceeds the 256 KiB limit")
    data = json.loads(raw)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["doctor", "plan"])
    parser.add_argument("--inventory", type=Path,
                        help="Sanitized, current-session capability inventory JSON")
    parser.add_argument("--session", help="Current session ID; must match the inventory")
    parser.add_argument("--snapshot", help="Current workspace fingerprint, including dirty files")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="balanced")
    parser.add_argument("--task", choices=sorted(TASKS), default="implementation")
    parser.add_argument("--enable", action="append", choices=sorted(PROVIDERS), default=[])
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
                                     ("codex", "claude", "context-mode", "codebase-memory-mcp", "rtk")},
                "availability": availability(manifest, inventory, args.session),
                "live_mcp_checked": False,
                "hooks_checked": False,
                "runtime_model_verified": False,
                "notice": "Binary presence is not MCP availability, permission, or compatibility.",
            }
        else:
            report = make_plan(manifest, inventory, args.profile, args.task,
                               set(args.enable), args.session, args.snapshot)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, UnicodeError, TypeError, AttributeError) as exc:
        # Parse errors can contain input fragments. Do not print config or credential data.
        message = "Malformed JSON" if isinstance(exc, json.JSONDecodeError) else type(exc).__name__
        print(json.dumps({"error": message, "action": "Check the documented input schema."}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
