import json

import pytest

from repopilot import FakeModelClient, RepoPilot, SessionStore, WorkspaceContext
from repopilot.inspection import build_inspection_prompt, run_inspection, select_inspection_files


def build_agent(tmp_path, outputs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".repopilot" / "sessions")
    return RepoPilot(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
    )


def test_select_inspection_files_is_deterministic_and_workspace_bound(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / ".repopilot").mkdir()
    (tmp_path / ".repopilot" / "state.py").write_text("ignore\n", encoding="utf-8")

    assert select_inspection_files(tmp_path, ["src/app.py", ".repopilot/state.py", "missing.py"]) == ["src/app.py"]

    with pytest.raises(ValueError, match="escapes workspace"):
        select_inspection_files(tmp_path, ["../outside.py"])


def test_run_inspection_uses_bounded_read_only_child_loop_and_writes_report(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    finding = {
        "path": "src/app.py",
        "line": 2,
        "severity": "low",
        "category": "maintainability",
        "snippet": "return 1",
        "rationale": "The return value is unexplained.",
        "suggestion": "Name the constant or add context.",
    }
    agent = build_agent(
        tmp_path,
        [
            '<tool>{"name":"read_file","args":{"path":"src/app.py","start":1,"end":80}}</tool>',
            f"<final><finding>{json.dumps(finding)}</finding></final>",
        ],
    )

    report = run_inspection(agent, paths=["src/app.py"], max_steps=2)

    assert report["mode"] == "inspect"
    assert report["selected_files"] == ["src/app.py"]
    assert report["summary"]["selected_count"] == 1
    assert report["summary"]["finding_count"] == 1
    assert report["summary"]["anchored_finding_count"] == 1
    assert report["findings"] == [finding]
    assert report["file_results"][0]["status"] == "completed"
    assert report["file_results"][0]["run_id"].startswith("run_")
    assert "LOW src/app.py:2" in report["rendered"]
    assert report["report_path"]


def test_build_inspection_prompt_requires_read_file_and_structured_finding():
    prompt = build_inspection_prompt("src/app.py")

    assert "Use read_file" in prompt
    assert "<finding>{JSON}</finding>" in prompt
    assert "src/app.py" in prompt
