"""Fail-closed validation and file staging for an external context worker."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MAX_OBJECTIVE_CHARS = 2000
MAX_APPROVED_PATHS = 128
MAX_FILES = 128
MAX_DEPTH = 32
MAX_DIRECTORY_ENTRIES = 4096
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
    rb'''(?im)(?:^|[\s,{])['"]?([a-z_][a-z0-9_-]*)['"]?\s*[:=]\s*['"]?([^\s,}\r\n'"]+)'''
)
REDACTED_VALUES = {b"<redacted>", b"redacted", b"<secret>", b"changeme", b"example"}


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
    for part in parts:
        lowered = part.casefold()
        require(not lowered.startswith(".env"), "Sensitive path forbidden")
        stem = lowered.rsplit(".", 1)[0]
        require(not any(word in stem for word in ("credential", "password", "passwd", "private_key")),
                "Sensitive path forbidden")
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
    if PRIVATE_KEY_MARKER in raw:
        return True
    for match in CREDENTIAL_ASSIGNMENT.finditer(raw):
        key = match.group(1).lower()
        if not any(word in key for word in
                   (b"token", b"secret", b"password", b"passwd", b"api_key", b"apikey",
                    b"auth", b"credential", b"access_key")):
            continue
        value = match.group(2).strip().lower()
        if value not in REDACTED_VALUES and not value.startswith(b"${"):
            return True
    return False


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


def _read_verified_file(root: Path, relative: str) -> bytes:
    """Read one regular file once, rejecting swaps, size growth, binary and secrets."""
    path = _validated_file(root, relative)
    before = path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError("Approved file cannot be safely opened") from error
    try:
        opened = os.fstat(descriptor)
        require(stat.S_ISREG(opened.st_mode) and not _is_link_or_reparse(opened) and
                (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
                "Approved file changed while opening")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 65536):
            size += len(chunk)
            require(size <= MAX_FILE_BYTES, "Approved file exceeds size limit")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "Approved file changed while reading")
    raw = b"".join(chunks)
    require(b"\x00" not in raw and not _contains_sensitive_text(raw),
            "Approved file is binary or sensitive")
    return raw


def expand_approved_scope(root: Path, approved_paths: list[str]) -> list[str]:
    """Return sorted, privacy-checked regular files without following links."""
    require(isinstance(root, Path) and root.is_dir(), "Workspace root is unavailable")
    require(isinstance(approved_paths, list) and 1 <= len(approved_paths) <= MAX_APPROVED_PATHS,
            "Invalid approved path list")
    paths = [_relative_path(value) for value in approved_paths]
    require(len(paths) == len(set(paths)), "Duplicate approved path")
    files: set[str] = set()
    entries_seen = 0

    def walk(relative: str, depth: int) -> None:
        nonlocal entries_seen
        require(depth <= MAX_DEPTH, "Approved path exceeds depth limit")
        path = root.joinpath(*relative.split("/"))
        try:
            info = path.lstat()
        except OSError as error:
            raise ValueError("Approved path is unavailable") from error
        require(not _is_link_or_reparse(info), "Links and reparse points are forbidden")
        if stat.S_ISREG(info.st_mode):
            _validated_file(root, relative)
            files.add(relative)
            require(len(files) <= MAX_FILES, "Approved file count exceeds limit")
            return
        require(stat.S_ISDIR(info.st_mode), "Only regular files and directories are allowed")
        with os.scandir(path) as directory:
            for entry in directory:
                entries_seen += 1
                require(entries_seen <= MAX_DIRECTORY_ENTRIES, "Approved traversal exceeds entry limit")
                walk(relative + "/" + entry.name, depth + 1)

    for path in paths:
        walk(path, 0)
    ordered = sorted(files)
    require(ordered, "Approved scope is empty")
    total = 0
    for relative in ordered:
        raw = _read_verified_file(root, relative)
        total += len(raw)
        require(total <= MAX_TOTAL_BYTES, "Approved aggregate exceeds size limit")
    return ordered


def fingerprint_scope(root: Path, scope: list[str]) -> str:
    """Produce a deterministic digest of names, sizes, and streamed approved file bytes."""
    require(isinstance(scope, list) and 1 <= len(scope) <= MAX_FILES and scope == sorted(set(scope)),
            "Invalid scope")
    digest = hashlib.sha256()
    total = 0
    for relative in scope:
        raw = _read_verified_file(root, relative)
        total += len(raw)
        require(total <= MAX_TOTAL_BYTES, "Approved aggregate exceeds size limit")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(raw)).encode("ascii"))
        digest.update(b"\0")
        digest.update(raw)
    return digest.hexdigest()


def stage_scope(root: Path, scope: list[str], destination: Path,
                expected_snapshot: str | None = None) -> list[str]:
    """Copy approved bytes into a separate view after checking the original snapshot."""
    snapshot = fingerprint_scope(root, scope)
    if expected_snapshot is not None:
        require(snapshot == expected_snapshot, "Approved workspace snapshot changed")
    require(isinstance(destination, Path) and destination.parent.is_dir(), "Invalid staging destination")
    for parent in reversed(destination.parents):
        try:
            require(not _is_link_or_reparse(parent.lstat()), "Staging parent is a link")
        except OSError as error:
            raise ValueError("Staging parent is unavailable") from error
    if destination.exists():
        info = destination.lstat()
        require(stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info) and
                not any(destination.iterdir()), "Staging destination must be a fresh empty directory")
    else:
        destination.mkdir()
        require(not _is_link_or_reparse(destination.lstat()), "Staging destination is a link")
    staged_digest = hashlib.sha256()
    for relative in scope:
        raw = _read_verified_file(root, relative)
        target = destination.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        parent_info = target.parent.lstat()
        require(stat.S_ISDIR(parent_info.st_mode) and not _is_link_or_reparse(parent_info),
                "Staging destination contains a link")
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        except OSError as error:
            raise ValueError("Staging target cannot be safely created") from error
        try:
            os.write(descriptor, raw)
        finally:
            os.close(descriptor)
        staged_digest.update(relative.encode("utf-8"))
        staged_digest.update(b"\0")
        staged_digest.update(str(len(raw)).encode("ascii"))
        staged_digest.update(b"\0")
        staged_digest.update(raw)
    require(staged_digest.hexdigest() == snapshot, "Approved workspace changed while staging")
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
