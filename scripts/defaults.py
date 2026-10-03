#!/usr/bin/env python3
"""Remember OmniCodex policy for new local Codex sessions. Writes require --apply."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import tomllib
import uuid
from pathlib import Path
from typing import Any

PROFILES = ("auto", "economy", "balanced", "quality", "max")
MODEL_KEYS = ("model", "model_reasoning_effort")
START = "<!-- omnicodex:persistent-defaults:v1 -->"
END = "<!-- /omnicodex:persistent-defaults:v1 -->"
MAX_FILE_BYTES = 1024 * 1024
POLICIES = {
    "auto": "Select bounded workers by task risk and complexity; keep the user's current parent model.",
    "economy": "Prefer the least expensive capable installed worker; retain required tests and review.",
    "balanced": "Keep planning and acceptance with the parent; delegate bounded work and review material risks.",
    "quality": "Favor thorough verification and independent review for consequential changes.",
    "max": "Use the configured strong parent, but do not spend premium calls on mechanical work unnecessarily.",
}


class DefaultsError(RuntimeError):
    """Messages are fixed codes: never include config contents or credentials."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DefaultsError(code)


def absolute(path: Path) -> Path:
    # Do not resolve links before checking the path.
    return Path(os.path.abspath(path.expanduser()))


def guard(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode), "symlink_path_refused")
        require(not (getattr(info, "st_file_attributes", 0) & 0x400), "reparse_path_refused")


def read(path: Path) -> bytes | None:
    guard(path)
    try:
        with path.open("rb") as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "non_regular_file_refused")
            data = stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return None
    require(len(data) <= MAX_FILE_BYTES, "file_size_limit")
    return data


def digest(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def decode(data: bytes | None) -> str:
    try:
        return (data or b"").decode("utf-8-sig")
    except UnicodeError:
        raise DefaultsError("utf8_required") from None


def parse_config(data: bytes | None) -> dict[str, Any]:
    try:
        return tomllib.loads(decode(data))
    except tomllib.TOMLDecodeError:
        raise DefaultsError("invalid_config_toml") from None


def unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_state_key")
        result[key] = value
    return result


def state_path(home: Path) -> Path:
    return home / "omnicodex" / "preferences.json"


def load_state(home: Path) -> dict[str, Any] | None:
    data = read(state_path(home))
    if data is None:
        return None
    try:
        value = json.loads(decode(data), object_pairs_hook=unique_json)
    except (ValueError, TypeError):
        raise DefaultsError("invalid_preferences_json") from None
    require(isinstance(value, dict) and value.get("schema_version") == 1, "unsupported_preferences")
    require(type(value.get("enabled")) is bool and value.get("profile") in PROFILES, "invalid_preferences")
    require(value.get("model_mode") in ("profile", "pinned"), "invalid_model_mode")
    require(value.get("guidance_file") in ("AGENTS.md", "AGENTS.override.md"), "invalid_guidance_file")
    require(isinstance(value.get("block"), str) and isinstance(value.get("skills_home"), str), "invalid_preferences")
    for name in ("original_model", "managed_model"):
        require(isinstance(value.get(name), dict) and set(value[name]) <= set(MODEL_KEYS), "invalid_model_state")
    for record in value["original_model"].values():
        require(isinstance(record, dict) and type(record.get("present")) is bool, "invalid_model_state")
        require(not record["present"] or isinstance(record.get("value"), str), "invalid_model_state")
    require(all(isinstance(v, str) for v in value["managed_model"].values()), "invalid_model_state")
    if value["enabled"]:
        require(value["block"].startswith(START) and value["block"].endswith(END + "\n\n"), "invalid_managed_block")
    else:
        require(value["block"] == "" and not value["managed_model"], "invalid_disabled_state")
    return value


def guidance_file(home: Path) -> str:
    return "AGENTS.override.md" if decode(read(home / "AGENTS.override.md")).strip() else "AGENTS.md"


def _managed_block_span(text: str, block: str) -> tuple[int, int]:
    """Match the saved block, allowing only LF/CRLF line-ending differences.

    Editors and Windows text-mode writes may change newlines without changing
    instructions. Match an escaped literal per line, not arbitrary whitespace,
    and return offsets into the ORIGINAL text so unowned content is untouched.
    """
    require(text.count(START) == text.count(END) == 1,
            "managed_guidance_changed_review_required")
    pattern = r"\r?\n".join(re.escape(line) for line in block.split("\n"))
    match = re.search(pattern, text)
    require(match is not None, "managed_guidance_changed_review_required")
    return match.span()


def strip_block(text: str, previous: dict[str, Any] | None) -> str:
    if previous and previous["enabled"]:
        start, end = _managed_block_span(text, previous["block"])
        return text[:start] + text[end:]
    require(START not in text and END not in text, "unowned_managed_block")
    return text


def model_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    for key in MODEL_KEYS:
        require(key not in config or isinstance(config[key], str), "model_config_must_be_string")
    return {key: {"present": key in config, "value": config.get(key)} for key in MODEL_KEYS}


def edit_model_fields(raw: bytes | None, changes: dict[str, str | None]) -> bytes:
    """Conservative byte-preserving edit. Reject unsupported layouts instead of guessing.

    A removable one-line assignment must parse to exactly the original TOML minus
    its root key. This excludes nested fields and matches inside multiline strings.
    """
    original = parse_config(raw)
    text = decode(raw)
    bom = b"\xef\xbb\xbf" if raw and raw.startswith(b"\xef\xbb\xbf") else b""
    expected = copy.deepcopy(original)
    for key in changes:
        if key not in original:
            continue
        current = tomllib.loads(text)
        without = copy.deepcopy(current)
        without.pop(key)
        lines = text.splitlines(keepends=True)
        pattern = re.compile(r"^\s*(?:" + key + r'|"' + key + r'"|\'' + key + r"')\s*=")
        found = None
        for index, line in enumerate(lines):
            if not pattern.match(line):
                continue
            candidate = "".join(lines[:index] + lines[index + 1:])
            try:
                if tomllib.loads(candidate) == without:
                    found = candidate
                    break
            except tomllib.TOMLDecodeError:
                pass
        require(found is not None, "unsupported_model_assignment_layout")
        text = found
    newline = "\r\n" if "\r\n" in text else "\n"
    prefix = ""
    for key, value in changes.items():
        if value is None:
            expected.pop(key, None)
        else:
            expected[key] = value
            prefix += key + " = " + json.dumps(value, ensure_ascii=False) + newline
    result = bom + (prefix + text).encode("utf-8")
    require(parse_config(result) == expected, "unrelated_config_change_refused")
    return result


def recommendations(home: Path, profile: str, source_profiles: Path | None) -> dict[str, str]:
    path = ((source_profiles / f"{profile}.config.toml") if source_profiles else
            home / f"omnicodex-{profile}.config.toml")
    data = read(path)
    require(data is not None, "profile_not_installed")
    config = parse_config(data)
    require(all(isinstance(config.get(k), str) and config[k] for k in MODEL_KEYS), "profile_missing_model")
    return {key: config[key] for key in MODEL_KEYS}


def block_for(home: Path, skills: Path, state: dict[str, Any]) -> str:
    profile = state["profile"]
    return (
        START + "\n# OmniCodex persistent defaults\n"
        "For new coding tasks, use the installed OmniCodex routing skill automatically; "
        "do not require a manual skill mention in every chat.\n"
        f"Saved policy: {profile}. {POLICIES[profile]}\n"
        f"Skill: {json.dumps(str(skills / 'omnicodex' / 'SKILL.md'))}.\n"
        "Explicit session profiles, model choices, project instructions and higher-priority "
        "instructions still take precedence. Use only available, approved tools and workers. "
        "Never change permissions or enable paid/external providers just by choosing a profile.\n"
        "Jev, Laya and FreeLLMAPI remain separately opt-in; these defaults do not install them "
        "or preprocess input before the parent model reads it. Keep tiny tasks local.\n"
        "A temporary instruction applies only to this session. For an explicit request to save "
        "a profile for future chats, use the preferences tool with normal approval: "
        f"python {json.dumps(str(home / 'omnicodex' / 'defaults.py'))} set PROFILE --apply "
        "(PROFILE: auto, economy, balanced, quality, max). Add --recommended to drop a pinned "
        "model. Never claim a running model changed from a saved file; use the client's "
        "supported next-turn model selection, or report that a new session/restart is needed.\n"
        + END + "\n\n"
    )


def build_plan(home: Path, *, profile: str | None = None, skills_home: Path | None = None,
               enabled: bool | None = None, model: str | None = None, effort: str | None = None,
               recommended: bool = False, source_profiles: Path | None = None) -> dict[str, Any]:
    home = absolute(home)
    guard(home)
    raw_state = read(state_path(home))
    previous = load_state(home)
    state = copy.deepcopy(previous) if previous else {
        "schema_version": 1, "enabled": True, "profile": "auto", "model_mode": "profile",
        "pinned_model": None, "pinned_effort": None, "original_model": {}, "managed_model": {},
        "guidance_file": guidance_file(home), "block": "", "guidance_existed": False,
    }
    if profile is not None:
        require(profile in PROFILES, "invalid_profile")
        state["profile"] = profile
    if enabled is not None:
        state["enabled"] = enabled
    require((model is None) == (effort is None), "provide_model_and_effort_together")
    require(not (recommended and model is not None), "conflicting_model_selection")
    if model is not None:
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", model) is not None, "invalid_model_id")
        require(re.fullmatch(r"[a-z][a-z0-9_-]{0,23}", effort or "") is not None, "invalid_effort")
        state.update(model_mode="pinned", pinned_model=model, pinned_effort=effort)
    elif recommended:
        state.update(model_mode="profile", pinned_model=None, pinned_effort=None)
    skills = absolute(skills_home if skills_home is not None else
                      Path(previous["skills_home"]) if previous else Path.home() / ".agents/skills")
    state["skills_home"] = str(skills)
    selected = guidance_file(home)
    if previous and previous["enabled"]:
        # Do not silently write a second block when an override shadows the old file.
        require(selected == previous["guidance_file"], "guidance_shadowed_review_required")
    else:
        state["guidance_file"] = selected
    guidance = home / state["guidance_file"]
    raw_guidance = read(guidance)
    if not previous or not previous["enabled"]:
        state["guidance_existed"] = raw_guidance is not None
    plain = strip_block(decode(raw_guidance), previous)
    raw_config = read(home / "config.toml")
    config = parse_config(raw_config)
    current = model_snapshot(config)
    owned = dict(state["managed_model"])
    for key, value in owned.items():
        require(current[key]["present"] and current[key]["value"] == value, "managed_model_changed_review_required")
    target: dict[str, str] = {}
    if state["enabled"]:
        if state["model_mode"] == "pinned":
            require(isinstance(state["pinned_model"], str) and isinstance(state["pinned_effort"], str), "invalid_pin")
            target = dict(zip(MODEL_KEYS, (state["pinned_model"], state["pinned_effort"])))
        elif state["profile"] != "auto":
            require(config.get("model_provider", "openai") == "openai", "native_profile_provider_conflict")
            target = recommendations(home, state["profile"], source_profiles)
    changes: dict[str, str | None] = {}
    if target:
        if not owned:
            state["original_model"] = current
        changes = target
        state["managed_model"] = target
    else:
        if owned:
            for key, record in state["original_model"].items():
                changes[key] = record["value"] if record["present"] else None
        state["original_model"] = {}
        state["managed_model"] = {}
    after_config = edit_model_fields(raw_config, changes) if changes else raw_config
    if changes and after_config == b"" and raw_config is None:
        after_config = None
    state["block"] = block_for(home, skills, state) if state["enabled"] else ""
    text = state["block"] + plain
    after_guidance = text.encode("utf-8") if text or state["guidance_existed"] else None
    if raw_guidance and raw_guidance.startswith(b"\xef\xbb\xbf") and after_guidance is not None:
        after_guidance = b"\xef\xbb\xbf" + after_guidance
    tool = home / "omnicodex/defaults.py"
    raw_tool = read(tool)
    if raw_tool is not None:
        require(previous is not None and digest(raw_tool) == previous.get("tool_sha256"), "unowned_or_edited_tool")
    source_tool = Path(__file__).read_bytes()
    state["tool_sha256"] = digest(source_tool)
    before = {guidance: raw_guidance, home / "config.toml": raw_config,
              tool: raw_tool, state_path(home): raw_state}
    after = {guidance: after_guidance, home / "config.toml": after_config,
             tool: source_tool, state_path(home): (json.dumps(state, indent=2) + "\n").encode()}
    require(read(state_path(home)) == raw_state, "concurrent_preferences_change")
    return {"home": home, "state": state, "before": before, "after": after}


def atomic_replace(path: Path, data: bytes | None) -> None:
    guard(path)
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".omni-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        guard(path)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    home, state = plan["home"], plan["state"]
    if state["enabled"]:
        require(read(Path(state["skills_home"]) / "omnicodex/SKILL.md") is not None, "skill_not_installed")
        require(all(read(home / f"omnicodex-{p}.config.toml") is not None for p in PROFILES[1:]),
                "profiles_not_installed")
    changes = [p for p in plan["before"] if plan["before"][p] != plan["after"][p]]
    if not changes:
        return {"result": "unchanged", "changed_files": [], "runtime_verified": False}
    folder = home / "omnicodex"
    guard(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = folder / "preferences.lock"
    guard(lock)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise DefaultsError("preferences_locked_review_recovery_first") from None
    os.close(descriptor)
    committed: list[Path] = []
    safe_to_unlock = True
    backup = folder / "preferences-backups" / uuid.uuid4().hex
    try:
        for path, before in plan["before"].items():
            require(read(path) == before, "concurrent_change_refused")
        require(guidance_file(home) == state["guidance_file"], "guidance_changed_during_setup")
        guard(backup)
        backup.mkdir(parents=True, exist_ok=False, mode=0o700)
        journal = []
        for index, path in enumerate(changes):
            original = plan["before"][path]
            if original is not None:
                atomic_replace(backup / f"{index}.before", original)
            journal.append({"target": str(path), "original_file": f"{index}.before" if original is not None else None,
                            "before_sha256": digest(original), "after_sha256": digest(plan["after"][path])})
        atomic_replace(backup / "journal.json", (json.dumps(journal, indent=2) + "\n").encode())
        for path in changes:
            require(read(path) == plan["before"][path], "concurrent_change_refused")
            committed.append(path)
            atomic_replace(path, plan["after"][path])
        return {"result": "configured_for_new_sessions", "changed_files": [str(p) for p in changes],
                "backup": str(backup), "runtime_verified": False}
    except BaseException:
        for path in reversed(committed):
            try:
                current = read(path)
                if current != plan["before"][path]:
                    require(current == plan["after"][path], "rollback_conflict")
                    atomic_replace(path, plan["before"][path])
            except BaseException:
                safe_to_unlock = False
        if not safe_to_unlock:
            raise DefaultsError("rollback_incomplete_keep_backups_and_lock") from None
        raise
    finally:
        if safe_to_unlock:
            lock.unlink(missing_ok=True)


def summary(plan: dict[str, Any]) -> dict[str, Any]:
    state = plan["state"]
    return {"mode": "preview", "enabled": state["enabled"], "profile": state["profile"],
            "model_mode": state["model_mode"], "requested_model_settings": state["managed_model"],
            "guidance_file": state["guidance_file"],
            "would_change": [str(p) for p in plan["before"] if plan["before"][p] != plan["after"][p]],
            "runtime_verified": False, "model_availability_verified": False,
            "applies_to": "new local sessions that load this CODEX_HOME; restart cached clients",
            "note": "No native dropdown, in-flight model switch, permission change or external provider activation."}


def status(home: Path) -> dict[str, Any]:
    home = absolute(home)
    state = load_state(home)
    if state is None:
        return {"configured": False, "runtime_verified": False}
    guidance = decode(read(home / state["guidance_file"]))
    config = parse_config(read(home / "config.toml"))
    try:
        strip_block(guidance, state)
        block_intact = True
    except DefaultsError:
        block_intact = False
    return {"configured": True, "enabled": state["enabled"], "profile": state["profile"],
            "model_mode": state["model_mode"], "requested_model_settings": state["managed_model"],
            "guidance_is_active_file": guidance_file(home) == state["guidance_file"],
            "managed_block_intact": block_intact,
            "model_defaults_match": all(config.get(k) == v for k, v in state["managed_model"].items()),
            "tool_intact": digest(read(home / "omnicodex/defaults.py")) == state["tool_sha256"],
            "lock_present": (home / "omnicodex/preferences.lock").exists(), "runtime_verified": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "enable", "set", "disable"))
    parser.add_argument("profile", nargs="?", choices=PROFILES)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--skills-home", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--effort")
    parser.add_argument("--recommended", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Persist changes. Omit to preview.")
    args = parser.parse_args(argv)
    try:
        if args.action == "status":
            require(not (args.profile or args.model or args.effort or args.recommended or args.apply), "status_is_read_only")
            print(json.dumps(status(args.codex_home), indent=2))
            return 0
        require(args.action != "set" or args.profile is not None, "set_requires_profile")
        require(args.action != "disable" or not (args.profile or args.model or args.effort or args.recommended), "invalid_disable_options")
        plan = build_plan(args.codex_home, profile=args.profile, skills_home=args.skills_home,
                          enabled=args.action != "disable", model=args.model, effort=args.effort,
                          recommended=args.recommended)
        report = summary(plan)
        if args.apply:
            report.update(apply_plan(plan), mode="configuration_write")
        print(json.dumps(report, indent=2))
        return 0
    except (DefaultsError, OSError, ValueError, TypeError, KeyError):
        exc = sys.exception()
        print(json.dumps({"error": str(exc) if isinstance(exc, DefaultsError) else "local_configuration_error",
                          "runtime_verified": False, "note": "No credentials or config contents printed. Review before retrying."}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
