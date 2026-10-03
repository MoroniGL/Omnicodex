"""Safety contract tests for bounded FreeLLMAPI worker inputs."""
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


class FreeContextWorkerTests(unittest.TestCase):
    def request(self, **overrides):
        value = {
            "schema_version": 1,
            "task_kind": "repo_scout",
            "objective": "Map the bounded routing implementation.",
            "approved_paths": ["scripts/efficiency.py"],
            "data_classification": "public",
            "external_offload_approved": True,
            "metrics": {
                "schema_version": 1,
                "task_kind": "repo_scout",
                "estimated_chars": 80000,
                "file_count": 1,
                "diff_lines": 0,
                "log_bytes": 0,
                "search_hits": 1,
                "data_classification": "public",
                "external_offload_approved": True,
                "independent_units": 1,
            },
        }
        value.update(overrides)
        return value

    def test_request_accepts_only_bounded_approved_public_fields(self):
        request = self.request(expected_snapshot="a" * 64)
        offload_scope.validate_worker_request(request)

    def test_request_accepts_explicitly_approved_private_context(self):
        request = self.request(data_classification="approved_private")
        request["metrics"]["data_classification"] = "approved_private"
        offload_scope.validate_worker_request(request)

    def test_request_rejects_unknown_fields_and_unapproved_private_data(self):
        for request in (
            self.request(unexpected=True),
            self.request(data_classification="approved_private",
                         external_offload_approved=False),
            self.request(data_classification="sensitive"),
            self.request(objective="inspect password=secret"),
        ):
            with self.subTest(request=request):
                with self.assertRaises(ValueError):
                    offload_scope.validate_worker_request(request)

    def test_request_rejects_path_traversal_and_windows_absolute_paths(self):
        for path in ("../secret", "/etc/passwd", "C:/Windows/win.ini", "C:\\Windows\\win.ini",
                     "scripts\\efficiency.py", "safe/trailing.", "safe/trailing ",
                     "safe/CON", "safe/nul.txt", "safe/bad:name.txt", "safe/bad?.txt"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    offload_scope.validate_worker_request(self.request(approved_paths=[path]))

    def test_request_rejects_portable_path_aliases_and_prefix_conflicts(self):
        for paths in (
            ["safe/A.txt", "safe/a.txt"],
            ["safe/a", "safe/a/b"],
        ):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                offload_scope.validate_worker_request(self.request(approved_paths=paths))

    def test_endpoint_rejects_credentials_query_and_non_http_schemes(self):
        self.assertEqual(offload_scope.validate_endpoint("http://127.0.0.1:3001/v1"),
                         "http://127.0.0.1:3001/v1")
        for endpoint in ("https://key@example.test/v1", "https://example.test/v1?key=x",
                         "file:///tmp/provider", " http://example.test/v1"):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    offload_scope.validate_endpoint(endpoint)

    def test_expand_scope_rejects_sensitive_binary_links_and_special_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "ok.txt").write_text("safe text\n", encoding="utf-8")
            (root / ".env.local").write_text("TOKEN=nope\n", encoding="utf-8")
            (root / "safe" / "key.pem").write_text("not a real key\n", encoding="utf-8")
            (root / "safe" / "binary.bin").write_bytes(b"\x00\x01")
            for path in (".env.local", "safe/key.pem", "safe/binary.bin"):
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        offload_scope.expand_approved_scope(root, [path])
            try:
                (root / "safe" / "link.txt").symlink_to(root / "safe" / "ok.txt")
            except OSError:
                reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                synthetic = mock.Mock(st_mode=stat.S_IFREG, st_file_attributes=reparse)
                self.assertTrue(offload_scope._is_link_or_reparse(synthetic))
            else:
                with self.assertRaises(ValueError):
                    offload_scope.expand_approved_scope(root, ["safe/link.txt"])

    def test_expand_scope_rejects_real_credentials_but_allows_redacted_placeholders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "placeholder.txt").write_text(
                '"api_key": "<redacted>"\nAWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}\n', encoding="utf-8"
            )
            self.assertEqual(offload_scope.expand_approved_scope(root, ["safe/placeholder.txt"]),
                             ["safe/placeholder.txt"])
            for name, content in (
                ("api.txt", '"api_key": "live-secret-value"\n'),
                ("hyphen.txt", "api-key=live-secret-value\n"),
                ("aws.txt", "aws_access_key_id=AKIAIOSFODNN7EXAMPLE\n"),
                ("token.txt", "_authToken=live-token-value\n"),
                ("credentials.txt", "ordinary text\n"),
                ("private.txt", "-----BEGIN PRIVATE KEY-----\n"),
            ):
                (root / "safe" / name).write_text(content, encoding="utf-8")
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        offload_scope.expand_approved_scope(root, [f"safe/{name}"])

    def test_expand_scope_rejects_exact_sensitive_stems_but_allows_token_offload_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "token-offload.md").write_text("ordinary documentation\n", encoding="utf-8")
            self.assertEqual(offload_scope.expand_approved_scope(root, ["safe/token-offload.md"]),
                             ["safe/token-offload.md"])
            for name in ("private-key.txt", "auth.json", "token.md", "secret.txt", "api-key.txt",
                         "api_key.txt", "apikey.txt"):
                (root / "safe" / name).write_text("ordinary text\n", encoding="utf-8")
                with self.subTest(name=name), self.assertRaises(ValueError):
                    offload_scope.expand_approved_scope(root, [f"safe/{name}"])

    def test_discovered_sensitive_empty_child_is_rejected_before_file_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "ok.txt").write_text("safe\n", encoding="utf-8")
            (root / "safe" / ".git").mkdir()
            with self.assertRaises(ValueError):
                offload_scope.expand_approved_scope(root, ["safe"])

    def test_expand_scope_is_bounded_and_snapshot_changes_with_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            path = root / "safe" / "ok.txt"
            path.write_text("first\n", encoding="utf-8")
            scope = offload_scope.expand_approved_scope(root, ["safe"])
            self.assertEqual(scope, ["safe/ok.txt"])
            first = offload_scope.fingerprint_scope(root, scope)
            path.write_text("second\n", encoding="utf-8")
            second = offload_scope.fingerprint_scope(root, scope)
            self.assertNotEqual(first, second)

    def test_expand_scope_rejects_file_and_count_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "large.txt").write_bytes(b"x" * (offload_scope.MAX_FILE_BYTES + 1))
            with self.assertRaises(ValueError):
                offload_scope.expand_approved_scope(root, ["safe/large.txt"])
            for index in range(offload_scope.MAX_FILES + 1):
                (root / "safe" / f"{index}.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                offload_scope.expand_approved_scope(root, ["safe"])

    def test_expand_scope_rejects_aggregate_limit_and_excessive_depth(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bytes").mkdir()
            for index in range(3):
                (root / "bytes" / f"{index}.txt").write_bytes(b"x" * (offload_scope.MAX_FILE_BYTES - 1))
            with self.assertRaises(ValueError):
                offload_scope.expand_approved_scope(root, ["bytes"])
            current = root / "deep"
            current.mkdir()
            for index in range(offload_scope.MAX_DEPTH + 1):
                current = current / str(index)
                current.mkdir()
            (current / "leaf.txt").write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                offload_scope.expand_approved_scope(root, ["deep"])

    def test_expand_scope_enforces_directory_entry_limit_incrementally(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            for index in range(3):
                (root / "safe" / f"{index}.txt").write_text("x", encoding="utf-8")
            with mock.patch.object(offload_scope, "MAX_DIRECTORY_ENTRIES", 2):
                with self.assertRaises(ValueError):
                    offload_scope.expand_approved_scope(root, ["safe"])

    def test_read_limit_uses_only_one_sentinel_byte_beyond_remaining_allowance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "file.txt").write_bytes(b"abcdef")
            requests = []
            real_read = offload_scope.os.read

            def bounded_read(descriptor, count):
                requests.append(count)
                return real_read(descriptor, count)

            with mock.patch.object(offload_scope.os, "read", side_effect=bounded_read):
                with self.assertRaises(ValueError):
                    offload_scope._read_verified_file(root, "safe/file.txt", 3)
            self.assertTrue(requests)
            self.assertLessEqual(max(requests), 4)

    def test_staging_preserves_relative_names_and_captured_bytes(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            root = Path(directory)
            (root / "safe").mkdir()
            path = root / "safe" / "ok.txt"
            path.write_text("safe text\n", encoding="utf-8")
            scope = offload_scope.expand_approved_scope(root, ["safe"])
            captured = offload_scope.capture_scope(root, scope)
            path.write_text("changed\n", encoding="utf-8")
            stage, _ = offload_scope.stage_captured_scope(captured, Path(staging))
            staged = [entry.path for entry in captured.entries]
            self.assertEqual(staged, ["safe/ok.txt"])
            self.assertEqual((stage / "safe" / "ok.txt").read_text(encoding="utf-8"), "safe text\n")

    def test_staging_rejects_mutation_to_sensitive_content_and_matches_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            root = Path(directory)
            (root / "safe").mkdir()
            source = root / "safe" / "ok.txt"
            source.write_text("safe\n", encoding="utf-8")
            scope = offload_scope.expand_approved_scope(root, ["safe"])
            source.write_text('"api_key": "live-secret-value"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                offload_scope.capture_scope(root, scope)
            source.write_text("safe again\n", encoding="utf-8")
            snapshot = offload_scope.fingerprint_scope(root, scope)
            captured = offload_scope.capture_scope(root, scope)
            stage, _ = offload_scope.stage_captured_scope(captured, Path(staging))
            self.assertEqual(offload_scope.fingerprint_scope(stage, scope), snapshot)

    def test_staging_rejects_destination_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging, \
                tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "ok.txt").write_text("safe\n", encoding="utf-8")
            captured = offload_scope.capture_scope(root, ["safe"])
            destination = Path(staging) / "link"
            try:
                destination.symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                with mock.patch.object(offload_scope, "_is_link_or_reparse", return_value=True):
                    with self.assertRaises(ValueError):
                        offload_scope.stage_captured_scope(captured, Path(staging))
            else:
                with self.assertRaises(ValueError):
                    offload_scope.stage_captured_scope(captured, destination)

    def test_staging_returns_the_only_fresh_stage_and_writes_all_partial_chunks(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            root = Path(directory)
            (root / "safe").mkdir()
            source = root / "safe" / "ok.txt"
            source.write_text("all staged bytes\n", encoding="utf-8")
            scope = offload_scope.expand_approved_scope(root, ["safe"])
            real_write = offload_scope.os.write

            def partial_write(descriptor, data):
                return real_write(descriptor, data[:1])

            with mock.patch.object(offload_scope.os, "write", side_effect=partial_write):
                stage, _ = offload_scope.stage_captured_scope(
                    offload_scope.capture_scope(root, scope), Path(staging)
                )
            self.assertTrue(stage.is_dir())
            self.assertEqual(list(Path(staging).iterdir()), [stage])
            self.assertEqual((stage / "safe" / "ok.txt").read_text(encoding="utf-8"),
                             "all staged bytes\n")

    def test_capture_rejects_real_ancestor_swap_at_open_boundary(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            safe = root / "safe"
            safe.mkdir()
            (safe / "ok.txt").write_text("safe\n", encoding="utf-8")
            (Path(outside) / "ok.txt").write_text("outside\n", encoding="utf-8")
            real_open = offload_scope.os.open
            swapped = False

            def swap_then_open(path, flags, *args):
                nonlocal swapped
                if not swapped and Path(path).name == "ok.txt":
                    safe.rename(root / "safe-old")
                    Path(outside).rename(safe)
                    swapped = True
                return real_open(path, flags, *args)

            with mock.patch.object(offload_scope.os, "open", side_effect=swap_then_open):
                with self.assertRaises(ValueError):
                    offload_scope.capture_scope(root, ["safe/ok.txt"])

    def test_captured_scope_stages_bytes_to_a_fresh_private_directory(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "ok.txt").write_text("captured\n", encoding="utf-8")
            captured = offload_scope.capture_scope(root, ["safe"])
            stage, staged = offload_scope.stage_captured_scope(captured, Path(staging))
            self.assertNotEqual(stage, Path(staging))
            self.assertEqual(staged.fingerprint, captured.fingerprint)
            self.assertEqual((stage / "safe" / "ok.txt").read_text(encoding="utf-8"), "captured\n")

    def test_captured_scope_rejects_corrupted_staged_bytes(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "ok.txt").write_text("captured\n", encoding="utf-8")
            captured = offload_scope.capture_scope(root, ["safe"])
            real_write = offload_scope.os.write
            corrupted = False

            def corrupt_first_write(descriptor, data):
                nonlocal corrupted
                if not corrupted:
                    corrupted = True
                    return real_write(descriptor, b"X" + data[1:])
                return real_write(descriptor, data)

            with mock.patch.object(offload_scope.os, "write", side_effect=corrupt_first_write):
                with self.assertRaises(ValueError):
                    offload_scope.stage_captured_scope(captured, Path(staging))

    def test_staging_rejects_forged_paths_before_any_filesystem_mutation(self):
        with tempfile.TemporaryDirectory() as staging:
            parent = Path(staging)
            outside = parent / "escape.txt"
            invalid_entries = (
                offload_scope.CapturedEntry("../escape.txt", b"escape\n",
                                            "0" * 64),
            )
            forged = offload_scope.CapturedScope(invalid_entries, "0" * 64)

            with self.assertRaises(ValueError):
                offload_scope.stage_captured_scope(forged, parent)

            self.assertFalse(outside.exists())
            self.assertEqual(list(parent.iterdir()), [])

    def test_staging_rejects_path_aliases_and_prefixes_before_creating_stage(self):
        def entry(path):
            data = b"safe\n"
            return offload_scope.CapturedEntry(
                path, data, hashlib.sha256(data).hexdigest()
            )

        cases = {
            "file ancestor prefix": (entry("safe/a"), entry("safe/a/b")),
            "case insensitive collision": (entry("safe/A.txt"), entry("safe/a.txt")),
            "trailing dot": (entry("safe/name."),),
            "trailing space": (entry("safe/name "),),
            "reserved device": (entry("safe/CON"),),
            "reserved device with suffix": (entry("safe/nul.txt"),),
            "invalid Windows character": (entry("safe/bad:name.txt"),),
        }

        for name, entries in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as staging:
                parent = Path(staging)
                forged = offload_scope.CapturedScope(
                    entries, offload_scope._fingerprint_entries(entries)
                )

                with self.assertRaises(ValueError):
                    offload_scope.stage_captured_scope(forged, parent)

                self.assertEqual(list(parent.iterdir()), [])

    def test_staging_rejects_forged_entry_invariants_before_creating_stage(self):
        def entry(path, data=b"safe\n", digest=None):
            if digest is None:
                digest = hashlib.sha256(data).hexdigest()
            return offload_scope.CapturedEntry(path, data, digest)

        class ForgedEntry(offload_scope.CapturedEntry):
            pass

        class ForgedPath(str):
            pass

        class ForgedDigest(str):
            pass

        safe_a = entry("safe/a.txt")
        safe_b = entry("safe/b.txt")
        forged_entry = ForgedEntry(safe_a.path, safe_a.data, safe_a.digest)
        cases = {
            "duplicate": (safe_a, safe_a),
            "unsorted": (safe_b, safe_a),
            "too many entries": tuple(
                entry(f"safe/{index:03}.txt", b"x")
                for index in range(offload_scope.MAX_FILES + 1)
            ),
            "oversized": (entry("safe/large.txt", b"x" * (offload_scope.MAX_FILE_BYTES + 1)),),
            "sensitive path": (entry("safe/.env.local"),),
            "sensitive suffix": (entry("safe/key.pem"),),
            "entry subclass": (forged_entry,),
            "path subclass": (entry(ForgedPath("safe/data.txt")),),
            "non-bytes data": (
                offload_scope.CapturedEntry("safe/data.txt", bytearray(b"safe\n"),
                                            safe_a.digest),
            ),
            "binary content": (entry("safe/data.txt", b"safe\x00binary"),),
            "sensitive content": (entry("safe/data.txt", b"password=live-secret\n"),),
            "digest subclass": (
                entry("safe/data.txt", digest=ForgedDigest(hashlib.sha256(b"safe\n").hexdigest())),
            ),
            "wrong entry digest": (entry("safe/data.txt", digest="0" * 64),),
        }

        for name, entries in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as staging:
                parent = Path(staging)
                forged = offload_scope.CapturedScope(
                    entries, offload_scope._fingerprint_entries(entries)
                )
                with self.assertRaises(ValueError):
                    offload_scope.stage_captured_scope(forged, parent)
                self.assertEqual(list(parent.iterdir()), [])

    def test_staging_rejects_forged_scope_shape_total_size_and_fingerprint_before_writes(self):
        def entry(path, data):
            return offload_scope.CapturedEntry(
                path, data, hashlib.sha256(data).hexdigest()
            )

        valid = entry("safe/data.txt", b"safe\n")
        aggregate = tuple(
            entry(f"safe/{index}.txt", b"x" * (offload_scope.MAX_FILE_BYTES - 1))
            for index in range(3)
        )

        class ForgedScope(offload_scope.CapturedScope):
            pass

        cases = {
            "empty entries": offload_scope.CapturedScope(
                (), offload_scope._fingerprint_entries(())
            ),
            "entries are not a tuple": offload_scope.CapturedScope(
                [valid], offload_scope._fingerprint_entries((valid,))
            ),
            "aggregate oversized": offload_scope.CapturedScope(
                aggregate, offload_scope._fingerprint_entries(aggregate)
            ),
            "wrong overall fingerprint": offload_scope.CapturedScope((valid,), "0" * 64),
            "non-string fingerprint": offload_scope.CapturedScope((valid,), b"0" * 64),
            "scope subclass": ForgedScope((valid,), offload_scope._fingerprint_entries((valid,))),
        }

        for name, forged in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as staging:
                parent = Path(staging)
                with self.assertRaises(ValueError):
                    offload_scope.stage_captured_scope(forged, parent)
                self.assertEqual(list(parent.iterdir()), [])

    def test_evidence_references_must_point_inside_original_scope_and_real_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe").mkdir()
            (root / "safe" / "ok.txt").write_text("one\ntwo\n", encoding="utf-8")
            scope = offload_scope.expand_approved_scope(root, ["safe"])
            evidence = [{"path": "safe/ok.txt", "start_line": 1, "end_line": 2, "kind": "source"}]
            offload_scope.validate_evidence_references(root, scope, evidence)
            for bad in (
                [{"path": "safe/missing.txt", "start_line": 1, "end_line": 1, "kind": "source"}],
                [{"path": "safe/ok.txt", "start_line": 2, "end_line": 3, "kind": "source"}],
                [{"path": "../outside", "start_line": 1, "end_line": 1, "kind": "source"}],
            ):
                with self.subTest(evidence=bad):
                    with self.assertRaises(ValueError):
                        offload_scope.validate_evidence_references(root, scope, bad)


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
                     timeout_seconds=0.2, max_final_message_bytes=None):
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
                result = self.execute_fake(mode)
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


class WorkerOrchestrationTests(unittest.TestCase):
    """End-to-end orchestration with a real subprocess boundary.

    Removing the native gate or sending the original workspace to Codex must
    make these tests fail.
    """

    def worker(self):
        self.assertIsNotNone(free_context_worker, "free context worker is missing")
        return free_context_worker

    def request(self, estimated_chars=80_000):
        return {
            "schema_version": 1, "task_kind": "repo_scout", "objective": "Map code.",
            "approved_paths": ["safe.txt"], "data_classification": "public",
            "external_offload_approved": True,
            "metrics": {"schema_version": 1, "task_kind": "repo_scout",
                        "estimated_chars": estimated_chars, "file_count": 1,
                        "diff_lines": 0, "log_bytes": 0, "search_hits": 1,
                        "data_classification": "public", "external_offload_approved": True,
                        "independent_units": 1},
        }

    def large_text(self, marker="public-context-marker"):
        return marker + "\n" + ("public context line\n" * 4_000)

    def test_small_request_returns_native_fallback_without_starting_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            (root / "safe.txt").write_text("unique-staged-marker\n", encoding="utf-8")
            request = Path(directory) / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            result, code = self.worker().run_action(
                "dry-run", root, request, "balanced", None, None, 1, environment={}
            )
        self.assertEqual(code, 0)
        self.assertEqual((result["status"], result["route"]), ("fallback", "native"))
        self.assertIn("context_below_offload_threshold", result["reason_codes"])

    def test_eligible_request_runs_once_against_staged_scope_and_writes_accepted_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            source_text = self.large_text("unique-staged-marker")
            source = root / "safe.txt"
            source.write_text(source_text, encoding="utf-8")
            source_bytes = source.read_bytes()
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            fake = base / "fake.py"
            fake.write_text(
                "import json,pathlib,sys\n"
                "a=sys.argv; stage=pathlib.Path(a[a.index('--cd')+1]); out=pathlib.Path(a[a.index('--output-last-message')+1])\n"
                "content=(stage/'safe.txt').read_text(); assert content.startswith('unique-staged-marker\\n'); assert len(content) > 48000\n"
                "assert not (stage/'outside.txt').exists()\n"
                "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'cached_input_tokens':0,'output_tokens':1,'reasoning_output_tokens':0}}))\n"
                "out.write_text(json.dumps({'schema_version':1,'status':'completed','task_kind':'repo_scout','snapshot':sys.stdin.read().split('snapshot=')[1].split('\\n')[0],'summary':'unique-staged-marker','relevant_files':['safe.txt'],'findings':[{'claim':'marker','evidence':[{'path':'safe.txt','start_line':1,'end_line':1,'kind':'source'}]}],'risks':[],'unknowns':[],'validation':[]}))\n",
                encoding="utf-8",
            )
            artifacts = base / "artifacts"
            result, code = self.worker().run_action(
                "run", root, request, "balanced", (sys.executable, str(fake)), artifacts, 2,
                environment={"FREELLMAPI_API_KEY": "not-in-result"},
            )
            receipt = json.loads((artifacts / "receipt.json").read_text(encoding="utf-8"))
            pack = json.loads((artifacts / "evidence-pack.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(pack["summary"], "unique-staged-marker")
        self.assertEqual(receipt["worker_outcome"], "completed")
        self.assertEqual(receipt["captured_raw_bytes"], len(source_bytes))
        self.assertEqual(receipt["estimated_raw_tokens"],
                         (len(source_bytes) + 3) // 4)
        self.assertLess(receipt["estimated_compact_handoff_tokens"],
                        receipt["estimated_raw_tokens"])
        self.assertNotIn("not-in-result", json.dumps(result))
        self.assertNotIn("unique-staged-marker", json.dumps(result))

    def test_missing_key_or_binary_falls_back_without_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            (root / "safe.txt").write_text(self.large_text(), encoding="utf-8")
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            cases = (
                ((sys.executable, "unused.py"), {}, "missing_key"),
                (None, {"FREELLMAPI_API_KEY": "configured"}, "codex_unavailable"),
            )
            for codex, environment, reason in cases:
                with self.subTest(reason=reason):
                    artifacts = base / (reason + "-artifacts")
                    result, code = self.worker().run_action(
                        "run", root, request, "balanced", codex, artifacts, 1,
                        environment=environment,
                    )
                    self.assertEqual((code, result["status"], result["route"]),
                                     (0, "fallback", "native"))
                    self.assertIn(reason, result["reason_codes"])
                    self.assertFalse(artifacts.exists())

    def test_dry_run_is_offline_secret_free_and_uses_scope_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            marker = "raw-marker-never-in-command"
            (root / "safe.txt").write_text(self.large_text(marker), encoding="utf-8")
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            secret = "worker-key-never-serialized"
            result, code = self.worker().run_action(
                "dry-run", root, request, "balanced", (sys.executable, "fake.py"),
                None, 1, environment={"FREELLMAPI_API_KEY": secret},
            )
        rendered = json.dumps(result)
        self.assertEqual((code, result["status"], result["route"]),
                         (0, "ready", "free_context_worker"))
        self.assertRegex(result["snapshot"], r"^[0-9a-f]{64}$")
        self.assertNotIn(secret, rendered)
        self.assertNotIn(marker, rendered)
        preview = result["command_preview_posix"]
        self.assertNotIn("--sandbox", preview)
        self.assertIn("default_permissions", preview)

    def test_snapshot_mismatch_and_invalid_endpoint_fail_without_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            (root / "safe.txt").write_text(self.large_text(), encoding="utf-8")
            value = self.request()
            value["expected_snapshot"] = "0" * 64
            request = base / "request.json"
            request.write_text(json.dumps(value), encoding="utf-8")
            result, code = self.worker().run_action(
                "run", root, request, "balanced", (sys.executable, "unused.py"),
                base / "artifacts", 1,
                environment={"FREELLMAPI_API_KEY": "configured"},
            )
            self.assertEqual((code, result["reason_code"]), (3, "snapshot_mismatch"))
            self.assertEqual(result["route"], "native")
            self.assertTrue(result["native_fallback_recommended"])
            value.pop("expected_snapshot")
            request.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.worker().run_action(
                    "dry-run", root, request, "balanced", (sys.executable, "unused.py"),
                    None, 1,
                    environment={"FREELLMAPI_API_KEY": "configured",
                                 "FREELLMAPI_BASE_URL": "https://key@example.test/v1"},
                )

    def test_timeout_and_artifact_placement_are_bounded_before_worker_start(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            (root / "safe.txt").write_text(self.large_text(), encoding="utf-8")
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            environment = {"FREELLMAPI_API_KEY": "configured"}
            for timeout in (0, -1, float("inf"), float("nan"), 301):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    self.worker().run_action(
                        "dry-run", root, request, "balanced",
                        (sys.executable, "unused.py"), None, timeout,
                        environment=environment,
                    )
            with self.assertRaises(ValueError):
                self.worker().run_action(
                    "run", root, request, "balanced", (sys.executable, "unused.py"),
                    root / "artifacts", 1, environment=environment,
                )
            self.assertFalse((root / "artifacts").exists())

    def test_invalid_pack_is_rejected_once_and_receipt_contains_no_raw_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            marker = "raw-source-must-stay-local"
            (root / "safe.txt").write_text(self.large_text(marker), encoding="utf-8")
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            counter = base / "count.txt"
            fake = base / "fake.py"
            fake.write_text(
                "import pathlib,sys\n"
                "a=sys.argv; c=pathlib.Path(sys.argv[1]); c.write_text((c.read_text() if c.exists() else '')+'x')\n"
                "pathlib.Path(a[a.index('--output-last-message')+1]).write_text('{}')\n",
                encoding="utf-8",
            )
            artifacts = base / "artifacts"
            result, code = self.worker().run_action(
                "run", root, request, "balanced", (sys.executable, str(fake), str(counter)),
                artifacts, 2, environment={"FREELLMAPI_API_KEY": "configured"},
            )
            receipt = json.loads((artifacts / "receipt.json").read_text(encoding="utf-8"))
            count = counter.read_text(encoding="utf-8")
            evidence_pack_exists = (artifacts / "evidence-pack.json").exists()
        self.assertEqual((code, result["reason_code"]), (3, "invalid_pack"))
        self.assertEqual(result["route"], "native")
        self.assertTrue(result["native_fallback_recommended"])
        self.assertEqual(count, "x")
        self.assertTrue(receipt["native_fallback_recommended"])
        self.assertFalse(evidence_pack_exists)
        self.assertNotIn(marker, json.dumps(receipt))

    def test_workspace_mutation_invalidates_pack_after_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            source = root / "safe.txt"
            source.write_text(self.large_text("before"), encoding="utf-8")
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            fake = base / "slow.py"
            fake.write_text(
                "import json,pathlib,sys,time\n"
                "a=sys.argv; prompt=sys.stdin.read(); time.sleep(.2)\n"
                "snap=prompt.split('snapshot=')[1].split('\\n')[0]\n"
                "pathlib.Path(a[a.index('--output-last-message')+1]).write_text(json.dumps({'schema_version':1,'status':'completed','task_kind':'repo_scout','snapshot':snap,'summary':'ok','relevant_files':['safe.txt'],'findings':[{'claim':'c','evidence':[{'path':'safe.txt','start_line':1,'end_line':1,'kind':'source'}]}],'risks':[],'unknowns':[],'validation':[]}))\n",
                encoding="utf-8",
            )
            thread = threading.Thread(
                target=lambda: (time.sleep(.08), source.write_text("after\n", encoding="utf-8"))
            )
            thread.start()
            try:
                result, code = self.worker().run_action(
                    "run", root, request, "balanced", (sys.executable, str(fake)),
                    base / "artifacts", 2,
                    environment={"FREELLMAPI_API_KEY": "configured"},
                )
            finally:
                thread.join()
        self.assertEqual((code, result["reason_code"]), (3, "workspace_mutated"))
        self.assertEqual(result["route"], "native")
        self.assertTrue(result["native_fallback_recommended"])

    def test_missing_pack_is_invalid_and_valid_noncompleted_status_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            (root / "safe.txt").write_text(self.large_text(), encoding="utf-8")
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            missing = base / "missing.py"
            missing.write_text("import json; print(json.dumps({'type':'turn.completed','usage':{}}))\n",
                               encoding="utf-8")
            result, code = self.worker().run_action(
                "run", root, request, "balanced", (sys.executable, str(missing)),
                base / "missing-artifacts", 2,
                environment={"FREELLMAPI_API_KEY": "configured"},
            )
            self.assertEqual((code, result["reason_code"], result["route"]),
                             (3, "invalid_pack", "native"))

            blocked = base / "blocked.py"
            blocked.write_text(
                "import json,pathlib,sys\n"
                "a=sys.argv; p=sys.stdin.read(); s=p.split('snapshot=')[1].split('\\n')[0]\n"
                "pathlib.Path(a[a.index('--output-last-message')+1]).write_text(json.dumps({'schema_version':1,'status':'blocked','task_kind':'repo_scout','snapshot':s,'summary':'needs input','relevant_files':[],'findings':[],'risks':[],'unknowns':['not enough evidence'],'validation':[]}))\n",
                encoding="utf-8",
            )
            blocked_result, blocked_code = self.worker().run_action(
                "run", root, request, "balanced", (sys.executable, str(blocked)),
                base / "blocked-artifacts", 2,
                environment={"FREELLMAPI_API_KEY": "configured"},
            )
            blocked_receipt = json.loads(
                (base / "blocked-artifacts" / "receipt.json").read_text(encoding="utf-8")
            )
        self.assertEqual((blocked_code, blocked_result["status"], blocked_result["route"]),
                         (0, "blocked", "free_context_worker"))
        self.assertEqual(blocked_receipt["evidence_pack_status"], "blocked")

    def test_worker_process_failures_map_transparently_without_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            (root / "safe.txt").write_text(self.large_text(), encoding="utf-8")
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            fake = base / "fail.py"
            fake.write_text(
                "import pathlib,sys,time\n"
                "mode=sys.argv[1]; a=sys.argv\n"
                "if mode == 'timeout': time.sleep(5)\n"
                "elif mode == 'nonzero': sys.exit(7)\n"
                "elif mode == 'oversize': pathlib.Path(a[a.index('--output-last-message')+1]).write_text('x'*262145)\n",
                encoding="utf-8",
            )
            cases = {
                "timeout": "worker_timeout",
                "nonzero": "worker_failed",
                "missing": "invalid_pack",
                "oversize": "invalid_pack",
            }
            for mode, reason in cases.items():
                with self.subTest(mode=mode):
                    result, code = self.worker().run_action(
                        "run", root, request, "balanced",
                        (sys.executable, str(fake), mode), base / (mode + "-artifacts"),
                        .15 if mode == "timeout" else 2,
                        environment={"FREELLMAPI_API_KEY": "configured"},
                    )
                    self.assertEqual((code, result["reason_code"], result["route"]),
                                     (3, reason, "native"))
                    self.assertTrue(result["native_fallback_recommended"])

    def test_pack_plus_cited_source_must_be_smaller_than_captured_context(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            (root / "safe.txt").write_text(("x" * 128 + "\n") * 400, encoding="utf-8")
            request = base / "request.json"
            request.write_text(json.dumps(self.request()), encoding="utf-8")
            fake = base / "full-citation.py"
            fake.write_text(
                "import json,pathlib,sys\n"
                "a=sys.argv; p=sys.stdin.read(); s=p.split('snapshot=')[1].split('\\n')[0]\n"
                "pathlib.Path(a[a.index('--output-last-message')+1]).write_text(json.dumps({'schema_version':1,'status':'completed','task_kind':'repo_scout','snapshot':s,'summary':'not compact','relevant_files':['safe.txt'],'findings':[{'claim':'all','evidence':[{'path':'safe.txt','start_line':1,'end_line':400,'kind':'source'}]}],'risks':[],'unknowns':[],'validation':[]}))\n",
                encoding="utf-8",
            )
            result, code = self.worker().run_action(
                "run", root, request, "balanced", (sys.executable, str(fake)),
                base / "artifacts", 2,
                environment={"FREELLMAPI_API_KEY": "configured"},
            )
            receipt = json.loads(
                (base / "artifacts" / "receipt.json").read_text(encoding="utf-8")
            )
        self.assertEqual((code, result["reason_code"], result["route"]),
                         (3, "invalid_pack", "native"))
        self.assertIsNone(receipt["estimated_compact_handoff_tokens"])

    def test_doctor_reports_local_prerequisites_without_live_claims_or_key(self):
        secret = "doctor-secret"
        result, code = self.worker().run_action(
            "doctor", None, None, "balanced", (sys.executable,), None, 1,
            environment={"FREELLMAPI_API_KEY": secret},
        )
        self.assertEqual(code, 0)
        self.assertTrue(result["key_configured"])
        self.assertTrue(result["codex_available"])
        self.assertFalse(result["gateway_probed"])
        self.assertFalse(result["runtime_model_verified"])
        self.assertNotIn(secret, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
