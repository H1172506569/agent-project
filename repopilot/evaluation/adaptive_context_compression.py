"""Adaptive context-compression scheduler experiment."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .. import FakeModelClient, RepoPilot, SessionStore, WorkspaceContext
from ..context_manager import ContextManager


def run_adaptive_context_compression_experiment(output_dir=None):
    scenarios = [
        _run_no_trigger_scenario(),
        _run_async_threshold_scenario(),
        _run_sync_threshold_scenario(),
        _run_persisted_reuse_scenario(),
    ]
    summary = {
        "scenario_count": len(scenarios),
        "async_scheduled_count": sum(1 for item in scenarios if item["scheduler_action"] == "async_scheduled"),
        "sync_compressed_count": sum(1 for item in scenarios if item["scheduler_action"] == "sync_compressed"),
        "persisted_reuse_count": sum(1 for item in scenarios if item.get("persisted_summary_used")),
        "sync_prompt_reduction_rate": _rate_for_scenario(scenarios, "sync_80"),
    }
    result = {"summary": summary, "scenarios": scenarios}
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "adaptive-context-compression-experiment.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (output_dir / "adaptive-context-compression-experiment.md").write_text(
            render_adaptive_experiment_markdown(result),
            encoding="utf-8",
        )
    return result


def render_adaptive_experiment_markdown(result):
    lines = [
        "# Adaptive Context Compression Experiment",
        "",
        "## Setup",
        "",
        "- Feature flag: `adaptive_context_compression=True`.",
        "- Async threshold: 60% prompt budget usage.",
        "- Sync threshold: 80% prompt budget usage.",
        "- Compression backend: deterministic tool-round compressor for runtime stability.",
        "",
        "## Results",
        "",
        "| Scenario | Usage before | Action | Prompt before | Prompt after | Summary status | Persisted summary used | Current request preserved |",
        "| --- | ---: | --- | ---: | ---: | --- | --- | --- |",
    ]
    for row in result["scenarios"]:
        lines.append(
            "| {scenario} | {usage_ratio_before:.1%} | {scheduler_action} | {prompt_chars_before} | {prompt_chars_after} | {summary_status} | {persisted_summary_used} | {current_request_preserved} |".format(**row)
        )
    summary = result["summary"]
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Async compression scheduled scenarios: {summary['async_scheduled_count']}.",
            f"- Sync compression scenarios: {summary['sync_compressed_count']}.",
            f"- Persisted summary reuse scenarios: {summary['persisted_reuse_count']}.",
            f"- Sync prompt reduction rate: {summary['sync_prompt_reduction_rate']:.1%}.",
            "",
            "## Resume-Safe Wording",
            "",
            "- Added an adaptive context-compression scheduler with 60% async pre-compression and 80% sync compression thresholds; compressed history summaries are persisted in session state and reused by later prompt builds.",
        ]
    )
    return "\n".join(lines) + "\n"


def _rate_for_scenario(rows, scenario):
    for row in rows:
        if row["scenario"] == scenario and row["prompt_chars_before"]:
            return round((row["prompt_chars_before"] - row["prompt_chars_after"]) / row["prompt_chars_before"], 4)
    return 0.0


def _build_agent(root, total_budget, history_budget):
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(root)
    agent = RepoPilot(
        model_client=FakeModelClient([]),
        workspace=workspace,
        session_store=SessionStore(root / ".repopilot" / "sessions"),
        approval_policy="auto",
        feature_flags={"adaptive_context_compression": True, "tool_round_compression": False},
    )
    agent.prefix = "P" * 80
    agent.context_manager = ContextManager(
        agent,
        total_budget=total_budget,
        section_budgets={"prefix": 80, "project_rules": 0, "memory": 40, "relevant_memory": 20, "history": history_budget},
        section_floors={"prefix": 20, "project_rules": 0, "memory": 20, "relevant_memory": 10, "history": 100},
    )
    return agent


def _record_tool(agent, name, path, content, minute):
    args = {"path": path} if name == "read_file" else {"command": path}
    agent.record(
        {
            "role": "tool",
            "name": name,
            "args": args,
            "content": content,
            "created_at": f"2026-04-07T09:{minute:02d}:00+00:00",
        }
    )


def _scenario_row(scenario, prompt, metadata, state=None, prompt_before=None):
    scheduler = metadata.get("context_compression_scheduler", {})
    history = metadata.get("history", {})
    state = state or {}
    request = metadata.get("current_request", {}).get("text", "")
    return {
        "scenario": scenario,
        "usage_ratio_before": float(scheduler.get("usage_ratio", 0.0)),
        "scheduler_action": scheduler.get("action", "none"),
        "prompt_chars_before": int(scheduler.get("before_prompt_chars", prompt_before or len(prompt))),
        "prompt_chars_after": int(scheduler.get("after_prompt_chars", len(prompt))),
        "summary_status": state.get("status", "none"),
        "summary_mode": state.get("mode", ""),
        "summary_rendered_chars": int(state.get("rendered_chars", 0) or 0),
        "persisted_summary_used": bool(history.get("persisted_summary_used", False)),
        "current_request_preserved": bool(request and prompt.endswith(request)),
    }


def _run_no_trigger_scenario():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _build_agent(Path(tmp) / "no_trigger", total_budget=1400, history_budget=220)
        _record_tool(agent, "read_file", "src/small.py", "small\n", 1)
        prompt, metadata = agent._build_prompt_and_metadata("short request")
        return _scenario_row("no_trigger", prompt, metadata, agent.session.get("context_compression", {}))


def _run_async_threshold_scenario():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _build_agent(Path(tmp) / "async_60", total_budget=900, history_budget=430)
        for index in range(4):
            _record_tool(agent, "read_file", f"src/async_{index}.py", "A" * 150, index)
        prompt, metadata = agent._build_prompt_and_metadata("trigger async compression")
        state = agent.wait_for_context_compression(timeout=3)
        row = _scenario_row("async_60", prompt, metadata, state)
        next_prompt, next_metadata = agent._build_prompt_and_metadata("reuse async summary")
        row["next_prompt_chars"] = len(next_prompt)
        row["next_persisted_summary_used"] = bool(next_metadata.get("history", {}).get("persisted_summary_used", False))
        return row


def _run_sync_threshold_scenario():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _build_agent(Path(tmp) / "sync_80", total_budget=900, history_budget=620)
        for index in range(10):
            _record_tool(agent, "read_file", f"src/sync_{index}.py", "S" * 260, index)
        prompt, metadata = agent._build_prompt_and_metadata("sync compression must preserve me")
        return _scenario_row("sync_80", prompt, metadata, agent.session.get("context_compression", {}))


def _run_persisted_reuse_scenario():
    with tempfile.TemporaryDirectory() as tmp:
        agent = _build_agent(Path(tmp) / "reuse", total_budget=900, history_budget=520)
        for index in range(6):
            _record_tool(agent, "read_file", f"src/base_{index}.py", "B" * 220, index)
        state = agent._run_context_compression(mode="sync", trigger_ratio=0.9, history_budget=420)
        _record_tool(agent, "run_shell", "pytest -q", "NEW_TAIL_RESULT\nexit_code: 0\n", 20)
        prompt, metadata = agent._build_prompt_and_metadata("reuse persisted summary")
        return _scenario_row("persisted_reuse", prompt, metadata, state)
