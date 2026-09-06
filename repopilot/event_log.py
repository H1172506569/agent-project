"""Event log projections for RepoPilot runs."""

import json
from pathlib import Path


def load_events(path):
    event_path = Path(path)
    if not event_path.exists():
        return []
    return [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _without_source(event):
    hidden = {"source", "type", "version", "seq", "session_id", "run_id"}
    return {key: value for key, value in event.items() if key not in hidden}


def project_trace(events):
    return [_without_source(event) for event in events if event.get("source") == "trace"]


def project_history(events):
    """投影出模型看到的对话历史。

    这里把事件的 `seq` 一并带上（`event_seq`）：模型引用证据时报的就是这个编号，
    而它必须是**写入时固定在事件上的稳定 id**，不能是列表位置——位置会随过滤条件
    和新增事件类型整体错位。
    """
    history = []
    for event in events:
        if event.get("source") != "history":
            continue
        item = event.get("history")
        if isinstance(item, dict):
            item = dict(item)
            seq = event.get("seq")
            if seq is not None:
                item["event_seq"] = int(seq)
            history.append(item)
    return history


def event_log_metrics(events):
    trace_events = [event for event in events if event.get("source") == "trace"]
    history_events = [event for event in events if event.get("source") == "history"]
    memory_events = [event for event in events if event.get("source") == "memory"]
    structured_tool_results = [
        event
        for event in trace_events
        if event.get("event") == "tool_executed" and event.get("structured_data_keys")
    ]
    return {
        "event_count": len(events),
        "trace_event_count": len(trace_events),
        "history_event_count": len(history_events),
        "memory_event_count": len(memory_events),
        "structured_tool_result_count": len(structured_tool_results),
    }
