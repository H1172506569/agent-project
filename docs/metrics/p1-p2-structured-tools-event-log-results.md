# P1/P2 Structured Tools And Event Log Test Results

Date: 2026-08-23
Branch: `feature/p1-p2-structured-tools-event-log`

## Scope

本轮只改 P1/P2：

- P1：工具协议从纯文本结果向结构化工具结果演进，保留模型可读 `content`，新增机器可读 `data`。
- P1：为 7 个工具补充 machine-readable parameter schema，并把 schema 纳入 `tool_signature`。
- P1：`run_shell` 状态不再从字符串正则提取 `exit_code`，而是读取 `ToolOutput.data["exit_code"]`。
- P2：新增 `event_log.jsonl` 作为统一事件流，trace/history/memory 都写入 event log。
- P2：新增 projection：从 event log 投影 `trace`、`history`，并计算 report 指标。

## Targeted Regression Results

Command:

```bash
python -m pytest tests/test_safety_invariants.py::test_bound_tool_methods_delegate_into_tools_module tests/test_tool_executor.py tests/test_run_store.py tests/test_agent_loop.py tests/test_prompt_prefix.py -q
```

Result:

```text
17 passed, 2 warnings in 4.47s
```

Warnings were pytest cache write warnings under the current Windows/sandbox path. They did not affect assertions.

## Full Suite Result

Command:

```bash
python -m pytest -q
```

Result:

```text
2 failed, 145 passed, 1 skipped, 3 warnings in 163.03s
```

Remaining failures observed after P1/P2 fixes:

- `tests/test_evaluator.py::test_run_task_anchors_paths_to_fixture_copy_even_inside_repo_workspace`
  - Failure: Windows `PermissionError` while deleting an existing benchmark fixture run artifact: `.repopilot/runs/.../report.json`.
  - Assessment: environment/fixture cleanup issue, not caused by structured tool result or event log assertions.
- `tests/test_repopilot.py::test_welcome_screen_keeps_box_shape_for_long_paths`
  - Failure: expected welcome text `(  o o  )` not present.
  - Assessment: current dirty `repopilot/cli.py` already changes welcome UI behavior; this file was not touched in P1/P2.

## Resume-Safe Metrics

These are the numbers that can be used later in resume/interview wording, with the caveat that full-suite green requires separately resolving the two unrelated failures above.

| Metric | Result | Evidence |
| --- | ---: | --- |
| P1/P2 targeted regression pass count | 17/17 passed | targeted pytest command |
| Full suite non-failing tests | 145 passed, 1 skipped | full pytest command |
| Tools with machine-readable parameter schema | 7 | `list_files`, `read_file`, `search`, `run_shell`, `write_file`, `patch_file`, `delegate` |
| Structured shell status regression | passed | mocked text says `exit_code: 0`, structured data says `exit_code: 9`, executor reports error |
| Event log trace projection parity | passed | `project_trace(event_log)` equals `trace.jsonl` for fixed FakeModel tool loop |
| Event log history projection parity | passed | `project_history(event_log)` equals session history slice for fixed FakeModel tool loop |
| Report event-log metrics | present | `event_count`, `trace_event_count`, `history_event_count`, `memory_event_count`, `structured_tool_result_count` |

## Interview Wording

可以这样说：

> 我把 RepoPilot 的工具边界从纯自然语言协议推进到 schema-first + structured tool result。模型仍然看到兼容的文本结果，但 runtime/trace/report 消费的是机器字段，例如 `run_shell` 的 exit code 不再靠正则从 stdout 里猜。与此同时，我加入了 append-only event log，把 trace、history、memory 更新统一落成事件，再通过 projection 生成不同视图。这样 agent loop 更容易回放、测试和接入 provider-native tool calling。

更具体的数据表达：

> 我为 7 个工具补齐机器可读参数 schema，并加入 17 个 P1/P2 定向回归断言；其中包括结构化 shell 状态解析、event log 到 trace/history 的投影一致性，以及 report 级运行指标。全量测试当前 145 passed / 1 skipped，剩余 2 个失败来自既有 welcome UI 断言和 Windows fixture 清理权限，需要单独处理。
