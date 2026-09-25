"""Offline tests for the optional TypeSafe Jev helper."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("jev_helper", ROOT / "scripts" / "jev.py")
jev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jev)


class JevTests(unittest.TestCase):
    def test_route_payload_is_typed_and_bounded(self) -> None:
        payload = jev.build_payload("route-task", "account-visible-model", {"task": "inspect"})
        self.assertEqual(payload["model"], "account-visible-model")
        self.assertEqual(payload["questions"]["route"]["type"], "choice")
        self.assertEqual(payload["questions"]["needs_review"]["type"], "noul")

    def test_missing_model_is_rejected(self) -> None:
        with self.assertRaises(jev.JevError):
            jev.build_payload("route-task", "", "task")

    def test_doctor_is_offline_and_does_not_print_key(self) -> None:
        output = io.StringIO()
        with patch.dict(os.environ, {"OMNI_JEV": "1", "JEV_API_KEY": "SECRET_SENTINEL"}, clear=True),                 patch.object(jev.urllib.request, "urlopen") as urlopen,                 contextlib.redirect_stdout(output):
            self.assertEqual(jev.main(["doctor"]), 0)
        urlopen.assert_not_called()
        self.assertNotIn("SECRET_SENTINEL", output.getvalue())
        report = json.loads(output.getvalue())
        self.assertTrue(report["api_key_present"])
        self.assertFalse(report["network_checked"])

    def test_network_call_requires_explicit_opt_in(self) -> None:
        with patch.dict(os.environ, {"JEV_API_KEY": "x"}, clear=True),                 self.assertRaises(jev.JevError):
            jev._request("GET", "/v1/models")

    def test_dry_run_needs_no_key_or_network(self) -> None:
        output = io.StringIO()
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as stream:
            stream.write('{"task":"small"}')
            name = stream.name
        try:
            with patch.dict(os.environ, {}, clear=True),                     patch.object(jev.urllib.request, "urlopen") as urlopen,                     contextlib.redirect_stdout(output):
                self.assertEqual(jev.main([
                    "route-task", "--model", "example-model",
                    "--state-file", name, "--dry-run"
                ]), 0)
            urlopen.assert_not_called()
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["state"], {"task": "small"})
        finally:
            Path(name).unlink(missing_ok=True)

    def test_state_file_is_size_bounded(self) -> None:
        with tempfile.NamedTemporaryFile("wb", delete=False) as stream:
            stream.write(b"x" * (jev.MAX_STATE_BYTES + 1))
            name = stream.name
        try:
            with self.assertRaises(jev.JevError):
                jev._read_state(Path(name))
        finally:
            Path(name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
