"""Offline tests for installation of the OmniCodex session-switch hook."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import session_setup as setup


class SessionSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.home = self.root / "codex"
        (self.repo / "scripts").mkdir(parents=True)
        self.home.mkdir()
        (self.repo / "scripts/session_switch.py").write_text(
            "#!/usr/bin/env python3\nprint('fixture')\n", encoding="utf-8"
        )

    def plan(self, **kwargs):
        return setup.build_plan(
            self.repo, self.home, python_executable="python", **kwargs
        )

    def test_preview_writes_nothing(self):
        plan = self.plan()
        report = setup.summary(plan)
        self.assertEqual(report["mode"], "preview")
        self.assertTrue(report["hook_trust_required"])
        self.assertFalse((self.home / "hooks.json").exists())
        self.assertFalse((self.home / "omnicodex/session_switch.py").exists())

    def test_apply_installs_script_and_hook(self):
        result = setup.apply_plan(self.plan())
        self.assertEqual(result["result"], "configured_for_session_switching")
        hooks = json.loads((self.home / "hooks.json").read_text())
        groups = hooks["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(groups), 1)
        handler = groups[0]["hooks"][0]
        self.assertEqual(handler["statusMessage"], setup.STATUS_MESSAGE)
        self.assertIn("session_switch.py", handler["command"])
        self.assertTrue((self.home / "omnicodex/session_switch.py").is_file())

    def test_existing_unrelated_hooks_are_preserved(self):
        original = {
            "description": "user hooks",
            "hooks": {
                "PostToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "echo ok"}],
                }]
            },
        }
        (self.home / "hooks.json").write_text(json.dumps(original), encoding="utf-8")
        setup.apply_plan(self.plan())
        hooks = json.loads((self.home / "hooks.json").read_text())
        self.assertEqual(hooks["description"], "user hooks")
        self.assertEqual(hooks["hooks"]["PostToolUse"], original["hooks"]["PostToolUse"])
        self.assertIn("UserPromptSubmit", hooks["hooks"])

    def test_repeated_install_is_idempotent(self):
        setup.apply_plan(self.plan())
        second = self.plan()
        self.assertEqual(second["changes"], [])
        self.assertEqual(setup.apply_plan(second)["result"], "unchanged")

    def test_different_existing_script_requires_explicit_review(self):
        path = self.home / "omnicodex/session_switch.py"
        path.parent.mkdir(parents=True)
        path.write_text("different", encoding="utf-8")
        with self.assertRaisesRegex(
            setup.SessionSetupError,
            "session_switch_conflict_use_replace_existing_after_review",
        ):
            self.plan()
        plan = self.plan(replace_existing=True)
        result = setup.apply_plan(plan)
        self.assertEqual(result["result"], "configured_for_session_switching")
        backup = Path(result["backup"])
        self.assertTrue(any(p.name.endswith(".before") for p in backup.iterdir()))

    def test_owned_hook_with_different_definition_is_refused(self):
        bad = {
            "hooks": {
                "UserPromptSubmit": [{
                    "hooks": [{
                        "type": "command",
                        "command": "python old.py hook",
                        "statusMessage": setup.STATUS_MESSAGE,
                    }]
                }]
            }
        }
        (self.home / "hooks.json").write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaisesRegex(
            setup.SessionSetupError,
            "existing_omnicodex_hook_differs_review_required",
        ):
            self.plan()

    def test_duplicate_owned_hooks_are_refused(self):
        group = {
            "hooks": [{
                "type": "command",
                "command": "python old.py hook",
                "statusMessage": setup.STATUS_MESSAGE,
            }]
        }
        (self.home / "hooks.json").write_text(
            json.dumps({"hooks": {"UserPromptSubmit": [group, group]}}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            setup.SessionSetupError, "duplicate_omnicodex_hook"
        ):
            self.plan()

    def test_invalid_hooks_json_is_refused_without_writes(self):
        before = b"{invalid"
        (self.home / "hooks.json").write_bytes(before)
        with self.assertRaisesRegex(setup.SessionSetupError, "invalid_hooks_json"):
            self.plan()
        self.assertEqual((self.home / "hooks.json").read_bytes(), before)
        self.assertFalse((self.home / "omnicodex/session_switch.py").exists())

    def test_setup_does_not_touch_config_or_agents(self):
        config = self.home / "config.toml"
        agents = self.home / "AGENTS.md"
        config.write_text('model = "keep"\n', encoding="utf-8")
        agents.write_text("keep instructions\n", encoding="utf-8")
        before = (config.read_bytes(), agents.read_bytes())
        setup.apply_plan(self.plan())
        self.assertEqual((config.read_bytes(), agents.read_bytes()), before)

    def test_custom_python_executable_is_encoded_in_hook_command(self):
        plan = setup.build_plan(
            self.repo, self.home,
            python_executable=r"C:\Program Files\Python312\python.exe",
        )
        self.assertIn("Python312", plan["command"])
        self.assertIn("session_switch.py", plan["command"])


if __name__ == "__main__":
    unittest.main()
