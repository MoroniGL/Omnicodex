#!/usr/bin/env python3
"""Per-session OmniCodex policy switching for Codex UserPromptSubmit hooks.

This helper never changes the running model, permissions, provider, or persistent
defaults by itself. It records a session-scoped policy override and injects
bounded developer context on later prompts in the same Codex session.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

PROFILES = ("auto", "economy", "balanced", "quality", "max")
MODEL_KEYS = ("model", "model_reasoning_effort")
MAX_STDIN_BYTES = 64 * 1024
MAX_FILE_BYTES = 1024 * 1024
SCHEMA_VERSION = 1
POLICIES = {
    "auto": "Select bounded workers by task risk and complexity; keep the current parent model.",
    "economy": "Prefer the least expensive capable installed worker while preserving tests and review.",
    "balanced": "Keep planning and acceptance with the parent; delegate bounded work and review material risks.",
    "quality": "Favor thorough verification and independent review for consequential changes.",
    "max": "Use the configured strong parent while avoiding premium calls for mechanical work.",
}

class SessionSwitchError(RuntimeError):
    """Fixed error codes only; never echo prompt or local configuration contents."""

def require(condition: bool, code: str) -> None:
    if not condition:
        raise SessionSwitchError(code)

def absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))

def guard(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode), "symlink_path_refused")
        require(not (getattr(info, "st_file_attributes", 0) & 0x400), "reparse_path_refused")

def read(path: Path, limit: int = MAX_FILE_BYTES) -> bytes | None:
    guard(path)
    try:
        with path.open("rb") as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "non_regular_file_refused")
            data = stream.read(limit + 1)
    except FileNotFoundError:
        return None
    require(len(data) <= limit, "file_size_limit")
    return data

def decode(data: bytes | None) -> str:
    try:
        return (data or b"").decode("utf-8-sig")
    except UnicodeError:
        raise SessionSwitchError("utf8_required") from None

def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result

def parse_json(data: bytes | None) -> dict[str, Any] | None:
    if data is None:
        return None
    try:
        value = json.loads(decode(data), object_pairs_hook=unique_object)
    except (ValueError, TypeError):
        raise SessionSwitchError("invalid_json") from None
    require(isinstance(value, dict), "invalid_json")
    return value

def default_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return absolute(Path(configured))
    source = absolute(Path(__file__))
    if source.parent.name == "omnicodex":
        return source.parent.parent
    return absolute(Path.home() / ".codex")

def preferences_path(home: Path) -> Path:
    return home / "omnicodex" / "preferences.json"

def saved_profile(home: Path) -> tuple[bool, str]:
    value = parse_json(read(preferences_path(home)))
    if value is None:
        return False, "auto"
    enabled = value.get("enabled")
    profile = value.get("profile")
    require(type(enabled) is bool and profile in PROFILES, "invalid_preferences")
    return enabled, str(profile)

def recommendation(home: Path, profile: str) -> dict[str, str]:
    if profile == "auto":
        return {}
    path = home / f"omnicodex-{profile}.config.toml"
    raw = read(path)
    require(raw is not None, "profile_not_installed")
    try:
        data = tomllib.loads(decode(raw))
    except tomllib.TOMLDecodeError:
        raise SessionSwitchError("invalid_profile_toml") from None
    result = {}
    for key in MODEL_KEYS:
        value = data.get(key)
        require(isinstance(value, str) and value, "profile_missing_model")
        result[key] = value
    return result


def gemini_offload_status() -> dict[str, Any]:
    """Return local Gemini Direct configuration without treating it as reachability."""

    try:
        from scripts.providers.gemini import GeminiProvider
        status = GeminiProvider(environment=os.environ).status()
    except (ImportError, OSError, ValueError, TypeError, AttributeError):
        return {"provider": "gemini_direct", "model": None, "configured": False}
    if (not isinstance(status, dict) or status.get("provider") != "gemini_direct"
            or not isinstance(status.get("configured"), bool)
            or status.get("model") is not None and not isinstance(status.get("model"), str)):
        return {"provider": "gemini_direct", "model": None, "configured": False}
    return {"provider": "gemini_direct", "model": status["model"],
            "configured": status["configured"]}

def session_key(session_id: str) -> str:
    require(isinstance(session_id, str) and 1 <= len(session_id) <= 512, "invalid_session_id")
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

def session_path(home: Path, session_id: str) -> Path:
    return home / "omnicodex" / "session-overrides" / f"{session_key(session_id)}.json"

def load_session(home: Path, session_id: str) -> dict[str, Any] | None:
    value = parse_json(read(session_path(home, session_id), 64 * 1024))
    if value is None:
        return None
    require(value.get("schema_version") == SCHEMA_VERSION, "unsupported_session_state")
    require(value.get("profile") in PROFILES, "invalid_session_state")
    require(value.get("session_key") == session_key(session_id), "session_state_mismatch")
    pending = value.get("persist_requested")
    require(pending is None or pending in PROFILES, "invalid_session_state")
    return value

def atomic_write(path: Path, data: bytes | None) -> None:
    guard(path)
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".omni-session-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        guard(path)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)

def save_session(home: Path, session_id: str, profile: str,
                 persist_requested: str | None = None) -> dict[str, Any]:
    require(profile in PROFILES, "invalid_profile")
    value = {
        "schema_version": SCHEMA_VERSION,
        "session_key": session_key(session_id),
        "profile": profile,
        "persist_requested": persist_requested,
    }
    atomic_write(session_path(home, session_id),
                 (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return value

def clear_session(home: Path, session_id: str) -> None:
    atomic_write(session_path(home, session_id), None)

def parse_command(prompt: str) -> dict[str, str] | None:
    require(isinstance(prompt, str), "invalid_prompt")
    text = prompt.strip()
    match = re.fullmatch(
        r"(?i)(?:omni|omnicodex)\s+(?:(?:profile|use)\s+)?"
        r"(auto|economy|balanced|quality|max)",
        text,
    )
    if match:
        return {"action": "set", "profile": match.group(1).lower()}
    match = re.fullmatch(
        r"(?i)(?:omni|omnicodex)\s+save\s+"
        r"(auto|economy|balanced|quality|max)",
        text,
    )
    if match:
        return {"action": "save", "profile": match.group(1).lower()}
    if re.fullmatch(r"(?i)(?:omni|omnicodex)\s+(?:reset|default|saved)", text):
        return {"action": "reset"}
    if re.fullmatch(r"(?i)(?:omni|omnicodex)\s+status", text):
        return {"action": "status"}
    return None

def _persist_profile(home: Path, profile: str) -> dict[str, Any]:
    """Persist an exact `omni save PROFILE` request inside the trusted hook.

    The agent tool shell can be sandboxed away from the host Python installation,
    while this already-trusted hook process has the host access needed to maintain
    CODEX_HOME. Reuse the installed defaults module directly instead of asking the
    model to run a shell command. The exact `omni save` prompt is the user's
    explicit authorization for this persistent preference change.
    """
    require(profile in PROFILES, "invalid_profile")
    tool = home / "omnicodex" / "defaults.py"
    raw_tool = read(tool)
    require(raw_tool is not None, "defaults_tool_missing")

    preferences = parse_json(read(preferences_path(home)))
    require(preferences is not None, "preferences_missing")
    expected = preferences.get("tool_sha256")
    if expected is not None:
        require(
            isinstance(expected, str)
            and hashlib.sha256(raw_tool).hexdigest() == expected,
            "defaults_tool_integrity_mismatch",
        )

    module_name = "_omnicodex_defaults_" + hashlib.sha256(
        str(tool).encode("utf-8")
    ).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(module_name, tool)
    require(spec is not None and spec.loader is not None, "defaults_tool_load_failed")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        build_plan = getattr(module, "build_plan")
        apply_plan = getattr(module, "apply_plan")
    except (AttributeError, ImportError, OSError, ValueError, TypeError):
        raise SessionSwitchError("defaults_tool_load_failed") from None

    try:
        plan = build_plan(
            home,
            profile=profile,
            enabled=True,
            recommended=True,
        )
        result = apply_plan(plan)
    except Exception as exc:
        code = getattr(exc, "args", [""])[0]
        if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,96}", code):
            raise SessionSwitchError("persistent_save_failed_" + code) from None
        raise SessionSwitchError("persistent_save_failed") from None

    enabled, saved = saved_profile(home)
    require(enabled and saved == profile, "persistent_save_not_verified")
    return result if isinstance(result, dict) else {"result": "configured"}

def context_for(home: Path, state: dict[str, Any] | None, *,
                active_model: str, command: dict[str, str] | None,
                saved_enabled: bool, saved: str,
                persistence_status: str | None = None) -> str:
    if state is None:
        effective = saved if saved_enabled else "disabled"
        scope = "saved persistent default"
        target = recommendation(home, saved) if saved_enabled and saved != "auto" else {}
    else:
        effective = str(state["profile"])
        scope = "temporary override for this Codex session only"
        target = recommendation(home, effective)

    lines = [
        "OmniCodex session control:",
        f"- Effective policy: {effective}.",
        f"- Scope: {scope}.",
        f"- Saved persistent policy: {saved if saved_enabled else 'disabled'}.",
        f"- Hook-reported active model: {active_model or 'unknown'}.",
    ]
    if effective in POLICIES:
        lines.append(f"- Policy behavior: {POLICIES[effective]}")
    if target:
        lines.append(
            "- Profile-recommended parent: "
            f"{target['model']} / reasoning {target['model_reasoning_effort']}."
        )
        if active_model:
            lines.append(
                "- Active model matches the profile recommendation: "
                f"{str(active_model == target['model']).lower()}."
            )
        lines.append(
            "- The hook cannot change the running parent model or verify reasoning effort. "
            "If the user wants the recommended parent in this same thread, tell them to use "
            "the native /model selector; do not claim the model changed until runtime UI/metadata confirms it."
        )
    else:
        lines.append("- Auto keeps the current parent model; no parent-model change is requested.")

    lines.append(
        "- Apply this policy on the next turn boundary and subsequent turns in this thread. "
        "Do not change permissions, providers, sandbox settings, or worker definitions."
    )

    pending = state.get("persist_requested") if state else None
    if persistence_status == "saved":
        lines.append(
            "- Persistent save completed inside the trusted hook and was verified "
            f"against the saved preference: {saved}."
        )
    elif persistence_status == "failed":
        lines.append(
            "- Persistent save failed inside the trusted hook. The temporary session "
            "override remains active, the saved default was not changed, and the agent "
            "must not retry persistence through its shell."
        )
    elif pending:
        if saved_enabled and saved == pending:
            lines.append("- The requested persistent profile is already saved; no persistence action remains.")
        else:
            lines.append(
                "- A persistent save request is still pending from an earlier failed attempt. "
                "Do not retry it through the agent shell. The user can retry the exact "
                f"`omni save {pending}` control message after the hook is repaired."
            )

    if command:
        action = command["action"]
        if action == "status":
            offload = gemini_offload_status()
            lines.extend((
                "- Native path: READY.",
                "- Gemini Direct offload: " +
                ("READY" if offload["configured"] else "NOT CONFIGURED") +
                f" (provider: {offload['provider']}; model: {offload['model'] or 'unconfigured'}).",
                "- Gemini Direct READY means local configuration only; connectivity was not probed.",
            ))
            lines.append("- The current user message asks only for Omni session status; answer concisely from this context.")
        elif action == "reset":
            lines.append("- The current user message cleared the temporary override; use the saved policy from this turn onward.")
        elif action == "set":
            lines.append("- The current user message selected this profile temporarily; do not persist it.")
        elif action == "save":
            lines.append(
                "- The current user message selected this profile now and explicitly "
                "authorized saving it for future chats."
            )

    return "\n".join(lines)

def process(payload: dict[str, Any], *, home: Path | None = None) -> dict[str, Any] | None:
    require(isinstance(payload, dict), "invalid_hook_input")
    require(payload.get("hook_event_name") == "UserPromptSubmit", "unsupported_hook_event")
    session_id = payload.get("session_id")
    prompt = payload.get("prompt")
    active_model = payload.get("model", "")
    require(isinstance(session_id, str), "invalid_session_id")
    require(isinstance(prompt, str), "invalid_prompt")
    require(isinstance(active_model, str), "invalid_model")

    home = absolute(home or default_home())
    guard(home)
    saved_enabled, saved = saved_profile(home)
    state = load_session(home, session_id)
    command = parse_command(prompt)
    persistence_status: str | None = None

    if command:
        action = command["action"]
        if action == "set":
            state = save_session(home, session_id, command["profile"])
        elif action == "save":
            profile = command["profile"]
            state = save_session(home, session_id, profile, profile)
            try:
                _persist_profile(home, profile)
            except (SessionSwitchError, OSError, ValueError, TypeError, KeyError):
                persistence_status = "failed"
            else:
                saved_enabled, saved = saved_profile(home)
                state = save_session(home, session_id, profile, None)
                persistence_status = "saved"
        elif action == "reset":
            clear_session(home, session_id)
            state = None
        elif action == "status":
            pass

    if state and state.get("persist_requested") and saved_enabled and saved == state["persist_requested"]:
        state = save_session(home, session_id, state["profile"], None)

    if state is None and command is None:
        return None

    context = context_for(
        home, state, active_model=active_model, command=command,
        saved_enabled=saved_enabled, saved=saved,
        persistence_status=persistence_status,
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }

def _read_stdin() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
    require(len(raw) <= MAX_STDIN_BYTES, "hook_input_too_large")
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        raise SessionSwitchError("invalid_hook_json") from None
    require(isinstance(value, dict), "invalid_hook_input")
    return value

def doctor(home: Path | None = None) -> dict[str, Any]:
    home = absolute(home or default_home())
    enabled, profile = saved_profile(home)
    offload = gemini_offload_status()
    profiles = {}
    for name in PROFILES:
        if name == "auto":
            profiles[name] = {"installed": True}
            continue
        try:
            profiles[name] = {"installed": True, **recommendation(home, name)}
        except SessionSwitchError:
            profiles[name] = {"installed": False}
    return {
        "saved_enabled": enabled,
        "saved_profile": profile,
        "profiles": profiles,
        "network_requests": 0,
        "model_switch_performed": False,
        "native_status": "READY",
        "free_context_offload": {
            "status": "READY" if offload["configured"] else "NOT CONFIGURED",
            "provider": offload["provider"],
            "model": offload["model"],
            "connectivity_verified": False,
        },
        "note": "Session policy switching is hook-driven; model changes remain native /model actions.",
    }

def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("hook", "doctor"))
    parser.add_argument("--codex-home", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "doctor":
            print(json.dumps(doctor(args.codex_home), indent=2))
            return 0
        report = process(_read_stdin(), home=args.codex_home)
        if report is not None:
            print(json.dumps(report, ensure_ascii=True))
        return 0
    except (SessionSwitchError, OSError, ValueError, TypeError, KeyError):
        if args.action == "hook":
            print(json.dumps({
                "continue": True,
                "systemMessage": "OmniCodex session override unavailable; saved startup policy remains in effect.",
            }))
            return 0
        print(json.dumps({"error": "session_switch_diagnostic_failed"}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
