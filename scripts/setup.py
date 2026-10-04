#!/usr/bin/env python3
"""Install assets and persistent OmniCodex defaults. Preview by default; --apply writes."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__:
    from . import defaults
    from . import install as installer
    from . import session_setup
else:
    import defaults
    import install as installer
    import session_setup


def setup(repo: Path, home: Path, skills: Path, *, apply: bool = False,
          replace_existing: bool = False, profile: str | None = None,
          python_executable: str | None = None) -> dict:
    repo, home, skills = map(defaults.absolute, (repo, home, skills))
    defaults.guard(home)
    defaults.guard(skills)
    # Preference conflicts are caught BEFORE invoking the asset installer.
    plan = defaults.build_plan(home, profile=profile, skills_home=skills,
                               enabled=True if profile is not None else None,
                               source_profiles=repo / "profiles")
    items = installer._installation_items(repo, home, skills)
    installer._validate_sources(items)
    for item in items:
        current = defaults.read(item.destination)
        defaults.require(current is None or current == item.source.read_bytes() or replace_existing,
                         "asset_conflict_use_replace_existing_after_review")
    # Validate the session hook plan before any write so hook conflicts cannot
    # leave a fresh install partially activated.
    session_plan = session_setup.build_plan(
        repo,
        home,
        replace_existing=replace_existing,
        python_executable=python_executable or sys.executable,
    )
    session_preview = session_setup.summary(session_plan)
    result = {"assets": len(items), "preferences": defaults.summary(plan),
              "session_switch": session_preview,
              "mode": "preview", "network_requests": 0, "runtime_verified": False,
              "offload_status": installer.offload_status()}
    if not apply:
        return result
    # Existing install() remains the asset-only API. Its batch is NOT transactional.
    manifest = installer.install(repo, home, skills, replace_existing=replace_existing)
    try:
        persisted = defaults.apply_plan(plan)
    except BaseException:
        print(json.dumps({"asset_phase": "installed", "asset_backup": manifest["backup"],
                          "preferences_phase": "failed", "runtime_verified": False,
                          "note": "Preserve backups; do not claim complete activation."}), file=sys.stderr)
        raise
    try:
        session_result = session_setup.apply_plan(session_plan)
    except BaseException:
        print(json.dumps({"asset_phase": "installed", "preferences_phase": "configured",
                          "session_switch_phase": "failed", "runtime_verified": False,
                          "note": "Assets/defaults are installed; preserve backups and review hook setup before retrying."}),
              file=sys.stderr)
        raise
    result.update(mode="configured_for_new_sessions", asset_backup=manifest["backup"],
                  preferences={**result["preferences"], **persisted},
                  session_switch={**session_preview, **session_result, "mode": "configuration_write"})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--skills-home", type=Path, default=Path.home() / ".agents/skills")
    parser.add_argument("--profile", choices=defaults.PROFILES,
                        help="Explicit persistent choice. Omit to preserve existing choice; new installs use Auto.")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(setup(args.repo_root, args.codex_home, args.skills_home,
                               apply=args.apply, replace_existing=args.replace_existing,
                               profile=args.profile), indent=2))
        return 0
    except (defaults.DefaultsError, installer.InstallConflict, session_setup.SessionSetupError,
            OSError, ValueError, TypeError, KeyError) as exc:
        safe_error = str(exc) if isinstance(
            exc, (defaults.DefaultsError, session_setup.SessionSetupError)
        ) else "setup_failed"
        print(json.dumps({"error": safe_error, "runtime_verified": False,
                          "note": "Review the local setup; do not retry blindly."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
