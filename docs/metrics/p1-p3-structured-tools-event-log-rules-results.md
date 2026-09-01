# P1-P3 Structured Tools, Event Log, And Rules Results

Date: 2026-08-23
Branch: `RepoPilotv2.0`

## Scope

本轮在已完成 P1/P2 的基础上继续完成 P3：

- P1：schema-first tool parameters + structured tool result。
- P2：append-only `event_log.jsonl` + trace/history projection。
- P3：轻量 path-based project rule resolver。

P3 新增能力：

- 支持项目级 `.repopilot/rules.json`。
- 支持 `include` / `exclude` / `rules: [{path, rule}]`。
- 支持 `**/*.py` 这类 glob，其中 `**` 按 zero-or-more path segments 处理。
- 从当前用户请求和最近工具历史里提取候选文件路径。
- 只注入命中的 project rules；无命中时不向 prompt 注入噪声。
- 在 prompt metadata 中记录 `candidate_paths`、`excluded_paths`、`matched_rules`、`matched_count`、`all_rule_chars`、`rendered_chars`。

## Targeted P3 Results

Command:

```bash
python -m pytest tests/test_rules.py tests/test_context_manager.py -q
```

Result:

```text
13 passed, 2 warnings in 1.79s
```

## P1/P2/P3 Combined Regression

Command:

```bash
python -m pytest tests/test_safety_invariants.py::test_bound_tool_methods_delegate_into_tools_module tests/test_tool_executor.py tests/test_run_store.py tests/test_agent_loop.py tests/test_prompt_prefix.py tests/test_rules.py tests/test_context_manager.py -q
```

Result:

```text
30 passed, 2 warnings in 6.40s
```

## Full Suite Result

Command:

```bash
python -m pytest -q
```

Result:

```text
2 failed, 151 passed, 1 skipped, 3 warnings in 159.45s
```

Remaining failures are the same known non-P3 failures from the previous run:

- `tests/test_evaluator.py::test_run_task_anchors_paths_to_fixture_copy_even_inside_repo_workspace`
  - Windows `PermissionError` while deleting an existing benchmark fixture artifact: `.repopilot/runs/.../report.json`.
- `tests/test_repopilot.py::test_welcome_screen_keeps_box_shape_for_long_paths`
  - Existing dirty `repopilot/cli.py` welcome UI does not contain expected `(  o o  )`. P3 did not touch `repopilot/cli.py`.

Warnings are pytest cache write warnings under the current Windows/sandbox path. They did not affect assertions.

## Resume-Safe Metrics

| Metric | Result | Evidence |
| --- | ---: | --- |
| P3 targeted tests | 13/13 passed | `tests/test_rules.py`, `tests/test_context_manager.py` |
| P1/P2/P3 combined regression | 30/30 passed | targeted combined command |
| Full suite non-failing tests | 151 passed, 1 skipped | full pytest command |
| Tool schemas | 7 tools | P1 structured tool schema |
| Rule config surface | 3 fields | `include`, `exclude`, `rules` |
| Rule metadata fields | 6 fields | `candidate_paths`, `excluded_paths`, `matched_rules`, `matched_count`, `all_rule_chars`, `rendered_chars` |
| Rule injection noise behavior | passed | no matched rules inject no `Project rules` section |
| Rule match from current request | passed | `repopilot/runtime.py` matches runtime rule |
| Rule match from tool history | passed | recent `read_file tests/test_agent_loop.py` triggers test rule |
| Exclude precedence | passed | `tests/fixtures/**` excluded before rule injection |

## Interview Wording

可以这样说：

> 我在 RepoPilotv2.0 中继续加入了 path-based project rules。它读取 `.repopilot/rules.json`，按 include/exclude 和 glob path 匹配当前任务涉及的文件，只把命中的规则注入 prompt。规则命中来自两类信号：当前用户请求里的路径，以及最近工具历史里的路径。metadata 会记录候选路径、被排除路径、命中规则和规则字符数，因此规则系统不是静态 prompt，而是可测试、可审计、可量化的上下文注入机制。

简历可以写成：

> 实现轻量级 path-based rule resolver，支持项目级 `include/exclude/rules` 配置，基于当前请求与工具历史动态注入最小必要规则；构建 13 个规则/上下文定向测试和 30 个 P1-P3 组合回归测试，验证规则匹配、排除优先级、prompt 降噪与 metadata 可观测性。
