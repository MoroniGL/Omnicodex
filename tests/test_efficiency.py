"""Offline policy tests. Synthetic inventories are not live integration evidence."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("efficiency", ROOT / "scripts" / "efficiency.py")
efficiency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(efficiency)


class EfficiencyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = efficiency.read_json(ROOT / "integrations" / "efficiency.json")
        self.inventory = efficiency.read_json(ROOT / "examples" / "efficiency-inventory.json")

    def plan(self, task="structural", enable=None, session="example-only-not-live",
             snapshot="example-workspace-fingerprint", profile="balanced"):
        return efficiency.make_plan(self.manifest, self.inventory, profile, task,
                                    set(enable or []), session, snapshot)

    def test_shipped_manifest_is_valid(self):
        efficiency.validate_manifest(self.manifest)

    def test_shipped_inventory_is_valid(self):
        efficiency.validate_inventory(self.inventory)

    def test_no_inventory_uses_native(self):
        self.inventory = None
        self.assertEqual(self.plan(enable=["codebase-memory-mcp"])["provider"], "native")

    def test_opt_in_is_required(self):
        self.assertEqual(self.plan()["provider"], "native")

    def test_graph_selected_from_supplied_evidence(self):
        result = self.plan(enable=["codebase-memory-mcp"])
        self.assertEqual(result["provider"], "codebase-memory-mcp")
        self.assertFalse(result["runtime_model_verified"])
        self.assertEqual(result["mode"], "advisory_dry_run")

    def test_stale_graph_falls_back(self):
        self.assertEqual(self.plan(enable=["codebase-memory-mcp"],
                                   snapshot="changed-worktree")["provider"], "native")

    def test_unknown_graph_snapshot_falls_back(self):
        self.assertEqual(self.plan(enable=["codebase-memory-mcp"], snapshot=None)["provider"], "native")

    def test_other_session_falls_back(self):
        self.assertEqual(self.plan(enable=["codebase-memory-mcp"], session="other")["provider"], "native")

    def test_missing_session_falls_back(self):
        self.assertEqual(self.plan(enable=["context-mode"], task="large-output",
                                   session=None)["provider"], "native")

    def test_failed_probe_falls_back(self):
        self.inventory["providers"]["context-mode"]["probe_ok"] = False
        self.assertEqual(self.plan(task="large-output", enable=["context-mode"])["provider"], "native")

    def test_missing_tool_falls_back(self):
        self.inventory["providers"]["context-mode"]["tools"].remove("ctx_search")
        self.assertEqual(self.plan(task="large-output", enable=["context-mode"])["provider"], "native")

    def test_output_path_selects_one_compressor(self):
        result = self.plan(task="large-output", enable=list(efficiency.PROVIDERS))
        self.assertEqual(result["provider"], "context-mode")
        self.assertEqual(result["output_compressor"], "context-mode")

    def test_small_implementation_stays_native(self):
        self.assertEqual(self.plan(task="implementation", enable=list(efficiency.PROVIDERS))
                         ["provider"], "native")

    def test_review_does_not_force_compression(self):
        self.assertEqual(self.plan(task="review", enable=list(efficiency.PROVIDERS))
                         ["output_compressor"], "none")

    def test_all_profiles_preserve_quality_and_no_switch(self):
        for profile in efficiency.PROFILES:
            with self.subTest(profile=profile):
                result = self.plan(profile=profile)
                self.assertTrue(result["quality_checks_required"])
                self.assertTrue(result["raw_evidence_required"])
                self.assertTrue(result["handoff_target_is_soft"])
                self.assertFalse(result["model_switch_performed"])

    def test_unknown_provider_rejected(self):
        with self.assertRaises(ValueError):
            self.plan(enable=["rtk"])

    def test_unknown_inventory_provider_rejected(self):
        self.inventory["providers"]["unknown"] = {}
        with self.assertRaises(ValueError):
            efficiency.validate_inventory(self.inventory)

    def test_string_boolean_rejected(self):
        self.inventory["providers"]["context-mode"]["probe_ok"] = "true"
        with self.assertRaises(ValueError):
            efficiency.validate_inventory(self.inventory)

    def test_duplicate_tool_rejected(self):
        self.inventory["providers"]["context-mode"]["tools"].append("ctx_search")
        with self.assertRaises(ValueError):
            efficiency.validate_inventory(self.inventory)

    def test_empty_session_rejected(self):
        self.inventory["session_id"] = ""
        with self.assertRaises(ValueError):
            efficiency.validate_inventory(self.inventory)

    def test_safety_policy_cannot_be_disabled(self):
        for key in self.manifest["policy"]:
            manifest = copy.deepcopy(self.manifest)
            manifest["policy"][key] = not manifest["policy"][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                efficiency.validate_manifest(manifest)

    def test_boolean_budget_rejected(self):
        self.manifest["profiles"]["balanced"]["handoff_target_words"] = True
        with self.assertRaises(ValueError):
            efficiency.validate_manifest(self.manifest)

    def test_input_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b" " * (efficiency.MAX_INPUT_BYTES + 1))
            with self.assertRaises(ValueError):
                efficiency.read_json(path)

    def test_bad_json_does_not_echo_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"credential": SECRET_SENTINEL}', encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                result = efficiency.main(["plan", "--inventory", str(path)])
            self.assertEqual(result, 2)
            self.assertNotIn("SECRET_SENTINEL", error.getvalue())

    def test_doctor_does_not_assert_runtime_success(self):
        output = io.StringIO()
        with patch.object(efficiency.shutil, "which", return_value="/example/bin/tool"), \
                contextlib.redirect_stdout(output):
            self.assertEqual(efficiency.main(["doctor"]), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(all(result["binaries_on_path"].values()))
        self.assertFalse(result["live_mcp_checked"])
        self.assertFalse(result["hooks_checked"])
        self.assertFalse(result["runtime_model_verified"])

    def test_skill_metadata_and_reference_exist(self):
        skill = (ROOT / "skills" / "omnicodex" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: omnicodex\n"))
        self.assertIn("\ndescription: ", skill)
        self.assertTrue((ROOT / "skills" / "omnicodex" / "references" / "efficiency.md").is_file())


if __name__ == "__main__":
    unittest.main()
