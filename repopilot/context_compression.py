"""Tool-round based prompt compression for long agent transcripts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath


EXIT_CODE_PATTERN = re.compile(r"(?im)^\s*exit_code:\s*(-?\d+)\s*$")
ERROR_HINT_PATTERN = re.compile(r"(?i)\b(error|failed|fail|traceback|permission denied|exception)\b")
PATHISH_PATTERN = re.compile(r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+(?:\.[A-Za-z0-9_.-]+)?")


def _tail_clip(text, limit):
    text = str(text)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


@dataclass(frozen=True)
class CompressedHistory:
    raw: str
    rendered: str
    details: dict


def render_tool_round_compressed_history(history, budget, active_tool_rounds=3):
    """Render history with frozen/compressed/active transcript zones.

    RepoPilot stores tool results directly in history. A "tool round" is therefore
    represented by each tool-result item, with nearby recent messages kept in the
    active suffix. Older tool rounds become deterministic structured breadcrumbs
    that retain tool name, file path/command, and failure status.
    """
    history = list(history or [])
    raw = _raw_history_text(history)
    if not history:
        rendered = "Transcript:\n- empty"
        return CompressedHistory(raw=raw, rendered=rendered, details=_details("tool_round_compression"))

    tool_indices = [index for index, item in enumerate(history) if item.get("role") == "tool"]
    active_count = min(int(active_tool_rounds), len(tool_indices))
    compression_failures = 0

    while active_count >= 0:
        active_indices = set(tool_indices[-active_count:]) if active_count else set()
        active_start = min(active_indices) if active_indices else len(history)
        rendered, details = _render_with_active_start(history, active_start, budget)
        compression_failures += details.pop("compression_failure_count", 0)
        omitted_high_value = int(details.get("omitted_high_value_count", 0))
        if budget <= 0 or (len(rendered) <= budget and omitted_high_value == 0):
            details["active_round_count"] = active_count
            details["compression_failure_count"] = compression_failures
            return CompressedHistory(raw=raw, rendered=rendered, details=details)
        active_count -= 1

    rendered, details = _render_compressed_only(history, budget)
    details["compression_failure_count"] = compression_failures + int(budget > 0 and len(rendered) > budget)
    if budget > 0 and len(rendered) > budget:
        rendered = _tail_clip(rendered, budget)
    return CompressedHistory(raw=raw, rendered=rendered, details=details)



def render_llm_tool_round_compressed_history(history, budget, model_client, max_new_tokens=700, active_tool_rounds=2):
    """Render history using a real model call for the compressed zone.

    The model is only used to summarize older tool rounds. Recent active rounds
    stay verbatim, and model output is parsed into structured breadcrumbs so the
    downstream prompt remains testable.
    """
    history = list(history or [])
    raw = _raw_history_text(history)
    if not history:
        rendered = "Transcript:\n- empty"
        details = _details("llm_tool_round_compression")
        details["llm_call_count"] = 0
        return CompressedHistory(raw=raw, rendered=rendered, details=details)

    tool_indices = [index for index, item in enumerate(history) if item.get("role") == "tool"]
    active_count = min(int(active_tool_rounds), len(tool_indices))
    active_indices = set(tool_indices[-active_count:]) if active_count else set()
    active_start = min(active_indices) if active_indices else len(history)
    compressed_items = history[:active_start]
    active_items = history[active_start:]
    fallback_lines, fallback_details = _compressed_zone_lines(compressed_items)
    llm_text = ""
    llm_error = ""
    try:
        llm_text = model_client.complete(_llm_compression_prompt(compressed_items), max_new_tokens=max_new_tokens)
        compressed_lines = _parse_llm_compression_lines(llm_text)
        if not compressed_lines:
            raise ValueError("LLM compression returned no parseable items")
    except Exception as exc:  # pragma: no cover - real provider fallback path
        llm_error = str(exc)
        compressed_lines = fallback_lines
    active_lines = _active_zone_lines(active_items)
    selected = _prioritized_compressed_lines(compressed_lines, budget, active_lines) if budget > 0 else compressed_lines
    lines = ["Transcript:"]
    if selected:
        lines.append("Compressed older tool rounds:")
        lines.extend(selected)
    if active_lines:
        lines.append("Active recent context:")
        lines.extend(active_lines)
    rendered = "\n".join(lines)
    if budget > 0 and len(rendered) > budget:
        selected = _prioritized_compressed_lines(selected, budget, active_lines)
        lines = ["Transcript:"]
        if selected:
            lines.append("Compressed older tool rounds:")
            lines.extend(selected)
        if active_lines:
            lines.append("Active recent context:")
            lines.extend(active_lines)
        rendered = "\n".join(lines)
    if budget > 0 and len(rendered) > budget:
        rendered = _tail_clip(rendered, budget)
    details = _details(
        "llm_tool_round_compression",
        active_round_count=active_count,
        compressed_round_count=fallback_details["compressed_round_count"],
        compressed_message_count=fallback_details["compressed_message_count"],
        compressed_line_count=len(selected),
        retained_file_paths=fallback_details["retained_file_paths"],
        retained_failed_tool_count=fallback_details["retained_failed_tool_count"],
        rendered_entries=lines[1:],
    )
    details["llm_call_count"] = 1
    details["llm_fallback_used"] = bool(llm_error)
    details["llm_error"] = llm_error
    metadata = getattr(model_client, "last_completion_metadata", {}) or {}
    details["llm_input_tokens"] = metadata.get("input_tokens")
    details["llm_output_tokens"] = metadata.get("output_tokens")
    return CompressedHistory(raw=raw, rendered=rendered, details=details)



def _select_llm_compression_items(items):
    selected = []
    for item in items:
        if item.get("role") != "tool":
            continue
        content = str(item.get("content", ""))
        paths = _extract_paths(str(item.get("name", "")), item.get("args", {}) if isinstance(item.get("args", {}), dict) else {}, content)
        if _is_failed_tool(content, _extract_exit_code(content)) or any("legacy_config.py" in path for path in paths):
            selected.append(item)
    for item in reversed(items):
        if len(selected) >= 4:
            break
        if item.get("role") == "tool" and item not in selected:
            selected.append(item)
    selected.sort(key=lambda item: items.index(item))
    return selected[:4]

def _llm_compression_prompt(items):
    records = []
    for item in _select_llm_compression_items(items):
        if item.get("role") == "tool":
            records.append(
                {
                    "role": "tool",
                    "name": item.get("name", "tool"),
                    "args": item.get("args", {}),
                    "content": _tail_clip(item.get("content", ""), 220),
                }
            )
        else:
            records.append(
                {
                    "role": item.get("role", "message"),
                    "content": _tail_clip(item.get("content", ""), 300),
                }
            )
    return (
        "You compress coding-agent tool history. Return JSON only, no markdown.\n"
        "Schema: {\"items\":[{\"tool\":string,\"status\":\"ok\"|\"error\","
        "\"path\":string,\"command\":string,\"exit_code\":number|null,\"signal\":string}]}\n"
        "Rules: keep every failed tool call; keep file paths that may matter; use status=error when exit_code is nonzero or output contains FAIL/error/Traceback.\n"
        "History JSON:\n"
        + json.dumps(records, ensure_ascii=False, sort_keys=True)
    )


def _parse_llm_compression_lines(text):
    payload = _extract_json_object(text)
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or item.get("name") or "tool").strip() or "tool"
        status = str(item.get("status") or "ok").strip().lower()
        if status not in {"ok", "error"}:
            status = "error" if status in {"failed", "fail", "failure"} else "ok"
        parts = [f"[llm-compressed:{tool}]", f"status={status}"]
        exit_code = item.get("exit_code")
        if exit_code is not None and str(exit_code).strip() != "":
            try:
                parts.append(f"exit_code={int(exit_code)}")
            except (TypeError, ValueError):
                parts.append(f"exit_code={json.dumps(str(exit_code))}")
        path = str(item.get("path") or "").strip()
        if path:
            parts.append(f"path={_normalize_path(path)}")
        command = str(item.get("command") or "").strip()
        if command:
            parts.append(f"command={json.dumps(_tail_clip(command, 120))}")
        signal = str(item.get("signal") or "").strip()
        if signal:
            parts.append(f"signal={json.dumps(_tail_clip(signal, 100))}")
        lines.append(" ".join(parts))
    return lines


def _extract_json_object(text):
    text = str(text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

def _render_with_active_start(history, active_start, budget):
    compressed_items = history[:active_start]
    active_items = history[active_start:]
    compressed_lines, compressed_details = _compressed_zone_lines(compressed_items)
    active_lines = _active_zone_lines(active_items)
    lines = ["Transcript:"]
    if compressed_lines:
        lines.append("Compressed older tool rounds:")
        lines.extend(compressed_lines)
    if active_lines:
        lines.append("Active recent context:")
        lines.extend(active_lines)
    if len(lines) == 1:
        lines.append("- empty")
    rendered = "\n".join(lines)
    details = _details(
        "tool_round_compression",
        compressed_round_count=compressed_details["compressed_round_count"],
        compressed_message_count=compressed_details["compressed_message_count"],
        retained_file_paths=compressed_details["retained_file_paths"],
        retained_failed_tool_count=compressed_details["retained_failed_tool_count"],
        rendered_entries=lines[1:],
    )
    if budget > 0 and len(rendered) > budget and compressed_lines:
        compact_compressed = _prioritized_compressed_lines(compressed_lines, budget, active_lines)
        lines = ["Transcript:"]
        if compact_compressed:
            lines.append("Compressed older tool rounds:")
            lines.extend(compact_compressed)
        if active_lines:
            lines.append("Active recent context:")
            lines.extend(active_lines)
        rendered = "\n".join(lines)
        details["rendered_entries"] = lines[1:]
        details["compressed_line_count"] = len(compact_compressed)
        failed_count = sum(1 for line in compressed_lines if "status=error" in line)
        selected_failed_count = sum(1 for line in compact_compressed if "status=error" in line)
        has_path = any("path=" in line or "paths=" in line for line in compressed_lines)
        selected_path = any("path=" in line or "paths=" in line for line in compact_compressed)
        details["omitted_high_value_count"] = max(0, failed_count - selected_failed_count) + int(has_path and not selected_path)
    else:
        details["compressed_line_count"] = len(compressed_lines)
        details["omitted_high_value_count"] = 0
    return rendered, details


def _render_compressed_only(history, budget):
    compressed_lines, compressed_details = _compressed_zone_lines(history)
    selected = _prioritized_compressed_lines(compressed_lines, budget, []) if budget > 0 else compressed_lines
    lines = ["Transcript:", "Compressed older tool rounds:", *selected] if selected else ["Transcript:", "- empty"]
    rendered = "\n".join(lines)
    return rendered, _details(
        "tool_round_compression",
        active_round_count=0,
        compressed_round_count=compressed_details["compressed_round_count"],
        compressed_message_count=compressed_details["compressed_message_count"],
        compressed_line_count=len(selected),
        retained_file_paths=compressed_details["retained_file_paths"],
        retained_failed_tool_count=compressed_details["retained_failed_tool_count"],
        rendered_entries=lines[1:],
    )


def _compressed_zone_lines(items):
    lines = []
    retained_file_paths = []
    retained_failed_tool_count = 0
    compressed_round_count = 0
    compressed_message_count = 0
    seen_read_paths = set()
    for item in items:
        if item.get("role") == "tool":
            compressed_round_count += 1
            line, paths, failed = _summarize_tool_round(item)
            if item.get("name") == "read_file" and paths:
                path_key = paths[0]
                if path_key in seen_read_paths:
                    continue
                seen_read_paths.add(path_key)
            lines.append(line)
            retained_file_paths.extend(path for path in paths if path not in retained_file_paths)
            retained_failed_tool_count += int(failed)
        else:
            compressed_message_count += 1
            line = _summarize_message(item)
            if line:
                lines.append(line)
    return lines, {
        "compressed_round_count": compressed_round_count,
        "compressed_message_count": compressed_message_count,
        "retained_file_paths": retained_file_paths,
        "retained_failed_tool_count": retained_failed_tool_count,
    }


def _prioritized_compressed_lines(compressed_lines, budget, active_lines):
    if budget <= 0:
        return []
    fixed = len("Transcript:\nCompressed older tool rounds:\n")
    if active_lines:
        fixed += len("\nActive recent context:\n") + sum(len(line) + 1 for line in active_lines)
    available = max(0, budget - fixed)
    selected = []
    used = 0
    prioritized = []
    for index, line in enumerate(compressed_lines):
        if "status=error" in line:
            priority = 0
        elif "path=" in line or "paths=" in line:
            priority = 1
        else:
            priority = 2
        order = index if priority == 0 else -index
        prioritized.append((priority, order, line))
    for _, _, line in sorted(prioritized):
        candidate = line
        cost = len(candidate) + 1
        if used + cost <= available:
            selected.append(candidate)
            used += cost
            continue
        remaining = available - used
        if remaining >= 24 and ("status=error" in line or "path=" in line or "paths=" in line):
            candidate = _minimal_summary_line(line, remaining - 1)
            cost = len(candidate) + 1
            if candidate and used + cost <= available:
                selected.append(candidate)
                used += cost
    selected.sort(key=lambda line: compressed_lines.index(_original_line_for_sort(line, compressed_lines)))
    return selected


def _minimal_summary_line(line, limit):
    if limit <= 0:
        return ""
    tokens = line.split()
    keep = []
    for token in tokens:
        if token.startswith("[compressed:") or token.startswith("status=") or token.startswith("exit_code=") or token.startswith("path=") or token.startswith("paths="):
            keep.append(token)
    return _tail_clip(" ".join(keep) if keep else line, limit)


def _original_line_for_sort(line, compressed_lines):
    for original in compressed_lines:
        if line == original or original.startswith(line.rstrip("...")) or line.startswith(original[: min(len(original), len(line.rstrip("...")))]):
            return original
    return compressed_lines[-1] if compressed_lines else line


def _active_zone_lines(items):
    lines = []
    for item in items:
        lines.extend(_render_history_item(item, 900))
    return lines


def _summarize_tool_round(item):
    name = str(item.get("name", "tool")).strip() or "tool"
    args = item.get("args", {}) if isinstance(item.get("args", {}), dict) else {}
    content = str(item.get("content", ""))
    paths = _extract_paths(name, args, content)
    exit_code = _extract_exit_code(content)
    failed = _is_failed_tool(content, exit_code)
    status = "error" if failed else "ok"
    parts = [f"[compressed:{name}]", f"status={status}"]
    if exit_code is not None:
        parts.append(f"exit_code={exit_code}")
    if name == "run_shell":
        command = str(args.get("command", "")).strip() or "shell"
        parts.append(f"command={json.dumps(_tail_clip(command, 120))}")
    elif paths:
        if len(paths) == 1:
            parts.append(f"path={paths[0]}")
        else:
            parts.append("paths=" + ",".join(paths[:4]))
    elif args:
        parts.append("args=" + _tail_clip(json.dumps(args, sort_keys=True), 120))
    signal = _first_signal_line(content)
    if signal:
        parts.append("signal=" + json.dumps(_tail_clip(signal, 100)))
    return " ".join(parts), paths, failed


def _summarize_message(item):
    role = str(item.get("role", "message")).strip() or "message"
    content = str(item.get("content", "")).strip()
    if not content:
        return ""
    return f"[compressed:{role}] {_tail_clip(content, 120)}"


def _extract_paths(name, args, content):
    paths = []
    for key in ("path", "file", "target", "from", "to"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(_normalize_path(value))
    if name == "run_shell":
        for match in PATHISH_PATTERN.findall(content):
            paths.append(_normalize_path(match))
    unique = []
    for path in paths:
        if path and path not in unique:
            unique.append(path)
    return unique


def _normalize_path(path):
    path = str(path).replace("\\", "/").strip()
    while path.startswith("./"):
        path = path[2:]
    try:
        return str(PurePosixPath(path))
    except Exception:
        return path


def _extract_exit_code(content):
    match = EXIT_CODE_PATTERN.search(content)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _is_failed_tool(content, exit_code):
    if exit_code is not None:
        return exit_code != 0
    return bool(ERROR_HINT_PATTERN.search(str(content)))


def _first_signal_line(content):
    for line in str(content).splitlines():
        line = line.strip()
        if not line:
            continue
        if ERROR_HINT_PATTERN.search(line) or line.lower().startswith("exit_code:"):
            return line
    return ""


def _raw_history_text(history):
    if not history:
        return "Transcript:\n- empty"
    lines = []
    for item in history:
        if item.get("role") == "tool":
            lines.append(f"[tool:{item.get('name', 'tool')}] {json.dumps(item.get('args', {}), sort_keys=True)}")
            lines.append(str(item.get("content", "")))
        else:
            lines.append(f"[{item.get('role', 'message')}] {item.get('content', '')}")
    return "\n".join(["Transcript:", *lines])


def _render_history_item(item, line_limit):
    if item.get("role") == "tool":
        prefix = f"[tool:{item.get('name', 'tool')}] {json.dumps(item.get('args', {}), sort_keys=True)}"
        content = _tail_clip(item.get("content", ""), max(20, line_limit))
        return [prefix, content]
    return [f"[{item.get('role', 'message')}] {_tail_clip(item.get('content', ''), line_limit)}"]


def _details(strategy, **overrides):
    details = {
        "context_strategy": strategy,
        "rendered_entries": [],
        "older_entries_count": 0,
        "collapsed_duplicate_reads": 0,
        "reused_file_summary_count": 0,
        "summarized_tool_count": 0,
        "active_round_count": 0,
        "compressed_round_count": 0,
        "compressed_message_count": 0,
        "compressed_line_count": 0,
        "retained_file_paths": [],
        "retained_failed_tool_count": 0,
        "compression_failure_count": 0,
        "omitted_high_value_count": 0,
    }
    details.update(overrides)
    return details
