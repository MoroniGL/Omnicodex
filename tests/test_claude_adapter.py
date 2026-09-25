"""Static validation for the experimental OmniClaude plugin assets."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "adapters" / "claude-code"


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError(f"missing frontmatter: {path}")
    block, separator, _ = text[4:].partition("\n---\n")
    if not separator:
        raise AssertionError(f"unclosed frontmatter: {path}")
    result = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip()
    return result


class ClaudeAdapterTests(unittest.TestCase):
    def test_plugin_manifest(self) -> None:
        manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "omniclaude")
        self.assertTrue(manifest["version"].startswith("0.1.0-alpha"))
        self.assertTrue(manifest["description"])

    def test_initial_agent_matrix(self) -> None:
        expected = {
            "researcher.md": "haiku",
            "implementer.md": "sonnet",
            "reviewer.md": "opus",
            "debugger.md": "opus",
        }
        self.assertEqual({p.name for p in (PLUGIN / "agents").glob("*.md")}, set(expected))
        for filename, model in expected.items():
            with self.subTest(filename=filename):
                meta = frontmatter(PLUGIN / "agents" / filename)
                self.assertEqual(meta["model"], model)
                self.assertTrue(meta["name"])
                self.assertTrue(meta["description"])

    def test_plugin_does_not_auto_register_hooks_or_mcp(self) -> None:
        self.assertFalse((PLUGIN / "hooks").exists())
        self.assertFalse((PLUGIN / ".mcp.json").exists())

    def test_skill_exists_and_keeps_parent_model_explicit(self) -> None:
        skill = PLUGIN / "skills" / "omniclaude" / "SKILL.md"
        meta = frontmatter(skill)
        self.assertEqual(meta["name"], "omniclaude")
        text = skill.read_text(encoding="utf-8")
        self.assertIn("Keep the active parent model unchanged", text)
        self.assertIn("OMNI_JEV=1", text)


if __name__ == "__main__":
    unittest.main()
