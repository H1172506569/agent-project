import json

from repopilot import FakeModelClient, RepoPilot, SessionStore, WorkspaceContext
from repopilot.memory_promotion import (
    ExistingMemoryTexts,
    MemoryCandidate,
    MemoryPromotionPolicy,
    event_evidence_id,
    generate_memory_candidates,
    memory_promotion_metrics,
)
from repopilot.features.memory import LayeredMemory


def build_memory(tmp_path):
    return LayeredMemory(workspace_root=tmp_path)


def test_save_policy_promotes_stable_actionable_verifiable_candidate(tmp_path):
    memory = build_memory(tmp_path)
    # 证据是配置文件读取——stable 由来源判定，不看候选的措辞。
    events = [
        {
            "source": "trace",
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": "pyproject.toml"},
            "result": "[tool.pytest.ini_options]",
        }
    ]
    candidate = MemoryCandidate(
        text="Project verification can run with pytest.",
        kind="dependency_fact",
        evidence_event_ids=(event_evidence_id(0),),
    )

    decision = MemoryPromotionPolicy().evaluate(candidate, memory, events=events)

    assert decision.promote
    assert decision.reason == "save_passed"
    # stable 来自证据来源（用户消息），不是候选的措辞。
    assert decision.save["stable"] is True
    assert decision.tier == "retrieval"


def test_save_policy_rejects_transient_and_sensitive_candidates(tmp_path):
    memory = build_memory(tmp_path)
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]
    policy = MemoryPromotionPolicy()

    transient = policy.evaluate(
        MemoryCandidate(
            text="Next step is reading tools.py.",
            kind="project_convention",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )
    sensitive = policy.evaluate(
        MemoryCandidate(
            text="Dependency API key is sk-live-secret-abc123.",
            kind="dependency_fact",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )

    assert transient.reject
    assert transient.reason == "transient"
    assert sensitive.reject
    assert sensitive.reason == "sensitive"


def test_save_policy_suppresses_duplicate_and_detects_conflict(tmp_path):
    memory = build_memory(tmp_path)
    memory.promote_durable([
        ("dependency-facts", "Project should not use pytest for tests."),
        ("project-conventions", "Project uses structured tool results."),
    ])
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]
    policy = MemoryPromotionPolicy()

    duplicate = policy.evaluate(
        MemoryCandidate(
            text="Project uses structured tool results.",
            kind="project_convention",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )
    conflict = policy.evaluate(
        MemoryCandidate(
            text="Project should use pytest for tests.",
            kind="dependency_fact",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )

    assert duplicate.reject
    assert duplicate.reason == "duplicate"
    assert conflict.pending_confirmation
    assert conflict.reason == "conflict"


def test_candidate_generation_extracts_user_preference_and_pytest_fact():
    events = [
        {"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "以后都用中文解释。"}},
        {
            "source": "trace",
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": "pyproject.toml"},
            "result": "[tool.pytest.ini_options]\naddopts = '-q'",
        },
    ]

    candidates = generate_memory_candidates(events)

    assert [candidate.kind for candidate in candidates] == ["user_preference", "dependency_fact"]
    assert candidates[0].evidence_event_ids == ("event:0",)
    assert candidates[1].evidence_event_ids == ("event:1",)


def test_candidate_generation_splits_multiple_user_preferences():
    events = [
        {
            "source": "history",
            "event": "history_recorded",
            "history": {
                "role": "user",
                "content": "- Always use pytest for project verification.\n- Never commit generated reports.",
            },
        },
    ]

    candidates = generate_memory_candidates(events)

    assert [candidate.text for candidate in candidates] == [
        "Always use pytest for project verification.",
        "Never commit generated reports.",
    ]


def test_agent_loop_promotes_memory_candidates_into_session_log_and_report(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".repopilot" / "sessions")
    agent = RepoPilot(
        model_client=FakeModelClient(["<final>Done.</final>"]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
    )

    assert agent.ask("以后都用中文解释。") == "Done."

    events = agent.run_events(agent.current_task_state.run_id)
    report = json.loads(agent.run_store.report_path(agent.current_task_state).read_text(encoding="utf-8"))
    memory_topic = tmp_path / ".repopilot" / "memory" / "topics" / "user-preferences.md"

    assert any(event.get("event") == "memory_candidate_created" for event in events)
    assert any(event.get("event") == "memory_promoted" for event in events)
    assert report["memory_promotion_metrics"]["candidate_count"] == 1
    assert report["memory_promotion_metrics"]["promoted_count"] == 1
    assert report["memory_promotion_metrics"]["evidence_coverage"] == 1.0
    assert "以后都用中文解释。" in memory_topic.read_text(encoding="utf-8")


def test_memory_promotion_metrics_report_policy_outcomes(tmp_path):
    memory = build_memory(tmp_path)
    events = [
        {
            "source": "trace",
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": "pyproject.toml"},
            "result": "[tool.pytest.ini_options]",
        }
    ]
    candidates = [
        MemoryCandidate("Project verification can run with pytest.", "dependency_fact", evidence_event_ids=(event_evidence_id(0),)),
        MemoryCandidate("Dependency API key is sk-live-secret-abc123.", "dependency_fact", evidence_event_ids=(event_evidence_id(0),)),
    ]
    policy = MemoryPromotionPolicy()
    decisions = [policy.evaluate(candidate, memory, events=events) for candidate in candidates]

    metrics = memory_promotion_metrics(candidates, decisions)

    assert metrics["candidate_count"] == 2
    assert metrics["promoted_count"] == 1
    assert metrics["rejected_sensitive_candidate_count"] == 1
    assert metrics["promotion_precision_proxy"] == 1.0


def test_batch_promotion_reads_durable_store_once_and_still_dedupes(tmp_path, monkeypatch):
    """晋升一批 candidate 时，长期记忆只读一次，但批内去重不能失效。"""
    memory = build_memory(tmp_path)
    events = [
        {
            "source": "trace",
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": "pyproject.toml"},
            "result": "[tool.pytest.ini_options]",
        }
    ]

    reads = []
    original = type(memory.durable_store).load_topic_notes
    monkeypatch.setattr(
        type(memory.durable_store),
        "load_topic_notes",
        lambda self, topic: (reads.append(topic), original(self, topic))[1],
    )

    shared = ExistingMemoryTexts(memory)
    policy = MemoryPromotionPolicy()
    candidate = MemoryCandidate(
        text="Project verification can run with pytest.",
        kind="dependency_fact",
        evidence_event_ids=(event_evidence_id(0),),
    )

    first = policy.evaluate(candidate, memory, events=events, existing_texts=shared.texts())
    assert first.promote
    memory.promote_durable([(candidate.durable_topic, candidate.text)])
    shared.record_promotion(candidate.text)

    second = policy.evaluate(candidate, memory, events=events, existing_texts=shared.texts())

    assert second.reject
    assert second.reason == "duplicate"
    # 快照只在构造 ExistingMemoryTexts 时读盘，两次 evaluate 都没有再读 topic 文件。
    assert reads == []


def test_promotion_snapshot_supersedes_same_subject_note(tmp_path):
    """同主语的新笔记会覆盖旧笔记，快照要跟着覆盖，否则后续去重会比对到已消失的文本。

    主语必须带区分度：光秃秃的 `project` 不算——那会让 "Project uses pytest" 和
    "Project uses pnpm" 这类互不相关的事实互相覆盖。
    """
    memory = build_memory(tmp_path)
    memory.promote_durable([("dependency-facts", "The frontend workspace uses pnpm.")])

    shared = ExistingMemoryTexts(memory)
    assert "The frontend workspace uses pnpm." in shared.texts()

    shared.record_promotion("The frontend workspace uses yarn.")

    assert "The frontend workspace uses pnpm." not in shared.texts()
    assert "The frontend workspace uses yarn." in shared.texts()


def test_generic_subject_does_not_supersede_unrelated_facts(tmp_path):
    """主语是通用词时宁可追加，不覆盖。

    模式是非贪婪的，`Project uses X` 抽出来永远是 `project`。以前这会让三条
    互不相关的依赖事实互相覆盖，只剩最后一条——而且 `superseded` 里还规规矩矩
    记着 "A -> B"，看起来像正常的事实更新。重复条目还能靠 cap 和冲突检测收拾，
    被删掉的事实找不回来。
    """
    memory = build_memory(tmp_path)

    _, superseded, _ = memory.promote_durable(
        [
            ("dependency-facts", "Project uses pytest for verification."),
            ("dependency-facts", "Project uses pnpm for the frontend workspace."),
            ("dependency-facts", "Project uses ruff for linting."),
        ]
    )

    texts = [note["text"] for note in memory.durable_store.load_topic_notes("dependency-facts")]
    assert len(texts) == 3
    assert superseded == []


def test_subject_key_is_stable_across_processes():
    """主语抽取不能依赖集合迭代顺序。

    `_tokenize()` 返回集合，`" ".join(集合)` 的顺序由字符串哈希决定，而 Python
    默认开哈希随机化——同一条笔记在不同进程里会得到不同主语，覆盖行为跟着不可复现。
    """
    import subprocess
    import sys

    code = (
        "from repopilot.features.memory import DurableMemoryStore as D;"
        "print(D.subject_key('The frontend workspace uses pnpm.'))"
    )
    results = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip()
        for _ in range(3)
    }

    assert len(results) == 1, results


def test_explicit_subject_survives_a_write_and_drives_the_next_supersede(tmp_path):
    """显式主语要跟着笔记落盘，否则它只在单次写入调用内有效。

    不持久化的话，下次写入时旧笔记的主语只能从正文重新猜，模型显式给的主语就丢了。
    """
    memory = build_memory(tmp_path)
    memory.promote_durable([("dependency-facts", "Verification runs with pytest.", "verification runner")])

    # 另起一次写入：旧笔记的主语必须从磁盘读回来才能匹配上。
    _, superseded, _ = memory.promote_durable(
        [("dependency-facts", "Verification runs with nose.", "verification runner")]
    )

    texts = [note["text"] for note in memory.durable_store.load_topic_notes("dependency-facts")]
    assert texts == ["Verification runs with nose."]
    assert superseded == ["dependency-facts: Verification runs with pytest. -> Verification runs with nose."]


def test_evaluate_without_snapshot_still_reads_current_memory(tmp_path):
    """不传 existing_texts 时行为不变，仍然按需读取当前长期记忆。"""
    memory = build_memory(tmp_path)
    memory.promote_durable([("dependency-facts", "Project verification can run with pytest.")])
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]

    decision = MemoryPromotionPolicy().evaluate(
        MemoryCandidate(
            text="Project verification can run with pytest.",
            kind="dependency_fact",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )

    assert decision.reject
    assert decision.reason == "duplicate"


def test_tier_admission_bar_is_stricter_for_resident(tmp_path):
    """同样的候选，检索层放行、常驻层挂起。

    判的是**准入门槛**，不是选层——层在候选出生时就由 kind 定死了。误报代价
    不对称：一条错误的检索记忆只在被召回时有害，一条错误的常驻记忆会污染之后
    的每一轮，所以常驻层要求 stable 和 actionable 兼备，检索层其一即可。
    没过常驻层门槛也不会被降级到检索层，而是进 pending。
    """
    memory = build_memory(tmp_path)
    # 证据是配置文件 -> stable；文本无情态词 -> 非 actionable。
    events = [
        {
            "source": "trace",
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": "pyproject.toml"},
            "result": "[tool.pytest.ini_options]",
        }
    ]
    policy = MemoryPromotionPolicy()
    text = "Verification settings live in pyproject.toml."

    retrieval = policy.evaluate(
        MemoryCandidate(text=text, kind="dependency_fact", evidence_event_ids=(event_evidence_id(0),)),
        memory,
        events=events,
    )
    resident = policy.evaluate(
        MemoryCandidate(text=text, kind="project_convention", evidence_event_ids=(event_evidence_id(0),)),
        memory,
        events=events,
    )

    assert retrieval.save == resident.save
    assert retrieval.save["stable"] is True
    assert retrieval.save["actionable"] is False
    assert retrieval.tier == "retrieval"
    assert retrieval.promote
    assert resident.tier == "resident"
    assert resident.pending_confirmation
    assert resident.reason == "save_score_below_threshold"


def test_stable_comes_from_evidence_source_not_wording(tmp_path):
    """措辞一模一样，证据来源不同，stable 判定就不同。

    这正是把 stable 从文本词表换成证据来源要买到的东西：不依赖措辞、
    中英文一视同仁、且模型自评操纵不了。
    """
    memory = build_memory(tmp_path)
    events = [
        {"source": "trace", "event": "tool_executed", "name": "read_file",
         "args": {"path": "pyproject.toml"}, "result": "[tool.pytest.ini_options]"},
        {"source": "trace", "event": "tool_executed", "name": "run_shell",
         "args": {"command": "pytest -q"}, "exit_code": 0, "result": "passed"},
    ]
    policy = MemoryPromotionPolicy()
    text = "Project verification always runs with pytest."

    from_config = policy.evaluate(
        MemoryCandidate(text=text, kind="dependency_fact", evidence_event_ids=(event_evidence_id(0),)),
        memory,
        events=events,
    )
    from_one_run = policy.evaluate(
        MemoryCandidate(text=text, kind="dependency_fact", evidence_event_ids=(event_evidence_id(1),)),
        memory,
        events=events,
    )

    assert from_config.save["stable"] is True
    assert from_one_run.save["stable"] is False


def test_resident_conflict_requires_explicit_confirmation(tmp_path):
    memory = build_memory(tmp_path)
    memory.promote_durable([("project-conventions", "Project should use tabs for indentation.")])
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]

    decision = MemoryPromotionPolicy().evaluate(
        MemoryCandidate(
            text="Project should not use tabs for indentation.",
            kind="project_convention",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )

    assert decision.pending_confirmation
    assert decision.reason == "resident_conflict"
    assert decision.requires_confirmation
    assert decision.conflict_with == "Project should use tabs for indentation."
    # 检索层的冲突仍然只是普通挂起，不需要用户拍板。
    assert not MemoryPromotionPolicy().evaluate(
        MemoryCandidate(
            text="Project should not use tabs for indentation.",
            kind="dependency_fact",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    ).requires_confirmation


def test_confirm_memory_conflict_revokes_old_resident_note(tmp_path):
    workspace = WorkspaceContext.build(tmp_path)
    agent = RepoPilot(
        FakeModelClient(["<final>done</final>"]),
        workspace,
        SessionStore(tmp_path / "sessions"),
        approval_policy="never",
    )
    agent.memory.promote_durable([("user-preferences", "以后都用英文解释。")])

    result = agent.confirm_memory_conflict(
        "user-preferences", "以后都用英文解释。", "以后都用中文解释。", accept=True
    )

    assert result["applied"] is True
    assert result["revoked"] is True
    assert agent.memory.resident_notes() == ["以后都用中文解释。"]

    declined = agent.confirm_memory_conflict(
        "user-preferences", "以后都用中文解释。", "以后都用日文解释。", accept=False
    )
    assert declined["applied"] is False
    assert agent.memory.resident_notes() == ["以后都用中文解释。"]


def test_retrieval_tier_conflicts_are_also_resolvable(tmp_path):
    """撤销不分层：检索层的冲突同样能被解决，只是不阻塞。

    以前待解决列表只收常驻层的项，检索层的新事实被判 pending 后就地丢弃，
    过期的旧笔记却永远留着，还会一直挡住自己的替代者。
    """
    workspace = WorkspaceContext.build(tmp_path)
    agent = RepoPilot(
        FakeModelClient(["<final>done</final>"]),
        workspace,
        SessionStore(tmp_path / "sessions"),
        approval_policy="never",
    )
    agent.memory.promote_durable([("dependency-facts", "Project should use nose for tests.")])
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]
    decision = MemoryPromotionPolicy().evaluate(
        MemoryCandidate(
            text="Project should not use nose for tests.",
            kind="dependency_fact",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        agent.memory,
        events=events,
    )
    agent.last_memory_promotion_decisions = [decision.to_dict()]

    pending = agent.pending_memory_confirmations()

    assert len(pending) == 1
    assert pending[0]["tier"] == "retrieval"
    # 检索层不阻塞：旧笔记只在被召回时有害，可以等。
    assert pending[0]["blocking"] is False
    assert pending[0]["topic"] == "dependency-facts"

    result = agent.confirm_memory_conflict(
        pending[0]["topic"], pending[0]["existing_text"], pending[0]["candidate_text"], accept=True
    )

    assert result["applied"] is True
    assert result["revoked"] is True
    notes = [note["text"] for note in agent.memory.durable_store.load_topic_notes("dependency-facts")]
    assert notes == ["Project should not use nose for tests."]


def test_resident_conflicts_are_marked_blocking(tmp_path):
    workspace = WorkspaceContext.build(tmp_path)
    agent = RepoPilot(
        FakeModelClient(["<final>done</final>"]),
        workspace,
        SessionStore(tmp_path / "sessions"),
        approval_policy="never",
    )
    agent.memory.promote_durable([("project-conventions", "Project should use tabs for indentation.")])
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]
    decision = MemoryPromotionPolicy().evaluate(
        MemoryCandidate(
            text="Project should not use tabs for indentation.",
            kind="project_convention",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        agent.memory,
        events=events,
    )
    agent.last_memory_promotion_decisions = [decision.to_dict()]

    pending = agent.pending_memory_confirmations()

    assert len(pending) == 1
    assert pending[0]["tier"] == "resident"
    assert pending[0]["blocking"] is True


def _model_block(items):
    return "<memory_candidates>" + json.dumps(items) + "</memory_candidates>"


def _agent_with_model_proposal(tmp_path, items, enabled=True, user_message=None):
    (tmp_path / "Makefile").write_text("check:\n\tpytest -q\n", encoding="utf-8")
    agent = RepoPilot(
        FakeModelClient(
            [
                '<tool>{"name":"read_file","args":{"path":"Makefile","start":1,"end":5}}</tool>',
                "<final>Done.</final>" + _model_block(items),
            ]
        ),
        WorkspaceContext.build(tmp_path),
        SessionStore(tmp_path / "sessions"),
        approval_policy="never",
    )
    agent.feature_flags["llm_memory_candidates"] = enabled
    agent.ask(user_message or "How is this project verified?")
    return agent


def _model_decisions(agent):
    return [
        decision
        for decision in agent.last_memory_promotion_decisions
        if decision["candidate"]["source"] == "model_proposal"
    ]


def _durable_texts(agent):
    texts = []
    for topic in agent.memory.durable_store.topic_slugs():
        texts.extend(note["text"] for note in agent.memory.durable_store.load_topic_notes(topic))
    return texts


def test_model_proposed_candidate_is_promoted_when_evidence_resolves(tmp_path):
    """模型提议走的是和 extractor 完全相同的 SAVE 通路。

    这条候选一个 actionable 关键词都不命中——正则是为 extractor 的固定句式写的，
    落到自然语言上是系统性漏判，所以分数项允许模型自评补上。
    """
    agent = _agent_with_model_proposal(
        tmp_path,
        [
            {
                "text": "Project verification runs through the Makefile check target.",
                "kind": "project_convention",
                "subject": "project verification",
                # 引用 transcript 里 [e6] 那条 read_file
                "evidence": 6,
                "stable": True,
                "actionable": True,
            }
        ],
    )

    decisions = _model_decisions(agent)

    assert len(decisions) == 1
    assert decisions[0]["action"] == "promote"
    assert decisions[0]["tier"] == "resident"
    assert "Project verification runs through the Makefile check target." in _durable_texts(agent)
    assert agent.last_memory_promotion_metrics["model_proposed_promoted_count"] == 1


def test_model_cannot_invent_evidence(tmp_path):
    """模型不能自报 event id，证据由 runtime 到真实事件流里核实。"""
    agent = _agent_with_model_proposal(
        tmp_path,
        [
            {
                "text": "Project always deploys on Fridays.",
                "kind": "project_convention",
                "subject": "deploy day",
                "evidence": 999,
                "stable": True,
                "actionable": True,
            }
        ],
    )

    decisions = _model_decisions(agent)

    assert decisions[0]["action"] == "pending_confirmation"
    assert decisions[0]["reason"] == "missing_evidence"
    assert "Project always deploys on Fridays." not in _durable_texts(agent)


def test_model_self_assessment_cannot_bypass_hard_gates(tmp_path):
    """自评只能加分，一道硬门也绕不过。"""
    agent = _agent_with_model_proposal(
        tmp_path,
        [
            {
                "text": "Deploy uses api key sk-live-abc123456.",
                "kind": "dependency_fact",
                "subject": "deploy key",
                "evidence": 6,
                "stable": True,
                "actionable": True,
            },
            {
                "text": "Next step is reading the Makefile again.",
                "kind": "project_convention",
                "subject": "next step",
                "evidence": 6,
                "stable": True,
                "actionable": True,
            },
        ],
    )

    reasons = {decision["reason"] for decision in _model_decisions(agent)}

    assert reasons == {"sensitive", "transient"}
    assert not any("sk-live" in text for text in _durable_texts(agent))


def test_model_proposals_are_ignored_when_flag_is_off(tmp_path):
    agent = _agent_with_model_proposal(
        tmp_path,
        [
            {
                "text": "Project verification runs through the Makefile check target.",
                "kind": "project_convention",
                "subject": "project verification",
                # 引用 transcript 里 [e6] 那条 read_file
                "evidence": 6,
                "stable": True,
                "actionable": True,
            }
        ],
        enabled=False,
    )

    assert _model_decisions(agent) == []
    assert agent.last_model_memory_candidate_count == 0
    assert "Project verification runs through the Makefile check target." not in _durable_texts(agent)


def test_malformed_memory_candidates_block_is_ignored():
    assert RepoPilot.parse_memory_candidates("<final>ok</final>") == []
    assert RepoPilot.parse_memory_candidates("<memory_candidates>not json</memory_candidates>") == []
    assert RepoPilot.parse_memory_candidates("<memory_candidates>[]</memory_candidates>") == []
    assert RepoPilot.parse_memory_candidates('<memory_candidates>{"text":"a"}</memory_candidates>') == [{"text": "a"}]


def test_model_subject_drives_conflict_detection(tmp_path):
    """模型给主语，是为了让去重/冲突检测不被自由表述绕过。"""
    memory = build_memory(tmp_path)
    memory.promote_durable([("dependency-facts", "Formatting must use black.")])
    events = [{"source": "history", "event": "history_recorded", "history": {"role": "user", "content": "x"}}]

    decision = MemoryPromotionPolicy().evaluate(
        MemoryCandidate(
            text="For this repository, formatting must never use black.",
            kind="dependency_fact",
            subject="formatting",
            evidence_event_ids=(event_evidence_id(0),),
        ),
        memory,
        events=events,
    )

    assert decision.pending_confirmation
    assert decision.reason == "conflict"
    assert decision.conflict_with == "Formatting must use black."


def test_casual_user_mention_is_not_durable_evidence(tmp_path):
    """用户“说过话”不等于“陈述了长期偏好”。

    不加这道判定的话，模型可以拿任何一句随口的用户消息，给一条凭空捏造的
    约定换来 stable，然后直接落进每轮都生效的常驻层。
    """
    agent = _agent_with_model_proposal(
        tmp_path,
        [
            {
                "text": "Project tests must always be skipped before release.",
                "kind": "project_convention",
                "subject": "release tests",
                "evidence": "pyproject",
                "actionable": True,
            }
        ],
        user_message="Check the pyproject config and make the project tests pass",
    )

    decision = _model_decisions(agent)[0]

    assert decision["save"]["stable"] is False
    assert decision["action"] == "pending_confirmation"
    assert "Project tests must always be skipped before release." not in _durable_texts(agent)


def test_user_preferences_are_captured_by_the_extractor_not_by_model_handles(tmp_path):
    """用户偏好走确定性抽取，模型引用同一条消息换不来 stable。

    区别在于候选和消息的关系：抽取器的偏好候选**就是从那条消息里切出来的片段**，
    消息当然支撑它；模型只是断言“这条消息说了 X”，不构成同一件事。
    偏好本身不会丢——抽取器精确抓到并入库。
    """
    agent = _agent_with_model_proposal(
        tmp_path,
        [
            {
                "text": "以后所有解释都必须用中文。",
                "kind": "user_preference",
                "subject": "language",
                "evidence": 0,
                "actionable": True,
            }
        ],
        user_message="以后所有解释都用中文",
    )

    # 模型那条：能引用到那条用户消息（证据成立），但**引用换不来 stable**，
    # 所以它进不了常驻层。
    decision = _model_decisions(agent)[0]
    assert decision["save"]["verifiable"] is True
    assert decision["save"]["stable"] is False
    assert decision["action"] == "pending_confirmation"

    # extractor 那条：偏好被精确抓到并入库。
    extracted = [
        decision
        for decision in agent.last_memory_promotion_decisions
        if decision["candidate"]["source"] == "user_message"
    ]
    assert extracted and extracted[0]["action"] == "promote"
    assert "以后所有解释都用中文" in _durable_texts(agent)


def test_evidence_seq_resolves_only_visible_history_events():
    """模型引用的是稳定 seq，且只能引用它在 transcript 里看得到的条目。

    内部 trace（run_started / prompt_built / …）模型根本看不到，也不该被引用：
    可见集合 == 可引用集合，这条不用额外维护。
    """
    from repopilot.memory_promotion import resolve_evidence_seq

    events = [
        {"source": "history", "seq": 0, "event": "history_recorded",
         "history": {"role": "user", "content": "check the config"}},
        {"source": "trace", "seq": 3, "event": "prompt_built"},
        {"source": "history", "seq": 6, "event": "history_recorded",
         "history": {"role": "tool", "name": "read_file", "args": {"path": "pyproject.toml"}, "content": "..."}},
    ]

    assert resolve_evidence_seq(6, events) == 2       # 按 seq 找，不是按位置
    assert resolve_evidence_seq(0, events) == 0
    assert resolve_evidence_seq(3, events) is None    # 内部 trace，不可引用
    assert resolve_evidence_seq(999, events) is None  # 不存在
    assert resolve_evidence_seq(None, events) is None
    assert resolve_evidence_seq("abc", events) is None


def test_fabricated_convention_cannot_borrow_a_user_message(tmp_path):
    """端到端复现那个洞：用户偏好说的是 A，模型拿它给 B 当证据。

    模型能引用用户消息（seq 是可见的），但引用不能换来 stable——抽取器的偏好
    候选**就是从那条消息里切出来的**，消息当然支撑它；模型只是断言“这条消息
    说了 X”，不构成同一件事。
    """
    agent = _agent_with_model_proposal(
        tmp_path,
        [
            {
                "text": "Project tests must always be skipped before release.",
                "kind": "project_convention",
                "subject": "release tests",
                "evidence": 0,
                "actionable": True,
            }
        ],
        user_message="Always run the linter first. Also check the project tests setup in pyproject.",
    )

    decision = _model_decisions(agent)[0]

    assert decision["save"]["stable"] is False
    assert decision["action"] == "pending_confirmation"
    assert "Project tests must always be skipped before release." not in _durable_texts(agent)
