"""Fail-closed validation and file staging for an external context worker."""
import hashlib
import importlib.util
import os
import re
import stat
import tempfile
from dataclasses import dataclass
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
SENSITIVE_PARTS = {".git", ".ssh", ".aws", ".gnupg", ".secrets", ".npmrc", ".netrc", ".pypirc",
                   ".docker", ".kube", ".azure", ".git-credentials"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".kdbx", ".jks"}
PRIVATE_KEY_MARKER = b"-----BEGIN "
CREDENTIAL_ASSIGNMENT = re.compile(
    rb'''(?im)(?:^|[\s,{/:])['"]?([a-z_][a-z0-9_-]*)['"]?\s*[:=]\s*['"]?([^\s,}\r\n'"]+)'''
)
AUTH_SIGNATURE = re.compile(
    rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    rb"AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b|"
    rb"(?i:machine\s+\S+[\s\S]{0,512}?\b(?:password|account)\s+\S+)"
)
REDACTED_VALUES = {b"<redacted>", b"redacted", b"<secret>", b"changeme", b"example"}
WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"|?*')
WINDOWS_RESERVED_STEMS = {
    "con", "prn", "aux", "nul", "conin$", "conout$",
    *(f"com{suffix}" for suffix in "123456789¹²³"),
    *(f"lpt{suffix}" for suffix in "123456789¹²³"),
}


@dataclass(frozen=True)
class CapturedEntry:
    path: str
    data: bytes
    digest: str


@dataclass(frozen=True)
class CapturedScope:
    entries: tuple[CapturedEntry, ...]
    fingerprint: str


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


def _relative_path_components(value: Any) -> tuple[str, ...]:
    require(isinstance(value, str) and 0 < len(value) <= 4096 and "\x00" not in value,
            "Invalid approved path")
    require("\\" not in value and not value.startswith("/"), "Path must be repo-relative")
    require(not re.match(r"^[A-Za-z]:", value), "Path must be repo-relative")
    parts = value.split("/")
    require(all(part not in {"", ".", ".."} for part in parts), "Path traversal is forbidden")
    require(not any(part.casefold() in SENSITIVE_PARTS for part in parts), "Sensitive path forbidden")
    for part in parts:
        lowered = part.casefold()
        require(not part.endswith((".", " ")) and
                not any(ord(character) < 32 or character in WINDOWS_INVALID_FILENAME_CHARS
                        for character in part),
                "Non-portable path component")
        require(lowered.split(".", 1)[0] not in WINDOWS_RESERVED_STEMS,
                "Reserved path component")
        require(not lowered.startswith(".env"), "Sensitive path forbidden")
        stem = lowered.rsplit(".", 1)[0]
        require(stem not in {"private-key", "private_key", "auth", "token", "tokens", "secret", "secrets",
                             "api-key", "api_key", "apikey", "api-tokens", "api_tokens", "authorized_keys",
                             "environment_dump", "environment-dump", "env_dump", "env-dump",
                             "conversation_history", "conversation-history", "chat_history", "chat-history"} and
                not any(word in stem for word in ("credential", "password", "passwd")),
                "Sensitive path forbidden")
    return tuple(part.casefold() for part in parts)


def _relative_path(value: Any) -> str:
    _relative_path_components(value)
    return value


def _relative_path_set(values: list[Any]) -> list[str]:
    """Validate paths and reject aliases or file/ancestor conflicts as a complete set."""
    paths: list[str] = []
    normalized: list[tuple[str, ...]] = []
    for value in values:
        normalized.append(_relative_path_components(value))
        paths.append(value)
    ordered = sorted(normalized)
    require(len(ordered) == len(set(ordered)), "Duplicate or aliased path")
    for parent, child in zip(ordered, ordered[1:]):
        require(not (len(parent) < len(child) and child[:len(parent)] == parent),
                "Path cannot also be an ancestor")
    return paths


def validate_worker_request(request: dict[str, Any]) -> None:
    """Validate a bounded request before examining any workspace path."""
    require(isinstance(request, dict) and set(request) <= REQUEST_FIELDS,
            "Unknown worker request field")
    require(type(request.get("schema_version")) is int and request["schema_version"] == 1,
            "Unsupported worker request schema")
    efficiency = _efficiency_module()
    require(request.get("task_kind") in efficiency.OFFLOAD_TASKS, "Unknown worker task")
    objective = request.get("objective")
    require(isinstance(objective, str) and 0 < len(objective) <= MAX_OBJECTIVE_CHARS and
            "\x00" not in objective and not _contains_sensitive_text(objective.encode("utf-8")),
            "Invalid or sensitive worker objective")
    paths = request.get("approved_paths")
    require(isinstance(paths, list) and 1 <= len(paths) <= MAX_APPROVED_PATHS,
            "Invalid approved path list")
    _relative_path_set(paths)
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
    if PRIVATE_KEY_MARKER in raw or AUTH_SIGNATURE.search(raw):
        return True
    for match in CREDENTIAL_ASSIGNMENT.finditer(raw):
        key = match.group(1).lower()
        if not any(word in key for word in
                   (b"token", b"secret", b"password", b"passwd", b"api_key", b"api-key", b"apikey",
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


def _workspace_root(root: Path) -> Path:
    try:
        resolved = root.resolve(strict=True)
        info = root.lstat()
    except OSError as error:
        raise ValueError("Workspace root is unavailable") from error
    require(stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info), "Workspace root is unsafe")
    return resolved


def _safe_workspace_path(root: Path, relative: str) -> Path:
    """Resolve every existing relative ancestor beneath a non-link workspace root."""
    relative = _relative_path(relative)
    resolved_root = _workspace_root(root)
    current = root
    for part in relative.split("/"):
        current = current / part
        try:
            info = current.lstat()
        except OSError as error:
            raise ValueError("Approved path is unavailable") from error
        require(not _is_link_or_reparse(info), "Links and reparse points are forbidden")
        if part != relative.split("/")[-1]:
            require(stat.S_ISDIR(info.st_mode), "Approved ancestor is not a directory")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise ValueError("Approved path escaped workspace") from error
    return current


def _validated_file(root: Path, relative: str) -> Path:
    _relative_path(relative)
    path = _safe_workspace_path(root, relative)
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError("Approved path is unavailable") from error
    require(stat.S_ISREG(info.st_mode) and not _is_link_or_reparse(info),
            "Only regular non-link files are allowed")
    require(info.st_size <= MAX_FILE_BYTES, "Approved file exceeds size limit")
    require(path.suffix.casefold() not in SENSITIVE_SUFFIXES, "Sensitive file forbidden")
    return path


def _read_verified_file(root: Path, relative: str, limit: int = MAX_FILE_BYTES) -> bytes:
    """Read one regular file once, rejecting swaps, size growth, binary and secrets."""
    require(0 <= limit <= MAX_FILE_BYTES, "Invalid read limit")
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
        while chunk := os.read(descriptor, min(65536, limit - size + 1)):
            size += len(chunk)
            require(size <= limit, "Approved file exceeds size limit")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    after_path = _safe_workspace_path(root, relative)
    after = after_path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
            "Approved file changed while reading")
    raw = b"".join(chunks)
    require(b"\x00" not in raw and not _contains_sensitive_text(raw),
            "Approved file is binary or sensitive")
    return raw


def _collect_approved_scope(root: Path, approved_paths: list[str]) -> list[str]:
    """Return sorted, privacy-checked regular files without following links."""
    require(isinstance(root, Path) and root.is_dir(), "Workspace root is unavailable")
    require(isinstance(approved_paths, list) and 1 <= len(approved_paths) <= MAX_APPROVED_PATHS,
            "Invalid approved path list")
    paths = _relative_path_set(approved_paths)
    files: set[str] = set()
    entries_seen = 0

    def walk(relative: str, depth: int) -> None:
        nonlocal entries_seen
        require(depth <= MAX_DEPTH, "Approved path exceeds depth limit")
        _relative_path(relative)
        path = _safe_workspace_path(root, relative)
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
    _relative_path_set(ordered)
    return ordered


def _fingerprint_entries(entries: tuple[CapturedEntry, ...]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(entry.data)).encode("ascii"))
        digest.update(b"\0")
        digest.update(entry.data)
    return digest.hexdigest()


def _validate_captured_scope(captured: Any) -> None:
    """Reject caller-forged captured values before staging mutates the filesystem."""
    require(type(captured) is CapturedScope, "Invalid captured scope")
    require(type(captured.entries) is tuple and 1 <= len(captured.entries) <= MAX_FILES,
            "Invalid captured entries")
    require(type(captured.fingerprint) is str, "Invalid captured fingerprint")

    paths: list[str] = []
    total = 0
    for entry in captured.entries:
        require(type(entry) is CapturedEntry, "Invalid captured entry")
        require(type(entry.path) is str, "Invalid captured path")
        path = _relative_path(entry.path)
        try:
            path.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("Invalid captured path") from error
        require(Path(path).suffix.casefold() not in SENSITIVE_SUFFIXES,
                "Sensitive path forbidden")
        require(type(entry.data) is bytes, "Invalid captured bytes")
        require(len(entry.data) <= MAX_FILE_BYTES, "Captured file exceeds size limit")
        total += len(entry.data)
        require(total <= MAX_TOTAL_BYTES, "Captured scope exceeds size limit")
        require(b"\x00" not in entry.data and not _contains_sensitive_text(entry.data),
                "Captured file is binary or sensitive")
        require(type(entry.digest) is str and
                entry.digest == hashlib.sha256(entry.data).hexdigest(),
                "Captured entry digest mismatch")
        paths.append(path)

    _relative_path_set(paths)
    require(paths == sorted(paths), "Captured paths must be sorted")
    require(captured.fingerprint == _fingerprint_entries(captured.entries),
            "Captured scope fingerprint mismatch")


def capture_scope(root: Path, approved_paths: list[str]) -> CapturedScope:
    """Capture one bounded, verified immutable view of the approved source files."""
    paths = _collect_approved_scope(root, approved_paths)
    entries: list[CapturedEntry] = []
    total = 0
    for relative in paths:
        raw = _read_verified_file(root, relative, min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total))
        total += len(raw)
        entries.append(CapturedEntry(relative, raw, hashlib.sha256(raw).hexdigest()))
    frozen = tuple(entries)
    return CapturedScope(frozen, _fingerprint_entries(frozen))


def expand_approved_scope(root: Path, approved_paths: list[str]) -> list[str]:
    return [entry.path for entry in capture_scope(root, approved_paths).entries]


def validate_captured_references(captured: CapturedScope, evidence: list[dict[str, Any]]) -> None:
    """Validate ranges solely against immutable approved bytes, with no filesystem access."""
    _validate_captured_scope(captured)
    require(isinstance(evidence, list), "Evidence must be a list")
    lines = {entry.path: len(entry.data.decode("utf-8").splitlines()) for entry in captured.entries}
    for item in evidence:
        require(isinstance(item, dict), "Invalid evidence reference")
        path = item.get("path")
        require(isinstance(path, str) and path in lines, "Evidence path is outside captured scope")
        start, end = item.get("start_line"), item.get("end_line")
        require(type(start) is int and type(end) is int and 1 <= start <= end <= lines[path],
                "Evidence line range is outside captured source")


def fingerprint_scope(root: Path, scope: list[str]) -> str:
    """Produce a deterministic digest of names, sizes, and streamed approved file bytes."""
    return capture_scope(root, scope).fingerprint


def stage_captured_scope(captured: CapturedScope, parent: Path) -> tuple[Path, CapturedScope]:
    """Create a random private stage below parent and verify its actual bytes."""
    _validate_captured_scope(captured)
    require(isinstance(parent, Path) and parent.is_dir(), "Invalid staging parent")
    for ancestor in reversed(parent.parents):
        require(not _is_link_or_reparse(ancestor.lstat()), "Staging parent is a link")
    require(not _is_link_or_reparse(parent.lstat()), "Staging parent is a link")
    try:
        stage = Path(tempfile.mkdtemp(prefix="offload-", dir=parent))
        os.chmod(stage, 0o700)
    except OSError as error:
        raise ValueError("Staging destination cannot be created") from error
    for entry in captured.entries:
        target = stage.joinpath(*entry.path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            written = 0
            while written < len(entry.data):
                count = os.write(descriptor, entry.data[written:])
                require(count > 0, "Staging write failed")
                written += count
            os.fsync(descriptor)
        except OSError as error:
            raise ValueError("Staging write failed") from error
        finally:
            try:
                os.close(descriptor)
            except (OSError, UnboundLocalError):
                pass
    actual = capture_scope(stage, [entry.path for entry in captured.entries])
    require(actual.fingerprint == captured.fingerprint, "Staged files do not match approved snapshot")
    return stage, actual


def validate_evidence_references(root: Path, original_scope: list[str], evidence: list[dict[str, Any]]) -> None:
    """Check evidence points at existing original approved lines, never staged-only data."""
    require(isinstance(evidence, list), "Evidence must be a list")
    allowed = set(original_scope)
    for item in evidence:
        require(isinstance(item, dict), "Invalid evidence reference")
        path = item.get("path")
        require(path in allowed, "Evidence path is outside approved scope")
        try:
            line_count = len(_read_verified_file(root, path).decode("utf-8").splitlines())
        except UnicodeError as error:
            raise ValueError("Evidence source is not text") from error
        start, end = item.get("start_line"), item.get("end_line")
        require(type(start) is int and type(end) is int and 1 <= start <= end <= line_count,
                "Evidence line range is outside source")
