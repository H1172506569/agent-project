import io
import time

from repopilot.terminal_feedback import ThinkingSpinner, tool_status_label


class FakeTTY(io.StringIO):
    encoding = "utf-8"

    def __init__(self):
        super().__init__()
        self.flush_count = 0

    def isatty(self):
        return True

    def flush(self):
        self.flush_count += 1


class FakePipe(io.StringIO):
    encoding = "utf-8"

    def isatty(self):
        return False


def test_thinking_spinner_writes_and_clears_for_tty():
    stream = FakeTTY()

    with ThinkingSpinner(stream=stream, interval=0.01):
        time.sleep(0.04)

    output = stream.getvalue()
    assert "Thinking" in output
    assert "\r\x1b[2K" in output
    assert output.endswith("\r\x1b[2K")
    assert stream.flush_count > 0




def test_thinking_spinner_can_persist_status_line_for_completed_tools():
    stream = FakeTTY()

    with ThinkingSpinner("Tool read_file: reading README.md lines 1-1", stream=stream, interval=0.01, persist_on_exit=True):
        time.sleep(0.03)

    output = stream.getvalue()
    assert "Tool read_file: reading README.md lines 1-1" in output
    assert output.endswith("Tool read_file: reading README.md lines 1-1\n")

def test_thinking_spinner_is_silent_for_non_tty():
    stream = FakePipe()

    with ThinkingSpinner(stream=stream, interval=0.01):
        time.sleep(0.02)

    assert stream.getvalue() == ""


def test_thinking_spinner_falls_back_to_ascii_when_circle_frames_are_not_encodable():
    stream = FakeTTY()
    stream.encoding = "ascii"
    spinner = ThinkingSpinner(stream=stream, interval=0.01)

    assert spinner._frames == ["|", "/", "-", "\\"]

def test_tool_status_label_describes_common_tools():
    assert tool_status_label("read_file", {"path": "README.md", "start": 1, "end": 20}) == "Tool read_file: reading README.md lines 1-20"
    assert tool_status_label("list_files", {"path": "src"}) == "Tool list_files: listing src"
    assert tool_status_label("search", {"pattern": "class AgentLoop", "path": "repopilot"}) == "Tool search: searching class AgentLoop in repopilot"
    assert tool_status_label("run_shell", {"command": "python -m pytest -q"}) == "Tool run_shell: running python -m pytest -q"
    assert tool_status_label("write_file", {"path": "notes.txt"}) == "Tool write_file: writing notes.txt"
    assert tool_status_label("patch_file", {"path": "repopilot/runtime.py"}) == "Tool patch_file: patching repopilot/runtime.py"
    assert tool_status_label("delegate", {"task": "inspect README.md"}) == "Tool delegate: delegating inspect README.md"


def test_tool_status_label_clips_long_values():
    label = tool_status_label("run_shell", {"command": "x" * 200})

    assert label.startswith("Tool run_shell: running ")
    assert len(label) < 110
    assert label.endswith("...")




