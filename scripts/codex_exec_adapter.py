"""Construct and run one bounded, isolated Codex exec worker."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import threading
import time
from typing import Any, Mapping, Sequence


DEFAULT_BASE_URL = "http://127.0.0.1:3001/v1"
MAX_PROMPT_BYTES = 16_384
MAX_CAPTURE_BYTES = 524_288
MAX_FINAL_MESSAGE_BYTES = 262_144


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
    settings = (
        'model_provider="freellmapi"',
        'model_providers.freellmapi.name="FreeLLMAPI"',
        f"model_providers.freellmapi.base_url={_toml_string(base_url)}",
        'model_providers.freellmapi.wire_api="responses"',
        'model_providers.freellmapi.env_key="FREELLMAPI_API_KEY"',
        'model_providers.freellmapi.requires_openai_auth=false',
        'web_search="disabled"',
        'shell_environment_policy.ignore_default_excludes=false',
        'shell_environment_policy.exclude=["FREELLMAPI_API_KEY"]',
    )
    argv = list(executable_prefix) + ["-a", "never", "exec", "--ephemeral", "--sandbox", "read-only"]
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


def _capture(stream, limit: int, captured: list[bytes], exceeded: list[bool]) -> None:
    size = 0
    while chunk := stream.read(65_536):
        if size < limit:
            captured.append(chunk[:limit - size])
        size += len(chunk)
        if size > limit:
            exceeded[0] = True


def _result(outcome: str, exit_code: int | None, started: float, **extra: Any) -> dict[str, Any]:
    return {"outcome": outcome, "exit_code": exit_code,
            "elapsed_ms": int((time.monotonic() - started) * 1000), **extra}


def execute_codex_exec(argv: Sequence[str], prompt: str, *, timeout_seconds: float,
                       environment: Mapping[str, str] | None = None,
                       max_capture_bytes: int = MAX_CAPTURE_BYTES,
                       max_final_message_bytes: int = MAX_FINAL_MESSAGE_BYTES) -> dict[str, Any]:
    """Run one worker with shell disabled and return a compact, secret-free result."""
    if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise ValueError("Prompt exceeds the bounded worker limit")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0 or \
            max_capture_bytes <= 0 or max_final_message_bytes <= 0:
        raise ValueError("Invalid execution bound")
    values = list(argv)
    if not values or not all(isinstance(value, str) and value for value in values):
        raise ValueError("Invalid Codex argv")
    try:
        output_path = Path(values[values.index("--output-last-message") + 1])
    except (ValueError, IndexError) as error:
        raise ValueError("Codex argv has no final message path") from error
    started = time.monotonic()
    try:
        process = subprocess.Popen(values, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   shell=False, env=dict(environment) if environment is not None else None)
    except OSError:
        return _result("start_failed", None, started)
    stdout, stderr, stdout_exceeded, stderr_exceeded = [], [], [False], [False]
    readers = [
        threading.Thread(target=_capture, args=(process.stdout, max_capture_bytes, stdout, stdout_exceeded)),
        threading.Thread(target=_capture, args=(process.stderr, max_capture_bytes, stderr, stderr_exceeded)),
    ]
    for reader in readers:
        reader.start()
    try:
        process.stdin.write(prompt.encode("utf-8"))
        process.stdin.close()
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        for reader in readers:
            reader.join()
        process.stdout.close()
        process.stderr.close()
        return _result("timeout", None, started)
    finally:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
    for reader in readers:
        reader.join()
    process.stdout.close()
    process.stderr.close()
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
        if not output_path.is_file() or output_path.stat().st_size > max_final_message_bytes:
            return _result("missing_output", process.returncode, started)
        final_message = json.loads(output_path.read_bytes().decode("utf-8"))
        if not isinstance(final_message, dict):
            raise ValueError("Final message must be an object")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _result("missing_output", process.returncode, started)
    return _result("completed", process.returncode, started, final_message=final_message,
                   telemetry=parsed_telemetry)
