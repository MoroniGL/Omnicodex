#!/usr/bin/env python3
"""Explicit live Gemini acceptance using only disposable synthetic public files."""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import efficiency, free_context_worker as worker, offload_scope as scope
from scripts.providers.gemini import GeminiProvider
from scripts.providers.base import ProviderError

MARKER = b"OMNICODEX_ACCEPTANCE_MARKER: deterministic synthetic public evidence\n"
RAW_ACCEPTANCE_BYTES = 180000  # 45k under the shipped 4-byte routing estimator.


def _fixture(workspace: Path, byte_count: int) -> None:
    workspace.mkdir()
    filler = b"Synthetic public context for a controlled acceptance test.\n"
    remaining = byte_count - len(MARKER)
    raw = MARKER + (filler * (remaining // len(filler) + 1))[:remaining]
    (workspace / "evidence.txt").write_bytes(raw)


def _request() -> dict[str, Any]:
    return {
        "schema_version": 1, "task_kind": "long_doc_digest",
        "objective": "Report only the single line containing OMNICODEX_ACCEPTANCE_MARKER and cite that exact line.",
        "approved_paths": ["evidence.txt"], "data_classification": "public",
        "external_offload_approved": True,
        "metrics": {"schema_version": 1, "task_kind": "long_doc_digest",
                    "estimated_chars": 0, "file_count": 0, "diff_lines": 0, "log_bytes": 0,
                    "search_hits": 0, "data_classification": "public",
                    "external_offload_approved": True, "independent_units": 1},
    }


def _verify_marker(pack: dict[str, Any], captured: scope.CapturedScope) -> None:
    if pack["status"] != "completed":
        raise ValueError("acceptance_not_completed")
    entries = {entry.path: entry.data.splitlines() for entry in captured.entries}
    cited = [line for finding in pack["findings"] for evidence in finding["evidence"]
             for line in entries[evidence["path"]][evidence["start_line"] - 1:evidence["end_line"]]]
    if not any(line == MARKER.rstrip(b"\n") for line in cited):
        raise ValueError("acceptance_marker_not_cited")


def _small_probe(base: Path, provider: GeminiProvider, timeout: float) -> dict[str, Any]:
    """A deliberate provider probe, separate from normal small-task native routing."""
    workspace = base / "probe"
    _fixture(workspace, 8192)
    request = _request()
    captured = scope.capture_scope(workspace, request["approved_paths"])
    manifest = efficiency.read_json(worker.MANIFEST)
    result = provider.generate_evidence_pack(
        {"task_kind": request["task_kind"], "objective": request["objective"]}, captured,
        efficiency.read_json(worker.OUTPUT_SCHEMA),
        {"timeout_seconds": timeout, "target_pack_tokens": 350, "max_output_tokens": 1500})
    pack_tokens, evidence_tokens = worker._validate_pack(
        result.pack, request, captured, {"max_pack_tokens": 1200, "estimated_raw_tokens": 2048}, manifest)
    _verify_marker(result.pack, captured)
    unchanged, after = worker._scope_unchanged(workspace, captured)
    if not unchanged:
        raise ValueError("workspace_mutated")
    return {
        "mode": "explicit_connectivity_probe", "validation_result": "accepted",
        "estimated_raw_tokens": 2048, "estimated_evidence_pack_tokens": pack_tokens,
        "estimated_verification_evidence_tokens": evidence_tokens,
        "estimated_premium_context_avoided": 2048 - pack_tokens - evidence_tokens,
        "workspace_hash_unchanged": unchanged, "snapshot_before": captured.fingerprint,
        "snapshot_after": after, "input_tokens": result.telemetry.get("input_tokens"),
        "output_tokens": result.telemetry.get("output_tokens"),
        "served_model": result.telemetry.get("served_model"), "elapsed_ms": result.telemetry["elapsed_ms"],
    }


def run_validation(*, environment: Mapping[str, str] | None = None, transport: Any | None = None,
                   timeout_seconds: float = worker.DEFAULT_TIMEOUT_SECONDS,
                   profile: str = "balanced") -> tuple[dict[str, Any], int]:
    """Make exactly two requests on success; no key or raw context enters the report."""
    started = time.monotonic()
    if profile not in efficiency.PROFILES or type(timeout_seconds) not in (int, float) or \
            not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= worker.MAX_TIMEOUT_SECONDS:
        raise ValueError("Invalid validation configuration")
    efficiency.validate_manifest(efficiency.read_json(worker.MANIFEST))
    env = worker._environment(environment)
    provider = GeminiProvider(environment=env, transport=transport)
    settings = provider.status()
    report: dict[str, Any] = {
        "native_status": "READY", "free_context_offload": "READY" if settings["configured"] else "NOT CONFIGURED",
        "requested_provider": settings["provider"], "requested_model": settings["model"],
        "connectivity_verified": False, "quota_fallback": False, "billing_verified": False,
        "token_estimator": "UTF-8 bytes / 4; provider usage is separate and may be unavailable",
    }
    if not settings["configured"]:
        report["status"] = "not_configured"
        return report, 2
    try:
        with tempfile.TemporaryDirectory(prefix="omnicodex-gemini-validation-") as directory:
            base = Path(directory)
            report["probe"] = _small_probe(base, provider, timeout_seconds)
            report["connectivity_verified"] = True
            workspace = base / "acceptance"
            _fixture(workspace, RAW_ACCEPTANCE_BYTES)
            request = _request()
            captured = scope.capture_scope(workspace, request["approved_paths"])
            request["expected_snapshot"] = captured.fingerprint
            request_path = base / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            preview, preview_code = worker.run_action(
                "dry-run", workspace, request_path, profile, None, timeout_seconds,
                environment=env, transport=transport)
            if preview_code or preview["status"] != "ready":
                raise ValueError("acceptance_gate_declined")
            artifacts = base / "artifacts"
            result, code = worker.run_action("run", workspace, request_path, profile, artifacts,
                                              timeout_seconds, environment=env, transport=transport)
            receipt = efficiency.read_json(artifacts / "receipt.json", worker.MAX_ARTIFACT_BYTES)
            unchanged, after = worker._scope_unchanged(workspace, captured)
            report["acceptance"] = {key: receipt[key] for key in (
                "profile", "validation_result", "captured_raw_bytes", "estimated_raw_tokens",
                "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens",
                "estimated_evidence_pack_tokens", "estimated_verification_evidence_tokens",
                "estimated_compact_handoff_tokens", "estimated_premium_context_avoided",
                "estimated_reduction_fraction", "served_model", "retry_count", "elapsed_ms",
                "snapshot_before", "snapshot_after", "orchestration_elapsed_ms")}
            report["acceptance"]["workspace_hash_unchanged"] = unchanged
            if code or not unchanged or after != captured.fingerprint:
                report.update(status="failed", reason_code=result.get("reason_code", "workspace_mutated"))
                return report, 3
            pack = efficiency.read_json(artifacts / "evidence-pack.json", worker.MAX_ARTIFACT_BYTES)
            _verify_marker(pack, captured)
            report["status"] = "accepted"
    except ProviderError as error:
        report.update(status="failed", reason_code=error.reason_code, native_fallback_recommended=True)
        return report, 3
    except (OSError, ValueError, TypeError, AttributeError, KeyError, UnicodeError, RecursionError):
        report.update(status="failed", reason_code="acceptance_validation_failed", native_fallback_recommended=True)
        return report, 3
    finally:
        report["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return report, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(sorted(efficiency.PROFILES)), default="balanced")
    parser.add_argument("--timeout", type=float, default=worker.DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    report, code = run_validation(timeout_seconds=args.timeout, profile=args.profile)
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
