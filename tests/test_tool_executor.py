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
