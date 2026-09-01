import repopilot.tool_executor as tool_executor_module
from repopilot import FakeModelClient, RepoPilot, SessionStore, WorkspaceContext
from repopilot.tool_executor import ToolExecutor, ToolExecutionResult
from repopilot.tools import ToolOutput


def build_agent(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".repopilot" / "sessions")
    return RepoPilot(
        model_client=FakeModelClient([]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
    )


def test_tool_executor_returns_content_and_metadata_without_side_channel(tmp_path):
    agent = build_agent(tmp_path)

    result = ToolExecutor(agent).execute("read_file", {"path": "README.md", "start": 1, "end": 1})

    assert isinstance(result, ToolExecutionResult)
    assert "# README.md" in result.content
    assert result.metadata["tool_status"] == "ok"
    assert result.metadata["read_only"] is True
    assert result.metadata["workspace_changed"] is False


def test_repopilot_run_tool_keeps_compatibility_metadata(tmp_path):
    agent = build_agent(tmp_path)

    content = agent.run_tool("read_file", {"path": "README.md", "start": 1, "end": 1})

    assert "# README.md" in content
    assert agent._last_tool_result_metadata["tool_status"] == "ok"


def test_run_shell_status_uses_structured_exit_code_not_result_text(tmp_path):
    agent = build_agent(tmp_path)
    agent.tools["run_shell"]["run"] = lambda args: ToolOutput(
        content="exit_code: 0\nstdout:\nlooks successful",
        data={"exit_code": 9, "stdout": "looks successful", "stderr": ""},
    )

    result = ToolExecutor(agent).execute("run_shell", {"command": "fake", "timeout": 20})

    assert result.content.startswith("exit_code: 0")
    assert result.data["exit_code"] == 9
    assert result.metadata["exit_code"] == 9
    assert result.metadata["tool_status"] == "error"
    assert result.metadata["tool_error_code"] == "tool_failed"
    assert result.metadata["structured_data_keys"] == ["exit_code", "stderr", "stdout"]

def test_tool_executor_reports_live_tool_status_label(tmp_path, monkeypatch):
    agent = build_agent(tmp_path)
    seen = []

    class CaptureSpinner:
        def __init__(self, label="Thinking", stream=None, enabled=True, persist_on_exit=False):
            del stream
            seen.append({"label": label, "enabled": enabled, "persist_on_exit": persist_on_exit})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tool_executor_module, "thinking_spinner", CaptureSpinner)

    result = ToolExecutor(agent).execute("read_file", {"path": "README.md", "start": 1, "end": 1})

    assert result.metadata["tool_status"] == "ok"
    assert seen == [{"label": "Tool read_file: reading README.md lines 1-1", "enabled": True, "persist_on_exit": True}]


def test_tool_executor_can_disable_live_tool_status(tmp_path, monkeypatch):
    agent = build_agent(tmp_path)
    agent.interactive_feedback = False
    seen = []

    class CaptureSpinner:
        def __init__(self, label="Thinking", stream=None, enabled=True, persist_on_exit=False):
            del stream
            seen.append({"label": label, "enabled": enabled, "persist_on_exit": persist_on_exit})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(tool_executor_module, "thinking_spinner", CaptureSpinner)

    ToolExecutor(agent).execute("read_file", {"path": "README.md", "start": 1, "end": 1})

    assert seen == [{"label": "Tool read_file: reading README.md lines 1-1", "enabled": False, "persist_on_exit": True}]





def test_repeated_read_file_same_effective_range_is_rejected(tmp_path):
    agent = build_agent(tmp_path)
    agent.record({"role": "tool", "name": "read_file", "args": {"path": "README.md"}, "content": "# README.md\n   1: demo", "created_at": "1"})

    result = ToolExecutor(agent).execute("read_file", {"path": "README.md", "start": 1, "end": 400})

    assert result.metadata["tool_status"] == "rejected"
    assert result.metadata["tool_error_code"] == "repeated_identical_call"
    assert result.content == "error: repeated identical tool call for read_file; read a new range instead, for example README.md lines 401-800"


def test_read_file_next_range_is_not_treated_as_repeat(tmp_path):
    agent = build_agent(tmp_path)
    (tmp_path / "README.md").write_text("\n".join(f"line {index}" for index in range(1, 451)), encoding="utf-8")
    agent.record({"role": "tool", "name": "read_file", "args": {"path": "README.md"}, "content": "# README.md\n   1: line 1", "created_at": "1"})

    result = ToolExecutor(agent).execute("read_file", {"path": "README.md", "start": 401, "end": 800})

    assert result.metadata["tool_status"] == "ok"
    assert " 401: line 401" in result.content


def test_repeated_list_files_same_effective_path_is_rejected_immediately(tmp_path):
    agent = build_agent(tmp_path)
    agent.record({"role": "tool", "name": "list_files", "args": {"path": "."}, "content": "[F] README.md", "created_at": "1"})

    result = ToolExecutor(agent).execute("list_files", {})

    assert result.metadata["tool_status"] == "rejected"
    assert result.metadata["tool_error_code"] == "repeated_identical_call"
    assert result.content == "error: repeated identical tool call for list_files; use a more specific directory or inspect a file instead"
