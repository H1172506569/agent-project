import json

import pytest

from repopilot import FakeModelClient, RepoPilot, SessionStore, WorkspaceContext
from repopilot.agent_loop import AgentLoop
from repopilot.event_log import project_history, project_trace


def build_agent(tmp_path, outputs, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".repopilot" / "sessions")
    return RepoPilot(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def test_agent_loop_runs_same_control_flow_as_repopilot_ask(tmp_path):
    (tmp_path / "hello.txt").write_text("alpha\n", encoding="utf-8")
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":1}}</tool>',
            "<final>Done.</final>",
        ],
    )

    answer = AgentLoop(agent).run("Inspect hello.txt")

    assert answer == "Done."
    assert agent.current_task_state.status == "completed"
    assert agent.run_store.report_path(agent.current_task_state.run_id).exists()


def test_repopilot_ask_delegates_to_agent_loop(tmp_path):
    agent = build_agent(tmp_path, ["<final>Facade works.</final>"])

    assert agent.ask("Use facade") == "Facade works."


def test_agent_loop_reserves_a_final_answer_after_tool_budget_is_exhausted(tmp_path):
    (tmp_path / "facts.txt").write_text("one\ntwo\nthree\nfour\nfive\nsix\n", encoding="utf-8")
    tool_outputs = [
        f'<tool>{{"name":"read_file","args":{{"path":"facts.txt","start":{line},"end":{line}}}}}</tool>'
        for line in range(1, 7)
    ]
    agent = build_agent(
        tmp_path,
        [*tool_outputs, "<final>All six facts were inspected.</final>"],
        max_steps=6,
    )

    answer = agent.ask("Inspect all facts and summarize them")

    assert answer == "All six facts were inspected."
    assert agent.current_task_state.status == "completed"
    assert agent.current_task_state.tool_steps == 6
    assert agent.current_task_state.attempts == 7
    trace_path = agent.run_store.trace_path(agent.current_task_state)
    trace_events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert any(
        event["event"] == "model_requested" and event.get("purpose") == "finalization"
        for event in trace_events
    )


def test_agent_loop_persists_model_failure_before_reraising(tmp_path):
    class FailingModelClient:
        supports_prompt_cache = False
        last_completion_metadata = {
            "stop_reason": "max_tokens",
            "content_block_types": ["thinking"],
        }

        def complete(self, *args, **kwargs):
            raise RuntimeError(
                "Anthropic-compatible response ended before a text block "
                "(stop_reason=max_tokens, content_types=thinking)"
            )

    agent = build_agent(tmp_path, [])
    agent.model_client = FailingModelClient()

    with pytest.raises(RuntimeError, match="ended before a text block"):
        agent.ask("Inspect the tests")

    state = agent.current_task_state
    assert state.status == "failed"
    assert state.stop_reason == "model_error"
    assert state.attempts == 1
    assert agent.run_store.task_state_path(state).exists()
    assert agent.run_store.report_path(state).exists()
    report = agent.run_store.load_report(state.run_id)
    assert report["stop_reason"] == "model_error"
    assert report["prompt_metadata"]["stop_reason"] == "max_tokens"


def test_agent_loop_event_log_projects_trace_and_history(tmp_path):
    (tmp_path / "hello.txt").write_text("alpha\n", encoding="utf-8")
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"hello.txt","start":1,"end":1}}</tool>',
            "<final>Done.</final>",
        ],
    )

    assert agent.ask("Inspect hello.txt") == "Done."

    state = agent.current_task_state
    events = agent.run_store.load_events(state.run_id)
    trace_events = [
        json.loads(line)
        for line in agent.run_store.trace_path(state.run_id).read_text(encoding="utf-8").splitlines()
    ]
    report = agent.run_store.load_report(state.run_id)

    assert project_trace(events) == trace_events
    assert project_history(events) == agent.session["history"][-3:]
    assert report["event_log_metrics"]["event_count"] == len(events)
    assert report["event_log_metrics"]["trace_event_count"] == len(trace_events)
    assert report["event_log_metrics"]["history_event_count"] == 3
    assert report["event_log_metrics"]["memory_event_count"] >= 1



def test_prompt_history_is_projected_from_event_log_not_session_cache(tmp_path):
    agent = build_agent(tmp_path, ["<final>Done.</final>"])
    agent.session["history"].append(
        {
            "role": "assistant",
            "content": "SESSION_ONLY_POISON_SHOULD_NOT_REACH_PROMPT",
            "created_at": "2026-04-07T08:00:00+00:00",
        }
    )
    agent.session_store.save(agent.session)

    assert agent.ask("Use only event log history") == "Done."

    prompt = agent.model_client.prompts[0]
    assert "SESSION_ONLY_POISON_SHOULD_NOT_REACH_PROMPT" not in prompt
    assert "Use only event log history" in prompt
    assert agent.last_prompt_metadata["history"]["source"] == "event_log"
    events = agent.run_store.load_events(agent.current_task_state.run_id)
    report = agent.run_store.load_report(agent.current_task_state.run_id)
    assert report["projected_history"] == project_history(events)
    assert report["history_source"] == "event_log"
    assert [item["content"] for item in project_history(events)] == ["Use only event log history", "Done."]
    assert all("SESSION_ONLY_POISON" not in item.get("content", "") for item in project_history(events))

def test_agent_loop_report_includes_coverage_manifest_from_event_log(tmp_path):
    (tmp_path / ".repopilot").mkdir(exist_ok=True)
    (tmp_path / ".repopilot" / "rules.json").write_text(
        '{"rules":[{"path":"notes.txt","rule":"Notes must stay concise."}]}',
        encoding="utf-8",
    )
    content_json = json.dumps("hello\n")
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":1}}</tool>',
            f'<tool>{{"name":"write_file","args":{{"path":"notes.txt","content":{content_json}}}}}</tool>',
            '<tool>{"name":"run_shell","args":{"command":"python -m pytest --version","timeout":20}}</tool>',
            "<final>Done.</final>",
        ],
        max_steps=4,
    )

    assert agent.ask("Read README.md, create notes.txt, then run python -m pytest --version") == "Done."

    report = agent.run_store.load_report(agent.current_task_state.run_id)
    manifest = report["coverage_manifest"]

    assert manifest["terminal_state"] == "complete"
    assert "README.md" in manifest["planned_files"]
    assert "notes.txt" in manifest["planned_files"]
    assert manifest["inspected_files"] == ["README.md"]
    assert manifest["modified_files"] == ["notes.txt"]
    assert manifest["verified_files"] == ["notes.txt"]
    assert manifest["verification_commands"][0]["command"] == "python -m pytest --version"
    assert manifest["metrics"]["verification_rate"] == 1.0
