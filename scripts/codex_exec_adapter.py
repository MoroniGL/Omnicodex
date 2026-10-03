"""Experimental legacy FreeLLMAPI/Codex adapter; never used by Gemini Direct.

Retained for compatibility tests only. The normal context worker does not import
or invoke this module and has no Codex subprocess or OS sandbox dependency.
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import threading
import time
from typing import Any, Mapping, Sequence


DEFAULT_BASE_URL = "http://127.0.0.1:3001/v1"
MAX_PROMPT_BYTES = 16_384
MAX_CAPTURE_BYTES = 524_288
MAX_FINAL_MESSAGE_BYTES = 262_144
MAX_TIMEOUT_SECONDS = 300
_SECRET_ENV_KEY = "FREELLMAPI_API_KEY"
_MAX_CLEANUP_RESERVE_SECONDS = 0.1


def _scope_module():
    path = Path(__file__).with_name("offload_scope.py")
    spec = importlib.util.spec_from_file_location("_adapter_offload_scope", path)
    if spec is None or spec.loader is None:
        raise ValueError("Scope validation is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_codex_exec_argv(executable_prefix: Sequence[str], staged_workspace: Path,
                          output_schema: Path, output_last_message: Path,
                          *, endpoint: str | None = None) -> list[str]:
    """Build a shell-free argv sequence for the isolated FreeLLMAPI worker."""
    if not isinstance(executable_prefix, Sequence) or isinstance(executable_prefix, (str, bytes)) or \
            not executable_prefix or not all(isinstance(item, str) and item for item in executable_prefix):
        raise ValueError("Invalid Codex executable prefix")
    if not all(isinstance(path, Path) for path in (staged_workspace, output_schema, output_last_message)):
        raise ValueError("Codex paths must be Path values")
    base_url = _scope_module().validate_endpoint(
        DEFAULT_BASE_URL if endpoint is None else endpoint
    )
    stage = _toml_string(str(staged_workspace.resolve()))
    settings = (
        'model_provider="freellmapi"',
        'model_providers.freellmapi.name="FreeLLMAPI"',
        f"model_providers.freellmapi.base_url={_toml_string(base_url)}",
        'model_providers.freellmapi.wire_api="responses"',
        'model_providers.freellmapi.env_key="FREELLMAPI_API_KEY"',
        'model_providers.freellmapi.requires_openai_auth=false',
        'web_search="disabled"',
        'default_permissions="omnicodex_worker"',
        'permissions.omnicodex_worker.description="Stage-only read access"',
        'permissions.omnicodex_worker.filesystem.":root"="deny"',
        'permissions.omnicodex_worker.filesystem.":minimal"="read"',
        f'permissions.omnicodex_worker.filesystem.{stage}="read"',
        'permissions.omnicodex_worker.network.enabled=false',
        'features.apps=false',
        'features.remote_plugin=false',
        'features.multi_agent=false',
        'shell_environment_policy.ignore_default_excludes=false',
        'shell_environment_policy.exclude=["FREELLMAPI_API_KEY"]',
    )
    # Permission profiles and --sandbox are mutually exclusive in current Codex.
    # Passing --sandbox would silently select the older, broader sandbox policy.
    argv = list(executable_prefix) + ["-a", "never", "exec", "--ephemeral"]
    for setting in settings:
        argv.extend(("-c", setting))
    argv.extend(("--output-schema", str(output_schema), "--json", "--output-last-message",
                 str(output_last_message), "--cd", str(staged_workspace), "--skip-git-repo-check",
                 "--ignore-user-config", "--strict-config", "--model", "auto", "-"))
    return argv


def format_command(argv: Sequence[str], *, platform: str) -> str:
    """Format argv for diagnostics only; production execution never uses this string."""
    if platform == "windows":
        return subprocess.list2cmdline(list(argv))
    if platform == "posix":
        return shlex.join(list(argv))
    raise ValueError("Unknown command display platform")


def _capture(stream, limit: int, captured: list[bytes], exceeded: list[bool], secret: bytes,
             leaked: list[bool]) -> None:
    size = 0
    tail = b""
    try:
        while chunk := stream.read(65_536):
            if secret and secret in tail + chunk:
                leaked[0] = True
            tail = (tail + chunk)[-(len(secret) - 1):] if len(secret) > 1 else b""
            if size < limit:
                captured.append(chunk[:limit - size])
            size += len(chunk)
            if size > limit:
                exceeded[0] = True
    finally:
        _close_stream(stream)


def _result(outcome: str, exit_code: int | None, started: float, **extra: Any) -> dict[str, Any]:
    return {"outcome": outcome, "exit_code": exit_code,
            "elapsed_ms": int((time.monotonic() - started) * 1000), **extra}


def _close_stream(stream) -> None:
    try:
        if stream is not None:
            stream.close()
    except OSError:
        pass


def _read_final_output(path: Path, limit: int) -> bytes:
    before = os.lstat(path)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(before, "st_file_attributes", 0)
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or \
            (reparse and attributes & reparse):
        raise ValueError("Final output is not a safe regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or (before.st_dev, before.st_ino) != \
                (info.st_dev, info.st_ino) or info.st_size > limit:
            raise ValueError("Final output is unavailable or exceeds its limit")
        raw = os.read(descriptor, limit + 1)
        if len(raw) > limit:
            raise ValueError("Final output exceeds its limit")
        return raw
    finally:
        os.close(descriptor)


def _signal_process_tree(process: subprocess.Popen[bytes], *, force: bool) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif not force and hasattr(signal, "CTRL_BREAK_EVENT"):
            # CREATE_NEW_PROCESS_GROUP makes the process id a Windows console
            # group id.  os.kill targets that group even if its leader exited.
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        elif force:
            process.kill()
        else:
            process.terminate()
    except (OSError, ValueError):
        try:
            process.kill() if force else process.terminate()
        except OSError:
            pass


def _wait_for_process(process: subprocess.Popen[bytes], deadline: float) -> bool:
    try:
        process.wait(timeout=max(0.0, deadline - time.monotonic()))
        return True
    except subprocess.TimeoutExpired:
        return False


def _terminate_process_tree(process: subprocess.Popen[bytes], deadline: float) -> None:
    _signal_process_tree(process, force=False)
    remaining = max(0.0, deadline - time.monotonic())
    graceful_deadline = time.monotonic() + remaining / 2
    if _wait_for_process(process, graceful_deadline):
        return
    _signal_process_tree(process, force=True)
    _wait_for_process(process, deadline)


def _join_threads(threads: Sequence[threading.Thread], deadline: float) -> bool:
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    return not any(thread.is_alive() for thread in threads)


def execute_codex_exec(argv: Sequence[str], prompt: str, *, timeout_seconds: float,
                       environment: Mapping[str, str] | None = None,
                       max_capture_bytes: int = MAX_CAPTURE_BYTES,
                       max_final_message_bytes: int = MAX_FINAL_MESSAGE_BYTES) -> dict[str, Any]:
    """Run one worker with shell disabled and return a compact, secret-free result."""
    started = time.monotonic()
    if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError("Prompt exceeds the bounded worker limit")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or \
            not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS or \
            max_capture_bytes <= 0 or max_final_message_bytes <= 0:
        raise ValueError("Invalid execution bound")
    values = list(argv)
    if not values or not all(isinstance(value, str) and value for value in values):
        raise ValueError("Invalid Codex argv")
    try:
        output_path = Path(values[values.index("--output-last-message") + 1])
    except (ValueError, IndexError) as error:
        raise ValueError("Codex argv has no final message path") from error
    execution_environment = dict(environment) if environment is not None else dict(os.environ)
    key_value = execution_environment.get(_SECRET_ENV_KEY)
    secret = key_value.encode("utf-8") if isinstance(key_value, str) and key_value else b""
    if secret and secret in prompt.encode("utf-8"):
        return _result("credential_leak", None, started)
    try:
        os.lstat(output_path)
    except FileNotFoundError:
        pass
    except OSError:
        return _result("stale_output", None, started)
    else:
        return _result("stale_output", None, started)
    deadline = started + float(timeout_seconds)
    cleanup_reserve = min(_MAX_CLEANUP_RESERVE_SECONDS, float(timeout_seconds) / 2)
    worker_deadline = deadline - cleanup_reserve
    popen_options: dict[str, Any] = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                                     "stderr": subprocess.PIPE, "shell": False,
                                     "env": execution_environment}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    else:
        popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(values, **popen_options)
    except OSError:
        return _result("start_failed", None, started)
    stdout, stderr, stdout_exceeded, stderr_exceeded, leaked = [], [], [False], [False], [False]
    readers = [
        threading.Thread(target=_capture, args=(process.stdout, max_capture_bytes, stdout, stdout_exceeded,
                                                secret, leaked), daemon=True),
        threading.Thread(target=_capture, args=(process.stderr, max_capture_bytes, stderr, stderr_exceeded,
                                                secret, leaked), daemon=True),
    ]
    for reader in readers:
        reader.start()
    def deliver_prompt() -> None:
        try:
            process.stdin.write(prompt.encode("utf-8"))
        except OSError:
            pass
        finally:
            _close_stream(process.stdin)

    writer = threading.Thread(target=deliver_prompt, daemon=True)
    writer.start()
    timed_out = False
    try:
        process.wait(timeout=max(0, worker_deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        timed_out = True
    threads = [writer, *readers]
    if timed_out:
        _terminate_process_tree(process, deadline)
        _join_threads(threads, deadline)
        return _result("timeout", None, started)
    if not _join_threads(threads, worker_deadline):
        _terminate_process_tree(process, deadline)
        _join_threads(threads, deadline)
        return _result("timeout", None, started)
    if leaked[0]:
        return _result("credential_leak", process.returncode, started)
    if stdout_exceeded[0] or stderr_exceeded[0]:
        return _result("output_limit_exceeded", process.returncode, started)
    if process.returncode != 0:
        return _result("nonzero_exit", process.returncode, started)
    raw_stdout = b"".join(stdout)
    try:
        telemetry_spec = importlib.util.spec_from_file_location(
            "_adapter_telemetry", Path(__file__).with_name("offload_telemetry.py")
        )
        if telemetry_spec is None or telemetry_spec.loader is None:
            raise ValueError("Telemetry parser is unavailable")
        telemetry = importlib.util.module_from_spec(telemetry_spec)
        telemetry_spec.loader.exec_module(telemetry)
        parsed_telemetry = telemetry.parse_jsonl_usage(raw_stdout)
    except (ValueError, UnicodeError):
        return _result("malformed_output", process.returncode, started)
    try:
        final_bytes = _read_final_output(output_path, max_final_message_bytes)
        if secret and secret in final_bytes:
            return _result("credential_leak", process.returncode, started)
        final_message = json.loads(final_bytes.decode("utf-8"))
        if not isinstance(final_message, dict):
            raise ValueError("Final message must be an object")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _result("missing_output", process.returncode, started)
    return _result("completed", process.returncode, started, final_message=final_message,
                   telemetry=parsed_telemetry)
