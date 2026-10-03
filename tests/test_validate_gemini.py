"""Live acceptance is tested through the serialized Gemini boundary without quota."""
import json
import re
import unittest

from scripts import validate_gemini


class LiveValidationTests(unittest.TestCase):
    def transport(self, requests, *, usage=True, invalid=False):
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

    def test_invalid_configuration_is_rejected_before_any_request(self):
        calls = []
        for profile, timeout in (("invalid", 1), ("balanced", 0), ("balanced", float("nan")),
                                 ("balanced", float("inf"))):
            with self.subTest(profile=profile, timeout=timeout), self.assertRaises(ValueError):
                validate_gemini.run_validation(environment={"GEMINI_API_KEY": "acceptance-key"},
                    transport=self.transport(calls), profile=profile, timeout_seconds=timeout)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
