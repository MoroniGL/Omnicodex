"""Explicit LF/CRLF regression cases; run on every OS without model calls."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import defaults as d


class DefaultsNewlineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home = self.root / "codex"
        self.skills = self.root / "skills"
        self.home.mkdir()
        (self.skills / "omnicodex").mkdir(parents=True)
        (self.skills / "omnicodex/SKILL.md").write_bytes(b"---\nname: omnicodex\n---\nPolicy\n")
        for profile in d.PROFILES[1:]:
            (self.home / f"omnicodex-{profile}.config.toml").write_bytes(
                f'model = "fixture-{profile}"\nmodel_reasoning_effort = "medium"\n'.encode())
        self.config = self.home / "config.toml"
        self.original_config = b'model = "original"\nmodel_reasoning_effort = "low"\n'
        self.config.write_bytes(self.original_config)
        self.guidance = self.home / "AGENTS.md"

    def plan(self, **kwargs):
        return d.build_plan(self.home, skills_home=self.skills, **kwargs)

    def apply(self, **kwargs):
        return d.apply_plan(self.plan(**kwargs))

    def snapshot(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob("*") if p.is_file()}

    def test_strip_lf_crlf_and_mixed_preserves_unmanaged_text_exactly(self):
        self.apply()
        state = d.load_state(self.home)
        block = state["block"]
        parts = block.split("\n")
        mixed = "".join(part + ("\r\n" if index % 2 else "\n")
                        for index, part in enumerate(parts[:-1])) + parts[-1]
        prefix = "# User header\r\n  keep spaces\n"
        suffix = "User note\r\nUnicode: ação\n\tkeep tab\rbare-CR\r\n"
        for variant in (block, block.replace("\n", "\r\n"), mixed):
            with self.subTest(variant=repr(variant[-20:])):
                self.assertEqual(d.strip_block(prefix + variant + suffix, state), prefix + suffix)

    def test_windows_text_rewrite_then_profile_change(self):
        self.apply()
        # Force Windows text-mode conversion even on Linux CI. Original test stays unchanged.
        content = self.guidance.read_text(encoding="utf-8") + "New user guidance.\n"
        self.guidance.write_text(content, encoding="utf-8", newline="\r\n")
        self.assertIn(b"\r\n", self.guidance.read_bytes())
        self.assertTrue(d.status(self.home)["managed_block_intact"])
        before = self.snapshot()
        plan = self.plan(profile="balanced")
        self.assertEqual(self.snapshot(), before)  # Preview remains read-only.
        self.assertTrue(plan["after"][self.guidance].endswith(b"New user guidance.\r\n"))
        d.apply_plan(plan)
        self.assertEqual(d.status(self.home)["profile"], "balanced")
        self.assertTrue(d.status(self.home)["managed_block_intact"])
        self.assertEqual(self.apply()["result"], "unchanged")

    def test_disable_preserves_bom_and_unmanaged_bytes_after_crlf_rewrite(self):
        self.apply(profile="balanced")
        block = d.load_state(self.home)["block"].replace("\n", "\r\n").encode()
        tail = "# Minhas instruções\r\n  trailing spaces  \n\tKeep\r\n".encode()
        bom = b"\xef\xbb\xbf"
        self.guidance.write_bytes(bom + block + tail)
        self.apply(enabled=False)
        self.assertEqual(self.guidance.read_bytes(), bom + tail)
        self.assertEqual(d.parse_config(self.config.read_bytes()), d.parse_config(self.original_config))
        self.assertFalse(d.status(self.home)["enabled"])

    def test_status_accepts_crlf_without_rewriting_anything(self):
        self.apply()
        self.guidance.write_bytes(self.guidance.read_bytes().replace(b"\n", b"\r\n"))
        before = self.snapshot()
        self.assertTrue(d.status(self.home)["managed_block_intact"])
        self.assertFalse(d.status(self.home)["runtime_verified"])
        self.assertEqual(self.snapshot(), before)

    def test_semantic_whitespace_and_bare_cr_edits_still_rejected(self):
        self.apply()
        state = d.load_state(self.home)
        block = state["block"]
        variants = (
            block.replace("Saved policy: auto", "Saved policy: max"),
            block.replace("Never change permissions", "Change permissions"),
            block.replace("Saved policy:", "Saved  policy:"),
            block.replace("\n# OmniCodex", "\n\n# OmniCodex"),
            block.replace("\n", "\r"),
            block.replace("\n", "\r\r\n"),
        )
        for variant in variants:
            with self.subTest(variant=repr(variant[:80])):
                with self.assertRaisesRegex(d.DefaultsError, "managed_guidance_changed"):
                    d.strip_block(variant, state)

    def test_duplicate_or_missing_markers_refused_by_status_and_plan(self):
        self.apply()
        block = d.load_state(self.home)["block"].replace("\n", "\r\n")
        variants = (block + block, block + d.START, block + d.END,
                    block.replace(d.START, "", 1), block.replace(d.END, "", 1))
        for variant in variants:
            with self.subTest(variant=repr(variant[-80:])):
                self.guidance.write_bytes(variant.encode())
                before = self.snapshot()
                self.assertFalse(d.status(self.home)["managed_block_intact"])
                with self.assertRaisesRegex(d.DefaultsError, "managed_guidance_changed"):
                    self.plan(profile="balanced")
                self.assertEqual(self.snapshot(), before)

    def test_real_edit_with_crlf_still_blocks_before_writes(self):
        self.apply()
        block = d.load_state(self.home)["block"]
        self.guidance.write_bytes(block.replace("Saved policy: auto", "Saved policy: max")
                                  .replace("\n", "\r\n").encode())
        before = self.snapshot()
        self.assertFalse(d.status(self.home)["managed_block_intact"])
        with self.assertRaisesRegex(d.DefaultsError, "managed_guidance_changed"):
            self.apply(profile="balanced")
        self.assertEqual(self.snapshot(), before)

    def test_rollback_restores_exact_crlf_bytes_on_later_write_failure(self):
        self.apply()
        block = d.load_state(self.home)["block"].replace("\n", "\r\n")
        original_guidance = (block + "User note\r\n").encode()
        self.guidance.write_bytes(original_guidance)
        previous_state = d.state_path(self.home).read_bytes()
        previous_tool = (self.home / "omnicodex/defaults.py").read_bytes()
        plan = self.plan(profile="balanced")
        real = d.atomic_replace

        def fail_config(path, data):
            if path == self.config:
                raise OSError("synthetic write failure")
            return real(path, data)

        with patch.object(d, "atomic_replace", side_effect=fail_config), self.assertRaises(OSError):
            d.apply_plan(plan)
        self.assertEqual(self.guidance.read_bytes(), original_guidance)
        self.assertEqual(self.config.read_bytes(), self.original_config)
        self.assertEqual(d.state_path(self.home).read_bytes(), previous_state)
        self.assertEqual((self.home / "omnicodex/defaults.py").read_bytes(), previous_tool)
        self.assertFalse((self.home / "omnicodex/preferences.lock").exists())


if __name__ == "__main__":
    unittest.main()
