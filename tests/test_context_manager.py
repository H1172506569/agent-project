from repopilot import FakeModelClient, RepoPilot, SessionStore, WorkspaceContext
from repopilot.context_manager import ContextManager


def build_workspace(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def build_agent(tmp_path, outputs, **kwargs):
    workspace = build_workspace(tmp_path)
    store = SessionStore(tmp_path / ".repopilot" / "sessions")
    approval_policy = kwargs.pop("approval_policy", "auto")
    return RepoPilot(
        model_client=FakeModelClient(outputs),
        workspace=workspace,
        session_store=store,
        approval_policy=approval_policy,
        **kwargs,
    )


def test_context_manager_assembles_sections_in_expected_order(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.memory.promote_durable([("dependency-facts", "deploy key is red")])
    agent.record({"role": "user", "content": "old request", "created_at": "2026-04-07T09:59:00+00:00"})
    agent.record({"role": "assistant", "content": "old answer", "created_at": "2026-04-07T10:00:30+00:00"})

    prompt, metadata = ContextManager(agent).build("Where is the deploy key?")

    # 常驻层紧跟 prefix：两者在一次 run 内都稳定，排在一起才能被同一段
    # 可缓存前缀覆盖；每轮都变的内容全部排在它们之后。
    assert prompt.index("You are repopilot") < prompt.index("Durable memory:")
    assert prompt.index("Durable memory:") < prompt.index("Memory:")
    assert prompt.index("Memory:") < prompt.index("Relevant memory:")
    assert prompt.index("Relevant memory:") < prompt.index("Transcript:")
    assert prompt.index("Transcript:") < prompt.index("Current user request:")
    assert prompt.rstrip().endswith("Current user request:\nWhere is the deploy key?")
    assert metadata["section_order"] == [
        "prefix",
        "resident_memory",
        "project_rules",
        "memory",
        "relevant_memory",
        "history",
        "current_request",
    ]


def test_context_manager_reduces_relevant_memory_before_history_and_preserves_newer_context(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.prefix = "PREFIX " + ("A" * 600)
    agent.memory.render_memory_text = lambda: "MEMORY " + ("B" * 600)
    agent.memory.promote_durable([
        ("dependency-facts", "keep durable note one " + ("C" * 220)),
        ("dependency-facts", "keep durable note two " + ("D" * 220)),
        ("dependency-facts", "keep durable note three " + ("E" * 220)),
    ])
    agent.record({"role": "user", "content": "OLD-CONTEXT " + ("D" * 260), "created_at": "2026-04-07T09:59:00+00:00"})
    for minute in range(1, 8):
        role = "assistant" if minute % 2 == 1 else "user"
        content = "RECENT-CONTEXT " + ("E" * 260) if minute == 7 else f"recent-{minute} " + ("E" * 180)
        agent.record({"role": role, "content": content, "created_at": f"2026-04-07T10:0{minute}:00+00:00"})

    manager = ContextManager(
        agent,
        total_budget=700,
        section_budgets={
            "prefix": 120,
            "memory": 120,
            "relevant_memory": 120,
            "history": 400,
        },
    )

    prompt, metadata = manager.build("keep this request verbatim")

    for section in ("prefix", "memory", "relevant_memory", "history"):
        assert metadata["sections"][section]["rendered_chars"] <= metadata["sections"][section]["budget_chars"]

    reduction_sections = [entry["section"] for entry in metadata["budget_reductions"]]
    assert reduction_sections[0] == "relevant_memory"
    assert reduction_sections
    assert "RECENT-CONTEXT" in prompt
    assert "OLD-CONTEXT" not in prompt
    assert "keep this request verbatim" in prompt


def test_context_manager_renders_top_three_durable_notes_per_note_under_budget(tmp_path):
    """检索层最多选 3 条，并在预算内逐条渲染。

    同分候选按写入顺序排列：durable 笔记的 created_at 来自 topic 文件的
    updated_at，同一 topic 内没有逐条时间戳可比，排序只能是稳定的写入顺序。
    """
    agent = build_agent(tmp_path, [])
    agent.memory.promote_durable([
        ("dependency-facts", "alpha recall note " + ("A" * 120)),
        ("dependency-facts", "beta recall note " + ("B" * 120)),
        ("dependency-facts", "gamma recall note " + ("C" * 120)),
        ("dependency-facts", "older unmatched note"),
        ("dependency-facts", "Unrelated note"),
    ])

    prompt, metadata = ContextManager(
        agent,
        # 常驻层独立成段后，prompt 多出一段固定开销；这里给总预算补上，
        # 免得触发裁剪——这个测试要验的是 relevant_memory 的逐条渲染。
        total_budget=300,
        section_budgets={
            "prefix": 60,
            "resident_memory": 40,
            "memory": 60,
            "relevant_memory": 80,
            "history": 60,
        },
    ).build("recall")

    assert metadata["relevant_memory"]["selected_count"] == 3
    assert metadata["relevant_memory"]["limit"] == 3
    assert metadata["relevant_memory"]["selected_notes"] == [
        "alpha recall note " + ("A" * 120),
        "beta recall note " + ("B" * 120),
        "gamma recall note " + ("C" * 120),
    ]
    assert len(metadata["relevant_memory"]["rendered_notes"]) == 3
    assert metadata["relevant_memory"]["rendered_count"] == 3
    assert metadata["relevant_memory"]["rendered_notes"][0].startswith("alpha recall")
    assert metadata["relevant_memory"]["rendered_notes"][1].startswith("beta recall")
    assert metadata["relevant_memory"]["rendered_notes"][2].startswith("gamma recall")
    relevant_section = prompt.split("Relevant memory:\n", 1)[1].split("\n\nTranscript:", 1)[0]
    assert len([line for line in relevant_section.splitlines() if line.startswith("- ")]) == 3
    assert "alpha recall" in relevant_section
    assert "beta recall" in relevant_section
    assert "gamma recall" in relevant_section
    assert "older unmatched note" not in relevant_section


def test_context_manager_preserves_current_request_when_over_budget(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.prefix = "PREFIX " + ("A" * 600)
    agent.memory.render_memory_text = lambda: "MEMORY " + ("B" * 600)
    agent.memory.retrieval_view = lambda query, limit=3: "Relevant memory:\n" + "\n".join(f"- {i} " + ("C" * 220) for i in range(5))
    agent.history_text = lambda: "Transcript:\n" + "\n".join(f"[user] {i} " + ("D" * 220) for i in range(5))

    request = "please preserve this request exactly"
    prompt, metadata = ContextManager(
        agent,
        total_budget=250,
        section_budgets={
            "prefix": 80,
            "memory": 80,
            "relevant_memory": 80,
            "history": 80,
        },
    ).build(request)

    assert prompt.split("Current user request:\n", 1)[1] == request
    assert metadata["current_request"]["text"] == request
    assert metadata["current_request"]["rendered_chars"] == len(request)


def test_context_manager_collapses_older_duplicate_reads_into_one_summary_line(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\n", encoding="utf-8")
    agent = build_agent(tmp_path, [])
    agent.memory.set_file_summary("sample.txt", "alpha | beta")
    agent.memory.remember_file("sample.txt")

    for created_at in ("2026-04-07T09:00:00+00:00", "2026-04-07T09:01:00+00:00"):
        agent.record(
            {
                "role": "tool",
                "name": "read_file",
                "args": {"path": "sample.txt", "start": 1, "end": 2},
                "content": "# sample.txt\nalpha\nbeta\n",
                "created_at": created_at,
            }
        )

    for minute in range(2, 8):
        role = "user" if minute % 2 == 0 else "assistant"
        agent.record(
            {
                "role": role,
                "content": f"recent-{minute}",
                "created_at": f"2026-04-07T09:0{minute}:00+00:00",
            }
        )

    prompt, metadata = ContextManager(agent).build("check the file")
    transcript = prompt.split("\n\nTranscript:\n", 1)[1].split("\n\nCurrent user request:", 1)[0]

    assert transcript.count("[tool:read_file]") == 0
    assert "sample.txt -> alpha | beta" in transcript
    assert metadata["history"]["older_entries_count"] == 1
    assert metadata["history"]["collapsed_duplicate_reads"] == 1
    assert metadata["history"]["reused_file_summary_count"] == 1


def test_context_manager_summarizes_older_tool_output_into_one_line(tmp_path):
    agent = build_agent(tmp_path, [])
    agent.record(
        {
            "role": "tool",
            "name": "run_shell",
            "args": {"command": "pytest -q"},
            "content": "FAIL test_one\nFAIL test_two\nFAIL test_three\nFAIL test_four\n",
            "created_at": "2026-04-07T09:00:00+00:00",
        }
    )

    for minute in range(1, 7):
        role = "user" if minute % 2 == 1 else "assistant"
        agent.record(
            {
                "role": role,
                "content": f"recent-{minute}",
                "created_at": f"2026-04-07T09:0{minute}:00+00:00",
            }
        )

    prompt, metadata = ContextManager(agent).build("check failures")
    transcript = prompt.split("\n\nTranscript:\n", 1)[1].split("\n\nCurrent user request:", 1)[0]

    assert 'pytest -q -> FAIL test_one | FAIL test_two | FAIL test_three' in transcript
    assert "FAIL test_four" not in transcript
    assert metadata["history"]["summarized_tool_count"] == 1
    assert metadata["history"]["reused_file_summary_count"] == 0


def test_context_manager_relevant_memory_can_mix_durable_notes(tmp_path):
    memory_root = tmp_path / ".repopilot" / "memory"
    topics_dir = memory_root / "topics"
    topics_dir.mkdir(parents=True)
    (memory_root / "MEMORY.md").write_text(
        "# Durable Memory Index\n\n"
        "- [dependency-facts](topics/dependency-facts.md): Dependency Facts\n"
        "  - summary: Stable dependency and environment facts.\n"
        "  - tags: dependency\n",
        encoding="utf-8",
    )
    (topics_dir / "dependency-facts.md").write_text(
        "# Dependency Facts\n\n"
        "- topic: dependency-facts\n"
        "- summary: Stable dependency and environment facts.\n"
        "- tags: dependency\n"
        "- updated_at: 2026-04-12T08:14:49+00:00\n\n"
        "## Notes\n"
        "- Project verification runs with pytest.\n",
        encoding="utf-8",
    )

    agent = build_agent(tmp_path, [])

    prompt, metadata = ContextManager(agent).build("How do I run pytest verification?")
    relevant_section = prompt.split("Relevant memory:\n", 1)[1].split("\n\nTranscript:", 1)[0]

    assert "Project verification runs with pytest." in relevant_section
    assert any("Project verification runs with pytest." in item for item in metadata["relevant_memory"]["selected_notes"])
    assert metadata["relevant_memory"]["selected_durable_count"] == 1
    assert metadata["relevant_memory"]["selected_sources"] == ["dependency-facts"]
    assert metadata["relevant_memory"]["selected_kinds"] == ["durable"]


def test_context_manager_resident_durable_notes_bypass_retrieval(tmp_path):
    """常驻层不参与检索，而是整体进 Memory 段。

    它装的是无锚点的记忆：用户 query 里没有任何 token 能召回“以后都用中文解释”，
    所以检索对这类记忆结构性失效，只能每轮常驻。
    """
    memory_root = tmp_path / ".repopilot" / "memory"
    topics_dir = memory_root / "topics"
    topics_dir.mkdir(parents=True)
    (memory_root / "MEMORY.md").write_text(
        "# Durable Memory Index\n\n"
        "- [project-conventions](topics/project-conventions.md): Project Conventions\n"
        "  - summary: Stable repository conventions.\n"
        "  - tags: convention\n",
        encoding="utf-8",
    )
    (topics_dir / "project-conventions.md").write_text(
        "# Project Conventions\n\n"
        "- topic: project-conventions\n"
        "- summary: Stable repository conventions.\n"
        "- tags: convention\n"
        "- updated_at: 2026-04-12T08:14:49+00:00\n\n"
        "## Notes\n"
        "- Use constrained tools instead of guessing.\n",
        encoding="utf-8",
    )

    agent = build_agent(tmp_path, [])

    # 一个和这条约定毫无词面重叠的问题：检索必然召不回，常驻层却必须在。
    prompt, metadata = ContextManager(agent).build("Rename the helper in utils.py")

    resident_section = prompt.split("Durable memory:\n", 1)[1].split("\n\n", 1)[0]
    assert "Use constrained tools instead of guessing." in resident_section
    assert metadata["sections"]["resident_memory"]["rendered_chars"] > 0
    assert metadata["relevant_memory"]["selected_durable_count"] == 0


def test_context_manager_injects_only_path_matched_project_rules(tmp_path):
    rules_dir = tmp_path / ".repopilot"
    rules_dir.mkdir()
    (rules_dir / "rules.json").write_text(
        '{"include":["repopilot/**/*.py","tests/**/*.py"],"exclude":["tests/fixtures/**"],"rules":['
        '{"path":"repopilot/**/*.py","rule":"Runtime code should keep dependencies minimal."},'
        '{"path":"tests/**/*.py","rule":"Tests should use FakeModelClient and avoid network."},'
        '{"path":"**/*.md","rule":"Markdown docs should be concise."}'
        ']}',
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, [])

    prompt, metadata = ContextManager(agent).build("Update repopilot/runtime.py and tests/fixtures/sample.py")

    rules_section = prompt.split("Project rules:\n", 1)[1].split("\n\nMemory:", 1)[0]
    assert "Runtime code should keep dependencies minimal." in rules_section
    assert "Tests should use FakeModelClient" not in rules_section
    assert "Markdown docs should be concise." not in rules_section
    assert metadata["project_rules"]["candidate_paths"] == ["repopilot/runtime.py", "tests/fixtures/sample.py"]
    assert metadata["project_rules"]["excluded_paths"] == ["tests/fixtures/sample.py"]
    assert metadata["project_rules"]["matched_count"] == 1
    assert metadata["project_rules"]["all_rule_chars"] > metadata["project_rules"]["rendered_chars"]


def test_context_manager_project_rules_can_match_recent_tool_history(tmp_path):
    rules_dir = tmp_path / ".repopilot"
    rules_dir.mkdir()
    (rules_dir / "rules.json").write_text(
        '{"rules":[{"path":"tests/**/*.py","rule":"Tests should use FakeModelClient and avoid network."}]}',
        encoding="utf-8",
    )
    agent = build_agent(tmp_path, [])
    agent.record(
        {
            "role": "tool",
            "name": "read_file",
            "args": {"path": "tests/test_agent_loop.py"},
            "content": "",
            "created_at": "2026-04-07T09:00:00+00:00",
        }
    )

    prompt, metadata = ContextManager(agent).build("Continue the same test change")

    assert "Tests should use FakeModelClient and avoid network." in prompt
    assert metadata["project_rules"]["candidate_paths"] == ["tests/test_agent_loop.py"]
    assert metadata["project_rules"]["matched_count"] == 1


def test_prefix_clipping_keeps_checkpoint_and_drops_static_rules(tmp_path):
    """prefix 超预算时先砍工作手册，不砍 resume 状态。

    checkpoint 拼在 prefix 段尾部，而裁剪砍的就是尾巴——不特殊处理的话，
    只要 prefix 一超预算，第一个丢掉的永远是“上次做到哪”。
    """
    agent = build_agent(tmp_path, [])
    agent.prefix = "STATIC-RULES " + ("A" * 900)
    agent.render_checkpoint_text = lambda: "Task checkpoint:\nNext step: re-read runtime.py"

    prompt, metadata = ContextManager(agent, section_budgets={"prefix": 300}).build("Continue")

    assert "Task checkpoint:" in prompt
    assert "Next step: re-read runtime.py" in prompt
    assert "STATIC-RULES" in prompt
    assert metadata["sections"]["prefix"]["rendered_chars"] <= 300
