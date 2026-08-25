# P1-P4 Structured Tools, Event Log, Rules, And Coverage Results

Date: 2026-08-23
Branch: `RepoPilotv2.0`

## Scope

本轮在 P1/P2/P3 的基础上完成 P4：Coverage Manifest。

已有能力：

- P1：schema-first tool parameters + structured tool result。
- P2：append-only `event_log.jsonl` + trace/history projection。
- P3：path-based project rule resolver。

P4 新增能力：

- 从 `event_log.jsonl` 投影生成 `coverage_manifest`，不新增并行 mutable 状态。
- 在 `report.json` 中输出 `coverage_manifest`。
- 记录 `planned_files`、`inspected_files`、`modified_files`、`verified_files`、`failed_files`、`skipped_files`。
- 记录 `verification_commands` 和 `failed_tools`。
- 计算 `file_coverage_rate`、`verification_rate`、planned/inspected/modified/verified/failed/skipped counts。
- 根据 task status 和 failed files 计算 terminal state：`complete` / `partial` / `failed` / `unknown`。

## P4 Targeted Results

Command:

```bash
python -m pytest tests/test_coverage_manifest.py tests/test_agent_loop.py -q
```

Result:

```text
9 passed, 2 warnings in 5.00s
```

## P1-P4 Combined Regression

Command:

```bash
python -m pytest tests/test_safety_invariants.py::test_bound_tool_methods_delegate_into_tools_module tests/test_tool_executor.py tests/test_run_store.py tests/test_agent_loop.py tests/test_prompt_prefix.py tests/test_rules.py tests/test_context_manager.py tests/test_coverage_manifest.py -q
```

Result:

```text
34 passed, 2 warnings in 7.77s
```

## Full Suite Result

Command:

```bash
python -m pytest -q
```

Result:

```text
2 failed, 155 passed, 1 skipped, 3 warnings in 158.23s
```

Remaining failures are the same known non-P4 failures from previous runs:

- `tests/test_evaluator.py::test_run_task_anchors_paths_to_fixture_copy_even_inside_repo_workspace`
  - Windows `PermissionError` while deleting an existing benchmark fixture artifact: `.repopilot/runs/.../report.json`.
- `tests/test_repopilot.py::test_welcome_screen_keeps_box_shape_for_long_paths`
  - Existing dirty `repopilot/cli.py` welcome UI does not contain expected `(  o o  )`. P4 did not touch `repopilot/cli.py`.

Warnings are pytest cache write warnings under the current Windows/sandbox path. They did not affect assertions.

## Resume-Safe Metrics

| Metric | Result | Evidence |
| --- | ---: | --- |
| P4 targeted tests | 9/9 passed | `tests/test_coverage_manifest.py`, `tests/test_agent_loop.py` |
| P1-P4 combined regression | 34/34 passed | targeted combined command |
| Full suite non-failing tests | 155 passed, 1 skipped | full pytest command |
| Coverage manifest schema version | 1 | `coverage_manifest.schema_version` |
| Coverage file sets | 6 sets | planned, inspected, modified, verified, failed, skipped |
| Coverage metrics | 8 metrics | planned/inspected/modified/verified/failed/skipped counts, file coverage rate, verification rate |
| Verification command detection | passed | recognizes pytest/npm/go test style commands |
| Event-log projection design | passed | manifest generated from event log, not parallel runtime state |
| Report integration | passed | `report.json` includes `coverage_manifest` |
| Terminal state classification | passed | completed + failed files becomes `partial` |

## Interview Wording

可以这样说：

> 我在 RepoPilotv2.0 中把 agent run 从“自然语言 Done”升级为可审计的 coverage manifest。manifest 不是在 loop 里手动维护的第二份状态，而是从 append-only event log 投影生成；它记录 planned、inspected、modified、verified、failed、skipped 文件集合，并计算 file coverage rate 和 verification rate。这样一次 agent 任务能回答：它看了哪些文件，改了哪些文件，是否运行了验证，哪些文件失败或被跳过。

简历可以写成：

> 设计 event-sourced coverage manifest，从 agent event log 投影 planned/inspected/modified/verified/failed/skipped 文件集合，并输出 coverage/verification metrics；构建 9 个 P4 定向测试和 34 个 P1-P4 组合回归测试，验证 report 集成、终态分类、验证命令识别和失败文件归因。
