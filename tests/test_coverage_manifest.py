from repopilot.coverage_manifest import build_coverage_manifest, is_verification_command


def test_coverage_manifest_projects_files_and_verification_from_events():
    events = [
        {
            "event": "prompt_built",
            "prompt_metadata": {
                "project_rules": {
                    "candidate_paths": ["repopilot/runtime.py", "tests/fixtures/sample.py"],
                    "excluded_paths": ["tests/fixtures/sample.py"],
                }
            },
        },
        {
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": "repopilot/runtime.py"},
            "tool_status": "ok",
            "affected_paths": [],
        },
        {
            "event": "tool_executed",
            "name": "patch_file",
            "args": {"path": "repopilot/runtime.py"},
            "tool_status": "ok",
            "affected_paths": ["repopilot/runtime.py"],
            "workspace_changed": True,
        },
        {
            "event": "tool_executed",
            "name": "run_shell",
            "args": {"command": "python -m pytest tests/test_runtime.py -q"},
            "tool_status": "ok",
            "exit_code": 0,
            "affected_paths": [],
            "workspace_changed": False,
        },
    ]

    manifest = build_coverage_manifest(events, {"status": "completed"})

    assert manifest["terminal_state"] == "complete"
    assert manifest["planned_files"] == ["repopilot/runtime.py", "tests/fixtures/sample.py"]
    assert manifest["inspected_files"] == ["repopilot/runtime.py"]
    assert manifest["modified_files"] == ["repopilot/runtime.py"]
    assert manifest["verified_files"] == ["repopilot/runtime.py"]
    assert manifest["skipped_files"] == [{"path": "tests/fixtures/sample.py", "reason": "project_rules_exclude"}]
    assert manifest["metrics"]["file_coverage_rate"] == 0.5
    assert manifest["metrics"]["verification_rate"] == 1.0


def test_coverage_manifest_records_failed_file_and_partial_terminal_state():
    events = [
        {
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": "missing.py"},
            "tool_status": "error",
            "tool_error_code": "tool_failed",
            "affected_paths": [],
        }
    ]

    manifest = build_coverage_manifest(events, {"status": "completed"})

    assert manifest["terminal_state"] == "partial"
    assert manifest["planned_files"] == ["missing.py"]
    assert manifest["failed_files"] == [
        {"path": "missing.py", "tool": "read_file", "status": "error", "error_code": "tool_failed"}
    ]
    assert manifest["failed_tools"] == [
        {"tool": "read_file", "status": "error", "error_code": "tool_failed", "paths": ["missing.py"]}
    ]
    assert manifest["metrics"]["failed_count"] == 1


def test_is_verification_command_recognizes_common_test_commands():
    assert is_verification_command("python -m pytest -q") is True
    assert is_verification_command("npm test") is True
    assert is_verification_command("go test ./...") is True
    assert is_verification_command("python script.py") is False
