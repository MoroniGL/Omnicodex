"""Offline persistence regression tests. No installed client, credentials or network."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import defaults as d


class DefaultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "codex"
        self.skills = self.root / "skills"
        self.home.mkdir()
        (self.skills / "omnicodex").mkdir(parents=True)
        (self.skills / "omnicodex/SKILL.md").write_text("---\nname: omnicodex\n---\nPolicy", encoding="utf-8")
        for profile in d.PROFILES[1:]:
            (self.home / f"omnicodex-{profile}.config.toml").write_text(
                f'model = "fixture-{profile}"\nmodel_reasoning_effort = "medium"\n', encoding="utf-8")
        self.config = self.home / "config.toml"
        self.config.write_text('# retained\nmodel = "original"\nmodel_reasoning_effort = "low"\n'
                               '[sandbox_workspace_write]\nnetwork_access = false\n', encoding="utf-8")

    def plan(self, **kwargs):
        return d.build_plan(self.home, skills_home=self.skills, **kwargs)

    def apply(self, **kwargs):
        plan = self.plan(**kwargs)
        d.apply_plan(plan)
        return plan

    def test_preview_writes_nothing(self):
        before = self.config.read_bytes()
        plan = self.plan()
        self.assertEqual(d.summary(plan)["profile"], "auto")
        self.assertFalse((self.home / "AGENTS.md").exists())
        self.assertFalse(d.state_path(self.home).exists())
        self.assertEqual(before, self.config.read_bytes())

    def test_auto_preserves_parent_and_persists_bootstrap(self):
        before = self.config.read_bytes()
        self.apply()
        self.assertEqual(before, self.config.read_bytes())
        self.assertTrue(d.status(self.home)["managed_block_intact"])
        self.assertEqual(d.load_state(self.home)["profile"], "auto")
        self.assertIn("do not require a manual skill mention", (self.home / "AGENTS.md").read_text())
        self.assertFalse(d.status(self.home)["runtime_verified"])

    def test_balanced_changes_only_model_fields(self):
        before = tomllib.loads(self.config.read_text())
        self.apply(profile="balanced")
        after = tomllib.loads(self.config.read_text())
        self.assertEqual(after.pop("model"), "fixture-balanced")
        self.assertEqual(after.pop("model_reasoning_effort"), "medium")
        for key in d.MODEL_KEYS:
            before.pop(key)
        self.assertEqual(before, after)
        self.assertIn("# retained", self.config.read_text())

    def test_repeated_setup_preserves_choice_and_is_idempotent(self):
        self.apply(profile="quality")
        plan = self.plan()
        self.assertEqual(plan["state"]["profile"], "quality")
        self.assertEqual(d.apply_plan(plan)["result"], "unchanged")
        self.assertEqual((self.home / "AGENTS.md").read_text().count(d.START), 1)

    def test_manual_pin_survives_profile_change(self):
        self.apply(profile="balanced", model="user-model", effort="high")
        self.apply(profile="economy")
        state = d.load_state(self.home)
        self.assertEqual(state["profile"], "economy")
        self.assertEqual(state["model_mode"], "pinned")
        self.assertEqual(tomllib.loads(self.config.read_text())["model"], "user-model")

    def test_recommended_explicitly_removes_pin(self):
        self.apply(profile="balanced", model="user-model", effort="high")
        self.apply(profile="economy", recommended=True)
        self.assertEqual(d.load_state(self.home)["model_mode"], "profile")
        self.assertEqual(tomllib.loads(self.config.read_text())["model"], "fixture-economy")

    def test_auto_restores_original_model(self):
        self.apply(profile="balanced")
        self.apply(profile="auto", recommended=True)
        config = tomllib.loads(self.config.read_text())
        self.assertEqual(config["model"], "original")
        self.assertEqual(config["model_reasoning_effort"], "low")

    def test_disable_preserves_user_guidance_and_other_config_changes(self):
        (self.home / "AGENTS.md").write_text("User instructions.\n", encoding="utf-8")
        self.apply(profile="balanced")
        with self.config.open("a", encoding="utf-8") as stream:
            stream.write("another_user_flag = true\n")
        self.apply(enabled=False)
        self.assertEqual((self.home / "AGENTS.md").read_text(), "User instructions.\n")
        config = tomllib.loads(self.config.read_text())
        self.assertEqual(config["model"], "original")
        self.assertTrue(config["sandbox_workspace_write"]["another_user_flag"])

    def test_update_does_not_reenable_disabled(self):
        self.apply()
        self.apply(enabled=False)
        plan = self.plan()
        self.assertFalse(plan["state"]["enabled"])
        self.assertEqual(d.apply_plan(plan)["result"], "unchanged")

    def test_nonempty_global_override_used_without_touching_base(self):
        (self.home / "AGENTS.md").write_text("Base stays.\n")
        override = self.home / "AGENTS.override.md"
        override.write_text("Temporary rules.\n")
        self.apply()
        self.assertEqual((self.home / "AGENTS.md").read_text(), "Base stays.\n")
        self.assertTrue(override.read_text().endswith("Temporary rules.\n"))
        self.assertEqual(d.status(self.home)["guidance_is_active_file"], True)

    def test_empty_override_falls_back_to_agents(self):
        (self.home / "AGENTS.override.md").write_text(" \n")
        self.apply()
        self.assertEqual(d.load_state(self.home)["guidance_file"], "AGENTS.md")

    def test_later_override_is_reported_and_refused(self):
        self.apply()
        (self.home / "AGENTS.override.md").write_text("Other instructions")
        self.assertFalse(d.status(self.home)["guidance_is_active_file"])
        with self.assertRaisesRegex(d.DefaultsError, "guidance_shadowed"):
            self.plan(profile="balanced")

    def test_edited_model_not_overwritten(self):
        self.apply(profile="balanced")
        self.config.write_text(self.config.read_text().replace('"fixture-balanced"', '"manual-change"'))
        self.assertFalse(d.status(self.home)["model_defaults_match"])
        with self.assertRaisesRegex(d.DefaultsError, "managed_model_changed"):
            self.plan(enabled=False)

    def test_edited_managed_block_refused(self):
        self.apply()
        path = self.home / "AGENTS.md"
        path.write_text(path.read_text().replace("Saved policy: auto", "Saved policy: invalid"))
        with self.assertRaisesRegex(d.DefaultsError, "managed_guidance_changed"):
            self.plan()

    def test_other_user_guidance_can_change(self):
        self.apply()
        path = self.home / "AGENTS.md"
        path.write_text(path.read_text() + "New user guidance.\n")
        self.apply(profile="balanced")
        self.assertTrue(path.read_text().endswith("New user guidance.\n"))

    def test_symlink_home_refused(self):
        link = self.root / "linked-home"
        real_lstat = Path.lstat
        from types import SimpleNamespace
        symlink = SimpleNamespace(st_mode=stat_mode_symlink(), st_file_attributes=0)
        with patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=lambda path: symlink if path == link else real_lstat(path),
        ):
            with self.assertRaisesRegex(d.DefaultsError, "symlink"):
                d.build_plan(link, skills_home=self.skills)

    def test_symlink_guidance_refused_before_writes(self):
        outside = self.root / "outside"
        outside.write_text("sentinel")
        guidance = self.home / "AGENTS.md"
        real_lstat = Path.lstat
        from types import SimpleNamespace
        symlink = SimpleNamespace(st_mode=stat_mode_symlink(), st_file_attributes=0)
        with patch.object(
            Path,
            "lstat",
            autospec=True,
            side_effect=lambda path: symlink if path == guidance else real_lstat(path),
        ):
            with self.assertRaises(d.DefaultsError):
                self.plan()
        self.assertEqual(outside.read_text(), "sentinel")
        self.assertFalse(d.state_path(self.home).exists())

    def test_simulated_windows_reparse_point_refused(self):
        from types import SimpleNamespace
        info = SimpleNamespace(st_mode=stat_mode_directory(), st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=info):
            with self.assertRaisesRegex(d.DefaultsError, "reparse"):
                d.guard(self.home)

    def test_directories_not_accepted_as_files(self):
        (self.home / "AGENTS.md").mkdir()
        with self.assertRaises((d.DefaultsError, OSError)):
            self.plan()

    def test_configuration_secret_is_not_printed(self):
        self.config.write_text(self.config.read_text() + '\n[env]\nKEY = "SECRET_SENTINEL"\n')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = d.main(["set", "balanced", "--codex-home", str(self.home), "--skills-home", str(self.skills)])
        self.assertEqual(code, 0)
        self.assertNotIn("SECRET_SENTINEL", out.getvalue())
        self.assertIn("preview", out.getvalue())

    def test_nested_model_and_multiline_instruction_preserved(self):
        raw = (b'developer_instructions = """\nmodel = "do-not-edit"\n[not-a-table]\n"""\n'
               b'model = "parent"\n[other]\nmodel = "nested"\n')
        edited = d.edit_model_fields(raw, {"model": "new-parent"})
        expected = tomllib.loads(raw.decode())
        expected["model"] = "new-parent"
        self.assertEqual(tomllib.loads(edited.decode()), expected)
        self.assertIn(b'model = "nested"', edited)

    def test_bom_crlf_preserved(self):
        raw = b'\xef\xbb\xbfmodel = "original"\r\n# comment\r\n[other]\r\nenabled = true\r\n'
        out = d.edit_model_fields(raw, {"model": "new"})
        self.assertTrue(out.startswith(b'\xef\xbb\xbfmodel = "new"\r\n'))
        self.assertTrue(out.endswith(b'# comment\r\n[other]\r\nenabled = true\r\n'))

    def test_quoted_root_keys_supported(self):
        out = d.edit_model_fields(b'"model" = "old"\n', {"model": "new"})
        self.assertEqual(tomllib.loads(out.decode())["model"], "new")

    def test_multiline_model_assignment_rejected_without_writes(self):
        self.config.write_text('model = """\nold\n"""\n')
        with self.assertRaisesRegex(d.DefaultsError, "unsupported_model_assignment"):
            self.plan(profile="balanced")
        self.assertFalse(d.state_path(self.home).exists())

    def test_non_openai_provider_not_silently_replaced(self):
        self.config.write_text('model = "other"\nmodel_provider = "freellmapi"\n')
        with self.assertRaisesRegex(d.DefaultsError, "provider_conflict"):
            self.plan(profile="balanced")
        self.apply(profile="auto")
        self.assertEqual(tomllib.loads(self.config.read_text())["model_provider"], "freellmapi")

    def test_invalid_pin_and_conflicting_options_refused(self):
        for kwargs in ({"model": "x"}, {"model": "x", "effort": "low", "recommended": True},
                       {"model": "bad\nmodel", "effort": "low"}, {"profile": "bad"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(d.DefaultsError):
                self.plan(**kwargs)

    def test_missing_assets_blocks_apply_not_preview(self):
        (self.skills / "omnicodex/SKILL.md").unlink()
        plan = self.plan()
        with self.assertRaisesRegex(d.DefaultsError, "skill_not_installed"):
            d.apply_plan(plan)
        self.assertFalse(d.state_path(self.home).exists())

    def test_concurrent_change_does_not_get_overwritten(self):
        plan = self.plan(profile="balanced")
        self.config.write_text('model = "changed-after-preview"\n')
        with self.assertRaisesRegex(d.DefaultsError, "concurrent_change"):
            d.apply_plan(plan)
        self.assertIn("changed-after-preview", self.config.read_text())

    def test_lock_prevents_two_writers(self):
        (self.home / "omnicodex").mkdir()
        (self.home / "omnicodex/preferences.lock").touch()
        with self.assertRaisesRegex(d.DefaultsError, "locked"):
            d.apply_plan(self.plan())

    def test_partial_write_failure_rolls_back_modified_files(self):
        plan = self.plan(profile="balanced")
        original = self.config.read_bytes()
        real = d.atomic_replace
        failed = False
        def fail_once(path, data):
            nonlocal failed
            if path == self.config and not failed:
                failed = True
                raise OSError("synthetic")
            return real(path, data)
        with patch.object(d, "atomic_replace", side_effect=fail_once), self.assertRaises(OSError):
            d.apply_plan(plan)
        self.assertEqual(self.config.read_bytes(), original)
        self.assertFalse((self.home / "AGENTS.md").exists())
        self.assertFalse(d.state_path(self.home).exists())
        self.assertFalse((self.home / "omnicodex/preferences.lock").exists())
        self.assertEqual(len(list((self.home / "omnicodex/preferences-backups").glob("*/journal.json"))), 1)

    def test_failure_after_replace_is_also_rolled_back(self):
        plan = self.plan(profile="balanced")
        before = self.config.read_bytes()
        real = d.atomic_replace
        failed = False
        def fail_after(path, data):
            nonlocal failed
            real(path, data)
            if path == self.config and not failed:
                failed = True
                raise OSError("after replace")
        with patch.object(d, "atomic_replace", side_effect=fail_after), self.assertRaises(OSError):
            d.apply_plan(plan)
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.home / "AGENTS.md").exists())

    def test_snapshot_backups_created(self):
        before = self.config.read_bytes()
        result = d.apply_plan(self.plan(profile="balanced"))
        folder = Path(result["backup"])
        journal = json.loads((folder / "journal.json").read_text())
        record = next(x for x in journal if x["target"] == str(self.config))
        self.assertEqual((folder / record["original_file"]).read_bytes(), before)

    def test_status_no_write_and_absent_state(self):
        self.assertEqual(d.status(self.home), {"configured": False, "runtime_verified": False})
        self.assertFalse((self.home / "omnicodex").exists())

    def test_duplicate_state_keys_rejected(self):
        (self.home / "omnicodex").mkdir()
        d.state_path(self.home).write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaises(d.DefaultsError):
            d.load_state(self.home)

    def test_unowned_installed_tool_refused(self):
        (self.home / "omnicodex").mkdir()
        (self.home / "omnicodex/defaults.py").write_text("other tool")
        with self.assertRaisesRegex(d.DefaultsError, "unowned_or_edited_tool"):
            self.plan()

    def test_global_env_selection_for_status(self):
        out = io.StringIO()
        with patch.dict(os.environ, {"CODEX_HOME": str(self.home)}), contextlib.redirect_stdout(out):
            self.assertEqual(d.main(["status"]), 0)
        self.assertFalse(json.loads(out.getvalue())["configured"])

    def test_no_legacy_profile_key_written_or_provider_or_permissions_changed(self):
        self.apply(profile="max")
        data = tomllib.loads(self.config.read_text())
        self.assertNotIn("profile", data)
        self.assertNotIn("model_provider", data)
        self.assertNotIn("approval_policy", data)
        self.assertFalse(data["sandbox_workspace_write"]["network_access"])


def stat_mode_directory():
    import stat
    return stat.S_IFDIR | 0o700


def stat_mode_symlink():
    import stat
    return stat.S_IFLNK | 0o777


if __name__ == "__main__":
    unittest.main()
