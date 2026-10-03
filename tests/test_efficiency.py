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

    def offload_metrics(self, **overrides):
        value = {
            "schema_version": 1,
            "task_kind": "repo_scout",
            "estimated_chars": 80_000,
            "file_count": 24,
            "diff_lines": 0,
            "log_bytes": 0,
            "search_hits": 80,
            "data_classification": "public",
            "external_offload_approved": True,
            "provider_available": True,
            "independent_units": 4,
        }
        value.update(overrides)
        return value

    def evidence_pack(self):
        return {
            "schema_version": 1,
            "status": "completed",
            "task_kind": "repo_scout",
            "snapshot": "example-worktree",
            "summary": "Relevant routing state is split between session and persistent helpers.",
            "relevant_files": ["scripts/session_switch.py", "scripts/defaults.py"],
            "findings": [{
                "claim": "Session overrides and saved defaults use separate state paths.",
                "evidence": [{
                    "path": "scripts/session_switch.py",
                    "start_line": 80,
                    "end_line": 130,
                    "kind": "source",
                }],
            }],
            "risks": ["Live provider behavior is not proven by this offline pack."],
            "unknowns": [],
            "validation": [{
                "check": "offline contract",
                "status": "not_run",
                "reference": "example-only",
            }],
        }

    def test_large_approved_context_routes_to_free_context_worker(self):
        result = efficiency.make_offload_plan(
            self.manifest, self.offload_metrics(), "balanced"
        )
        self.assertEqual(result["route"], "free_context_worker")
        self.assertEqual(result["provider"], "freellmapi")
        self.assertTrue(result["read_only_worker"])
        self.assertTrue(result["parallel_read_only_ok"])
        self.assertFalse(result["quota_fallback"])
        self.assertEqual(result["network_requests"], 0)

    def test_small_context_stays_native(self):
        result = efficiency.make_offload_plan(
            self.manifest,
            self.offload_metrics(estimated_chars=4_000, file_count=2),
            "balanced",
        )
        self.assertEqual(result["route"], "native")
        self.assertIn("context_below_offload_threshold", result["reason_codes"])

    def test_sensitive_or_unapproved_context_never_externalizes(self):
        for overrides, reason in (
            ({"data_classification": "sensitive"}, "sensitive_data"),
            ({"external_offload_approved": False}, "workspace_not_opted_in"),
            ({"provider_available": False}, "provider_not_available"),
        ):
            with self.subTest(reason=reason):
                result = efficiency.make_offload_plan(
                    self.manifest, self.offload_metrics(**overrides), "economy"
                )
                self.assertEqual(result["route"], "native")
                self.assertIn(reason, result["reason_codes"])

    def test_task_volume_gate_can_trigger_below_primary_threshold(self):
        result = efficiency.make_offload_plan(
            self.manifest,
            self.offload_metrics(estimated_chars=32_000, file_count=20),
            "balanced",
        )
        self.assertEqual(result["route"], "free_context_worker")
        self.assertIn("task_volume_threshold", result["reason_codes"])

    def test_evidence_pack_contract_is_source_linked_and_bounded(self):
        pack = self.evidence_pack()
        efficiency.validate_evidence_pack(pack)
        raw = json.dumps(pack)
        self.assertNotIn("raw_content", raw)
        self.assertNotIn("source_excerpt", raw)
        bad = copy.deepcopy(pack)
        bad["relevant_files"] = ["../secret.txt"]
        with self.assertRaises(ValueError):
            efficiency.validate_evidence_pack(bad)

    def test_offload_receipt_estimates_avoided_context_not_billing(self):
        result = efficiency.make_offload_receipt(
            self.manifest, self.offload_metrics(), self.evidence_pack(), "balanced"
        )
        self.assertGreater(result["estimated_premium_context_avoided"], 0)
        self.assertFalse(result["billing_verified"])
        self.assertFalse(result["runtime_verified"])
        self.assertFalse(result["quota_fallback"])

    def test_manifest_keeps_quota_fallback_disabled(self):
        self.assertEqual(self.manifest["token_offload"]["provider"], "freellmapi")
        self.assertFalse(self.manifest["token_offload"]["quota_fallback"])
        self.assertTrue(self.manifest["token_offload"]["workspace_opt_in_required"])
        self.assertTrue(self.manifest["token_offload"]["sensitive_externalization_forbidden"])

    def test_skill_metadata_and_reference_exist(self):
        skill = (ROOT / "skills" / "omnicodex" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: omnicodex\n"))
        self.assertIn("\ndescription: ", skill)
        self.assertTrue((ROOT / "skills" / "omnicodex" / "references" / "efficiency.md").is_file())


if __name__ == "__main__":
    unittest.main()
