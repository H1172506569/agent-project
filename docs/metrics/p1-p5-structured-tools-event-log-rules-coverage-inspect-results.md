# P1-P5 Structured Tools, Event Log, Rules, Coverage, And Inspect Results

Date: 2026-08-23
Branch: `RepoPilotv2.0`

## Scope

本轮在 P1-P4 基础上完成 P5：Review/Inspect 专用模式。

已有能力：

- P1：schema-first tool parameters + structured tool result。
- P2：append-only `event_log.jsonl` + trace/history projection。
- P3：path-based project rule resolver。
- P4：event-sourced coverage manifest。

P5 新增能力：

- 新增 deterministic file selection：显式 paths 优先；无 paths 时可从 `git diff --name-only` 选择。
- 新增 bounded read-only per-file inspection loop：每个文件启动受限 child agent，仅允许 `read_file` / `search`。
- 新增 structured finding schema：`path`、`line`、`severity`、`category`、`snippet`、`rationale`、`suggestion`。
- 支持 `<finding>{JSON}</finding>` 结构化输出解析。
- 新增 `agent.inspect(paths)` runtime API。
- 新增 CLI `--inspect path...`。
- 输出 `.repopilot/inspections/inspection-*.json`，包含 selected files、file results、findings、summary 和 rendered findings。

## P5 Targeted Results

Command:

```bash
python -m pytest tests/test_findings.py tests/test_inspection.py tests/test_public_api_contract.py -q
```

Result:

```text
10 passed, 2 warnings in 1.04s
```

## P1-P5 Combined Regression

Command:

```bash
python -m pytest tests/test_safety_invariants.py::test_bound_tool_methods_delegate_into_tools_module tests/test_tool_executor.py tests/test_run_store.py tests/test_agent_loop.py tests/test_prompt_prefix.py tests/test_rules.py tests/test_context_manager.py tests/test_coverage_manifest.py tests/test_findings.py tests/test_inspection.py tests/test_public_api_contract.py -q
```

Result:

```text
44 passed, 2 warnings in 9.46s
```

## Full Suite Result

Command:

```bash
python -m pytest -q
```

Result:

```text
2 failed, 161 passed, 1 skipped, 3 warnings in 164.95s
```

Remaining failures are the same known non-P5 failures from previous runs:

- `tests/test_evaluator.py::test_run_task_anchors_paths_to_fixture_copy_even_inside_repo_workspace`
  - Windows `PermissionError` while deleting an existing benchmark fixture artifact: `.repopilot/runs/.../report.json`.
- `tests/test_repopilot.py::test_welcome_screen_keeps_box_shape_for_long_paths`
  - Existing dirty `repopilot/cli.py` welcome UI does not contain expected `(  o o  )`. P5 only added `--inspect`; it did not change welcome rendering.

Warnings are pytest cache write warnings under the current Windows/sandbox path. They did not affect assertions.

## Resume-Safe Metrics

| Metric | Result | Evidence |
| --- | ---: | --- |
| P5 targeted tests | 10/10 passed | `tests/test_findings.py`, `tests/test_inspection.py`, public API parser test |
| P1-P5 combined regression | 44/44 passed | targeted combined command |
| Full suite non-failing tests | 161 passed, 1 skipped | full pytest command |
| Structured finding required fields | 7 fields | path, line, severity, category, snippet, rationale, suggestion |
| Inspect child tools | 2 tools | `read_file`, `search` only |
| Inspect loop boundary | read-only + bounded | child agent uses `approval_policy=never`, `read_only=True`, `max_steps` |
| Inspection report schema version | 1 | `.repopilot/inspections/inspection-*.json` |
| Finding anchoring metric | present | `anchored_finding_count` |
| Per-file status metrics | present | selected/completed/failed/finding counts |
| CLI inspect mode | passed | `--inspect src/app.py` parser test |

## Interview Wording

可以这样说：

> 我在 RepoPilotv2.0 中实现了一个轻量 review/inspect 垂直模式。它不是让通用 agent 自由探索，而是先用确定性逻辑选择文件，再为每个文件启动 bounded read-only child agent，只开放 `read_file` 和 `search`。模型输出必须是 `<finding>{JSON}</finding>`，finding 包含路径、行号、严重级别、类别、代码片段、原因和建议。最终生成 inspection report，统计 selected/completed/failed/finding/anchored finding 等指标。

简历可以写成：

> 借鉴 OpenCodeReview 的 deterministic per-file pipeline，实现 RepoPilot inspect 模式：确定性文件选择、只读子 agent、structured finding schema 和 inspection report；构建 10 个 P5 定向测试和 44 个 P1-P5 组合回归测试，验证 finding 解析、路径边界、只读工具集、CLI inspect 入口和 anchored finding 指标。
