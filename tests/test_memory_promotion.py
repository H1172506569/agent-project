import json

from repopilot import FakeModelClient, RepoPilot, SessionStore, WorkspaceContext
from repopilot.memory_promotion import (
    MemoryCandidate,
    MemoryPromotionPolicy,
    event_evidence_id,
    generate_memory_candidates,
    memory_promotion_metrics,
)
from repopilot.features.memory import LayeredMemory


def build_memory(tmp_path):
    return LayeredMemory(workspace_root=tmp_path)


def test_save_policy_promotes_stable_actionable_verifiable_candidate(tmp_path):
    memory = build_memory(tmp_path)
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "Use pytest."}}]
    candidate = MemoryCandidate(
        text="Project verification can run with pytest.",
        kind="dependency_fact",
        evidence_event_ids=(event_evidence_id(0),),
    )

    decision = MemoryPromotionPolicy().evaluate(candidate, memory, events=events)

    assert decision.promote
    assert decision.score == 4
    assert decision.reason == "save_passed"


def test_save_policy_rejects_transient_and_sensitive_candidates(tmp_path):
    memory = build_memory(tmp_path)
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]
    policy = MemoryPromotionPolicy()

    transient = policy.evaluate(
        MemoryCandidate(
            text="Next step is reading tools.py.",
            kind="project_convention",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )
    sensitive = policy.evaluate(
        MemoryCandidate(
            text="Dependency API key is sk-live-secret-abc123.",
            kind="dependency_fact",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )

    assert transient.reject
    assert transient.reason == "transient"
    assert sensitive.reject
    assert sensitive.reason == "sensitive"


def test_save_policy_suppresses_duplicate_and_detects_conflict(tmp_path):
    memory = build_memory(tmp_path)
    memory.promote_durable([
        ("dependency-facts", "Project should not use pytest for tests."),
        ("project-conventions", "Project uses structured tool results."),
    ])
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]
    policy = MemoryPromotionPolicy()

    duplicate = policy.evaluate(
        MemoryCandidate(
            text="Project uses structured tool results.",
            kind="project_convention",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )
    conflict = policy.evaluate(
        MemoryCandidate(
            text="Project should use pytest for tests.",
            kind="dependency_fact",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )

    assert duplicate.reject
    assert duplicate.reason == "duplicate"
    assert conflict.pending_confirmation
    assert conflict.reason == "conflict"


def test_candidate_generation_extracts_user_preference_and_pytest_fact():
    events = [
        {"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "以后都用中文解释。"}},
        {
            "source": "trace",
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": "pyproject.toml"},
            "result": "[tool.pytest.ini_options]\naddopts = '-q'",
        },
    ]

    candidates = generate_memory_candidates(events)

    assert [candidate.kind for candidate in candidates] == ["user_preference", "dependency_fact"]
    assert candidates[0].evidence_event_ids == ("event:0",)
    assert candidates[1].evidence_event_ids == ("event:1",)


def test_agent_loop_promotes_memory_candidates_into_event_log_and_report(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".repopilot" / "sessions")
    agent = RepoPilot(
        model_client=FakeModelClient(["<final>Done.</final>"]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
    )

    assert agent.ask("以后都用中文解释。") == "Done."

    events = agent.run_store.load_events(agent.current_task_state.run_id)
    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))
    memory_topic = tmp_path / ".repopilot" / "memory" / "topics" / "user-preferences.md"

    assert any(event.get("event") == "memory_candidate_created" for event in events)
    assert any(event.get("event") == "memory_promoted" for event in events)
    assert report["memory_promotion_metrics"]["candidate_count"] == 1
    assert report["memory_promotion_metrics"]["promoted_count"] == 1
    assert report["memory_promotion_metrics"]["evidence_coverage"] == 1.0
    assert "以后都用中文解释。" in memory_topic.read_text(encoding="utf-8")


def test_memory_promotion_metrics_report_policy_outcomes(tmp_path):
    memory = build_memory(tmp_path)
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]
    candidates = [
        MemoryCandidate("Project verification can run with pytest.", "dependency_fact", evidence_event_ids=(event_evidence_id(0),)),
        MemoryCandidate("Dependency API key is sk-live-secret-abc123.", "dependency_fact", evidence_event_ids=(event_evidence_id(0),)),
    ]
    policy = MemoryPromotionPolicy()
    decisions = [policy.evaluate(candidate, memory, events=events) for candidate in candidates]

    metrics = memory_promotion_metrics(candidates, decisions)

    assert metrics["candidate_count"] == 2
    assert metrics["promoted_count"] == 1
    assert metrics["rejected_sensitive_candidate_count"] == 1
    assert metrics["promotion_precision_proxy"] == 1.0
