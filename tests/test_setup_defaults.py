"""Exercise the real installer against isolated synthetic assets and temporary homes."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import defaults as d
from scripts import session_setup
from scripts import setup as setup_module


class SetupDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.repo, self.home, self.skills = root / "repo", root / "home", root / "skills"
        for p in (self.repo / "profiles", self.repo / "agents", self.repo / "scripts",
                  self.repo / "skills/omnicodex/references", self.home):
            p.mkdir(parents=True)
        for name in d.PROFILES[1:]:
            (self.repo / f"profiles/{name}.config.toml").write_text(
                f'model = "fixture-{name}"\nmodel_reasoning_effort = "medium"\n')
        for i in range(7):
            (self.repo / f"agents/role-{i}.toml").write_text('model = "fixture-worker"\n')
        (self.repo / "skills/omnicodex/SKILL.md").write_text('---\nname: omnicodex\n---\nPolicy\n')
        for name in ("routing", "efficiency", "token-offload"):
            (self.repo / f"skills/omnicodex/references/{name}.md").write_text("Optional reference\n")
        (self.repo / "scripts/session_switch.py").write_text(
            "#!/usr/bin/env python3\nprint('session fixture')\n", encoding="utf-8"
        )
        for relative in (
            "scripts/__init__.py",
            "scripts/efficiency.py",
            "scripts/offload_scope.py",
            "scripts/codex_exec_adapter.py",
            "scripts/offload_telemetry.py",
            "scripts/free_context_worker.py",
            "scripts/validate_gemini.py",
            "scripts/providers/__init__.py",
            "scripts/providers/base.py",
            "scripts/providers/gemini.py",
            "integrations/efficiency.json",
            "schemas/evidence-pack.schema.json",
        ):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n" if path.suffix == ".json" else f"fixture {relative}\n",
                            encoding="utf-8")
        (self.home / "config.toml").write_text('model = "original"\n')

    def run_setup(self, **kwargs):
        return setup_module.setup(self.repo, self.home, self.skills, **kwargs)

    def test_preview_has_no_writes(self):
        result = self.run_setup()
        self.assertEqual(result["mode"], "preview")
        self.assertEqual(result["assets"], 27)
        self.assertEqual(result["offload_status"]["native_status"], "READY")
        self.assertEqual(result["offload_status"]["free_context_offload"], "NOT CONFIGURED")
        self.assertTrue(result["session_switch"]["hook_trust_required"])
        self.assertEqual(len(result["session_switch"]["would_change"]), 2)
        self.assertFalse((self.home / "omnicodex").exists())
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse(self.skills.exists())

    def test_fresh_setup_activates_auto_after_assets(self):
        result = self.run_setup(apply=True)
        self.assertEqual(result["preferences"]["profile"], "auto")
        self.assertEqual((self.home / "config.toml").read_text(), 'model = "original"\n')
        self.assertTrue((self.skills / "omnicodex/references/token-offload.md").exists())
        self.assertTrue(d.status(self.home)["managed_block_intact"])
        manifest = json.loads((self.home / "omnicodex/install-manifest.json").read_text())
        self.assertEqual(len(manifest["files"]), 27)
        self.assertEqual(
            (self.home / "omnicodex/scripts/free_context_worker.py").read_text(),
            "fixture scripts/free_context_worker.py\n",
        )
        self.assertEqual(
            (self.home / "omnicodex/scripts/providers/gemini.py").read_text(),
            "fixture scripts/providers/gemini.py\n",
        )
        self.assertTrue((self.home / "omnicodex/session_switch.py").is_file())
        hooks = json.loads((self.home / "hooks.json").read_text())
        handler = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        self.assertEqual(handler["statusMessage"], session_setup.STATUS_MESSAGE)
        self.assertTrue(result["session_switch"]["hook_trust_required"])

    def test_setup_update_preserves_selection(self):
        self.run_setup(apply=True, profile="quality")
        self.run_setup(apply=True)
        self.assertEqual(d.load_state(self.home)["profile"], "quality")

    def test_setup_update_preserves_disabled(self):
        self.run_setup(apply=True)
        d.apply_plan(d.build_plan(self.home, enabled=False))
        self.run_setup(apply=True)
        self.assertFalse(d.load_state(self.home)["enabled"])

    def test_invalid_config_fails_before_installing_assets(self):
        (self.home / "config.toml").write_text("invalid [toml")
        with self.assertRaises(d.DefaultsError):
            self.run_setup(apply=True)
        self.assertFalse(self.skills.exists())

    def test_asset_conflict_requires_explicit_replace(self):
        self.run_setup(apply=True)
        (self.skills / "omnicodex/SKILL.md").write_text("user changes")
        before = (self.home / "AGENTS.md").read_bytes()
        with self.assertRaisesRegex(d.DefaultsError, "asset_conflict"):
            self.run_setup(apply=True)
        self.assertEqual((self.home / "AGENTS.md").read_bytes(), before)
        self.run_setup(apply=True, replace_existing=True)
        self.assertIn("name: omnicodex", (self.skills / "omnicodex/SKILL.md").read_text())

    def test_preferences_failure_does_not_claim_full_success(self):
        output = io.StringIO()
        with patch.object(d, "apply_plan", side_effect=d.DefaultsError("synthetic")), contextlib.redirect_stderr(output):
            with self.assertRaises(d.DefaultsError):
                self.run_setup(apply=True)
        report = json.loads(output.getvalue())
        self.assertEqual(report["asset_phase"], "installed")
        self.assertEqual(report["preferences_phase"], "failed")
        self.assertFalse(d.state_path(self.home).exists())

    def test_hook_conflict_fails_before_any_install_write(self):
        bad = {
            "hooks": {
                "UserPromptSubmit": [{
                    "hooks": [{
                        "type": "command",
                        "command": "python old.py hook",
                        "statusMessage": session_setup.STATUS_MESSAGE,
                    }]
                }]
            }
        }
        (self.home / "hooks.json").write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaisesRegex(
            session_setup.SessionSetupError,
            "existing_omnicodex_hook_differs_review_required",
        ):
            self.run_setup(apply=True)
        self.assertFalse(self.skills.exists())
        self.assertFalse(d.state_path(self.home).exists())

    def test_session_hook_failure_reports_partial_activation(self):
        output = io.StringIO()
        with patch.object(
            session_setup,
            "apply_plan",
            side_effect=session_setup.SessionSetupError("synthetic_hook_failure"),
        ), contextlib.redirect_stderr(output):
            with self.assertRaises(session_setup.SessionSetupError):
                self.run_setup(apply=True)
        report = json.loads(output.getvalue())
        self.assertEqual(report["asset_phase"], "installed")
        self.assertEqual(report["preferences_phase"], "configured")
        self.assertEqual(report["session_switch_phase"], "failed")
        self.assertTrue(d.state_path(self.home).exists())

    def test_profile_reads_real_source_values_not_hardcoded_models(self):
        (self.repo / "profiles/balanced.config.toml").write_text(
            'model = "changed-template"\nmodel_reasoning_effort = "low"\n')
        self.run_setup(apply=True, profile="balanced")
        state = d.load_state(self.home)
        self.assertEqual(state["managed_model"]["model"], "changed-template")
        self.assertEqual(state["managed_model"]["model_reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main()
