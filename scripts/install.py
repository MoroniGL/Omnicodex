#!/usr/bin/env python3
"""Install OmniCodex profiles, roles, and routing skill without silent overwrites."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROFILE_IDS = ("economy", "balanced", "quality", "max")
# Explicit assets prevent installing arbitrary local files or logs with the skill.
SKILL_FILES = ("SKILL.md", "references/efficiency.md")


class InstallConflict(RuntimeError):
    """Raised when an existing destination differs from the repository asset."""


@dataclass(frozen=True)
class InstallItem:
    source: Path
    destination: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _installation_items(repo_root: Path, codex_home: Path, skills_home: Path) -> list[InstallItem]:
    items = [
        InstallItem(
            repo_root / "profiles" / f"{profile_id}.config.toml",
            codex_home / f"omnicodex-{profile_id}.config.toml",
        )
        for profile_id in PROFILE_IDS
    ]
    items.extend(
        InstallItem(source, codex_home / "agents" / source.name)
        for source in sorted((repo_root / "agents").glob("*.toml"))
    )
    items.extend(
        InstallItem(
            repo_root / "skills" / "omnicodex" / relative,
            skills_home / "omnicodex" / relative,
        )
        for relative in SKILL_FILES
    )
    return items


def _validate_sources(items: list[InstallItem]) -> None:
    expected = len(PROFILE_IDS) + 7 + len(SKILL_FILES)
    if len(items) != expected:
        raise ValueError(f"expected {expected} OmniCodex assets, found {len(items)}")
    for item in items:
        if not item.source.is_file():
            raise FileNotFoundError(item.source)
        if item.source.suffix == ".toml":
            _load_toml(item.source)
    skill_source = next(item.source for item in items if item.source.name == "SKILL.md")
    skill = skill_source.read_text(encoding="utf-8")
    if not skill.startswith("---\n") or "\n---\n" not in skill[4:]:
        raise ValueError(f"skill frontmatter is missing: {skill_source}")


def _refuse_symlink_destination(path: Path) -> None:
    current = path
    while True:
        if current.is_symlink():
            raise InstallConflict(f"refusing symlink destination: {path}")
        if current == current.parent:
            return
        current = current.parent


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


def install(
    repo_root: Path,
    codex_home: Path,
    skills_home: Path,
    *,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Install all supported assets and return a rollback-oriented manifest."""

    repo_root = repo_root.resolve()
    codex_home = codex_home.resolve()
    skills_home = skills_home.resolve()
    items = _installation_items(repo_root, codex_home, skills_home)
    _validate_sources(items)

    conflicts: list[Path] = []
    for item in items:
        _refuse_symlink_destination(item.destination)
        if item.destination.exists() and item.destination.read_bytes() != item.source.read_bytes():
            conflicts.append(item.destination)
    if conflicts and not replace_existing:
        joined = "\n".join(str(path) for path in conflicts)
        raise InstallConflict(f"existing files differ; rerun with --replace-existing after review:\n{joined}")

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = codex_home / "backups" / f"omnicodex-{stamp}"
    backup.mkdir(parents=True, mode=0o700)
    config = codex_home / "config.toml"
    if config.is_file():
        shutil.copy2(config, backup / "config.toml")
        (backup / "config.toml").chmod(0o600)

    manifest_path = codex_home / "omnicodex" / "install-manifest.json"
    if manifest_path.is_file():
        shutil.copy2(manifest_path, backup / "previous-install-manifest.json")
        (backup / "previous-install-manifest.json").chmod(0o600)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "result": "installed",
        "backup": str(backup),
        "config": str(config),
        "config_sha256_before": _sha256(config) if config.is_file() else None,
        "files": [],
    }
    for index, item in enumerate(items):
        existed = item.destination.exists()
        entry: dict[str, Any] = {
            "source": str(item.source),
            "destination": str(item.destination),
            "sha256": _sha256(item.source),
            "existed": existed,
        }
        if existed and item.destination.read_bytes() != item.source.read_bytes():
            backup_file = backup / f"original-{index}-{item.destination.name}"
            shutil.copy2(item.destination, backup_file)
            backup_file.chmod(0o600)
            entry["backup"] = str(backup_file)
        if not existed or item.destination.read_bytes() != item.source.read_bytes():
            _atomic_copy(item.source, item.destination)
            entry["action"] = "replaced" if existed else "created"
        else:
            entry["action"] = "unchanged"
        if _sha256(item.destination) != entry["sha256"]:
            raise OSError(f"post-install hash mismatch: {item.destination}")
        manifest["files"].append(entry)

    manifest["config_sha256_after"] = _sha256(config) if config.is_file() else None
    if manifest["config_sha256_after"] != manifest["config_sha256_before"]:
        raise OSError("base config.toml changed during installation")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_text = json.dumps(manifest, indent=2) + "\n"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    manifest_path.chmod(0o600)
    (backup / "manifest.json").write_text(manifest_text, encoding="utf-8")
    (backup / "manifest.json").chmod(0o600)
    return manifest


def _project_config_paths(cwd: Path, codex_home: Path) -> list[Path]:
    cwd = cwd.resolve()
    ancestors = list(reversed((cwd, *cwd.parents)))
    user_config = (codex_home / "config.toml").resolve()
    return [
        path
        for base in ancestors
        if (path := base / ".codex" / "config.toml").is_file()
        and path.resolve() != user_config
    ]


def inspect_profile(codex_home: Path, profile_name: str, cwd: Path) -> dict[str, Any]:
    """Inspect candidate user/profile/project model layers; not runtime telemetry."""

    codex_home = codex_home.resolve()
    profile = codex_home / f"{profile_name}.config.toml"
    if not profile.is_file():
        raise FileNotFoundError(profile)
    project_layers = _project_config_paths(cwd, codex_home)
    layers = [codex_home / "config.toml", profile, *project_layers]
    model = None
    effort = None
    model_source = None
    effort_source = None
    project_override = False
    inspected: list[dict[str, Any]] = []
    for layer in layers:
        if not layer.is_file():
            continue
        data = _load_toml(layer)
        values = {
            "path": str(layer),
            "model": data.get("model"),
            "model_reasoning_effort": data.get("model_reasoning_effort"),
        }
        inspected.append(values)
        if values["model"] is not None:
            model = values["model"]
            model_source = str(layer)
            if layer in project_layers:
                project_override = True
        if values["model_reasoning_effort"] is not None:
            effort = values["model_reasoning_effort"]
            effort_source = str(layer)
            if layer in project_layers:
                project_override = True
    return {
        "profile": profile_name,
        "profile_path": str(profile),
        "cwd": str(cwd.resolve()),
        "resolved_model": model,
        "resolved_reasoning_effort": effort,
        "model_source": model_source,
        "reasoning_effort_source": effort_source,
        "project_overrides_profile": project_override,
        "layers": inspected,
        "note": "Static candidate layers only: project trust, managed policy, Desktop state, CLI -m/-c overrides, and actual runtime are not verified.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--skills-home", type=Path, default=Path.home() / ".agents" / "skills")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--inspect-profile", choices=[f"omnicodex-{name}" for name in PROFILE_IDS])
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.inspect_profile:
        print(json.dumps(inspect_profile(args.codex_home, args.inspect_profile, args.cwd), indent=2))
        return 0
    try:
        manifest = install(
            args.repo_root,
            args.codex_home,
            args.skills_home,
            replace_existing=args.replace_existing,
        )
    except InstallConflict as error:
        parser.error(str(error))
    print(json.dumps({"result": manifest["result"], "backup": manifest["backup"], "files": len(manifest["files"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
