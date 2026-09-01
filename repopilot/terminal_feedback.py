"""Small terminal feedback helpers for interactive CLI runs."""

from __future__ import annotations

import sys
import threading
import time


class ThinkingSpinner:
    def __init__(self, label="Thinking", stream=None, interval=0.12, enabled=True, persist_on_exit=False):
        self.label = str(label or "Thinking")
        self.stream = stream or sys.stderr
        self.interval = float(interval)
        self.enabled = bool(enabled)
        self.persist_on_exit = bool(persist_on_exit)
        self._stop = threading.Event()
        self._thread = None
        self._width = 0
        self._clear_prefix = "\r\x1b[2K"
        self._frames = self._select_frames()

    def _select_frames(self):
        frames = ["◐", "◓", "◑", "◒"]
        encoding = getattr(self.stream, "encoding", None) or "utf-8"
        try:
            "".join(frames).encode(encoding)
            return frames
        except (LookupError, UnicodeEncodeError):
            return ["|", "/", "-", "\\"]

    def _active(self):
        return self.enabled and hasattr(self.stream, "isatty") and self.stream.isatty()

    def __enter__(self):
        if not self._active():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._thread is None:
            return False
        self._stop.set()
        self._thread.join(timeout=self.interval * 3)
        if self.persist_on_exit:
            self._persist()
        else:
            self._clear()
        return False

    def _spin(self):
        index = 0
        while not self._stop.is_set():
            text = f"{self.label} {self._frames[index % len(self._frames)]}"
            self._width = max(self._width, len(text))
            self.stream.write(self._clear_prefix + text)
            self.stream.flush()
            index += 1
            self._stop.wait(self.interval)

    def _clear(self):
        self.stream.write(self._clear_prefix)
        self.stream.flush()

    def _persist(self):
        self.stream.write(self._clear_prefix + self.label + "\n")
        self.stream.flush()


def thinking_spinner(label="Thinking", stream=None, enabled=True, persist_on_exit=False):
    return ThinkingSpinner(label=label, stream=stream, enabled=enabled, persist_on_exit=persist_on_exit)


def _clip_status_value(value, limit=80):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def tool_status_label(name, args=None):
    args = args if isinstance(args, dict) else {}
    name = str(name or "tool")
    prefix = f"Tool {name}:"
    if name == "list_files":
        return f"{prefix} listing {_clip_status_value(args.get('path', '.'))}"
    if name == "read_file":
        path = _clip_status_value(args.get("path", ""))
        start = args.get("start", 1)
        end = args.get("end", 400)
        return f"{prefix} reading {path} lines {start}-{end}" if path else f"{prefix} reading file"
    if name == "search":
        pattern = _clip_status_value(args.get("pattern", ""), limit=50)
        path = _clip_status_value(args.get("path", "."), limit=50)
        return f"{prefix} searching {pattern} in {path}" if pattern else f"{prefix} searching in {path}"
    if name == "run_shell":
        command = _clip_status_value(args.get("command", ""), limit=70)
        return f"{prefix} running {command}" if command else f"{prefix} running shell command"
    if name == "write_file":
        path = _clip_status_value(args.get("path", ""))
        return f"{prefix} writing {path}" if path else f"{prefix} writing file"
    if name == "patch_file":
        path = _clip_status_value(args.get("path", ""))
        return f"{prefix} patching {path}" if path else f"{prefix} patching file"
    if name == "delegate":
        task = _clip_status_value(args.get("task", ""), limit=80)
        return f"{prefix} delegating {task}" if task else f"{prefix} delegating task"
    return f"{prefix} running"

