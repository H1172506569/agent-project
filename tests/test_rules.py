import pytest

from repopilot.rules import RuleResolver, extract_candidate_paths


def test_rule_resolver_matches_path_based_rules_and_respects_exclude():
    resolver = RuleResolver.from_dict(
        {
            "include": ["repopilot/**/*.py", "tests/**/*.py"],
            "exclude": ["tests/fixtures/**"],
            "rules": [
                {"path": "tests/**/*.py", "rule": "Tests should use FakeModelClient and avoid network."},
                {"path": "repopilot/**/*.py", "rule": "Runtime code should keep dependencies minimal."},
            ],
        }
    )

    context = resolver.match_context("Update tests/test_agent_loop.py and tests/fixtures/sample.py")

    assert context.candidate_paths == ["tests/test_agent_loop.py", "tests/fixtures/sample.py"]
    assert context.excluded_paths == ["tests/fixtures/sample.py"]
    assert context.matched_rules == [
        {
            "path": "tests/test_agent_loop.py",
            "pattern": "tests/**/*.py",
            "rule": "Tests should use FakeModelClient and avoid network.",
        }
    ]


def test_rule_resolver_defaults_to_empty_when_no_rules_file(tmp_path):
    resolver = RuleResolver.from_workspace(tmp_path)

    context = resolver.match_context("Read repopilot/runtime.py")

    assert context.candidate_paths == ["repopilot/runtime.py"]
    assert context.matched_rules == []
    assert context.render() == ""


def test_extract_candidate_paths_uses_user_message_and_recent_tool_history():
    history = [
        {"role": "tool", "name": "read_file", "args": {"path": "repopilot/runtime.py"}, "content": ""},
        {"role": "tool", "name": "write_file", "args": {"path": "tests/test_runtime.py"}, "content": ""},
    ]

    assert extract_candidate_paths("Check README.md", history) == [
        "README.md",
        "repopilot/runtime.py",
        "tests/test_runtime.py",
    ]


def test_rule_resolver_rejects_non_object_rules_json(tmp_path):
    rules_dir = tmp_path / ".repopilot"
    rules_dir.mkdir()
    (rules_dir / "rules.json").write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="rules.json must contain a JSON object"):
        RuleResolver.from_workspace(tmp_path)
