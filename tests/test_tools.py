import subprocess
from pathlib import Path

from repopilot.tool_context import ToolContext
from repopilot.tools import build_tool_registry, decode_process_output, tool_delegate, tool_read_file, tool_run_shell, tool_search


def test_tool_context_supports_file_tools_without_full_repopilot(tmp_path):
    (tmp_path / "sample.txt").write_text("alpha\n", encoding="utf-8")
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: (tmp_path / raw_path).resolve(),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=0,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
    )

    result = tool_read_file(context, {"path": "sample.txt", "start": 1, "end": 1})

    assert "# sample.txt" in result
    assert "alpha" in result


def test_delegate_uses_context_spawn_without_runtime_import(tmp_path):
    calls = []
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: Path(tmp_path / raw_path),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=0,
        max_depth=1,
        spawn_delegate=lambda args: calls.append(args) or "delegate_result:\nDone",
    )

    result = tool_delegate(context, {"task": "inspect README.md", "max_steps": 2})

    assert result == "delegate_result:\nDone"
    assert calls == [{"task": "inspect README.md", "max_steps": 2}]


def test_build_tool_registry_binds_runners_to_tool_context(tmp_path):
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: Path(tmp_path / raw_path),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=1,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
    )

    tools = build_tool_registry(context)

    assert "read_file" in tools
    assert "delegate" not in tools


def test_read_file_defaults_to_400_line_window(tmp_path):
    (tmp_path / "sample.txt").write_text("\n".join(f"line {index}" for index in range(1, 451)), encoding="utf-8")
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: (tmp_path / raw_path).resolve(),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=0,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
    )

    result = tool_read_file(context, {"path": "sample.txt"})

    assert " 400: line 400" in result
    assert " 401: line 401" not in result


def test_run_shell_decodes_utf8_bytes_without_windows_locale_failure(tmp_path, monkeypatch):
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: (tmp_path / raw_path).resolve(),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=0,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
    )

    def fake_run(*args, **kwargs):
        assert kwargs["text"] is False
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="\u6570\u636e\u6a21\u578b\n".encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr("repopilot.tools.subprocess.run", fake_run)

    result = tool_run_shell(context, {"command": "fake", "timeout": 20})

    assert result.data["exit_code"] == 0
    assert result.data["stdout"] == "\u6570\u636e\u6a21\u578b"
    assert "\u6570\u636e\u6a21\u578b" in result.content


def test_search_decodes_rg_utf8_bytes_without_windows_locale_failure(tmp_path, monkeypatch):
    context = ToolContext(
        root=tmp_path,
        path_resolver=lambda raw_path: (tmp_path / raw_path).resolve(),
        shell_env_provider=lambda: {"PWD": str(tmp_path)},
        depth=0,
        max_depth=1,
        spawn_delegate=lambda args: "unused",
    )

    def fake_run(*args, **kwargs):
        assert kwargs["text"] is False
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="src/User.java:1:\u7528\u6237\u6a21\u578b\n".encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr("repopilot.tools.shutil.which", lambda command: "rg")
    monkeypatch.setattr("repopilot.tools.subprocess.run", fake_run)

    result = tool_search(context, {"pattern": "User", "path": "."})

    assert "\u7528\u6237\u6a21\u578b" in result


def test_decode_process_output_replaces_undecodable_bytes(monkeypatch):
    monkeypatch.setattr("repopilot.tools.locale.getpreferredencoding", lambda do_setlocale=False: "ascii")

    assert decode_process_output(b"\xff") == "\ufffd"
