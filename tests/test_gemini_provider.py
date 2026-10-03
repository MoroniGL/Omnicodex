"""Transport-boundary tests for the direct Gemini evidence provider."""
from __future__ import annotations

import hashlib
import io
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.offload_scope import CapturedEntry, CapturedScope, _fingerprint_entries
from scripts.providers.gemini import (
    GeminiProvider, HttpTransport, ProviderError, TransportResponse, UrllibTransport,
    _DeadlineSocketProxy,
)


SECRET = "never-send-this-api-key"


def scope() -> CapturedScope:
    data = b"line one\nline two\n"
    entry = CapturedEntry("src/example.py", data, hashlib.sha256(data).hexdigest())
    entries = (entry,)
    return CapturedScope(entries, _fingerprint_entries(entries))


def schema() -> dict:
    return {"type": "object", "additionalProperties": False}


def task() -> dict:
    return {"task_kind": "repo_scout", "objective": "Find the example behavior."}


def limits(**overrides) -> dict:
    value = {"timeout_seconds": 5, "max_output_tokens": 400, "target_pack_tokens": 200}
    value.update(overrides)
    return value


def response(pack=None, **overrides) -> bytes:
    value = {
        "modelVersion": "gemini-2.5-flash-lite-001",
        "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(
            pack if pack is not None else {"summary": "safe"}
        )}]}}],
    }
    value.update(overrides)
    return json.dumps(value).encode("utf-8")


class RecordingTransport:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def request(self, url, body, headers, timeout):
        self.calls.append((url, body, headers, timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class FakeHttpResponse:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.status = 200

    def read(self, _size):
        return self.chunks.pop(0) if self.chunks else b""

    def getheaders(self):
        return [("content-type", "application/json")]


class FakeHttpConnection:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.timeout = None
        self.sock = None
        self.closed = False

    def request(self, method, path, body, headers):
        self.calls.append((method, path, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class SlowRawReader(io.RawIOBase):
    def __init__(self, clock):
        self._clock = clock
        self._remaining = bytearray(b"ab")

    def readable(self):
        return True

    def readinto(self, buffer):
        self._clock.advance(0.75)
        if not self._remaining:
            return 0
        buffer[:1] = self._remaining[:1]
        del self._remaining[:1]
        return 1


class AdvancingClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, amount):
        self.value += amount


class SlowSocket:
    def __init__(self, clock):
        self.clock = clock
        self.timeouts = []
        self.closed = False

    def makefile(self, mode, buffering=0):
        self.assert_mode = (mode, buffering)
        return SlowRawReader(self.clock)

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed = True


class BytesSocket:
    def __init__(self, data):
        self.data = data
        self.closed = False
        self.timeouts = []

    def makefile(self, mode, buffering=0):
        self.mode = (mode, buffering)
        return io.BytesIO(self.data)

    def settimeout(self, value):
        self.timeouts.append(value)

    def close(self):
        self.closed = True


class GeminiProviderTests(unittest.TestCase):
    def provider(self, transport, **environment):
        env = {"GEMINI_API_KEY": SECRET}
        env.update(environment)
        return GeminiProvider(environment=env, transport=transport, clock=iter((1.0, 1.125)).__next__)

    def test_serializes_fixed_official_request_with_json_schema_and_no_capabilities(self):
        transport = RecordingTransport(TransportResponse(200, {}, response()))
        result = self.provider(transport).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(result.pack, {"summary": "safe"})
        self.assertEqual(result.telemetry, {
            "requested_provider": "gemini_direct", "requested_model": "gemini-3.5-flash-lite",
            "retry_count": 0, "input_tokens": 11, "output_tokens": 7,
            "served_model": "gemini-2.5-flash-lite-001", "elapsed_ms": 125,
        })
        url, body, headers, timeout = transport.calls[0]
        self.assertEqual(url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent")
        self.assertEqual(headers, {"Content-Type": "application/json", "x-goog-api-key": SECRET})
        self.assertEqual(timeout, 5.0)
        payload = json.loads(body)
        self.assertEqual(payload["generationConfig"], {
            "responseMimeType": "application/json", "responseJsonSchema": schema(), "maxOutputTokens": 400,
        })
        self.assertEqual(set(payload), {"contents", "generationConfig"})
        self.assertNotIn("tools", payload)
        self.assertNotIn("src/example.py", url)
        self.assertIn("src/example.py", payload["contents"][0]["parts"][0]["text"])
        self.assertIn("target_pack_tokens=200", payload["contents"][0]["parts"][0]["text"])

    def test_shipped_schema_is_projected_to_gemini_supported_subset(self):
        canonical = json.loads((ROOT / "schemas" / "evidence-pack.schema.json").read_text(encoding="utf-8"))
        transport = RecordingTransport(TransportResponse(200, {}, response()))
        self.provider(transport).generate_evidence_pack(task(), scope(), canonical, limits())
        projected = json.loads(transport.calls[0][1])["generationConfig"]["responseJsonSchema"]
        self.assertNotIn("$schema", projected)
        self.assertEqual(projected["properties"]["schema_version"], {"type": "integer", "enum": [1]})
        self.assertEqual(projected["properties"]["status"]["type"], "string")
        encoded = json.dumps(projected)
        self.assertNotIn("uniqueItems", encoded)
        self.assertNotIn("minLength", encoded)
        self.assertNotIn("maxLength", encoded)
        self.assertIn("uniqueItems", json.dumps(canonical))

    def test_scope_is_captured_data_not_a_workspace_path(self):
        transport = RecordingTransport(TransportResponse(200, {}, response()))
        with self.assertRaises(ProviderError) as raised:
            self.provider(transport).generate_evidence_pack(task(), Path("C:/workspace"), schema(), limits())
        self.assertEqual(raised.exception.reason_code, "invalid_pack")
        self.assertEqual(transport.calls, [])

    def test_captured_content_cannot_carry_api_key_into_payload(self):
        data = SECRET.encode("utf-8")
        entry = CapturedEntry("src/example.py", data, hashlib.sha256(data).hexdigest())
        captured = CapturedScope((entry,), _fingerprint_entries((entry,)))
        transport = RecordingTransport(TransportResponse(200, {}, response()))
        with self.assertRaisesRegex(ProviderError, "credential_leak"):
            self.provider(transport).generate_evidence_pack(task(), captured, schema(), limits())
        self.assertEqual(transport.calls, [])

    def test_objective_or_schema_cannot_carry_api_key_into_payload(self):
        transport = RecordingTransport(TransportResponse(200, {}, response()))
        with self.assertRaisesRegex(ProviderError, "credential_leak"):
            self.provider(transport).generate_evidence_pack(
                {"task_kind": "repo_scout", "objective": SECRET}, scope(), schema(), limits()
            )
        self.assertEqual(transport.calls, [])
        with self.assertRaisesRegex(ProviderError, "credential_leak"):
            self.provider(transport).generate_evidence_pack(task(), scope(), {"description": SECRET}, limits())
        self.assertEqual(transport.calls, [])

    def test_missing_key_does_not_request_or_leak_configuration(self):
        transport = RecordingTransport(TransportResponse(200, {}, response()))
        provider = GeminiProvider(environment={}, transport=transport)
        self.assertEqual(provider.status(), {"provider": "gemini_direct", "model": "gemini-3.5-flash-lite", "configured": False})
        with self.assertRaises(ProviderError) as raised:
            provider.generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(raised.exception.reason_code, "provider_not_configured")
        self.assertEqual(transport.calls, [])

    def test_response_or_transport_error_echoing_key_never_propagates(self):
        transport = RecordingTransport(TransportResponse(200, {}, SECRET.encode("utf-8")))
        with self.assertRaises(ProviderError) as raised:
            self.provider(transport).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(raised.exception.reason_code, "credential_leak")
        self.assertNotIn(SECRET, str(raised.exception))
        failure = RecordingTransport(TransportResponse(500, {}, SECRET.encode("utf-8")))
        with self.assertRaises(ProviderError) as raised:
            self.provider(failure).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(raised.exception.reason_code, "provider_failed")
        self.assertNotIn(SECRET, str(raised.exception))

    def test_unicode_escaped_response_key_echo_is_rejected_before_telemetry(self):
        escaped = "".join(f"\\u{ord(character):04x}" for character in SECRET)
        raw = (
            '{"modelVersion":"' + escaped + '","candidates":[{"finishReason":"STOP",'
            '"content":{"parts":[{"text":"{}"}]}}]}'
        ).encode("utf-8")
        with self.assertRaisesRegex(ProviderError, "credential_leak"):
            self.provider(RecordingTransport(TransportResponse(200, {}, raw))).generate_evidence_pack(task(), scope(), schema(), limits())

    def test_model_setting_is_used_only_when_safe_and_never_inferred_as_served(self):
        transport = RecordingTransport(TransportResponse(200, {}, response(modelVersion=None)))
        provider = self.provider(transport, OMNICODEX_GEMINI_MODEL="gemini-2.5-flash")
        result = provider.generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(result.telemetry["requested_model"], "gemini-2.5-flash")
        self.assertIsNone(result.telemetry["served_model"])
        unsafe = GeminiProvider(environment={"GEMINI_API_KEY": SECRET, "OMNICODEX_GEMINI_MODEL": "model-" + SECRET}, transport=transport)
        self.assertEqual(unsafe.status(), {"provider": "gemini_direct", "model": None, "configured": False})
        with self.assertRaisesRegex(ProviderError, "credential_leak"):
            unsafe.generate_evidence_pack(task(), scope(), schema(), limits())

    def test_rejects_malformed_blocked_truncated_and_tool_results(self):
        cases = (
            response(candidates=[]),
            response(candidates=[{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}]),
            response(candidates=[{"finishReason": "STOP", "content": {"parts": [{"functionCall": {"name": "x"}}]}}]),
            response(candidates=[], promptFeedback={"blockReason": "SAFETY"}),
            response(candidates=[1]),
            b"not json",
        )
        for raw in cases:
            with self.subTest(raw=raw[:20]), self.assertRaisesRegex(ProviderError, "invalid_pack"):
                self.provider(RecordingTransport(TransportResponse(200, {}, raw))).generate_evidence_pack(task(), scope(), schema(), limits())

    def test_invalid_output_preserves_only_returned_usage_counts_in_error_telemetry(self):
        raw = response(candidates=[])
        with self.assertRaises(ProviderError) as raised:
            self.provider(RecordingTransport(TransportResponse(200, {}, raw))).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(raised.exception.telemetry["input_tokens"], 11)
        self.assertEqual(raised.exception.telemetry["output_tokens"], 7)
        self.assertEqual(raised.exception.telemetry["retry_count"], 0)

    def test_duplicate_json_keys_are_rejected(self):
        duplicate_envelope = b'{"candidates":[],"candidates":[]}'
        duplicate_pack = json.dumps({
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{
                "text": '{"summary":"safe","summary":"unsafe"}'
            }]}}]
        }).encode("utf-8")
        for raw in (duplicate_envelope, duplicate_pack):
            with self.subTest(raw=raw[:30]), self.assertRaisesRegex(ProviderError, "invalid_pack"):
                self.provider(RecordingTransport(TransportResponse(200, {}, raw))).generate_evidence_pack(task(), scope(), schema(), limits())

    def test_bounded_parser_rejects_deep_envelope_pack_and_unused_data(self):
        deep = "[" * 1_500 + "0" + "]" * 1_500
        deep_pack = json.dumps({"candidates": [{"finishReason": "STOP", "content": {"parts": [{
            "text": deep
        }]}}]}).encode("utf-8")
        deep_unused = (
            '{"unused":' + deep + ',"candidates":[{"finishReason":"STOP",'
            '"content":{"parts":[{"text":"{}"}]}}]}'
        ).encode("utf-8")
        for raw in (deep.encode("utf-8"), deep_pack, deep_unused):
            with self.subTest(size=len(raw)), self.assertRaisesRegex(ProviderError, "invalid_pack"):
                self.provider(RecordingTransport(TransportResponse(200, {}, raw))).generate_evidence_pack(task(), scope(), schema(), limits())

    def test_nonfinite_json_number_is_rejected(self):
        raw = b'{"usageMetadata":{"promptTokenCount":Infinity},"candidates":[]}'
        with self.assertRaisesRegex(ProviderError, "invalid_pack"):
            self.provider(RecordingTransport(TransportResponse(200, {}, raw))).generate_evidence_pack(task(), scope(), schema(), limits())

    def test_untrusted_provider_error_is_normalized(self):
        transport = RecordingTransport(ProviderError(SECRET, {
            "served_model": SECRET, "input_tokens": -1, "retry_count": 99,
        }))
        with self.assertRaises(ProviderError) as raised:
            self.provider(transport).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(raised.exception.reason_code, "provider_failed")
        self.assertNotIn(SECRET, str(raised.exception))
        self.assertNotIn("served_model", raised.exception.telemetry)
        self.assertNotIn("input_tokens", raised.exception.telemetry)
        self.assertEqual(raised.exception.telemetry["retry_count"], 0)

    def test_real_transport_serializes_post_headers_and_fixed_path(self):
        connection = FakeHttpConnection(FakeHttpResponse([b"{}", b""]))
        transport = HttpTransport(clock=lambda: 0.0, connection_factory=lambda *args, **kwargs: connection)
        actual = transport.request(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
            b"{}", {"x-goog-api-key": SECRET}, 5,
        )
        self.assertEqual(actual, TransportResponse(200, {"content-type": "application/json"}, b"{}"))
        self.assertEqual(connection.calls, [("POST", "/v1beta/models/gemini-2.5-flash-lite:generateContent",
                                             b"{}", {"x-goog-api-key": SECRET})])
        self.assertTrue(connection.closed)
        with self.assertRaisesRegex(ProviderError, "provider_failed"):
            transport.request("https://generativelanguage.googleapis.com:444/v1beta/models/gemini:generateContent",
                              b"{}", {}, 5)

    def test_real_transport_enforces_total_deadline_across_reads(self):
        moments = iter((0.0, 0.0, 0.0, 0.0, 2.0))
        connection = FakeHttpConnection(FakeHttpResponse([b"{}", b""]))
        transport = UrllibTransport(clock=moments.__next__, connection_factory=lambda *args, **kwargs: connection)
        with self.assertRaisesRegex(ProviderError, "provider_timeout"):
            transport.request("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
                              b"{}", {}, 1)
        self.assertTrue(connection.closed)

    def test_deadline_socket_proxy_times_each_underlying_slow_read(self):
        clock = AdvancingClock()
        socket = SlowSocket(clock)
        proxy = _DeadlineSocketProxy(socket, clock, deadline=1.0)
        with self.assertRaisesRegex(ProviderError, "provider_timeout"):
            proxy.makefile("rb").read()
        self.assertEqual(len(socket.timeouts), 2)
        self.assertGreater(socket.timeouts[0], socket.timeouts[1])

    def test_connection_close_does_not_close_live_http_response_file(self):
        wire = b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 2\r\n\r\n{}"
        socket = BytesSocket(wire)
        proxy = _DeadlineSocketProxy(socket, lambda: 0.0, deadline=1.0)
        response = __import__("http.client").client.HTTPResponse(proxy, method="POST")
        response.begin()
        proxy.close()
        self.assertEqual(response.read(), b"{}")
        proxy.close_files()
        self.assertEqual(proxy._files, [])

    def test_non_success_and_redirect_status_are_rejected_without_following(self):
        for status in (301, 302, 307, 308, 403):
            with self.subTest(status=status), self.assertRaisesRegex(ProviderError, "provider_failed"):
                self.provider(RecordingTransport(TransportResponse(status, {"Location": "https://other.test"}, b"{}"))).generate_evidence_pack(task(), scope(), schema(), limits())

    def test_http_failure_preserves_codes_but_never_messages_or_metadata(self):
        raw = json.dumps({"error": {"status": "INVALID_ARGUMENT", "message": SECRET,
            "details": [{"reason": "API_KEY_INVALID", "metadata": {"key": SECRET}}]}}).encode()
        with self.assertRaises(ProviderError) as raised:
            self.provider(RecordingTransport(TransportResponse(400, {}, raw))).generate_evidence_pack(
                task(), scope(), schema(), limits())
        telemetry = raised.exception.telemetry
        self.assertEqual(telemetry["provider_http_status"], 400)
        self.assertEqual(telemetry["provider_error_status"], "INVALID_ARGUMENT")
        self.assertEqual(telemetry["provider_error_reason"], "API_KEY_INVALID")
        self.assertNotIn(SECRET, json.dumps(telemetry))

    def test_http_diagnostics_ignore_untrusted_values_and_malformed_bodies(self):
        bodies = [b"not json", b"[1]", json.dumps({"error": {"status": SECRET,
            "details": [{"reason": SECRET}]}}).encode(),
            b'{"error":{"status":"INTERNAL","status":"UNAVAILABLE"}}']
        for raw in bodies:
            with self.subTest(raw=raw), self.assertRaises(ProviderError) as raised:
                self.provider(RecordingTransport(TransportResponse(503, {}, raw))).generate_evidence_pack(
                    task(), scope(), schema(), limits())
            self.assertEqual(raised.exception.telemetry["provider_http_status"], 503)
            self.assertNotIn("provider_error_status", raised.exception.telemetry)
            self.assertNotIn("provider_error_reason", raised.exception.telemetry)
            self.assertNotIn(SECRET, json.dumps(raised.exception.telemetry))

    def test_transport_diagnostics_classify_without_exception_text(self):
        import socket
        import ssl
        cases = ((ssl.SSLError(SECRET), "tls_error"),
                 (socket.gaierror(SECRET), "dns_error"),
                 (ConnectionError(SECRET), "connection_error"))
        for error, expected in cases:
            connection = FakeHttpConnection(FakeHttpResponse([]))
            def fail(*args, **kwargs):
                raise error
            connection.request = fail
            transport = HttpTransport(connection_factory=lambda *args, **kwargs: connection)
            with self.subTest(expected=expected), self.assertRaises(ProviderError) as raised:
                self.provider(transport).generate_evidence_pack(task(), scope(), schema(), limits())
            self.assertEqual(raised.exception.telemetry["transport_error"], expected)
            self.assertNotIn(SECRET, json.dumps(raised.exception.telemetry))

    def test_diagnostic_code_matching_key_is_omitted(self):
        key = "INVALID_ARGUMENT"
        raw = json.dumps({"error": {"status": key}}).encode()
        provider = GeminiProvider(environment={"GEMINI_API_KEY": key},
            transport=RecordingTransport(TransportResponse(400, {}, raw)))
        with self.assertRaises(ProviderError) as raised:
            provider.generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertNotIn(key, json.dumps(raised.exception.telemetry))

    def test_untrusted_transport_diagnostic_values_are_omitted(self):
        transport = RecordingTransport(ProviderError("provider_failed", {
            "provider_http_status": True, "provider_error_status": [SECRET],
            "provider_error_reason": {"secret": SECRET}, "transport_error": SECRET}))
        with self.assertRaises(ProviderError) as raised:
            self.provider(transport).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertFalse(any(field in raised.exception.telemetry for field in (
            "provider_http_status", "provider_error_status", "provider_error_reason", "transport_error")))

    def test_response_size_timeout_and_limits_are_bounded(self):
        oversized = b"x" * 32
        with self.assertRaisesRegex(ProviderError, "invalid_pack"):
            self.provider(RecordingTransport(TransportResponse(200, {}, oversized))).generate_evidence_pack(task(), scope(), schema(), limits(max_response_bytes=16))
        timed_out = RecordingTransport(TimeoutError("including " + SECRET))
        with self.assertRaises(ProviderError) as raised:
            self.provider(timed_out).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(raised.exception.reason_code, "provider_timeout")
        with self.assertRaisesRegex(ProviderError, "invalid_pack"):
            self.provider(RecordingTransport(TransportResponse(200, {}, response()))).generate_evidence_pack(task(), scope(), schema(), limits(timeout_seconds=0))

    def test_usage_is_absent_when_not_returned(self):
        raw = response(usageMetadata={})
        result = self.provider(RecordingTransport(TransportResponse(200, {}, raw))).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertNotIn("input_tokens", result.telemetry)
        self.assertNotIn("output_tokens", result.telemetry)
        self.assertEqual(result.telemetry["retry_count"], 0)

    def test_only_nonnegative_integer_usage_metadata_is_telemetry(self):
        raw = response(usageMetadata={"promptTokenCount": "11", "candidatesTokenCount": True,
                                      "thoughtsTokenCount": 3})
        result = self.provider(RecordingTransport(TransportResponse(200, {}, raw))).generate_evidence_pack(task(), scope(), schema(), limits())
        self.assertEqual(result.telemetry["reasoning_output_tokens"], 3)
        self.assertNotIn("input_tokens", result.telemetry)
        self.assertNotIn("output_tokens", result.telemetry)


if __name__ == "__main__":
    unittest.main()
