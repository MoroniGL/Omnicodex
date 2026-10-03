"""Fail-closed validation and file staging for an external context worker."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import shutil
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MAX_OBJECTIVE_CHARS = 2000
MAX_APPROVED_PATHS = 128
MAX_FILES = 128
MAX_FILE_BYTES = 262144
MAX_TOTAL_BYTES = 524288
MAX_ENDPOINT_CHARS = 2048
REQUEST_FIELDS = {
    "schema_version", "task_kind", "objective", "approved_paths",
    "data_classification", "external_offload_approved", "metrics", "expected_snapshot",
}
SENSITIVE_PARTS = {".git", ".ssh", ".aws", ".gnupg"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx", ".jks"}
PRIVATE_KEY_MARKER = b"-----BEGIN "
CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?im)(?:^|[\s,{])(?:[A-Z][A-Z0-9_]*?(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|AUTH)|"
    rb"password|passwd|token|secret|api[_-]?key|auth)\s*[:=]\s*[^\s#]+"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _efficiency_module() -> Any:
    path = Path(__file__).with_name("efficiency.py")
    spec = importlib.util.spec_from_file_location("_offload_efficiency", path)
    require(spec is not None and spec.loader is not None, "Efficiency gate unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _relative_path(value: Any) -> str:
    require(isinstance(value, str) and 0 < len(value) <= 4096 and "\x00" not in value,
            "Invalid approved path")
    require("\\" not in value and not value.startswith("/"), "Path must be repo-relative")
    require(not re.match(r"^[A-Za-z]:", value), "Path must be repo-relative")
    parts = value.split("/")
    require(all(part not in {"", ".", ".."} for part in parts), "Path traversal is forbidden")
    require(not any(part.casefold() in SENSITIVE_PARTS for part in parts), "Sensitive path forbidden")
    require(not any(part.casefold().startswith(".env") for part in parts), "Sensitive path forbidden")
    return value


def validate_worker_request(request: dict[str, Any]) -> None:
    """Validate a bounded request before examining any workspace path."""
    require(isinstance(request, dict) and set(request) <= REQUEST_FIELDS,
            "Unknown worker request field")
    require(request.get("schema_version") == 1, "Unsupported worker request schema")
    efficiency = _efficiency_module()
    require(request.get("task_kind") in efficiency.OFFLOAD_TASKS, "Unknown worker task")
    objective = request.get("objective")
    require(isinstance(objective, str) and 0 < len(objective) <= MAX_OBJECTIVE_CHARS and
            "\x00" not in objective and not _contains_sensitive_text(objective.encode("utf-8")),
            "Invalid or sensitive worker objective")
    paths = request.get("approved_paths")
    require(isinstance(paths, list) and 1 <= len(paths) <= MAX_APPROVED_PATHS,
            "Invalid approved path list")
    normal_paths = [_relative_path(path) for path in paths]
    require(len(set(normal_paths)) == len(normal_paths), "Duplicate approved path")
    classification = request.get("data_classification")
    require(classification in {"public", "approved_private"}, "Sensitive data cannot be offloaded")
    require(request.get("external_offload_approved") is True,
            "External offload approval is required")
    metrics = request.get("metrics")
    require(isinstance(metrics, dict), "Metrics must be an object")
    efficiency.validate_offload_metrics(metrics, require_provider_available=False)
    require(metrics.get("task_kind") == request["task_kind"] and
            metrics.get("data_classification") == classification and
            metrics.get("external_offload_approved") is True,
            "Request metrics do not match worker request")
    require("provider_available" not in metrics, "Runtime availability belongs to orchestration")
    if "expected_snapshot" in request:
        snapshot = request["expected_snapshot"]
        require(isinstance(snapshot, str) and re.fullmatch(r"[0-9a-f]{64}", snapshot) is not None,
                "Invalid expected snapshot")


def validate_endpoint(endpoint: str) -> str:
    """Allow only a simple HTTP(S) provider endpoint, never credentials or fragments."""
    require(isinstance(endpoint, str) and 0 < len(endpoint) <= MAX_ENDPOINT_CHARS and
            endpoint == endpoint.strip() and "\x00" not in endpoint, "Invalid endpoint")
    parsed = urlsplit(endpoint)
    require(parsed.scheme in {"http", "https"} and bool(parsed.hostname), "Invalid endpoint")
    require(parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment,
            "Endpoint credentials and query are forbidden")
    return endpoint


def _contains_sensitive_text(raw: bytes) -> bool:
    return PRIVATE_KEY_MARKER in raw or CREDENTIAL_ASSIGNMENT.search(raw) is not None


def _is_link_or_reparse(info: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse and attributes & reparse)


def _validated_file(root: Path, relative: str) -> Path:
    _relative_path(relative)
    path = root.joinpath(*relative.split("/"))
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError("Approved path is unavailable") from error
    require(stat.S_ISREG(info.st_mode) and not _is_link_or_reparse(info),
            "Only regular non-link files are allowed")
    require(info.st_size <= MAX_FILE_BYTES, "Approved file exceeds size limit")
    require(path.suffix.casefold() not in SENSITIVE_SUFFIXES, "Sensitive file forbidden")
    return path


def _walk_approved(root: Path, relative: str) -> list[str]:
    _relative_path(relative)
    path = root.joinpath(*relative.split("/"))
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError("Approved path is unavailable") from error
    require(not _is_link_or_reparse(info), "Links and reparse points are forbidden")
    if stat.S_ISREG(info.st_mode):
        _validated_file(root, relative)
        return [relative]
    require(stat.S_ISDIR(info.st_mode), "Only regular files and directories are allowed")
    found: list[str] = []
    with os.scandir(path) as entries:
        for entry in sorted(entries, key=lambda item: item.name):
            child = relative + "/" + entry.name
            found.extend(_walk_approved(root, child))
    return found


def expand_approved_scope(root: Path, approved_paths: list[str]) -> list[str]:
    """Return sorted, privacy-checked regular files without following links."""
    require(isinstance(root, Path) and root.is_dir(), "Workspace root is unavailable")
    require(isinstance(approved_paths, list) and 1 <= len(approved_paths) <= MAX_APPROVED_PATHS,
            "Invalid approved path list")
    paths = [_relative_path(value) for value in approved_paths]
    require(len(paths) == len(set(paths)), "Duplicate approved path")
    files = sorted({file for path in paths for file in _walk_approved(root, path)})
    require(1 <= len(files) <= MAX_FILES, "Approved file count exceeds limit")
    total = 0
    for relative in files:
        path = _validated_file(root, relative)
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        require(len(raw) <= MAX_FILE_BYTES and b"\x00" not in raw and not _contains_sensitive_text(raw),
                "Approved file is binary or sensitive")
        total += len(raw)
        require(total <= MAX_TOTAL_BYTES, "Approved aggregate exceeds size limit")
    return files


def fingerprint_scope(root: Path, scope: list[str]) -> str:
    """Produce a deterministic digest of names, sizes, and streamed approved file bytes."""
    require(isinstance(scope, list) and 1 <= len(scope) <= MAX_FILES and scope == sorted(set(scope)),
            "Invalid scope")
    digest = hashlib.sha256()
    total = 0
    for relative in scope:
        path = _validated_file(root, relative)
        size = path.stat().st_size
        total += size
        require(total <= MAX_TOTAL_BYTES, "Approved aggregate exceeds size limit")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            while chunk := stream.read(65536):
                digest.update(chunk)
    return digest.hexdigest()


def stage_scope(root: Path, scope: list[str], destination: Path,
                expected_snapshot: str | None = None) -> list[str]:
    """Copy approved bytes into a separate view after checking the original snapshot."""
    snapshot = fingerprint_scope(root, scope)
    if expected_snapshot is not None:
        require(snapshot == expected_snapshot, "Approved workspace snapshot changed")
    require(isinstance(destination, Path), "Invalid staging destination")
    destination.mkdir(parents=True, exist_ok=True)
    for relative in scope:
        source = _validated_file(root, relative)
        target = destination.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    require(fingerprint_scope(root, scope) == snapshot, "Approved workspace changed while staging")
    return list(scope)


def validate_evidence_references(root: Path, original_scope: list[str], evidence: list[dict[str, Any]]) -> None:
    """Check evidence points at existing original approved lines, never staged-only data."""
    require(isinstance(evidence, list), "Evidence must be a list")
    allowed = set(original_scope)
    for item in evidence:
        require(isinstance(item, dict), "Invalid evidence reference")
        path = item.get("path")
        require(path in allowed, "Evidence path is outside approved scope")
        source = _validated_file(root, path)
        try:
            with source.open("r", encoding="utf-8", newline=None) as stream:
                line_count = sum(1 for _ in stream)
        except UnicodeError as error:
            raise ValueError("Evidence source is not text") from error
        start, end = item.get("start_line"), item.get("end_line")
        require(type(start) is int and type(end) is int and 1 <= start <= end <= line_count,
                "Evidence line range is outside source")
