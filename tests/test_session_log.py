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
    # 投影把事件的稳定 seq 一并带出来：模型引用证据时报的就是这个编号。
    assert project_history(events) == [{"role": "user", "content": "hello", "event_seq": 0}]
    assert project_trace(events) == [{"event": "run_started", "created_at": "2026-04-07T00:00:00+00:00"}]
    assert event_log_metrics(events) == {
        "event_count": 3,
        "trace_event_count": 1,
        "history_event_count": 1,
        "memory_event_count": 1,
        "structured_tool_result_count": 0,
    }


def _session(tmp_path, session_id="session_seq"):
    return {
        "id": session_id,
        "created_at": "2026-04-07T00:00:00+00:00",
        "workspace_root": str(tmp_path),
    }


def test_append_event_keeps_seq_monotonic_without_rereading_the_log(tmp_path, monkeypatch):
    """seq 走缓存计数器，但编号必须和逐条重算完全一致。"""
    store = SessionLogStore(tmp_path / ".repopilot" / "sessions")
    session = _session(tmp_path)

    store.append_event(session, {"source": "trace", "event": "run_started"})

    loads = []
    original = SessionLogStore.load_events
    monkeypatch.setattr(
        SessionLogStore,
        "load_events",
        lambda self, session_id: (loads.append(session_id), original(self, session_id))[1],
    )

    for index in range(5):
        store.append_event(session, {"source": "trace", "event": f"step_{index}"})

    events = original(store, session["id"])
    assert [event["seq"] for event in events] == [0, 1, 2, 3, 4, 5]
    # 5 次 append 一次日志都没有重读。
    assert loads == []


def test_append_event_recovers_seq_when_another_writer_appended(tmp_path):
    """缓存靠文件大小自检：别的写入者动过日志时回退到重建，编号不会撞。"""
    root = tmp_path / ".repopilot" / "sessions"
    session = _session(tmp_path)

    first = SessionLogStore(root)
    first.append_event(session, {"source": "trace", "event": "a"})

    other = SessionLogStore(root)
    other.append_event(session, {"source": "trace", "event": "b"})

    first.append_event(session, {"source": "trace", "event": "c"})

    events = first.load_events(session["id"])
    assert [event["event"] for event in events] == ["a", "b", "c"]
    assert [event["seq"] for event in events] == [0, 1, 2]


def test_fresh_store_continues_seq_from_existing_log(tmp_path):
    """新建的 store 打开已有日志时，从磁盘上的真实长度接着编号。"""
    root = tmp_path / ".repopilot" / "sessions"
    session = _session(tmp_path)

    warm = SessionLogStore(root)
    for index in range(3):
        warm.append_event(session, {"source": "trace", "event": f"warm_{index}"})

    cold = SessionLogStore(root)
    cold.append_event(session, {"source": "trace", "event": "cold"})

    events = cold.load_events(session["id"])
    assert [event["seq"] for event in events] == [0, 1, 2, 3]
    assert events[-1]["event"] == "cold"
