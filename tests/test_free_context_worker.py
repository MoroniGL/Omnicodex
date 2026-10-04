"""Retained regressions for the experimental legacy Codex adapter."""
import hashlib
import io
import importlib.util
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "offload_scope", ROOT / "scripts" / "offload_scope.py"
)
offload_scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offload_scope)


def _load_optional_module(name):
    path = ROOT / "scripts" / f"{name}.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


codex_exec_adapter = _load_optional_module("codex_exec_adapter")
offload_telemetry = _load_optional_module("offload_telemetry")
free_context_worker = _load_optional_module("free_context_worker")


class CodexExecAdapterTests(unittest.TestCase):
    """Contract tests for the isolated worker boundary.

    Removing a required argv boundary, accepting a shell command, or exposing
    raw process output must make one of these tests fail.
    """

    def adapter(self):
        self.assertIsNotNone(codex_exec_adapter, "codex exec adapter is missing")
        return codex_exec_adapter

    def telemetry(self):
        self.assertIsNotNone(offload_telemetry, "offload telemetry parser is missing")
        return offload_telemetry

    def build_argv(self, endpoint=None):
        return self.adapter().build_codex_exec_argv(
            ("codex with spaces",), Path("C:/stage dir"), Path("C:/schema dir/pack schema.json"),
            Path("C:/output dir/last message.json"), endpoint=endpoint,
        )

    def test_build_argv_has_exact_isolation_provider_and_secret_boundaries(self):
        argv = self.build_argv()
        self.assertEqual(argv[:4], ["codex with spaces", "-a", "never", "exec"])
        self.assertEqual(argv[-1], "-")
        self.assertNotIn("--sandbox", argv)
        self.assertIn("--ephemeral", argv)
        self.assertIn("--json", argv)
        self.assertIn("--ignore-user-config", argv)
        self.assertIn("--strict-config", argv)
        self.assertIn("--skip-git-repo-check", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "auto")
        self.assertEqual(argv[argv.index("--cd") + 1], str(Path("C:/stage dir")))
        self.assertEqual(argv[argv.index("--output-schema") + 1],
                         str(Path("C:/schema dir/pack schema.json")))
        self.assertEqual(argv[argv.index("--output-last-message") + 1],
                         str(Path("C:/output dir/last message.json")))
        settings = [argv[index + 1] for index, value in enumerate(argv) if value == "-c"]
        stage = str(Path("C:/stage dir").resolve()).replace("\\", "\\\\")
        self.assertEqual(settings, [
            'model_provider="freellmapi"',
            'model_providers.freellmapi.name="FreeLLMAPI"',
            'model_providers.freellmapi.base_url="http://127.0.0.1:3001/v1"',
            'model_providers.freellmapi.wire_api="responses"',
            'model_providers.freellmapi.env_key="FREELLMAPI_API_KEY"',
            'model_providers.freellmapi.requires_openai_auth=false',
            'web_search="disabled"',
            'default_permissions="omnicodex_worker"',
            'permissions.omnicodex_worker.description="Stage-only read access"',
            'permissions.omnicodex_worker.filesystem.":root"="deny"',
            'permissions.omnicodex_worker.filesystem.":minimal"="read"',
            f'permissions.omnicodex_worker.filesystem."{stage}"="read"',
            'permissions.omnicodex_worker.network.enabled=false',
            'features.apps=false',
            'features.remote_plugin=false',
            'features.multi_agent=false',
            'shell_environment_policy.ignore_default_excludes=false',
            'shell_environment_policy.exclude=["FREELLMAPI_API_KEY"]',
        ])
        self.assertNotIn("secret-value", " ".join(argv))

    def test_build_argv_validates_custom_endpoint_and_formats_for_windows_and_posix(self):
        argv = self.build_argv("https://gateway.example/v1")
        self.assertIn('model_providers.freellmapi.base_url="https://gateway.example/v1"', argv)
        self.assertIn('"codex with spaces"', self.adapter().format_command(argv, platform="windows"))
        self.assertIn("'codex with spaces'", self.adapter().format_command(argv, platform="posix"))
        self.assertEqual(self.adapter().format_command(argv, platform="windows"), subprocess.list2cmdline(argv))
        self.assertEqual(self.adapter().format_command(argv, platform="posix"), shlex.join(argv))
        for endpoint in ("file:///not-a-provider", ""):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                self.build_argv(endpoint)

    def fake_prefix(self, directory):
        fake = Path(directory) / "fake_codex.py"
        fake.write_text(
            "import json, os, pathlib, subprocess, sys, time\n"
            "args = sys.argv[1:]\n"
            "mode = os.environ.get('FAKE_CODEX_MODE', 'success')\n"
            "if mode == 'no_read': time.sleep(5); sys.exit(0)\n"
            "prompt = sys.stdin.read()\n"
            "if mode == 'descendant': subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'], stdout=sys.stdout, stderr=sys.stderr); sys.exit(0)\n"
            "if mode == 'timeout': time.sleep(5)\n"
            "if mode == 'malformed': print('{not json}')\n"
            "elif mode == 'leak_stdout': print(os.environ['FREELLMAPI_API_KEY'])\n"
            "elif mode == 'leak_stderr': print(os.environ['FREELLMAPI_API_KEY'], file=sys.stderr)\n"
            "elif mode == 'leak_split':\n"
            "    secret = os.environ['FREELLMAPI_API_KEY'].encode()\n"
            "    sys.stdout.buffer.write(secret[:len(secret) // 2]); sys.stdout.buffer.flush(); time.sleep(0.02)\n"
            "    sys.stdout.buffer.write(secret[len(secret) // 2:] + b'\\n')\n"
            "else: print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 12, 'cached_input_tokens': 3, 'output_tokens': 4, 'reasoning_output_tokens': 2}, 'model': 'served-model', 'provider': 'served-provider', 'retry_count': 1, 'fallback_count': 0}))\n"
            "if mode == 'nonzero': sys.exit(7)\n"
            "if mode != 'missing': pathlib.Path(args[args.index('--output-last-message') + 1]).write_text(json.dumps({'status': 'completed', 'summary': os.environ['FREELLMAPI_API_KEY'] if mode == 'leak_final' else 'ok', 'prompt_has_staged_content': 'staged-secret-content' in prompt}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        return (sys.executable, str(fake))

    def execute_fake(self, mode, *, prompt="Read the staged workspace and return the schema result.",
                     timeout_seconds=1.0, max_final_message_bytes=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "stage"
            staged.mkdir()
            (staged / "only-approved.txt").write_text("staged-secret-content", encoding="utf-8")
            output = root / "result.json"
            argv = self.adapter().build_codex_exec_argv(
                self.fake_prefix(directory), staged, ROOT / "schemas" / "evidence-pack.schema.json", output
            )
            env = dict(os.environ, FAKE_CODEX_MODE=mode, FREELLMAPI_API_KEY="secret-value")
            options = {} if max_final_message_bytes is None else {
                "max_final_message_bytes": max_final_message_bytes
            }
            return self.adapter().execute_codex_exec(
                argv, prompt, timeout_seconds=timeout_seconds, environment=env, **options
            )

    def test_execute_real_subprocess_returns_sanitized_success_without_prompt_file_contents(self):
        result = self.execute_fake("success")
        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["final_message"]["prompt_has_staged_content"])
        self.assertNotIn("stdout", result)
        self.assertNotIn("stderr", result)
        self.assertNotIn("secret-value", json.dumps(result))

    def test_execute_real_subprocess_reports_timeout_nonzero_malformed_and_missing_output(self):
        expectations = {
            "timeout": ("timeout", None),
            "nonzero": ("nonzero_exit", 7),
            "malformed": ("malformed_output", 0),
            "missing": ("missing_output", 0),
        }
        for mode, expected in expectations.items():
            with self.subTest(mode=mode):
                result = self.execute_fake(mode, timeout_seconds=0.2 if mode == "timeout" else 1.0)
                self.assertEqual((result["outcome"], result["exit_code"]), expected)
                self.assertNotIn("stdout", result)
                self.assertNotIn("stderr", result)

    def test_execute_deadline_covers_nonreading_stdin_and_rejects_nonfinite_timeouts(self):
        started = time.monotonic()
        result = self.execute_fake("no_read", prompt="x" * self.adapter().MAX_PROMPT_BYTES,
                                   timeout_seconds=0.1)
        self.assertEqual(result["outcome"], "timeout")
        self.assertLess(time.monotonic() - started, 1)
        for timeout in (0, -1, float("inf"), float("nan"), 301):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.execute_fake("success", timeout_seconds=timeout)

    def test_execute_deadline_covers_descendant_held_pipe_handles(self):
        started = time.monotonic()
        result = self.execute_fake("descendant", timeout_seconds=0.15)
        self.assertEqual(result["outcome"], "timeout")
        self.assertLess(time.monotonic() - started, 1)

    def test_execute_rejects_prompt_and_worker_outputs_that_contain_the_provider_key(self):
        self.assertEqual(self.execute_fake("success", prompt="secret-value")["outcome"],
                         "credential_leak")
        for mode in ("leak_stdout", "leak_stderr", "leak_split", "leak_final"):
            with self.subTest(mode=mode):
                result = self.execute_fake(mode)
                self.assertEqual(result["outcome"], "credential_leak")
                self.assertNotIn("secret-value", json.dumps(result))

    def test_execute_rejects_stale_and_oversize_final_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "result.json"
            output.write_text('{"stale": true}', encoding="utf-8")
            argv = self.adapter().build_codex_exec_argv(
                self.fake_prefix(directory), root, ROOT / "schemas" / "evidence-pack.schema.json", output
            )
            result = self.adapter().execute_codex_exec(argv, "safe", timeout_seconds=0.2,
                                                       environment=dict(os.environ, FREELLMAPI_API_KEY="secret-value"))
            self.assertEqual(result["outcome"], "stale_output")
        self.assertEqual(self.execute_fake("success", max_final_message_bytes=8)["outcome"],
                         "missing_output")

    def test_telemetry_extracts_only_designated_runtime_usage_and_fails_closed_on_bad_json(self):
        raw = "\n".join((
            json.dumps({"type": "message", "usage": {"input_tokens": 999}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "cached_input_tokens": 3, "output_tokens": 4, "reasoning_output_tokens": 2}, "model": "served-model", "provider": "served-provider", "retry_count": 1, "fallback_count": 0}),
        ))
        telemetry = self.telemetry().parse_jsonl_usage(raw.encode("utf-8"))
        self.assertEqual(telemetry, {
            "input_tokens": 12, "cached_input_tokens": 3, "output_tokens": 4,
            "reasoning_output_tokens": 2, "served_model": None,
            "served_provider": None, "retry_count": None, "fallback_count": None,
        })
        with self.assertRaises(ValueError):
            self.telemetry().parse_jsonl_usage(b'{not json}\n')

    def test_telemetry_rejects_oversized_unterminated_line_before_json_materialization(self):
        oversized = b"x" * (self.telemetry().MAX_TELEMETRY_LINE_BYTES + 1)
        with self.assertRaises(ValueError):
            self.telemetry().parse_jsonl_usage(oversized)

    def test_capture_detects_one_character_and_split_chunk_credentials(self):
        for secret, chunks in ((b"x", [b"safe", b"x"]), (b"secret", [b"safe-se", b"cret"])):
            with self.subTest(secret=secret):
                class Chunks(io.RawIOBase):
                    def read(self, _size):
                        return chunks.pop(0) if chunks else b""

                captured, exceeded, leaked = [], [False], [False]
                self.adapter()._capture(Chunks(), 100, captured, exceeded, secret, leaked)
                self.assertTrue(leaked[0])

    def test_termination_wait_and_reap_share_the_operation_deadline(self):
        process = mock.Mock(pid=12345)
        process.wait.side_effect = subprocess.TimeoutExpired("fake", 0)
        deadline = time.monotonic() + 0.02
        signal_method = "killpg" if self.adapter().os.name == "posix" else "kill"
        with mock.patch.object(self.adapter().os, signal_method) as group_signal:
            self.adapter()._terminate_process_tree(process, deadline)
        self.assertEqual(process.wait.call_count, 2)
        if self.adapter().os.name == "posix":
            self.assertEqual(group_signal.call_count, 2)
        else:
            self.assertTrue(process.kill.called)
        for call in process.wait.call_args_list:
            self.assertLessEqual(call.kwargs["timeout"], 0.02 + 1e-6)

    def test_final_output_rejects_links_and_fifo_before_blocking_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "link.json"
            exercised = False
            try:
                link.symlink_to(target)
            except OSError:
                pass
            else:
                exercised = True
                with self.assertRaises(ValueError):
                    self.adapter()._read_final_output(link, 100)
            if hasattr(os, "mkfifo"):
                exercised = True
                fifo = root / "output.fifo"
                os.mkfifo(fifo)
                with self.assertRaises(ValueError):
                    self.adapter()._read_final_output(fifo, 100)
            if not exercised:
                reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                entry = mock.Mock(st_mode=stat.S_IFREG, st_file_attributes=reparse)
                with mock.patch.object(self.adapter().os, "lstat", return_value=entry), \
                        mock.patch.object(self.adapter().os, "open",
                                          side_effect=AssertionError("unsafe path opened")):
                    with self.assertRaises(ValueError):
                        self.adapter()._read_final_output(Path("unsafe-output"), 100)

    def test_final_output_rejects_reparse_and_nonregular_entries_before_open(self):
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        entries = (
            mock.Mock(st_mode=stat.S_IFREG, st_file_attributes=reparse),
            mock.Mock(st_mode=stat.S_IFIFO, st_file_attributes=0),
        )
        for entry in entries:
            with self.subTest(mode=entry.st_mode), \
                    mock.patch.object(self.adapter().os, "lstat", return_value=entry), \
                    mock.patch.object(self.adapter().os, "open",
                                      side_effect=AssertionError("unsafe path was opened")):
                with self.assertRaises(ValueError):
                    self.adapter()._read_final_output(Path("unsafe-output"), 100)

    def test_final_output_rejects_identity_change_between_lstat_and_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "expected.json"
            replacement = root / "replacement.json"
            expected.write_text('{"expected": true}', encoding="utf-8")
            replacement.write_text('{"replacement": true}', encoding="utf-8")
            before = os.lstat(expected)
            real_open = os.open
            with mock.patch.object(self.adapter().os, "lstat", return_value=before), \
                    mock.patch.object(self.adapter().os, "open",
                                      side_effect=lambda _path, flags: real_open(replacement, flags)):
                with self.assertRaises(ValueError):
                    self.adapter()._read_final_output(expected, 100)


if __name__ == "__main__":
    unittest.main()
