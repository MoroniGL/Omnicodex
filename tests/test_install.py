"""Behavior tests for the non-destructive OmniCodex installer."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.install import InstallConflict, inspect_profile, install


ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_installs_all_profiles_agents_and_skill_without_changing_base_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex-home"
            skills_home = root / "skills"
            codex_home.mkdir()
            original_config = 'model = "existing-model"\nmodel_reasoning_effort = "high"\n'
            (codex_home / "config.toml").write_text(original_config)

            manifest = install(ROOT, codex_home, skills_home)

            self.assertEqual((codex_home / "config.toml").read_text(), original_config)
            self.assertEqual(
                {path.name for path in codex_home.glob("omnicodex-*.config.toml")},
                {
                    "omnicodex-economy.config.toml",
                    "omnicodex-balanced.config.toml",
                    "omnicodex-quality.config.toml",
                    "omnicodex-max.config.toml",
                },
            )
            self.assertEqual(len(list((codex_home / "agents").glob("*.toml"))), 7)
            self.assertTrue((skills_home / "omnicodex" / "SKILL.md").is_file())
            reference = skills_home / "omnicodex" / "references" / "efficiency.md"
            self.assertEqual(reference.read_bytes(),
                             (ROOT / "skills/omnicodex/references/efficiency.md").read_bytes())
            self.assertEqual(len(manifest["files"]), 13)
            self.assertTrue(any(item["destination"] == str(reference.resolve())
                                for item in manifest["files"]))
            self.assertEqual(
                json.loads((codex_home / "omnicodex" / "install-manifest.json").read_text())["result"],
                "installed",
            )
            self.assertEqual((Path(manifest["backup"]) / "config.toml").read_text(), original_config)

    def test_refuses_to_replace_a_conflicting_destination_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex-home"
            skills_home = root / "skills"
            codex_home.mkdir()
            destination = codex_home / "omnicodex-balanced.config.toml"
            destination.write_text('model = "unrelated"\n')

            with self.assertRaises(InstallConflict):
                install(ROOT, codex_home, skills_home)

            self.assertEqual(destination.read_text(), 'model = "unrelated"\n')
            self.assertFalse((codex_home / "omnicodex-economy.config.toml").exists())

    def test_replacement_backs_up_the_previous_file_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex-home"
            skills_home = root / "skills"
            codex_home.mkdir()
            destination = codex_home / "omnicodex-balanced.config.toml"
            destination.write_text('model = "old-omnicodex"\n')

            manifest = install(ROOT, codex_home, skills_home, replace_existing=True)

            entry = next(
                item for item in manifest["files"] if item["destination"] == str(destination.resolve())
            )
            self.assertEqual(Path(entry["backup"]).read_text(), 'model = "old-omnicodex"\n')
            self.assertEqual(destination.read_bytes(), (ROOT / "profiles" / "balanced.config.toml").read_bytes())

    def test_reference_conflict_is_rejected_before_installing_other_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "skills/omnicodex/references/efficiency.md"
            reference.parent.mkdir(parents=True)
            reference.write_text("Existing custom reference.\n", encoding="utf-8")
            with self.assertRaises(InstallConflict):
                install(ROOT, root / "codex", root / "skills")
            self.assertEqual(reference.read_text(), "Existing custom reference.\n")
            self.assertFalse((root / "codex").exists())

    def test_reference_replacement_is_backed_up_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "skills/omnicodex/references/efficiency.md"
            reference.parent.mkdir(parents=True)
            reference.write_text("Previous reference.\n", encoding="utf-8")
            manifest = install(ROOT, root / "codex", root / "skills", replace_existing=True)
            entry = next(item for item in manifest["files"]
                         if item["destination"] == str(reference.resolve()))
            self.assertEqual(entry["action"], "replaced")
            self.assertEqual(Path(entry["backup"]).read_text(), "Previous reference.\n")
            self.assertEqual(reference.read_bytes(),
                             (ROOT / "skills/omnicodex/references/efficiency.md").read_bytes())

    def test_missing_required_reference_fails_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for name in ("profiles", "agents", "skills"):
                shutil.copytree(ROOT / name, source / name)
            (source / "skills/omnicodex/references/efficiency.md").unlink()
            with self.assertRaises(FileNotFoundError):
                install(source, root / "codex", root / "installed-skills")
            self.assertFalse((root / "codex").exists())
            self.assertFalse((root / "installed-skills").exists())


class ProfileInspectionTests(unittest.TestCase):
    def test_user_config_is_not_reloaded_as_a_project_layer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            codex_home = home / ".codex"
            project = home / "project"
            codex_home.mkdir()
            project.mkdir()
            (codex_home / "config.toml").write_text(
                'model = "global"\nmodel_reasoning_effort = "ultra"\n'
            )
            (codex_home / "omnicodex-balanced.config.toml").write_text(
                'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "medium"\n'
            )

            result = inspect_profile(codex_home, "omnicodex-balanced", project)

            self.assertEqual(result["resolved_model"], "gpt-5.6-sol")
            self.assertEqual(result["resolved_reasoning_effort"], "medium")
            self.assertFalse(result["project_overrides_profile"])

    def test_project_model_override_is_reported_as_higher_precedence_than_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex_home = root / "codex-home"
            project = root / "project"
            nested = project / "src"
            codex_home.mkdir()
            nested.mkdir(parents=True)
            (codex_home / "config.toml").write_text('model = "global"\nmodel_reasoning_effort = "low"\n')
            (codex_home / "omnicodex-balanced.config.toml").write_text(
                'model = "gpt-5.6-sol"\nmodel_reasoning_effort = "medium"\n'
            )
            (project / ".codex").mkdir()
            (project / ".codex" / "config.toml").write_text('model = "project-model"\n')

            result = inspect_profile(codex_home, "omnicodex-balanced", nested)

            self.assertEqual(result["resolved_model"], "project-model")
            self.assertEqual(result["resolved_reasoning_effort"], "medium")
            self.assertEqual(
                result["model_source"], str((project / ".codex" / "config.toml").resolve())
            )
            self.assertTrue(result["project_overrides_profile"])


if __name__ == "__main__":
    unittest.main()
