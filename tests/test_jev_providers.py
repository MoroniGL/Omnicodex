"""Offline contract/transport/shadow tests. All HTTP is mocked; no keys required."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
import urllib.error
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from scripts import jev, jev_shadow


GATEWAY_RESPONSE = {
    "model": "typesafe-ai/jev",
    "answers": {"needs_review": {"type": "boolean", "probability": 0.95}},
    "usage": {"inputTokens": 296, "outputTokens": 21},
    "providerMetadata": {"gateway": {"cost": "0.000012432"}},
}


def response_for(payload, provider="vercel"):
    answers = {}
    for name, q in payload["questions"].items():
        if q["type"] == "choice":
            first = next(iter(q["criteria"]))
            answers[name] = {"type": "choice", "choice": first, "confidence": 0.9,
                             "probabilities": {key: float(key == first) for key in q["criteria"]}}
        else:
            answers[name] = {"type": q["type"], "probability" if provider == "vercel" else "noul": 0.95}
    usage = {"inputTokens": 100, "outputTokens": 10} if provider == "vercel" else {"input_tokens": 100, "output_tokens": 10}
    return {"model": payload["model"], "answers": answers, "usage": usage,
            "providerMetadata": {"gateway": {"cost": "0.00001"}}}


def synthetic_evaluate(kind, state, *, provider, model):
    payload = jev.build_payload(kind, model, state, provider)
    return {"provider": provider, "elapsed_ms": 10, "action_executed": False,
            **jev.normalize_response(response_for(payload, provider), payload, provider)}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.payload = jev.build_payload("review-gate", "typesafe-ai/jev", "Synthetic auth change", "vercel")

    def test_provider_specific_question_types(self):
        for kind in jev.ACTIONS:
            for provider, model in (("typesafe", "account-model"), ("vercel", "typesafe-ai/jev")):
                p = jev.build_payload(kind, model, "Synthetic", provider)
                with self.subTest(kind=kind, provider=provider):
                    self.assertTrue(all(q["type"] in ("choice", "boolean" if provider == "vercel" else "noul") for q in p["questions"].values()))
                    jev.normalize_response(response_for(p, provider), p, provider)

    def test_recorded_gateway_response_shape(self):
        r = jev.normalize_response(GATEWAY_RESPONSE, self.payload, "vercel")
        self.assertEqual(r["answers"]["needs_review"]["probability"], 0.95)
        self.assertEqual(r["usage"], {"input_tokens": 296, "output_tokens": 21})
        self.assertEqual(Decimal(r["gateway_cost_usd"]), Decimal("0.000012432"))

    def test_direct_noul_and_alias_are_distinct_from_vercel(self):
        p = jev.build_payload("review-gate", "account-alias", "Synthetic")
        d = response_for(p, "typesafe")
        d["model"] = "account-resolved-model"
        r = jev.normalize_response(d, p, "typesafe")
        self.assertFalse(r["model_matches_request"])
        self.assertEqual(r["answers"]["needs_review"]["type"], "boolean")
        self.assertIsNone(r["gateway_cost_usd"])

    def test_credentials_never_cross_providers(self):
        os.environ.update({"JEV_API_KEY": "legacy-direct", "AI_GATEWAY_API_KEY": "gateway-only"})
        self.assertEqual(jev._api_key("vercel"), "gateway-only")
        self.assertEqual(jev._api_key("typesafe"), "legacy-direct")
        del os.environ["AI_GATEWAY_API_KEY"]
        with self.assertRaises(jev.JevError):
            jev._api_key("vercel")

    def test_conflicting_direct_credentials_rejected(self):
        os.environ.update({"JEV_API_KEY": "legacy", "TYPESAFE_API_KEY": "canonical"})
        with self.assertRaises(jev.JevError):
            jev._api_key()
        os.environ["JEV_API_KEY"] = "canonical"
        self.assertEqual(jev._api_key(), "canonical")

    def test_mislabelled_gateway_key_rejected_for_direct(self):
        os.environ.update({"JEV_API_KEY": "same-key", "AI_GATEWAY_API_KEY": "same-key"})
        with self.assertRaises(jev.JevError):
            jev._api_key("typesafe")
        self.assertEqual(jev._api_key("vercel"), "same-key")

    def test_key_header_injection_rejected(self):
        os.environ["AI_GATEWAY_API_KEY"] = "key\r\nBad: header"
        with self.assertRaises(jev.JevError):
            jev._api_key("vercel")

    def test_no_network_without_both_opt_in_and_key(self):
        for env in ({}, {"OMNI_JEV": "1"}, {"AI_GATEWAY_API_KEY": "key"}):
            with self.subTest(env=list(env)), patch.dict(os.environ, env, clear=True), patch.object(jev.urllib.request, "build_opener") as op:
                with self.assertRaises(jev.JevError):
                    jev._request("POST", "/v1/evaluate", payload=self.payload, provider="vercel")
                op.assert_not_called()

    def test_doctor_and_model_dry_run_never_network(self):
        os.environ.update({"OMNI_JEV": "1", "JEV_API_KEY": "SECRET_SENTINEL", "AI_GATEWAY_API_KEY": "GATEWAY_SENTINEL"})
        for args in (["doctor"], ["doctor", "--provider", "vercel"], ["models", "--dry-run"], ["models", "--provider", "vercel"]):
            out = io.StringIO()
            with self.subTest(args=args), patch.object(jev.urllib.request, "build_opener") as op, contextlib.redirect_stdout(out):
                self.assertEqual(jev.main(args), 0)
            op.assert_not_called()
            self.assertNotIn("SECRET_SENTINEL", out.getvalue())
            self.assertNotIn("GATEWAY_SENTINEL", out.getvalue())

    def test_vercel_requires_explicit_selection(self):
        os.environ["AI_GATEWAY_API_KEY"] = "gateway-key"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(jev.main(["doctor"]), 0)
        self.assertEqual(json.loads(out.getvalue())["provider"], "typesafe")

    def test_vercel_post_url_and_authorization(self):
        os.environ.update({"OMNI_JEV": "1", "AI_GATEWAY_API_KEY": "TEST_GATEWAY", "JEV_API_KEY": "TEST_DIRECT"})
        with patch.object(jev.urllib.request, "build_opener") as factory:
            factory.return_value.open.return_value = io.BytesIO(json.dumps(GATEWAY_RESPONSE).encode())
            r = jev.evaluate("review-gate", "Synthetic", provider="vercel", model="typesafe-ai/jev")
            call = factory.return_value.open.call_args
            req = call.args[0]
            self.assertEqual(req.full_url, "https://ai-gateway.vercel.sh/v1/evaluate")
            self.assertEqual(req.get_header("Authorization"), "Bearer TEST_GATEWAY")
            self.assertEqual(json.loads(req.data)["questions"]["needs_review"]["type"], "boolean")
            self.assertEqual(call.kwargs["timeout"], 30)
            self.assertFalse(r["action_executed"])
            self.assertEqual(len(r["state_sha256"]), 64)
            self.assertNotIn("TEST_GATEWAY", json.dumps(r))
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_typesafe_post_url(self):
        os.environ.update({"OMNI_JEV": "1", "TYPESAFE_API_KEY": "direct-key"})
        p = jev.build_payload("review-gate", "my-model", "Synthetic")
        with patch.object(jev.urllib.request, "build_opener") as f:
            f.return_value.open.return_value = io.BytesIO(json.dumps(response_for(p, "typesafe")).encode())
            jev.evaluate("review-gate", "Synthetic", provider="typesafe", model="my-model")
            self.assertEqual(f.return_value.open.call_args.args[0].full_url, "https://api.typesafe.ai/v1/systemone")

    def test_unapproved_endpoint_rejected(self):
        os.environ.update({"OMNI_JEV": "1", "AI_GATEWAY_API_KEY": "key"})
        with patch.object(jev.urllib.request, "build_opener") as f:
            with self.assertRaises(jev.JevError):
                jev._request("POST", "https://example.invalid", provider="vercel")
            f.assert_not_called()

    def test_redirect_refused_without_contacting_target(self):
        with self.assertRaises(jev.JevError):
            jev._NoRedirect().redirect_request(None, None, 302, "SECRET", {}, "https://other.invalid/?secret")

    def test_http_failures_no_retry_no_secret_body(self):
        os.environ.update({"OMNI_JEV": "1", "AI_GATEWAY_API_KEY": "key"})
        for code in (401, 403, 429, 500):
            with self.subTest(code=code), patch.object(jev.urllib.request, "build_opener") as f:
                f.return_value.open.side_effect = urllib.error.HTTPError("https://host/?SECRET", code, "SECRET", {}, io.BytesIO(b"SECRET"))
                with self.assertRaises(jev.JevError) as caught:
                    jev._request("POST", "/v1/evaluate", payload=self.payload, provider="vercel")
                self.assertEqual(f.return_value.open.call_count, 1)
                self.assertNotIn("SECRET", json.dumps(jev.error_record(caught.exception)))
                self.assertEqual(caught.exception.http_status, code)

    def test_timeout_no_retry(self):
        os.environ.update({"OMNI_JEV": "1", "AI_GATEWAY_API_KEY": "key"})
        with patch.object(jev.urllib.request, "build_opener") as f:
            f.return_value.open.side_effect = TimeoutError("private details")
            with self.assertRaises(jev.JevError):
                jev._request("POST", "/v1/evaluate", payload=self.payload, provider="vercel")
            self.assertEqual(f.return_value.open.call_count, 1)

    def test_bounded_and_strict_response_json(self):
        os.environ.update({"OMNI_JEV": "1", "AI_GATEWAY_API_KEY": "key"})
        for raw in (b"x" * (jev.MAX_RESPONSE_BYTES + 1), b'{"x":1,"x":2}', b'{"x":NaN}', b"[]", b"SECRET malformed"):
            with self.subTest(size=len(raw)), patch.object(jev.urllib.request, "build_opener") as f:
                f.return_value.open.return_value = io.BytesIO(raw)
                with self.assertRaises(jev.JevError):
                    jev._request("POST", "/v1/evaluate", payload=self.payload, provider="vercel")

    def test_missing_extra_or_wrong_type_answer_rejected(self):
        for answers in ({}, {**GATEWAY_RESPONSE["answers"], "extra": {}}, {"needs_review": {"type": "noul", "noul": 0.9}}):
            d = copy.deepcopy(GATEWAY_RESPONSE)
            d["answers"] = answers
            with self.assertRaises(jev.JevError):
                jev.normalize_response(d, self.payload, "vercel")

    def test_invalid_probabilities_rejected(self):
        for p in (None, True, "0.95", -1, 1.01, float("nan"), float("inf")):
            d = copy.deepcopy(GATEWAY_RESPONSE)
            d["answers"]["needs_review"]["probability"] = p
            with self.subTest(p=p), self.assertRaises(jev.JevError):
                jev.normalize_response(d, self.payload, "vercel")

    def test_invalid_usage_rejected(self):
        for value in (None, True, -1, 1.5, "296"):
            d = copy.deepcopy(GATEWAY_RESPONSE)
            d["usage"]["inputTokens"] = value
            with self.assertRaises(jev.JevError):
                jev.normalize_response(d, self.payload, "vercel")

    def test_cost_unknown_is_not_zero_and_invalid_is_rejected(self):
        d = copy.deepcopy(GATEWAY_RESPONSE)
        del d["providerMetadata"]
        self.assertIsNone(jev.normalize_response(d, self.payload, "vercel")["gateway_cost_usd"])
        for value in ("NaN", "Infinity", "-1", True, {}, "private text"):
            d = copy.deepcopy(GATEWAY_RESPONSE)
            d["providerMetadata"]["gateway"]["cost"] = value
            with self.assertRaises(jev.JevError):
                jev.normalize_response(d, self.payload, "vercel")

    def test_model_mismatch_and_invalid_model_rejected(self):
        for model in (None, "other/model", "bad\nmodel"):
            d = copy.deepcopy(GATEWAY_RESPONSE)
            d["model"] = model
            with self.assertRaises(jev.JevError):
                jev.normalize_response(d, self.payload, "vercel")

    def test_choice_shape_and_mass_are_validated(self):
        p = jev.build_payload("retry-strategy", "typesafe-ai/jev", "Synthetic", "vercel")
        for mutate in (lambda a: a.update(choice="invented"),
                       lambda a: a.update(probabilities={"retry_once": 1}),
                       lambda a: a["probabilities"].update(stop=0.5),
                       lambda a: a.update(choice="stop")):
            d = response_for(p)
            mutate(d["answers"]["retry"])
            with self.assertRaises(jev.JevError):
                jev.normalize_response(d, p, "vercel")

    def test_vercel_choice_confidence_is_optional_not_invented(self):
        p = jev.build_payload("retry-strategy", "typesafe-ai/jev", "Synthetic", "vercel")
        d = response_for(p)
        del d["answers"]["retry"]["confidence"]
        self.assertIsNone(jev.normalize_response(d, p, "vercel")["answers"]["retry"]["confidence"])
        direct = jev.build_payload("retry-strategy", "account-model", "Synthetic")
        d = response_for(direct, "typesafe")
        del d["answers"]["retry"]["confidence"]
        with self.assertRaises(jev.JevError):
            jev.normalize_response(d, direct, "typesafe")

    def test_known_credentials_cannot_be_sent_in_state(self):
        os.environ["AI_GATEWAY_API_KEY"] = "KNOWN_SECRET_SENTINEL"
        with self.assertRaises(jev.JevError):
            jev.build_payload("review-gate", "typesafe-ai/jev", {"data": "KNOWN_SECRET_SENTINEL"}, "vercel")

    def test_state_types_size_and_windows_bom(self):
        for state in (False, 1, None, {"p": float("nan")}, "x" * (jev.MAX_STATE_BYTES + 1)):
            with self.assertRaises(jev.JevError):
                jev.build_payload("review-gate", "typesafe-ai/jev", state, "vercel")
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "state.json"
            f.write_bytes(b'\xef\xbb\xbf{"task":"synthetic"}')
            self.assertEqual(jev._read_state(f), {"task": "synthetic"})

    def test_cli_invalid_input_error_does_not_echo_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "state.json"
            f.write_bytes(b'\xffPRIVATE_SENTINEL')
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                self.assertEqual(jev.main(["review-gate", "--provider", "vercel", "--state-file", str(f)]), 2)
            self.assertNotIn("PRIVATE_SENTINEL", error.getvalue())
            self.assertNotIn(str(f), error.getvalue())


class ShadowTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"OMNI_JEV": "1", "AI_GATEWAY_API_KEY": "TEST_KEY"}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def run_case(self, **kw):
        options = {"live": True, "limit": 6, "provider": "vercel", "model": "typesafe-ai/jev",
                   "output": None, "max_observed_cost": Decimal("0.01")}
        options.update(kw)
        return jev_shadow.run(**options)

    def test_preview_is_offline_even_with_keys(self):
        with patch.object(jev, "evaluate") as call:
            r = self.run_case(live=False)
        call.assert_not_called()
        self.assertEqual(r["planned_requests"], 6)
        self.assertFalse(r["network_checked"])
        self.assertTrue(all("expected" not in row["payload"]["state"] for row in r["cases"]))

    def test_six_requests_sequential_and_exact_cost_accounting(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(jev, "evaluate", side_effect=synthetic_evaluate) as call:
            out = Path(tmp) / "new-run"
            r = self.run_case(output=out)
            self.assertEqual(call.call_count, 6)
            self.assertEqual(r["valid_responses"], 6)
            self.assertEqual(Decimal(r["total_observed_cost_usd"]), Decimal("0.00006"))
            self.assertFalse(r["action_executed"])
            receipts = (out / "receipts.jsonl").read_text()
            self.assertEqual(len(receipts.splitlines()), 6)
            self.assertNotIn("TEST_KEY", receipts)
            self.assertNotIn('"state":', receipts)
            self.assertTrue((out / "REPORT.json").exists())

    def test_first_error_stops_and_cost_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(jev, "evaluate", side_effect=jev.JevError("http_error", 401)) as call:
            r = self.run_case(output=Path(tmp) / "new")
            self.assertEqual(call.call_count, 1)
            self.assertEqual(r["stop_reason"], "error_no_retry")
            self.assertIsNone(r["total_observed_cost_usd"])

    def test_observed_cost_stop_does_not_start_another_call(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(jev, "evaluate", side_effect=synthetic_evaluate) as call:
            r = self.run_case(output=Path(tmp) / "new", max_observed_cost=Decimal("0.000005"))
            self.assertEqual(call.call_count, 1)
            self.assertEqual(r["stop_reason"], "observed_cost_limit_stop")

    def test_missing_cost_stops_not_counted_as_free(self):
        def missing(*args, **kw):
            value = synthetic_evaluate(*args, **kw)
            value["gateway_cost_usd"] = None
            return value
        with tempfile.TemporaryDirectory() as tmp, patch.object(jev, "evaluate", side_effect=missing) as call:
            r = self.run_case(output=Path(tmp) / "new")
            self.assertEqual(call.call_count, 1)
            self.assertEqual(r["stop_reason"], "missing_cost_stop")
            self.assertFalse(r["cost_accounting_complete"])

    def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(jev, "evaluate") as call:
            with self.assertRaises(FileExistsError):
                self.run_case(output=Path(tmp))
            call.assert_not_called()

    def test_invalid_limits_make_no_calls(self):
        for limit in (0, 7):
            with patch.object(jev, "evaluate") as call, self.assertRaises(jev.JevError):
                self.run_case(limit=limit)
            call.assert_not_called()

    def test_no_key_no_output_or_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True), patch.object(jev, "evaluate") as call:
            out = Path(tmp) / "new"
            with self.assertRaises(jev.JevError):
                self.run_case(output=out)
            self.assertFalse(out.exists())
            call.assert_not_called()

    def test_exploratory_bands_include_uncertainty(self):
        self.assertEqual(jev_shadow.assessment({"complete": {"probability": 0.5}}, {"complete": True}), {"complete": "uncertain"})
        self.assertEqual(jev_shadow.assessment({"complete": {"probability": 0.95}}, {"complete": False}), {"complete": "disagrees"})


if __name__ == "__main__":
    unittest.main()
