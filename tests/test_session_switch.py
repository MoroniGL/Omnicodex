"""Offline tests for per-session OmniCodex profile switching."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import session_switch as s


class SessionSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "codex"
        (self.home / "omnicodex").mkdir(parents=True)
        (self.home / "omnicodex" / "preferences.json").write_text(
            json.dumps({"enabled": True, "profile": "balanced"}),
            encoding="utf-8",
        )
        profiles = {
            "economy": ("gpt-5.6-terra", "medium"),
            "balanced": ("gpt-5.6-sol", "medium"),
            "quality": ("gpt-5.6-sol", "high"),
            "max": ("gpt-6-astra", "high"),
        }
        for name, (model, effort) in profiles.items():
            (self.home / f"omnicodex-{name}.config.toml").write_text(
                f'model = "{model}"\nmodel_reasoning_effort = "{effort}"\n',
                encoding="utf-8",
            )

    def payload(self, prompt: str, session: str = "thr-a",
                model: str = "gpt-5.6-sol"):
        return {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session,
            "prompt": prompt,
            "model": model,
        }

    def context(self, result):
        return result["hookSpecificOutput"]["additionalContext"]

    def test_ordinary_prompt_without_override_adds_no_context(self):
        self.assertIsNone(s.process(self.payload("fix the tests"), home=self.home))
        self.assertFalse((self.home / "omnicodex/session-overrides").exists())

    def test_exact_temporary_command_persists_within_same_session_only(self):
        first = s.process(self.payload("omni quality"), home=self.home)
        self.assertIn("Effective policy: quality", self.context(first))
        second = s.process(self.payload("continue"), home=self.home)
        self.assertIn("Effective policy: quality", self.context(second))
        self.assertIsNone(
            s.process(self.payload("continue", session="thr-b"), home=self.home)
        )

    def test_alias_command_forms(self):
        for prompt in (
            "OmniCodex profile economy",
            "omni use economy",
            "OMNI ECONOMY",
        ):
            with self.subTest(prompt=prompt):
                session = "thr-" + str(abs(hash(prompt)))
                result = s.process(self.payload(prompt, session=session), home=self.home)
                self.assertIn("Effective policy: economy", self.context(result))

    def test_mentions_inside_other_text_are_not_commands(self):
        for prompt in (
            "Please document `omni quality` as an example.",
            "run omni quality and then continue",
            "```text\nomni quality\n```",
        ):
            with self.subTest(prompt=prompt):
                self.assertIsNone(
                    s.process(self.payload(prompt, session=prompt), home=self.home)
                )

    def test_reset_returns_to_saved_policy_and_deletes_state(self):
        s.process(self.payload("omni max"), home=self.home)
        result = s.process(self.payload("omni reset"), home=self.home)
        context = self.context(result)
        self.assertIn("Effective policy: balanced", context)
        self.assertIn("cleared the temporary override", context)
        self.assertIsNone(s.load_session(self.home, "thr-a"))

    def test_status_reports_saved_policy_without_creating_override(self):
        result = s.process(self.payload("omni status"), home=self.home)
        context = self.context(result)
        self.assertIn("Effective policy: balanced", context)
        self.assertIn("Saved persistent policy: balanced", context)
        self.assertIsNone(s.load_session(self.home, "thr-a"))

    def test_status_reports_offline_native_and_unconfigured_gemini_paths(self):
        with patch.dict("os.environ", {}, clear=True):
            result = s.process(self.payload("omni status"), home=self.home)
        context = self.context(result)
        self.assertIn("Native path: READY", context)
        self.assertIn("Gemini Direct offload: NOT CONFIGURED", context)
        self.assertIn("connectivity was not probed", context)

    def test_status_reports_configured_gemini_model_without_connectivity_claim(self):
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key-only",
            "OMNICODEX_GEMINI_MODEL": "gemini-2.5-flash-lite",
        }, clear=True):
            result = s.process(self.payload("omni status"), home=self.home)
        context = self.context(result)
        self.assertIn("Gemini Direct offload: READY", context)
        self.assertIn("provider: gemini_direct; model: gemini-2.5-flash-lite", context)
        self.assertNotIn("test-key-only", context)

    def test_save_persists_inside_trusted_hook_and_clears_pending(self):
        def persist(home, profile):
            (home / "omnicodex/preferences.json").write_text(
                json.dumps({"enabled": True, "profile": profile}), encoding="utf-8"
            )
            return {"result": "configured_for_new_sessions"}

        with patch.object(s, "_persist_profile", side_effect=persist) as call:
            result = s.process(self.payload("omni save max"), home=self.home)
        context = self.context(result)
        self.assertIn("Effective policy: max", context)
        self.assertIn("Saved persistent policy: max", context)
        self.assertIn("Persistent save completed inside the trusted hook", context)
        self.assertNotIn("defaults.py", context)
        self.assertEqual(call.call_count, 1)
        state = s.load_session(self.home, "thr-a")
        self.assertIsNone(state["persist_requested"])

    def test_save_failure_keeps_temporary_override_and_never_requests_agent_shell_retry(self):
        with patch.object(
            s, "_persist_profile", side_effect=s.SessionSwitchError("synthetic")
        ):
            result = s.process(self.payload("omni save quality"), home=self.home)
        context = self.context(result)
        self.assertIn("Effective policy: quality", context)
        self.assertIn("Saved persistent policy: balanced", context)
        self.assertIn("Persistent save failed inside the trusted hook", context)
        self.assertIn("must not retry persistence through its shell", context)
        self.assertNotIn("defaults.py", context)
        state = s.load_session(self.home, "thr-a")
        self.assertEqual(state["persist_requested"], "quality")

    def test_persistence_request_clears_after_saved_profile_matches(self):
        s.process(self.payload("omni save max"), home=self.home)
        (self.home / "omnicodex/preferences.json").write_text(
            json.dumps({"enabled": True, "profile": "max"}), encoding="utf-8"
        )
        result = s.process(self.payload("continue"), home=self.home)
        self.assertNotIn("explicitly requested persistence", self.context(result))
        self.assertIsNone(s.load_session(self.home, "thr-a")["persist_requested"])

    def test_profile_recommendation_and_model_match_are_reported(self):
        result = s.process(self.payload("omni quality"), home=self.home)
        context = self.context(result)
        self.assertIn("gpt-5.6-sol / reasoning high", context)
        self.assertIn("matches the profile recommendation: true", context)
        result = s.process(
            self.payload("continue", model="gpt-6-astra"), home=self.home
        )
        self.assertIn(
            "matches the profile recommendation: false", self.context(result)
        )

    def test_auto_explicitly_keeps_current_parent(self):
        result = s.process(
            self.payload("omni auto", model="gpt-6-astra"), home=self.home
        )
        context = self.context(result)
        self.assertIn("Effective policy: auto", context)
        self.assertIn("Auto keeps the current parent model", context)
        self.assertNotIn("Profile-recommended parent:", context)

    def test_session_state_does_not_store_prompt_or_raw_session_id(self):
        secret_prompt = "omni quality"
        raw_session = "thr-sensitive-value"
        s.process(self.payload(secret_prompt, session=raw_session), home=self.home)
        path = s.session_path(self.home, raw_session)
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn(secret_prompt, raw)
        self.assertNotIn(raw_session, raw)
        self.assertEqual(json.loads(raw)["profile"], "quality")

    def test_corrupt_or_wrong_session_state_is_rejected(self):
        path = s.session_path(self.home, "thr-a")
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({
                "schema_version": 1,
                "session_key": "wrong",
                "profile": "balanced",
                "persist_requested": None,
            }),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(s.SessionSwitchError, "session_state_mismatch"):
            s.process(self.payload("continue"), home=self.home)

    def test_disabled_saved_policy_is_reported_by_status(self):
        (self.home / "omnicodex/preferences.json").write_text(
            json.dumps({"enabled": False, "profile": "balanced"}), encoding="utf-8"
        )
        result = s.process(self.payload("omni status"), home=self.home)
        self.assertIn("Saved persistent policy: disabled", self.context(result))

    def test_doctor_is_offline_and_never_claims_model_switch(self):
        report = s.doctor(self.home)
        self.assertEqual(report["saved_profile"], "balanced")
        self.assertEqual(report["network_requests"], 0)
        self.assertFalse(report["model_switch_performed"])
        self.assertEqual(
            report["profiles"]["max"]["model_reasoning_effort"], "high"
        )

    def test_wrong_hook_event_is_rejected(self):
        payload = self.payload("omni balanced")
        payload["hook_event_name"] = "SessionStart"
        with self.assertRaisesRegex(s.SessionSwitchError, "unsupported_hook_event"):
            s.process(payload, home=self.home)

    def test_persist_profile_loads_exact_installed_defaults_tool_and_verifies_result(self):
        tool = self.home / "omnicodex/defaults.py"
        tool.write_text(
            "import json\n"
            "def build_plan(home, **kwargs):\n"
            "    return {'home': home, 'profile': kwargs['profile']}\n"
            "def apply_plan(plan):\n"
            "    p = plan['home'] / 'omnicodex' / 'preferences.json'\n"
            "    data = json.loads(p.read_text())\n"
            "    data['enabled'] = True\n"
            "    data['profile'] = plan['profile']\n"
            "    p.write_text(json.dumps(data))\n"
            "    return {'result': 'configured'}\n",
            encoding="utf-8",
        )
        result = s._persist_profile(self.home, "quality")
        self.assertEqual(result["result"], "configured")
        self.assertEqual(s.saved_profile(self.home), (True, "quality"))

    def test_persist_profile_refuses_installed_defaults_integrity_mismatch(self):
        tool = self.home / "omnicodex/defaults.py"
        tool.write_text("def build_plan(*a, **k): return {}\ndef apply_plan(p): return {}\n", encoding="utf-8")
        preferences = json.loads((self.home / "omnicodex/preferences.json").read_text())
        preferences["tool_sha256"] = "0" * 64
        (self.home / "omnicodex/preferences.json").write_text(
            json.dumps(preferences), encoding="utf-8"
        )
        with self.assertRaisesRegex(s.SessionSwitchError, "defaults_tool_integrity_mismatch"):
            s._persist_profile(self.home, "quality")

    def test_parse_command_surface(self):
        expected = {
            "omni balanced": {"action": "set", "profile": "balanced"},
            "omnicodex profile max": {"action": "set", "profile": "max"},
            "omni save quality": {"action": "save", "profile": "quality"},
            "omni reset": {"action": "reset"},
            "omnicodex status": {"action": "status"},
        }
        for prompt, parsed in expected.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(s.parse_command(prompt), parsed)


if __name__ == "__main__":
    unittest.main()
