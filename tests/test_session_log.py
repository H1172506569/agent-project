from repopilot.event_log import event_log_metrics, project_history, project_trace
from repopilot.session_log import SessionLogStore
from repopilot.task_state import TaskState


def test_session_log_appends_events_and_projects_views(tmp_path):
    store = SessionLogStore(tmp_path / ".repopilot" / "sessions")
    session = {
        "id": "session_001",
        "created_at": "2026-04-07T00:00:00+00:00",
        "workspace_root": str(tmp_path),
    }
    state = TaskState.create(run_id="run_005", task_id="task_005", user_request="Project session log.")

    store.append_event(
        session,
        {"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "hello"}},
        task_state=state,
    )
    store.append_event(
        session,
        {"source": "trace", "event": "run_started", "created_at": "2026-04-07T00:00:00+00:00"},
        task_state=state,
    )
    store.append_event(session, {"source": "memory", "event": "memory_updated", "tool_name": "read_file"})

    records = store.load_records(session["id"])
    events = store.load_events(session["id"])
    run_events = store.load_run_events(session["id"], state.run_id)

    assert records[0]["type"] == "session"
    assert records[0]["id"] == session["id"]
    assert [event["seq"] for event in events] == [0, 1, 2]
    assert [event["event"] for event in run_events] == ["history_recorded", "run_started"]
    assert project_history(events) == [{"role": "user", "content": "hello"}]
    assert project_trace(events) == [{"event": "run_started", "created_at": "2026-04-07T00:00:00+00:00"}]
    assert event_log_metrics(events) == {
        "event_count": 3,
        "trace_event_count": 1,
        "history_event_count": 1,
        "memory_event_count": 1,
        "structured_tool_result_count": 0,
    }
