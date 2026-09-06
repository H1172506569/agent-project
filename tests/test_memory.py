from repopilot.features.memory import LayeredMemory


def test_working_memory_tracks_summary_and_recent_files():
    memory = LayeredMemory()

    memory.set_task_summary("Investigate flaky tests")
    memory.remember_file("README.md")
    memory.remember_file("src/app.py")
    memory.remember_file("README.md")

    snapshot = memory.to_dict()

    assert snapshot["working"]["task_summary"] == "Investigate flaky tests"
    assert snapshot["working"]["recent_files"] == ["src/app.py", "README.md"]
    assert snapshot["task"] == "Investigate flaky tests"
    assert snapshot["files"] == ["src/app.py", "README.md"]


def test_file_summaries_use_canonical_paths_and_freshness(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\n", encoding="utf-8")
    memory = LayeredMemory(workspace_root=tmp_path)

    memory.set_file_summary("./sample.txt", "sample.txt: alpha")
    memory.remember_file("./sample.txt")
    snapshot = memory.to_dict()["file_summaries"]["sample.txt"]

    assert snapshot["summary"] == "sample.txt: alpha"
    assert snapshot["freshness"]

    assert "sample.txt: alpha" in memory.render_memory_text()
    file_path.write_text("beta\n", encoding="utf-8")
    assert "sample.txt: alpha" not in memory.render_memory_text()

    memory.invalidate_file_summary("sample.txt")

    assert "sample.txt" not in memory.to_dict()["file_summaries"]


def test_durable_memory_index_and_topic_notes_are_loaded_and_retrieved(tmp_path):
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
        "- Use constrained tools instead of guessing.\n"
        "- Preserve local agent state under .repopilot/.\n",
        encoding="utf-8",
    )

    memory = LayeredMemory(workspace_root=tmp_path)

    snapshot = memory.to_dict()
    assert snapshot["durable_topics"] == ["project-conventions"]

    # project-conventions 是常驻层：它不走检索，而是整体进 Memory 段。
    assert memory.resident_notes() == [
        "Use constrained tools instead of guessing.",
        "Preserve local agent state under .repopilot/.",
    ]
    # 常驻层是独立的一段，不再混在 Memory 段里。
    assert "durable" not in memory.render_memory_text().replace("durable_topics", "")
    rendered = memory.render_resident_memory_text()
    assert rendered.startswith("Durable memory:")
    assert "Use constrained tools instead of guessing." in rendered

    lines = [line for line in memory.retrieval_view("constrained tools", limit=4).splitlines() if line.startswith("- ")]
    assert lines == ["- none"]


def test_retrieval_tier_durable_notes_are_recalled_by_query(tmp_path):
    memory = LayeredMemory(workspace_root=tmp_path)
    memory.promote_durable([("dependency-facts", "Project verification runs with pytest.")])

    lines = [line for line in memory.retrieval_view("pytest verification", limit=4).splitlines() if line.startswith("- ")]

    assert any("Project verification runs with pytest." in line for line in lines)
    # 检索层不该把常驻层的内容再重复一遍。
    assert memory.resident_notes() == []


def test_chinese_query_recalls_retrieval_tier_notes(tmp_path):
    """中文 query 必须能召回中文笔记。

    分词只切 ASCII 时，中文 query 分词后是空集合，任何候选都匹配不上，
    检索层对中文恒为空——而晋升侧本来就支持中文偏好。
    """
    memory = LayeredMemory(workspace_root=tmp_path)
    memory.promote_durable([("dependency-facts", "依赖校验统一使用 pytest 执行。")])

    lines = [line for line in memory.retrieval_view("依赖校验怎么跑", limit=4).splitlines() if line.startswith("- ")]

    assert any("依赖校验统一使用 pytest 执行。" in line for line in lines)


def test_resident_cap_evicts_oldest_notes(tmp_path):
    """常驻层每轮都进 prompt，所以必须有上限，且淘汰要留痕。"""
    from repopilot.features.memory import RESIDENT_TOPIC_NOTE_LIMIT

    memory = LayeredMemory(workspace_root=tmp_path)
    total = RESIDENT_TOPIC_NOTE_LIMIT + 3
    _, _, evicted = memory.promote_durable(
        [("project-conventions", f"Convention number {index:02d} is enforced.") for index in range(total)]
    )

    notes = memory.resident_notes()
    assert len(notes) == RESIDENT_TOPIC_NOTE_LIMIT
    assert notes[0] == "Convention number 03 is enforced."
    assert notes[-1] == f"Convention number {total - 1:02d} is enforced."
    assert evicted == [f"project-conventions: Convention number {index:02d} is enforced." for index in range(3)]


def test_revoke_durable_removes_resident_note(tmp_path):
    memory = LayeredMemory(workspace_root=tmp_path)
    memory.promote_durable([("user-preferences", "以后都用中文解释。")])
    assert memory.resident_notes() == ["以后都用中文解释。"]

    assert memory.revoke_durable("user-preferences", "以后都用中文解释。") is True
    assert memory.resident_notes() == []
    assert memory.revoke_durable("user-preferences", "以后都用中文解释。") is False


def test_legacy_episodic_fields_are_dropped_from_restored_state():
    """磁盘上的旧 session 仍可能带着 episodic 字段，读回来时必须丢掉。

    这些内容要么和 file_summaries 重复，要么和 history 压缩保留的失败工具轮
    重复，而且没有 freshness——文件改写后仍会把过期摘要召回给模型。
    """
    legacy = {
        "task": "old task",
        "files": ["a.py"],
        "episodic_notes": [{"text": "stale read summary", "tags": [], "kind": "episodic"}],
        "notes": ["stale read summary"],
        "next_note_index": 7,
    }

    snapshot = LayeredMemory(state=legacy).to_dict()

    assert "episodic_notes" not in snapshot
    assert "notes" not in snapshot
    assert "next_note_index" not in snapshot
    assert snapshot["working"]["task_summary"] == "old task"
    assert snapshot["working"]["recent_files"] == ["a.py"]
