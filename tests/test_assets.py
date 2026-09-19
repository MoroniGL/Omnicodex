"""Regression checks for the declarative OmniCodex routing assets."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

AGENTS = {
    "luna-researcher": ("gpt-5.6-luna", "low"),
    "terra-explorer": ("gpt-5.6-terra", "low"),
    "terra-implementer": ("gpt-5.6-terra", "medium"),
    "sol-planner": ("gpt-5.6-sol", "medium"),
    "sol-reviewer": ("gpt-5.6-sol", "medium"),
    "sol-debugger": ("gpt-5.6-sol", "high"),
    "astra-expert": ("gpt-6-astra", "high"),
}

PROFILES = {
    "economy": ("gpt-5.6-terra", "medium"),
    "balanced": ("gpt-5.6-sol", "medium"),
    "quality": ("gpt-5.6-sol", "high"),
    "max": ("gpt-6-astra", "high"),
}


class AssetTests(unittest.TestCase):
    def test_agent_files_have_required_ids_and_explicit_runtime_fields(self) -> None:
        self.assertEqual(
            {path.stem for path in (ROOT / "agents").glob("*.toml")}, set(AGENTS)
        )
        for agent_id, (model, effort) in AGENTS.items():
            with self.subTest(agent=agent_id):
                with (ROOT / "agents" / f"{agent_id}.toml").open("rb") as asset:
                    agent = tomllib.load(asset)

                self.assertEqual(agent["name"], agent_id)
                self.assertEqual(agent["model"], model)
                self.assertEqual(agent["model_reasoning_effort"], effort)
                self.assertTrue(agent["description"].strip())
                self.assertTrue(agent["developer_instructions"].strip())

    def test_agent_models_use_canonical_model_ids(self) -> None:
        allowed_models = {model for model, _ in AGENTS.values()}
        for path in (ROOT / "agents").glob("*.toml"):
            with self.subTest(asset=path.name), path.open("rb") as asset:
                agent = tomllib.load(asset)
                self.assertIn(agent["model"], allowed_models)
                self.assertNotIn(agent["model"].lower(), {"astra", "luna", "sol", "terra"})

    def test_profile_matrix_uses_explicit_runtime_fields(self) -> None:
        self.assertEqual(
            {path.name.removesuffix(".config.toml") for path in (ROOT / "profiles").glob("*.config.toml")},
            set(PROFILES),
        )
        for profile_id, (model, effort) in PROFILES.items():
            with self.subTest(profile=profile_id):
                with (ROOT / "profiles" / f"{profile_id}.config.toml").open("rb") as asset:
                    profile = tomllib.load(asset)

                self.assertEqual(profile["model"], model)
                self.assertEqual(profile["model_reasoning_effort"], effort)
                self.assertIn(profile["model"], {model for model, _ in AGENTS.values()})
                self.assertIn(profile["agents"]["default_subagent_model"], {model for model, _ in AGENTS.values()})
                self.assertIn(
                    profile["agents"]["default_subagent_reasoning_effort"],
                    {"low", "medium", "high"},
                )

    def test_skill_has_required_frontmatter(self) -> None:
        skill = (ROOT / "skills" / "omnicodex" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        frontmatter, separator, _ = skill[4:].partition("\n---\n")
        self.assertTrue(separator, "Frontmatter must have a closing delimiter")
        self.assertTrue(frontmatter)
        metadata = dict(
            line.split(":", 1) for line in frontmatter.splitlines() if ":" in line
        )
        self.assertEqual(metadata.get("name", "").strip(), "omnicodex")
        self.assertTrue(metadata.get("description", "").strip())



if __name__ == "__main__":
    unittest.main()
