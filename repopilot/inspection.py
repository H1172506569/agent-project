"""Deterministic inspect/review mode."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .findings import parse_findings, render_findings
from .runtime import RepoPilot
from .workspace import IGNORED_PATH_NAMES, clip, now

INSPECTION_ALLOWED_TOOLS = ("read_file", "search")
DEFAULT_INSPECTION_MAX_FILES = 20


def _normalize_relative(root, path):
    candidate = Path(path)
    full = candidate if candidate.is_absolute() else Path(root) / candidate
    resolved = full.resolve()
    root = Path(root).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"inspection path escapes workspace: {path}") from exc
    return relative.as_posix()


def select_inspection_files(root, paths=None, max_files=DEFAULT_INSPECTION_MAX_FILES):
    root = Path(root).resolve()
    selected = []

    def add(path):
        rel = _normalize_relative(root, path)
        full = root / rel
        if not full.is_file():
            return
        if any(part in IGNORED_PATH_NAMES for part in Path(rel).parts):
            return
        if rel not in selected:
            selected.append(rel)

    if paths:
        for path in paths:
            add(path)
        return selected[:max_files]

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in result.stdout.splitlines():
            if line.strip():
                add(line.strip())
    except Exception:
        pass
    return selected[:max_files]


def build_inspection_prompt(path):
    return (
        f"Inspect {path} for concrete correctness, safety, maintainability, or test-risk issues. "
        "Use read_file before making claims. Return zero or more findings as "
        "<finding>{JSON}</finding> blocks. Each JSON object must include path, line, "
        "severity, category, snippet, rationale, and suggestion. If there are no issues, "
        "return <final>No findings.</final>."
    )


def run_inspection(agent, paths=None, max_files=DEFAULT_INSPECTION_MAX_FILES, max_steps=3):
    selected_files = select_inspection_files(agent.root, paths=paths, max_files=max_files)
    findings = []
    file_results = []

    for path in selected_files:
        child = RepoPilot(
            model_client=agent.model_client,
            workspace=agent.workspace,
            session_store=agent.session_store,
            run_store=agent.run_store,
            approval_policy="never",
            max_steps=max_steps,
            max_new_tokens=agent.max_new_tokens,
            depth=agent.depth + 1,
            max_depth=agent.max_depth,
            read_only=True,
            secret_env_names=agent.secret_env_names,
            shell_env_allowlist=agent.shell_env_allowlist,
            allowed_tools=INSPECTION_ALLOWED_TOOLS,
        )
        prompt = build_inspection_prompt(path)
        try:
            answer = child.ask(prompt)
            parsed = parse_findings(answer, default_path=path)
            findings.extend(parsed)
            file_results.append(
                {
                    "path": path,
                    "status": "completed",
                    "run_id": child.current_task_state.run_id if child.current_task_state else "",
                    "finding_count": len(parsed),
                }
            )
        except Exception as exc:
            file_results.append(
                {
                    "path": path,
                    "status": "failed",
                    "run_id": child.current_task_state.run_id if child.current_task_state else "",
                    "error": clip(str(exc), 500),
                    "finding_count": 0,
                }
            )

    report = {
        "schema_version": 1,
        "mode": "inspect",
        "created_at": now(),
        "selected_files": selected_files,
        "file_results": file_results,
        "findings": [finding.to_dict() for finding in findings],
        "summary": {
            "selected_count": len(selected_files),
            "completed_count": sum(1 for item in file_results if item.get("status") == "completed"),
            "failed_count": sum(1 for item in file_results if item.get("status") == "failed"),
            "finding_count": len(findings),
            "anchored_finding_count": sum(1 for finding in findings if finding.line >= 1),
        },
        "rendered": render_findings(findings),
    }
    output_dir = agent.root / ".repopilot" / "inspections"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"inspection-{report['created_at'].replace(':', '').replace('.', '-')}.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
