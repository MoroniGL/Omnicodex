"""Safety contract tests for bounded FreeLLMAPI worker inputs."""
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "offload_scope", ROOT / "scripts" / "offload_scope.py"
)
offload_scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offload_scope)


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
                     "scripts\\efficiency.py"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    offload_scope.validate_worker_request(self.request(approved_paths=[path]))

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
                self.skipTest("Host does not allow creating symlinks")
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
                ("aws.txt", "aws_access_key_id=AKIAIOSFODNN7EXAMPLE\n"),
                ("token.txt", "_authToken=live-token-value\n"),
                ("credentials.txt", "ordinary text\n"),
                ("private.txt", "-----BEGIN PRIVATE KEY-----\n"),
            ):
                (root / "safe" / name).write_text(content, encoding="utf-8")
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        offload_scope.expand_approved_scope(root, [f"safe/{name}"])

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

    def test_staging_preserves_relative_names_and_refuses_changed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            root = Path(directory)
            (root / "safe").mkdir()
            path = root / "safe" / "ok.txt"
            path.write_text("safe text\n", encoding="utf-8")
            scope = offload_scope.expand_approved_scope(root, ["safe"])
            snapshot = offload_scope.fingerprint_scope(root, scope)
            staged = offload_scope.stage_scope(root, scope, Path(staging), snapshot)
            self.assertEqual(staged, ["safe/ok.txt"])
            self.assertEqual((Path(staging) / "safe" / "ok.txt").read_text(encoding="utf-8"), "safe text\n")
            path.write_text("changed\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                offload_scope.stage_scope(root, scope, Path(staging), snapshot)

    def test_staging_rejects_mutation_to_sensitive_content_and_matches_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging:
            root = Path(directory)
            (root / "safe").mkdir()
            source = root / "safe" / "ok.txt"
            source.write_text("safe\n", encoding="utf-8")
            scope = offload_scope.expand_approved_scope(root, ["safe"])
            snapshot = offload_scope.fingerprint_scope(root, scope)
            source.write_text('"api_key": "live-secret-value"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                offload_scope.stage_scope(root, scope, Path(staging), snapshot)
            source.write_text("safe again\n", encoding="utf-8")
            snapshot = offload_scope.fingerprint_scope(root, scope)
            offload_scope.stage_scope(root, scope, Path(staging), snapshot)
            self.assertEqual(offload_scope.fingerprint_scope(Path(staging), scope), snapshot)

    def test_staging_rejects_destination_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as staging, \
                tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            destination = Path(staging)
            (root / "safe").mkdir()
            (root / "safe" / "ok.txt").write_text("safe\n", encoding="utf-8")
            scope = offload_scope.expand_approved_scope(root, ["safe"])
            try:
                (destination / "safe").symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                self.skipTest("Host does not allow creating symlinks")
            with self.assertRaises(ValueError):
                offload_scope.stage_scope(root, scope, destination)

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


if __name__ == "__main__":
    unittest.main()
