"""Legacy Codex JSONL telemetry for the experimental compatibility adapter.

Gemini Direct obtains telemetry from its HTTP response and never uses this parser.
"""
import io
import json
from typing import Any, BinaryIO


MAX_TELEMETRY_BYTES = 524_288
MAX_TELEMETRY_LINES = 4_096
MAX_TELEMETRY_LINE_BYTES = 65_536
# Only this Codex JSONL completion event is locally evidenced.  Do not infer
# served model/provider/retry metadata from fields that lack runtime evidence.
_RUNTIME_EVENT_TYPES = frozenset({"turn.completed"})
_USAGE_FIELDS = {
    "input_tokens": ("input_tokens", "prompt_tokens"),
    "cached_input_tokens": ("cached_input_tokens",),
    "output_tokens": ("output_tokens", "completion_tokens"),
    "reasoning_output_tokens": ("reasoning_output_tokens", "reasoning_tokens"),
}


def _line_stream(source: bytes | BinaryIO) -> BinaryIO:
    if isinstance(source, bytes):
        return io.BytesIO(source)
    if hasattr(source, "read"):
        return source
    raise ValueError("Telemetry must be bytes or a binary stream")


def _nonnegative_integer(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _runtime_event(event: Any) -> bool:
    return isinstance(event, dict) and event.get("type") in _RUNTIME_EVENT_TYPES and \
        isinstance(event.get("usage"), dict)


def parse_jsonl_usage(source: bytes | BinaryIO) -> dict[str, Any]:
    """Return only normalized runtime observations; reject malformed or excessive JSONL."""
    result: dict[str, Any] = {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "reasoning_output_tokens": None,
        "served_model": None,
        "served_provider": None,
        "retry_count": None,
        "fallback_count": None,
    }
    total = 0
    stream = _line_stream(source)
    count = 0
    while True:
        raw_line = stream.readline(MAX_TELEMETRY_LINE_BYTES + 1)
        if not raw_line:
            break
        count += 1
        if count > MAX_TELEMETRY_LINES:
            raise ValueError("Telemetry line limit exceeded")
        total += len(raw_line)
        if total > MAX_TELEMETRY_BYTES or len(raw_line) > MAX_TELEMETRY_LINE_BYTES:
            raise ValueError("Telemetry byte limit exceeded")
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Malformed telemetry JSONL") from error
        if not _runtime_event(event):
            continue
        usage = event["usage"]
        for target, aliases in _USAGE_FIELDS.items():
            for source_name in aliases:
                value = _nonnegative_integer(usage.get(source_name))
                if value is not None:
                    result[target] = value
                    break
    return result
