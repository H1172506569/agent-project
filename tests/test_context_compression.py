from repopilot import FakeModelClient, RepoPilot, SessionStore, WorkspaceContext
from repopilot.context_manager import ContextManager
from repopilot.context_compression import render_tool_round_compressed_history


def build_agent(tmp_path, **kwargs):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".repopilot" / "sessions")
    return RepoPilot(
        model_client=FakeModelClient([]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        feature_flags={"tool_round_compression": True, **kwargs.pop("feature_flags", {})},
        **kwargs,
    )



class CountingCompressionClient:
    def __init__(self, response=None, error=None):
        self.response = response or '{"items":[{"tool":"read_file","status":"ok","path":"src/kept.py","command":"","exit_code":null,"signal":"kept important context"}]}'
        self.error = error
        self.calls = 0
        self.last_completion_metadata = {}

    def complete(self, prompt, max_new_tokens, prompt_cache_key=None, prompt_cache_retention=None):
        del prompt_cache_key, prompt_cache_retention
        self.calls += 1
        self.last_completion_metadata = {
            "input_tokens": max(1, len(prompt) // 4),
            "output_tokens": max_new_tokens,
        }
        if self.error:
            raise self.error
        return self.response


def scripted_usage_ratio(agent, values):
    values = list(values)

    def next_ratio(_metadata):
        if values:
            return values.pop(0)
        return 0.0

    agent._context_usage_ratio = next_ratio
def record_tool(agent, name, args, content, minute):
    agent.record(
        {
            "role": "tool",
            "name": name,
            "args": args,
            "content": content,
            "created_at": f"2026-04-07T09:{minute:02d}:00+00:00",
        }
    )


def test_tool_round_compression_keeps_recent_tool_result_uncompressed(tmp_path):
    agent = build_agent(tmp_path)
    for index in range(6):
        record_tool(agent, "read_file", {"path": f"src/old_{index}.py"}, "OLD " + ("A" * 200), index)
    record_tool(agent, "run_shell", {"command": "pytest -q"}, "RECENT_EXIT_DETAIL\nexit_code: 0\n", 20)

    prompt, metadata = ContextManager(
        agent,
        total_budget=900,
        section_budgets={"prefix": 80, "memory": 80, "relevant_memory": 60, "history": 520},
    ).build("continue")

    assert "Active recent context:" in prompt
    assert "RECENT_EXIT_DETAIL" in prompt
    assert "[tool:run_shell]" in prompt
    assert "[compressed:run_shell]" not in prompt
    assert metadata["history"]["context_strategy"] == "tool_round_compression"
    assert metadata["history"]["active_round_count"] >= 1


def test_tool_round_compression_preserves_current_request_when_over_budget(tmp_path):
    agent = build_agent(tmp_path)
    agent.prefix = "PREFIX " + ("P" * 500)
    for index in range(8):
        record_tool(agent, "read_file", {"path": f"src/noisy_{index}.py"}, "NOISE " + ("N" * 300), index)

    request = "preserve this exact user request"
    prompt, metadata = ContextManager(
        agent,
        total_budget=240,
        section_budgets={"prefix": 50, "memory": 40, "relevant_memory": 30, "history": 80},
    ).build(request)

    assert prompt.split("Current user request:\n", 1)[1] == request
    assert metadata["current_request"]["text"] == request


def test_tool_round_compression_keeps_history_section_under_budget():
    history = []
    for index in range(10):
        history.append(
            {
                "role": "tool",
                "name": "read_file",
                "args": {"path": f"src/module_{index}.py"},
                "content": "line\n" + ("A" * 500),
            }
        )
    history.append(
        {
            "role": "tool",
            "name": "run_shell",
            "args": {"command": "pytest -q"},
            "content": "RECENT_RESULT\nexit_code: 0\n",
        }
    )

    rendered = render_tool_round_compressed_history(history, budget=360, active_tool_rounds=2)

    assert len(rendered.rendered) <= 360
    assert rendered.details["compression_failure_count"] == 0
    assert rendered.details["compressed_round_count"] >= 1


def test_tool_round_compression_retains_old_path_and_failed_status(tmp_path):
    agent = build_agent(tmp_path)
    record_tool(
        agent,
        "read_file",
        {"path": "src/legacy_config.py"},
        "LEGACY_SECRET_SHAPE\n" + ("A" * 300),
        1,
    )
    record_tool(
        agent,
        "run_shell",
        {"command": "pytest tests/test_legacy.py -q"},
        "FAIL tests/test_legacy.py::test_old\nexit_code: 1\n",
        2,
    )
    for index in range(8):
        agent.record(
            {
                "role": "assistant",
                "content": "recent planning note " + ("R" * 80),
                "created_at": f"2026-04-07T09:{10 + index:02d}:00+00:00",
            }
        )

    prompt, metadata = ContextManager(
        agent,
        total_budget=980,
        section_budgets={"prefix": 80, "memory": 70, "relevant_memory": 50, "history": 620},
    ).build("check legacy failure")

    assert "src/legacy_config.py" in prompt
    assert "status=error" in prompt
    assert "exit_code=1" in prompt
    assert metadata["history"]["retained_failed_tool_count"] >= 1
    assert "src/legacy_config.py" in metadata["history"]["retained_file_paths"]



def test_adaptive_context_compression_schedules_async_at_sixty_percent(tmp_path):
    agent = build_agent(
        tmp_path,
        feature_flags={"adaptive_context_compression": True, "tool_round_compression": False},
    )
    agent.prefix = "P" * 80
    for index in range(4):
        record_tool(agent, "read_file", {"path": f"src/async_{index}.py"}, "A" * 150, index)
    agent.context_manager = ContextManager(
        agent,
        total_budget=900,
        section_budgets={"prefix": 80, "project_rules": 0, "memory": 40, "relevant_memory": 20, "history": 430},
        section_floors={"prefix": 20, "project_rules": 0, "memory": 20, "relevant_memory": 10, "history": 100},
    )

    prompt, metadata = agent._build_prompt_and_metadata("trigger async compression")
    state = agent.wait_for_context_compression(timeout=3)

    assert metadata["context_compression_scheduler"]["action"] in {"async_scheduled", "async_summary_fresh", "async_pending"}
    assert state["status"] == "ready"
    assert state["mode"] == "async"
    assert state["rendered_chars"] > 0
    assert agent.session["context_compression"]["status"] == "ready"
    assert "trigger async compression" in prompt


def test_adaptive_context_compression_runs_sync_at_eighty_percent_and_preserves_request(tmp_path):
    agent = build_agent(
        tmp_path,
        feature_flags={"adaptive_context_compression": True, "tool_round_compression": False},
    )
    agent.prefix = "P" * 120
    for index in range(10):
        content = "S" * 260 if index < 8 else "recent small result\nexit_code: 0\n"
        record_tool(agent, "read_file", {"path": f"src/sync_{index}.py"}, content, index)
    agent.context_manager = ContextManager(
        agent,
        total_budget=900,
        section_budgets={"prefix": 100, "project_rules": 0, "memory": 40, "relevant_memory": 20, "history": 620},
        section_floors={"prefix": 20, "project_rules": 0, "memory": 20, "relevant_memory": 10, "history": 120},
    )

    request = "preserve current request during sync compression"
    prompt, metadata = agent._build_prompt_and_metadata(request)
    scheduler = metadata["context_compression_scheduler"]

    assert scheduler["action"] == "sync_compressed"
    assert scheduler["before_prompt_chars"] >= scheduler["after_prompt_chars"]
    assert agent.session["context_compression"]["status"] == "ready"
    assert agent.session["context_compression"]["mode"] == "sync"
    assert metadata["history"]["persisted_summary_used"] is True
    assert prompt.split("Current user request:\n", 1)[1] == request




def test_adaptive_context_compression_does_not_call_llm_between_sixty_and_eighty(tmp_path):
    compression_client = CountingCompressionClient(error=AssertionError("LLM compression should not run below 80%"))
    agent = build_agent(
        tmp_path,
        feature_flags={
            "adaptive_context_compression": True,
            "tool_round_compression": False,
            "llm_context_compression": True,
        },
        context_compression_model_client=compression_client,
    )
    for index in range(4):
        record_tool(agent, "read_file", {"path": f"src/async_{index}.py"}, "A" * 150, index)
    agent.context_manager = ContextManager(
        agent,
        total_budget=900,
        section_budgets={"prefix": 80, "project_rules": 0, "memory": 40, "relevant_memory": 20, "history": 430},
        section_floors={"prefix": 20, "project_rules": 0, "memory": 20, "relevant_memory": 10, "history": 100},
    )
    scripted_usage_ratio(agent, [0.70, 0.70])

    prompt, metadata = agent._build_prompt_and_metadata("trigger deterministic async compression")
    state = agent.wait_for_context_compression(timeout=3)

    assert metadata["context_compression_scheduler"]["action"] in {"async_scheduled", "async_summary_fresh", "async_pending"}
    assert compression_client.calls == 0
    assert state["status"] == "ready"
    assert state["backend"] == "deterministic"
    assert state["details"]["context_compression_backend"] == "deterministic"
    assert "trigger deterministic async compression" in prompt


def test_adaptive_context_compression_escalates_to_llm_only_after_sync_still_over_eighty(tmp_path):
    compression_client = CountingCompressionClient(
        response=(
            '{"items":[{"tool":"read_file","status":"ok","path":"src/legacy_config.py",'
            '"command":"","exit_code":null,"signal":"kept architecture decision"}]}'
        )
    )
    agent = build_agent(
        tmp_path,
        feature_flags={
            "adaptive_context_compression": True,
            "tool_round_compression": False,
            "llm_context_compression": True,
        },
        context_compression_model_client=compression_client,
    )
    for index in range(10):
        content = "S" * 260 if index < 8 else "recent small result\nexit_code: 0\n"
        record_tool(agent, "read_file", {"path": f"src/sync_{index}.py"}, content, index)
    agent.context_manager = ContextManager(
        agent,
        total_budget=900,
        section_budgets={"prefix": 100, "project_rules": 0, "memory": 40, "relevant_memory": 20, "history": 620},
        section_floors={"prefix": 20, "project_rules": 0, "memory": 20, "relevant_memory": 10, "history": 120},
    )
    scripted_usage_ratio(agent, [0.95, 0.95, 0.85, 0.65])

    request = "preserve current request during llm escalation"
    prompt, metadata = agent._build_prompt_and_metadata(request)
    scheduler = metadata["context_compression_scheduler"]

    assert scheduler["action"] == "sync_compressed_llm"
    assert scheduler["llm_escalation"] is True
    assert scheduler["llm_escalation_trigger_ratio"] == 0.85
    assert scheduler["llm_call_count"] == 1
    assert compression_client.calls == 1
    assert agent.session["context_compression"]["status"] == "ready"
    assert agent.session["context_compression"]["mode"] == "sync_llm"
    assert agent.session["context_compression"]["backend"] == "deepseek_llm"
    assert agent.session["context_compression"]["details"]["context_strategy"] == "llm_tool_round_compression"
    assert "[llm-compressed:read_file]" in prompt
    assert prompt.split("Current user request:\n", 1)[1] == request


def test_adaptive_context_compression_keeps_deterministic_summary_when_llm_escalation_fails(tmp_path):
    compression_client = CountingCompressionClient(error=RuntimeError("provider unavailable"))
    agent = build_agent(
        tmp_path,
        feature_flags={
            "adaptive_context_compression": True,
            "tool_round_compression": False,
            "llm_context_compression": True,
        },
        context_compression_model_client=compression_client,
    )
    for index in range(10):
        content = "S" * 260 if index < 8 else "recent small result\nexit_code: 0\n"
        record_tool(agent, "read_file", {"path": f"src/sync_{index}.py"}, content, index)
    agent.context_manager = ContextManager(
        agent,
        total_budget=900,
        section_budgets={"prefix": 100, "project_rules": 0, "memory": 40, "relevant_memory": 20, "history": 620},
        section_floors={"prefix": 20, "project_rules": 0, "memory": 20, "relevant_memory": 10, "history": 120},
    )
    scripted_usage_ratio(agent, [0.95, 0.95, 0.85])

    prompt, metadata = agent._build_prompt_and_metadata("fallback request stays intact")
    scheduler = metadata["context_compression_scheduler"]

    assert scheduler["action"] == "sync_compressed"
    assert scheduler["llm_escalation"] is True
    assert scheduler["llm_summary_status"] == "failed"
    assert compression_client.calls == 1
    assert agent.session["context_compression"]["status"] == "ready"
    assert agent.session["context_compression"]["mode"] == "sync"
    assert agent.session["context_compression"]["backend"] == "deterministic"
    assert prompt.split("Current user request:\n", 1)[1] == "fallback request stays intact"

def test_persisted_context_compression_summary_is_reused_with_new_tail(tmp_path):
    agent = build_agent(
        tmp_path,
        feature_flags={"adaptive_context_compression": True, "tool_round_compression": False},
    )
    for index in range(6):
        record_tool(agent, "read_file", {"path": f"src/base_{index}.py"}, "B" * 220, index)
    state = agent._run_context_compression(mode="sync", trigger_ratio=0.9, history_budget=420)
    assert state["status"] == "ready"
    record_tool(agent, "run_shell", {"command": "pytest -q"}, "NEW_TAIL_RESULT\nexit_code: 0\n", 20)

    prompt, metadata = ContextManager(
        agent,
        total_budget=900,
        section_budgets={"prefix": 80, "project_rules": 0, "memory": 40, "relevant_memory": 20, "history": 520},
    ).build("reuse summary")

    assert metadata["history"]["context_strategy"] == "persisted_tool_round_compression"
    assert metadata["history"]["persisted_summary_used"] is True
    assert metadata["history"]["persisted_tail_entries"] == 1
    assert "NEW_TAIL_RESULT" in prompt



