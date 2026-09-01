"""Append-only session event log persistence."""

import json
import threading
from pathlib import Path


class SessionLogStore:
    """Persist typed events for one RepoPilot session.

    The JSON session file keeps mutable caches/state. This log is the durable
    source for transcript, trace, memory, and per-run projections.
    """

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def session_dir(self, session_id):
        return self.root / str(session_id)

    def path(self, session_id):
        return self.session_dir(session_id) / "session.jsonl"

    def ensure_header(self, session):
        path = self.path(session["id"])
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "type": "session",
            "version": 1,
            "id": session["id"],
            "created_at": session.get("created_at", ""),
            "workspace_root": session.get("workspace_root", ""),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(header, sort_keys=True, ensure_ascii=True))
            handle.write("\n")
        return path

    def load_records(self, session_id):
        path = self.path(session_id)
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def load_events(self, session_id):
        events = []
        for record in self.load_records(session_id):
            if record.get("type") == "session":
                continue
            if record.get("type") == "event":
                events.append(dict(record))
            elif record.get("event"):
                events.append(dict(record))
        return events

    def load_run_events(self, session_id, run_id):
        run_id = str(run_id)
        return [
            event
            for event in self.load_events(session_id)
            if str(event.get("run_id", "")) == run_id
        ]

    def append_event(self, session, event, task_state=None):
        with self._lock:
            self.ensure_header(session)
            events = self.load_events(session["id"])
            payload = dict(event)
            payload.setdefault("type", "event")
            payload.setdefault("version", 1)
            payload["seq"] = len(events)
            payload["session_id"] = session["id"]
            if task_state is not None:
                payload.setdefault("run_id", str(getattr(task_state, "run_id", "")))
            else:
                payload.setdefault("run_id", "")
            path = self.path(session["id"])
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=True))
                handle.write("\n")
            return path
