# P6.5 Adaptive Context Compression 结果

## 本次完成内容

这次补齐了 P6 之后缺的 runtime 自动触发机制：

- 60% 阈值触发异步压缩：当 prompt usage ratio >= 60% 且 < 80% 时，当前轮不阻塞，后台线程压缩当前 history，并把 summary 持久化到 session。
- 80% 阈值触发同步压缩：当 prompt usage ratio >= 80% 时，runtime 先同步压缩 history，持久化 summary，然后重新 build prompt，再请求模型。
- runtime 持久化 compressed history summary：压缩结果写入 `session["context_compression"]`，包含 `status/mode/source_history_length/source_history_digest/rendered/details/raw_chars/rendered_chars` 等字段。
- 后续 prompt 复用 summary：`ContextManager` 会校验 digest，确认 summary 没过期后优先使用 persisted summary，并把 summary 后新增的 history tail 拼接进去。

## 代码位置

- `repopilot/runtime.py`: adaptive scheduler、async thread、sync compression、session persistence。
- `repopilot/context_manager.py`: persisted summary reuse。
- `repopilot/context_compression.py`: tool-round compression backend。
- `repopilot/evaluation/adaptive_context_compression.py`: 阈值实验。
- `scripts/run_adaptive_context_compression_experiment.py`: 实验入口。

## 实验设计

| Scenario | 目的 |
| --- | --- |
| `no_trigger` | prompt usage 低于 60%，不触发压缩。 |
| `async_60` | usage 落在 60%-80%，触发异步压缩，当前 prompt 不阻塞。 |
| `sync_80` | usage 超过 80%，同步压缩并重新 build prompt。 |
| `persisted_reuse` | 已有 summary 后新增 history tail，验证 summary 可复用且新 tail 不丢。 |

## 实验结果

| Scenario | Usage before | Action | Prompt before | Prompt after | Summary status | Persisted used | Current request preserved |
| --- | ---: | --- | ---: | ---: | --- | --- | --- |
| `no_trigger` | 17.7% | `none` | 248 | 248 | `none` | False | True |
| `async_60` | 66.8% | `async_scheduled` | 601 | 601 | `ready` | False | True |
| `sync_80` | 91.9% | `sync_compressed` | 827 | 610 | `ready` | True | True |
| `persisted_reuse` | 79.8% | `async_scheduled` | 718 | 718 | `ready` | True | True |

## 关键结论

- 60% 异步压缩验证通过：`async_60` usage 为 66.8%，action=`async_scheduled`，后台完成后 summary status=`ready`。
- 80% 同步压缩验证通过：`sync_80` usage 为 91.9%，action=`sync_compressed`。
- 同步压缩 prompt 从 827 降到 610，降幅 26.2%。
- persisted summary reuse 验证通过：已有 summary 被复用，同时新增 history tail 会继续出现在 prompt 中。
- 所有场景都保留了当前用户请求，避免压缩破坏本轮任务语义。

## 测试结果

- Targeted P6/P6.5 tests: `python -m pytest tests/test_context_compression.py -q` -> `7 passed`。
- P1-P6.5 regression: `python -m pytest tests/test_tool_executor.py tests/test_run_store.py tests/test_agent_loop.py tests/test_prompt_prefix.py tests/test_rules.py tests/test_context_manager.py tests/test_coverage_manifest.py tests/test_findings.py tests/test_inspection.py tests/test_public_api_contract.py tests/test_context_compression.py -q` -> `50 passed`。

## 简历可用表述

> 为 coding agent 设计 adaptive context compression scheduler：当 prompt 使用率达到 60% 时异步预压缩 history，达到 80% 时同步压缩并重新构建 prompt；压缩后的 tool-round summary 持久化到 session，并通过 digest 校验在后续轮次复用。

> 在 4 组 runtime 阈值实验中验证 no-trigger / async / sync / persisted-reuse 行为；同步压缩场景将 prompt 从 827 降到 610，降幅 26.2%，同时保证当前用户请求不被裁剪破坏。

面试解释重点：60% 异步压缩解决的是 latency，不阻塞当前模型请求；80% 同步压缩解决的是安全边界，避免 prompt 接近预算上限时继续膨胀；持久化 summary 解决的是复用问题，避免每轮重复压缩同一段历史。
