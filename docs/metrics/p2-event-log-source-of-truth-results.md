# P2 Event Log Source of Truth 完整化说明

## 为什么之前不算完整 P2

之前 P2 已经实现了 `event_log.jsonl`、`project_history(events)`、`project_trace(events)` 和 event log metrics，但 prompt 构建主路径仍然直接读取 `session["history"]`。

这意味着当时的状态是：

- `session["history"]`: runtime 主数据。
- `event_log.jsonl`: 旁路审计日志，可以投影出 history/trace，但不是 prompt 的事实来源。

这个设计能做审计，但不能说 event log 是 source of truth。你指出的 `ContextManager` 直接读取 session history 是准确问题。

## 现在改成什么

现在当前 run 的 prompt/history 主路径改成：

```text
run_store.load_events(current_task_state.run_id)
  -> project_history(events)
  -> ContextManager history section / project rules matching / history_text
```

也就是：

- run 内：`event_log.jsonl` 是事实来源。
- 非 run 场景、旧 session、测试直接构造历史：回退 `session["history"]`。
- `session["history"]` 仍保留为兼容缓存和跨 run 会话恢复数据，但不是当前 run prompt 的主事实来源。

## 关键代码变化

- `repopilot/runtime.py`
  - 新增 `RepoPilot.projected_history()`。
  - 新增 `RepoPilot.history_source()`。
  - `history_text()` 改为读取 `projected_history()`。
  - repeated tool call 检测改为读取 `projected_history()`。
  - adaptive context compression 的 history snapshot 改为读取 `projected_history()`。
  - report 增加 `projected_history` 和 `history_source`。

- `repopilot/context_manager.py`
  - 新增 `_history_items()`。
  - `_render_sections_without_reduction()` 使用 `_history_items()`。
  - `_resolve_project_rules()` 使用 `_history_items()`。
  - `_render_history_section()` 使用 `_history_items()`。
  - prompt metadata 的 `history.source` 标记为 `event_log` 或 `session`。

## 为什么还保留 session fallback

不能直接删除 `session["history"]`，原因有三个：

- 用户可能从旧 session 恢复，旧 session 没有 event log。
- 很多单元测试和非 run 调用会直接构造 `agent.record(...)`，这些场景没有 `current_task_state`。
- session 仍承担跨 run 会话恢复和兼容缓存角色。

所以最终设计不是“不允许 session history 存在”，而是“当前 run 的 prompt 读取不以 session history 为主”。

## 防回归测试

新增测试：

```text
tests/test_agent_loop.py::test_prompt_history_is_projected_from_event_log_not_session_cache
```

测试逻辑：

1. 在 `session["history"]` 里塞入一条 session-only 污染历史。
2. 启动真实 `agent.ask()` run。
3. prompt 中不允许出现这条污染历史。
4. prompt metadata 必须显示 `history.source == "event_log"`。
5. report 中的 `projected_history` 必须等于 `project_history(events)`。

这个测试能防止未来代码又退回直接读 `session["history"]`。

## 测试结果

- P2 相关测试：
  - `python -m pytest tests/test_agent_loop.py tests/test_context_manager.py tests/test_run_store.py -q`
  - 结果：`21 passed`

- P1-P6.5 回归：
  - `python -m pytest tests/test_tool_executor.py tests/test_run_store.py tests/test_agent_loop.py tests/test_prompt_prefix.py tests/test_rules.py tests/test_context_manager.py tests/test_coverage_manifest.py tests/test_findings.py tests/test_inspection.py tests/test_public_api_contract.py tests/test_context_compression.py -q`
  - 结果：`51 passed`

## 面试解释

可以这样说：

> 我最开始只是把 event log 做成审计旁路，可以从里面投影 history 和 trace，但 prompt 构建仍然读 session history。后来我把 P2 补成 event-log source of truth：当前 run 中 ContextManager 不直接读 session，而是通过 `projected_history()` 从 `event_log.jsonl` 投影 history；session history 只作为旧 session 和非 run 场景的 fallback。为了防止回退，我加了 session-only poison 测试，验证 prompt 只消费 event log 投影结果。

## 简历可用表述

> 将 agent 运行历史从 session 缓存迁移为 event-log source of truth：所有当前 run 的 prompt history、project rules path matching、history_text 和 report projected history 均由 `event_log.jsonl -> project_history(events)` 投影生成；保留 session history 作为旧会话 fallback，并通过 session-only poison regression test 防止 prompt 重新依赖旁路状态。
