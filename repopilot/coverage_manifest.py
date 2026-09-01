"""Coverage manifest projection for one RepoPilot run."""

from __future__ import annotations

import re

VERIFY_COMMAND_PATTERN = re.compile(
    r"(?i)\b(pytest|unittest|ruff|mypy|npm\s+test|pnpm\s+test|yarn\s+test|cargo\s+test|go\s+test|mvn\s+test|gradle\s+test)\b"
)


def _add_unique(items, value):
    text = str(value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.strip("/")
    if text and text not in items:
        items.append(text)


def _extend_unique(items, values):
    for value in values or []:
        _add_unique(items, value)


def _tool_path(event):
    args = event.get("args") or {}
    if isinstance(args, dict):
        return args.get("path", "")
    return ""


def is_verification_command(command):
    return bool(VERIFY_COMMAND_PATTERN.search(str(command or "")))


def terminal_state_from_task(task_state, failed_files):
    status = str(task_state.get("status", "")).strip()
    if status == "completed" and failed_files:
        return "partial"
    if status == "completed":
        return "complete"
    if status == "failed":
        return "failed"
    if status == "stopped":
        return "partial"
    return status or "unknown"


def build_coverage_manifest(events, task_state):
    planned_files = []
    inspected_files = []
    modified_files = []
    verified_files = []
    failed_files = []
    skipped_files = []
    verification_commands = []
    failed_tools = []

    for event in events:
        event_name = event.get("event")
        if event_name == "prompt_built":
            prompt_metadata = event.get("prompt_metadata") or {}
            project_rules = prompt_metadata.get("project_rules") or {}
            _extend_unique(planned_files, project_rules.get("candidate_paths", []))
            for path in project_rules.get("excluded_paths", []) or []:
                normalized = str(path or "").strip().replace("\\", "/")
                if normalized:
                    skipped_files.append({"path": normalized, "reason": "project_rules_exclude"})
            continue

        if event_name != "tool_executed":
            continue

        name = str(event.get("name", "")).strip()
        status = str(event.get("tool_status", "")).strip() or "unknown"
        path = _tool_path(event)
        affected_paths = list(event.get("affected_paths", []) or [])

        if path:
            _add_unique(planned_files, path)
        _extend_unique(planned_files, affected_paths)

        if name == "read_file" and path and status == "ok":
            _add_unique(inspected_files, path)
        elif name == "search" and path and status == "ok":
            _add_unique(inspected_files, path)

        if name in {"write_file", "patch_file"} and status in {"ok", "partial_success"}:
            _extend_unique(modified_files, affected_paths or [path])
        elif name == "run_shell" and event.get("workspace_changed"):
            _extend_unique(modified_files, affected_paths)

        if name == "run_shell":
            args = event.get("args") or {}
            command = args.get("command", "") if isinstance(args, dict) else ""
            if is_verification_command(command):
                verification_commands.append(
                    {
                        "command": str(command),
                        "status": status,
                        "exit_code": event.get("exit_code"),
                    }
                )
                if status == "ok":
                    _extend_unique(verified_files, modified_files)

        if status in {"error", "partial_success", "rejected"}:
            failed_record = {
                "tool": name,
                "status": status,
                "error_code": str(event.get("tool_error_code", "")),
                "paths": [],
            }
            if affected_paths:
                _extend_unique(failed_record["paths"], affected_paths)
            elif path:
                _add_unique(failed_record["paths"], path)
            failed_tools.append(failed_record)
            for failed_path in failed_record["paths"]:
                failed_files.append(
                    {
                        "path": failed_path,
                        "tool": name,
                        "status": status,
                        "error_code": failed_record["error_code"],
                    }
                )

    terminal_state = terminal_state_from_task(task_state, failed_files)
    planned_count = len(planned_files)
    modified_count = len(modified_files)
    return {
        "schema_version": 1,
        "terminal_state": terminal_state,
        "planned_files": planned_files,
        "inspected_files": inspected_files,
        "modified_files": modified_files,
        "verified_files": verified_files,
        "failed_files": failed_files,
        "skipped_files": skipped_files,
        "verification_commands": verification_commands,
        "failed_tools": failed_tools,
        "metrics": {
            "planned_count": planned_count,
            "inspected_count": len(inspected_files),
            "modified_count": modified_count,
            "verified_count": len(verified_files),
            "failed_count": len(failed_files),
            "skipped_count": len(skipped_files),
            "file_coverage_rate": (len(inspected_files) / planned_count) if planned_count else 0.0,
            "verification_rate": (len(verified_files) / modified_count) if modified_count else 0.0,
        },
    }
