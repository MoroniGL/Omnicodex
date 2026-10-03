#!/usr/bin/env python3
"""Install the experimental OmniCodex per-session switching hook.

Preview by default. --apply writes only the hook helper and user hooks.json.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 1024 * 1024
STATUS_MESSAGE = "OmniCodex session profile"
HOOK_EVENT = "UserPromptSubmit"

class SessionSetupError(RuntimeError):
    """Fixed error codes only."""

def require(condition: bool, code: str) -> None:
    if not condition:
        raise SessionSetupError(code)

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

def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result

def parse_hooks(raw: bytes | None) -> dict[str, Any]:
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError):
        raise SessionSetupError("invalid_hooks_json") from None
    require(isinstance(value, dict), "invalid_hooks_json")
    hooks = value.get("hooks")
    require(hooks is None or isinstance(hooks, dict), "invalid_hooks_table")
    return value

def command_for(python: str, script: Path) -> str:
    args = [python, str(script), "hook"]
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)

def desired_group(command: str) -> dict[str, Any]:
    return {
        "hooks": [{
            "type": "command",
            "command": command,
            "statusMessage": STATUS_MESSAGE,
            "timeout": 3,
            "additionalContextLimit": 4096,
        }]
    }

def is_owned_group(group: Any) -> bool:
    if not isinstance(group, dict):
        return False
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        return False
    return any(
        isinstance(handler, dict) and handler.get("statusMessage") == STATUS_MESSAGE
        for handler in handlers
    )

def merge_hooks(raw: bytes | None, command: str) -> bytes:
    data = parse_hooks(raw)
    hooks = data.setdefault("hooks", {})
    require(isinstance(hooks, dict), "invalid_hooks_table")
    groups = hooks.setdefault(HOOK_EVENT, [])
    require(isinstance(groups, list), "invalid_user_prompt_submit_hooks")
    desired = desired_group(command)

    owned = [group for group in groups if is_owned_group(group)]
    require(len(owned) <= 1, "duplicate_omnicodex_hook")
    if owned:
        require(owned[0] == desired, "existing_omnicodex_hook_differs_review_required")
        return raw if raw is not None else (json.dumps(data, indent=2) + "\n").encode("utf-8")

    groups.append(desired)
    return (json.dumps(data, indent=2, ensure_ascii=True) + "\n").encode("utf-8")

def atomic_replace(path: Path, data: bytes | None) -> None:
    guard(path)
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".omni-hook-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        guard(path)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)

def build_plan(repo: Path, home: Path, *, replace_existing: bool = False,
               python_executable: str | None = None) -> dict[str, Any]:
    repo, home = absolute(repo), absolute(home)
    guard(repo)
    guard(home)
    source = repo / "scripts" / "session_switch.py"
    source_raw = read(source)
    require(source_raw is not None, "session_switch_source_missing")

    destination = home / "omnicodex" / "session_switch.py"
    hooks_path = home / "hooks.json"
    installed = read(destination)
    if installed is not None and installed != source_raw:
        require(replace_existing, "session_switch_conflict_use_replace_existing_after_review")

    interpreter = python_executable or sys.executable
    require(isinstance(interpreter, str) and interpreter, "python_executable_required")
    command = command_for(interpreter, destination)
    hooks_before = read(hooks_path)
    hooks_after = merge_hooks(hooks_before, command)

    before = {destination: installed, hooks_path: hooks_before}
    after = {destination: source_raw, hooks_path: hooks_after}
    changes = [path for path in before if before[path] != after[path]]
    return {
        "repo": repo,
        "home": home,
        "before": before,
        "after": after,
        "changes": changes,
        "command": command,
    }

def apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not plan["changes"]:
        return {"result": "unchanged", "changed_files": [], "runtime_verified": False}
    home = plan["home"]
    backup = home / "omnicodex" / "session-switch-backups" / uuid.uuid4().hex
    guard(backup)
    backup.mkdir(parents=True, exist_ok=False, mode=0o700)

    journal = []
    committed: list[Path] = []
    try:
        for index, path in enumerate(plan["changes"]):
            current = read(path)
            require(current == plan["before"][path], "concurrent_change_refused")
            original_name = None
            if current is not None:
                original_name = f"{index}.before"
                atomic_replace(backup / original_name, current)
            journal.append({
                "target": str(path),
                "original_file": original_name,
            })
        atomic_replace(backup / "journal.json",
                       (json.dumps(journal, indent=2) + "\n").encode("utf-8"))
        for path in plan["changes"]:
            require(read(path) == plan["before"][path], "concurrent_change_refused")
            atomic_replace(path, plan["after"][path])
            committed.append(path)
        return {
            "result": "configured_for_session_switching",
            "changed_files": [str(path) for path in plan["changes"]],
            "backup": str(backup),
            "runtime_verified": False,
            "hook_trust_required": True,
        }
    except BaseException:
        rollback_ok = True
        for path in reversed(committed):
            try:
                current = read(path)
                require(current == plan["after"][path], "rollback_conflict")
                atomic_replace(path, plan["before"][path])
            except BaseException:
                rollback_ok = False
        if not rollback_ok:
            raise SessionSetupError("rollback_incomplete_keep_backup") from None
        raise

def summary(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "preview",
        "would_change": [str(path) for path in plan["changes"]],
        "hook_event": HOOK_EVENT,
        "hook_command": plan["command"],
        "network_requests": 0,
        "model_switch_performed": False,
        "runtime_verified": False,
        "hook_trust_required": True,
        "note": "Temporary policy switches apply at prompt boundaries; parent model changes remain native /model actions.",
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--codex-home", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.repo_root, args.codex_home,
                          replace_existing=args.replace_existing)
        report = summary(plan)
        if args.apply:
            report.update(apply_plan(plan), mode="configuration_write")
        print(json.dumps(report, indent=2))
        return 0
    except (SessionSetupError, OSError, ValueError, TypeError, KeyError):
        exc = sys.exception()
        print(json.dumps({
            "error": str(exc) if isinstance(exc, SessionSetupError) else "session_setup_failed",
            "runtime_verified": False,
            "note": "No configuration contents or credentials printed. Review before retrying.",
        }), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
