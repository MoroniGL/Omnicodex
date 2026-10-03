"""Live acceptance is tested through the serialized Gemini boundary without quota."""
import json
import re
import unittest

from scripts import validate_gemini


class LiveValidationTests(unittest.TestCase):
    def transport(self, requests, *, usage=True, invalid=False, part_metadata=None, thought=False):
        def send(url, body, headers, timeout):
            payload = json.loads(body)
            prompt = payload["contents"][0]["parts"][0]["text"]
            requests.append(payload)
            snapshot = re.search(r"snapshot=([a-f0-9]{64})", prompt).group(1)
            pack = {"schema_version": 1, "status": "completed", "task_kind": "long_doc_digest",
                    "snapshot": snapshot, "summary": "Acceptance marker found on line one.",
                    "relevant_files": ["evidence.txt"], "findings": [
                        {"claim": "Acceptance marker found.", "evidence": [
                            {"path": "evidence.txt", "start_line": 1, "end_line": 1,
                             "kind": "doc"}]}], "risks": [], "unknowns": [], "validation": []}
            response = {"candidates": [{"finishReason": "STOP", "content": {
                "parts": [{"text": json.dumps({} if invalid else pack)}]}}]}
            parts = response["candidates"][0]["content"]["parts"]
            parts[0].update(part_metadata or {})
            if thought:
                parts.insert(0, {"text": "Untrusted reasoning never enters the pack.", "thought": True})
            if usage:
                response.update(modelVersion="observed-model", usageMetadata={
                    "promptTokenCount": 46000, "candidatesTokenCount": 200})
            return (200, {}, json.dumps(response).encode())
        return send

    def test_mocked_live_like_serialization_and_parsing_end_to_end(self):
        requests = []
        report, code = validate_gemini.run_validation(
            environment={"GEMINI_API_KEY": "acceptance-key"}, transport=self.transport(requests))
        self.assertEqual(code, 0)
        self.assertTrue(report["connectivity_verified"])
        self.assertEqual(len(requests), 2)
        self.assertEqual(report["acceptance"]["estimated_raw_tokens"], 45000)
        self.assertEqual(report["acceptance"]["captured_raw_bytes"], 180000)
        self.assertTrue(report["acceptance"]["workspace_hash_unchanged"])
        self.assertEqual(report["acceptance"]["input_tokens"], 46000)
        self.assertEqual(report["acceptance"]["output_tokens"], 200)
        self.assertGreater(report["acceptance"]["estimated_premium_context_avoided"], 40000)
        self.assertLess(report["acceptance"]["estimated_evidence_pack_tokens"], 4000)
        self.assertNotIn("acceptance-key", json.dumps(report))

    def test_missing_key_is_nonfatal_for_native_operation_and_makes_no_request(self):
        requests = []
        report, code = validate_gemini.run_validation(environment={}, transport=self.transport(requests))
        self.assertEqual(report["native_status"], "READY")
        self.assertEqual(report["free_context_offload"], "NOT CONFIGURED")
        self.assertFalse(report["connectivity_verified"])
        self.assertEqual(requests, [])
        self.assertEqual(code, 2)  # This explicit live test needs configuration; install does not.

    def test_absent_usage_metadata_stays_unknown(self):
        report, code = validate_gemini.run_validation(
            environment={"GEMINI_API_KEY": "acceptance-key"}, transport=self.transport([], usage=False))
        self.assertEqual(code, 0)
        self.assertIsNone(report["acceptance"]["input_tokens"])
        self.assertIsNone(report["acceptance"]["output_tokens"])
        self.assertIsNone(report["acceptance"]["served_model"])

    def test_network_failure_is_sanitized_and_does_not_start_acceptance(self):
        calls = []

        def fail(*args):
            calls.append(args)
            raise OSError("unsafe acceptance-key exception")

        report, code = validate_gemini.run_validation(
            environment={"GEMINI_API_KEY": "acceptance-key"}, transport=fail)
        self.assertEqual(code, 3)
        self.assertEqual(len(calls), 1)
        self.assertFalse(report["connectivity_verified"])
        self.assertNotIn("acceptance-key", json.dumps(report))
        self.assertFalse(report["quota_fallback"])

    def test_invalid_probe_pack_fails_closed(self):
        calls = []
        report, code = validate_gemini.run_validation(
            environment={"GEMINI_API_KEY": "acceptance-key"},
            transport=self.transport(calls, invalid=True))
        self.assertEqual(code, 3)
        self.assertEqual(len(calls), 1)
        self.assertFalse(report["connectivity_verified"])

    def test_probe_failure_reports_only_safe_provider_diagnostics(self):
        body = json.dumps({"error": {"status": "RESOURCE_EXHAUSTED",
            "message": "unsafe acceptance-key", "details": [{"reason": "QUOTA_EXCEEDED"}]}}).encode()
        report, code = validate_gemini.run_validation(
            environment={"GEMINI_API_KEY": "acceptance-key"}, transport=lambda *args: (429, {}, body))
        self.assertEqual(code, 3)
        self.assertEqual(report["provider_diagnostics"], {
            "provider_http_status": 429, "provider_error_status": "RESOURCE_EXHAUSTED",
            "provider_error_reason": "QUOTA_EXCEEDED"})
        self.assertFalse(report["connectivity_verified"])
        self.assertNotIn("acceptance-key", json.dumps(report))

    def test_each_existing_profile_keeps_its_cost_gate_in_acceptance(self):
        for profile in ("economy", "balanced", "quality", "max", "auto"):
            with self.subTest(profile=profile):
                report, code = validate_gemini.run_validation(
                    environment={"GEMINI_API_KEY": "acceptance-key"},
                    transport=self.transport([]), profile=profile)
                self.assertEqual(code, 0)
                self.assertEqual(report["acceptance"]["profile"], profile)

    def test_request_error_hints_expose_fixed_terms_not_provider_message(self):
        cases = (
            ("Invalid responseJsonSchema enum value: acceptance-key", ["json_schema", "schema_enum"]),
            ("Schema exceeds maximum allowed nesting depth", ["schema_complexity"]),
            ("Unknown name responseFormat", ["response_format", "unsupported_field"]),
            ("API key not valid: acceptance-key", ["api_key"]),
            ("acceptance-key unrelated arbitrary message", []),
        )
        for message, expected in cases:
            body = json.dumps({"error": {"status": "INVALID_ARGUMENT", "message": message}}).encode()
            with self.subTest(message=message):
                report, code = validate_gemini.run_validation(
                    environment={"GEMINI_API_KEY": "acceptance-key"},
                    transport=lambda *args: (400, {}, body))
                self.assertEqual(code, 3)
                self.assertEqual(report["provider_diagnostics"].get("provider_error_hints", []), expected)
                self.assertNotIn("acceptance-key", json.dumps(report))
                self.assertNotIn("message", report["provider_diagnostics"])

    def test_request_hint_matching_key_is_omitted(self):
        body = b'{"error":{"message":"Invalid responseJsonSchema enum"}}'
        report, code = validate_gemini.run_validation(environment={"GEMINI_API_KEY": "schema_enum"},
            transport=lambda *args: (400, {}, body))
        self.assertEqual(code, 3)
        self.assertNotIn("schema_enum", json.dumps(report))

    def test_malformed_and_oversized_messages_produce_no_hints(self):
        for message in (None, True, ["acceptance-key"], {"key": "acceptance-key"}, "enum" * 3000):
            body = json.dumps({"error": {"message": message}}).encode()
            with self.subTest(message_type=type(message).__name__):
                report, code = validate_gemini.run_validation(
                    environment={"GEMINI_API_KEY": "acceptance-key"},
                    transport=lambda *args: (400, {}, body))
                self.assertEqual(code, 3)
                self.assertNotIn("provider_error_hints", report["provider_diagnostics"])
                self.assertNotIn("acceptance-key", json.dumps(report))

    def test_injected_hints_are_allowlisted_and_bounded(self):
        from scripts.providers.base import ProviderError
        for hints, expected in ((["api_key", "acceptance-key", ["secret"], "api_key"], ["api_key"]),
                                (["api_key"] * 11, [])):
            def fail(*args):
                raise ProviderError("provider_failed", {"provider_error_hints": hints})
            with self.subTest(hint_count=len(hints)):
                report, code = validate_gemini.run_validation(
                    environment={"GEMINI_API_KEY": "acceptance-key"}, transport=fail)
                self.assertEqual(code, 3)
                self.assertEqual(report["provider_diagnostics"].get("provider_error_hints", []), expected)
                self.assertNotIn("acceptance-key", json.dumps(report))

    def test_invalid_configuration_is_rejected_before_any_request(self):
        calls = []
        for profile, timeout in (("invalid", 1), ("balanced", 0), ("balanced", float("nan")),
                                 ("balanced", float("inf"))):
            with self.subTest(profile=profile, timeout=timeout), self.assertRaises(ValueError):
                validate_gemini.run_validation(environment={"GEMINI_API_KEY": "acceptance-key"},
                    transport=self.transport(calls), profile=profile, timeout_seconds=timeout)
        self.assertEqual(calls, [])

    def test_request_diagnostics_compare_one_variable_per_case_with_same_scope(self):
        calls = []
        report, code = validate_gemini.run_request_diagnostics(
            environment={"GEMINI_API_KEY": "acceptance-key"}, transport=self.transport(calls))
        self.assertEqual(code, 0)
        self.assertEqual(report["network_requests"], 4)
        self.assertEqual([case["case"] for case in report["cases"]],
            ["full_schema", "minimal_schema", "full_schema_without_array_bounds", "minimal_current_format"])
        self.assertTrue(all(case["http_success"] for case in report["cases"]))
        self.assertFalse(report["acceptance_verified"])
        self.assertTrue(report["workspace_hash_unchanged"])
        self.assertEqual(len({json.dumps(call["contents"]) for call in calls}), 1)
        full = calls[0]["generationConfig"]["responseJsonSchema"]
        minimal = calls[1]["generationConfig"]["responseJsonSchema"]
        relaxed = calls[2]["generationConfig"]["responseJsonSchema"]
        self.assertEqual(set(minimal["properties"]), {"summary"})
        self.assertIn("maxItems", json.dumps(full))
        self.assertNotIn("maxItems", json.dumps(relaxed))
        self.assertNotIn("minItems", json.dumps(relaxed))
        modern = calls[3]["generationConfig"]
        self.assertEqual(modern["responseFormat"], {"text": {"mimeType": "application/json", "schema": minimal}})
        self.assertNotIn("responseJsonSchema", modern)
        self.assertNotIn("responseMimeType", modern)
        self.assertNotIn("acceptance-key", json.dumps(report))

    def test_request_diagnostics_keep_http_success_distinct_from_pack_validation(self):
        calls = []
        def send(url, body, headers, timeout):
            calls.append(json.loads(body))
            return (200, {}, b'{"candidates":[]}')
        report, code = validate_gemini.run_request_diagnostics(
            environment={"GEMINI_API_KEY": "acceptance-key"}, transport=send)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 4)
        self.assertTrue(all(case["http_success"] for case in report["cases"]))
        self.assertTrue(all(case["reason_code"] == "invalid_pack" for case in report["cases"]))
        self.assertFalse(report["acceptance_verified"])

    def test_request_diagnostics_report_each_rejection_without_messages(self):
        body = b'{"error":{"status":"INVALID_ARGUMENT","message":"unsafe acceptance-key"}}'
        report, code = validate_gemini.run_request_diagnostics(
            environment={"GEMINI_API_KEY": "acceptance-key"}, transport=lambda *args: (400, {}, body))
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "diagnostic_complete")
        self.assertTrue(all(not case["http_success"] for case in report["cases"]))
        self.assertTrue(all(case["provider_http_status"] == 400 for case in report["cases"]))
        self.assertNotIn("acceptance-key", json.dumps(report))

    def test_request_diagnostics_require_configuration_and_valid_timeout(self):
        calls = []
        report, code = validate_gemini.run_request_diagnostics(environment={}, transport=self.transport(calls))
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "not_configured")
        for timeout in (0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                validate_gemini.run_request_diagnostics(environment={}, timeout_seconds=timeout)
        self.assertEqual(calls, [])

    def test_request_diagnostics_stop_on_auth_quota_or_transport_failures(self):
        for status in (401, 403, 429, None):
            calls = []
            def send(*args):
                calls.append(args)
                if status is None:
                    raise OSError("unsafe acceptance-key")
                return (status, {}, b"{}")
            with self.subTest(status=status):
                report, code = validate_gemini.run_request_diagnostics(
                    environment={"GEMINI_API_KEY": "acceptance-key"}, transport=send)
                self.assertEqual(code, 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(report["network_requests"], 1)
                self.assertNotIn("acceptance-key", json.dumps(report))

    def test_diagnostic_cli_dispatch_is_explicit(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        with patch.object(validate_gemini, "run_request_diagnostics", return_value=({}, 0)) as diagnostic, \
                patch.object(validate_gemini, "run_validation", return_value=({}, 0)) as acceptance, \
                redirect_stdout(StringIO()):
            self.assertEqual(validate_gemini.main(["--diagnose-request", "--timeout", "30"]), 0)
            diagnostic.assert_called_once_with(timeout_seconds=30.0)
            acceptance.assert_not_called()

    def test_signed_text_and_separate_thought_part_do_not_enter_handoff(self):
        for thought in (False, True):
            with self.subTest(thought=thought):
                report, code = validate_gemini.run_validation(
                    environment={"GEMINI_API_KEY": "acceptance-key"},
                    transport=self.transport([], part_metadata={"thoughtSignature": "opaque-signature", "thought": False},
                                             thought=thought))
                self.assertEqual(code, 0)
                self.assertEqual(report["status"], "accepted")
                self.assertNotIn("opaque-signature", json.dumps(report))
                self.assertNotIn("Untrusted reasoning", json.dumps(report))

    def test_text_metadata_never_permits_tool_parts_or_malformed_flags(self):
        for metadata in ({"functionCall": {"name": "unsafe"}}, {"thought": "false"},
                         {"thoughtSignature": 12}, {"unknown": True}):
            with self.subTest(metadata=metadata):
                report, code = validate_gemini.run_validation(
                    environment={"GEMINI_API_KEY": "acceptance-key"},
                    transport=self.transport([], part_metadata=metadata))
                self.assertEqual(code, 3)
                self.assertEqual(report["provider_diagnostics"]["provider_output_issue"], "invalid_content_parts")

    def test_signature_echoing_key_fails_before_output_diagnostics(self):
        report, code = validate_gemini.run_validation(environment={"GEMINI_API_KEY": "acceptance-key"},
            transport=self.transport([], part_metadata={"thoughtSignature": "acceptance-key"}))
        self.assertEqual(code, 3)
        self.assertEqual(report["reason_code"], "credential_leak")
        self.assertNotIn("acceptance-key", json.dumps(report))

    def test_output_diagnostics_report_stop_reason_without_content(self):
        body = b'{"candidates":[{"finishReason":"MAX_TOKENS","content":{"parts":[{"text":"truncated private"}]}}]}'
        report, code = validate_gemini.run_validation(environment={"GEMINI_API_KEY": "acceptance-key"},
            transport=lambda *args: (200, {}, body))
        self.assertEqual(code, 3)
        self.assertEqual(report["provider_diagnostics"]["provider_finish_reason"], "MAX_TOKENS")
        self.assertEqual(report["provider_diagnostics"]["provider_output_issue"], "non_stop_finish")
        self.assertNotIn("truncated private", json.dumps(report))

    def test_api_projection_does_not_relax_local_array_limit(self):
        underlying = self.transport([])
        def oversized(*args):
            status, headers, body = underlying(*args)
            payload = json.loads(body)
            part = payload["candidates"][0]["content"]["parts"][0]
            pack = json.loads(part["text"])
            pack["risks"] = ["Synthetic risk."] * 33
            part["text"] = json.dumps(pack)
            return status, headers, json.dumps(payload).encode()
        report, code = validate_gemini.run_validation(environment={"GEMINI_API_KEY": "acceptance-key"}, transport=oversized)
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["connectivity_verified"])


if __name__ == "__main__":
    unittest.main()
