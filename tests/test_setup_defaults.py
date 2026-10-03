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
from scripts import setup as setup_module


class SetupDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.repo, self.home, self.skills = root / "repo", root / "home", root / "skills"
        for p in (self.repo / "profiles", self.repo / "agents", self.repo / "skills/omnicodex/references", self.home):
            p.mkdir(parents=True)
        for name in d.PROFILES[1:]:
            (self.repo / f"profiles/{name}.config.toml").write_text(
                f'model = "fixture-{name}"\nmodel_reasoning_effort = "medium"\n')
        for i in range(7):
            (self.repo / f"agents/role-{i}.toml").write_text('model = "fixture-worker"\n')
        (self.repo / "skills/omnicodex/SKILL.md").write_text('---\nname: omnicodex\n---\nPolicy\n')
        for name in ("efficiency", "jev"):
            (self.repo / f"skills/omnicodex/references/{name}.md").write_text("Optional reference\n")
        (self.home / "config.toml").write_text('model = "original"\n')

    def run_setup(self, **kwargs):
        return setup_module.setup(self.repo, self.home, self.skills, **kwargs)

    def test_preview_has_no_writes(self):
        result = self.run_setup()
        self.assertEqual(result["mode"], "preview")
        self.assertEqual(result["assets"], 14)
        self.assertFalse((self.home / "omnicodex").exists())
        self.assertFalse(self.skills.exists())

    def test_fresh_setup_activates_auto_after_assets(self):
        result = self.run_setup(apply=True)
        self.assertEqual(result["preferences"]["profile"], "auto")
        self.assertEqual((self.home / "config.toml").read_text(), 'model = "original"\n')
        self.assertTrue((self.skills / "omnicodex/references/jev.md").exists())
        self.assertTrue(d.status(self.home)["managed_block_intact"])
        manifest = json.loads((self.home / "omnicodex/install-manifest.json").read_text())
        self.assertEqual(len(manifest["files"]), 14)

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

    def test_profile_reads_real_source_values_not_hardcoded_models(self):
        (self.repo / "profiles/balanced.config.toml").write_text(
            'model = "changed-template"\nmodel_reasoning_effort = "low"\n')
        self.run_setup(apply=True, profile="balanced")
        state = d.load_state(self.home)
        self.assertEqual(state["managed_model"]["model"], "changed-template")
        self.assertEqual(state["managed_model"]["model_reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main()
