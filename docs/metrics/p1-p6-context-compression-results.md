# P6 上下文压缩实验结果与简历数据

## 重要更正

上一版四组实验是 deterministic/offline ablation：它没有调用 DeepSeek，只验证了上下文压缩策略和指标管线，所以 DeepSeek API 平台调用数为 0。这个版本已补充真实 DeepSeek LLM compression 实验：在 `tool_round_compression_memory_on` 和 `tool_round_compression_memory_off` 两组中，旧工具轮次由 DeepSeek 实际压缩，实验记录 `llm_call_count=2`，`llm_fallback_count=0`。

## 本次 P6 改了什么

P6 在 RepoPilot 里新增了两层能力：

- deterministic tool-round compressor：用于单元测试和稳定回归，不依赖外部 API。
- DeepSeek LLM compressor：用于真实实验，把旧工具历史交给 DeepSeek 压缩成 JSON，再解析成结构化 breadcrumb。

压缩后的 breadcrumb 会保留 `tool name`、`path/command`、`status`、`exit_code`、失败信号等字段；最近的 active 工具轮次仍然原样保留。

对应代码：

- `repopilot/context_compression.py`: deterministic compressor + LLM compressor。
- `repopilot/context_manager.py`: runtime feature flag 接入 deterministic `tool_round_compression`。
- `repopilot/evaluation/context_compression.py`: 支持 `compression_mode=deterministic|llm` 的四组实验。
- `scripts/run_context_compression_experiment.py`: 支持 `--compression-mode llm --provider deepseek`。

## 四组真实 LLM 实验设计

实验使用 2x2 ablation：`context strategy` 和 `memory` 两个变量交叉。只有 tool-round compression 两组会调用 DeepSeek，因为 section clipping 本身没有压缩模型调用。

| Group | Context strategy | Memory | DeepSeek calls | 目的 |
| --- | --- | --- | ---: | --- |
| `section_clipping_memory_on` | `section_clipping` | True | 0 | 旧策略 + memory 的强基线。 |
| `section_clipping_memory_off` | `section_clipping` | False | 0 | 旧策略在无 memory 时的退化情况。 |
| `tool_round_compression_memory_on` | `llm_tool_round_compression` | True | 1 | DeepSeek LLM 压缩 + memory 的最优组合。 |
| `tool_round_compression_memory_off` | `llm_tool_round_compression` | False | 1 | 验证 DeepSeek LLM 压缩本身是否有独立收益。 |

## 实验结果

| Group | Prompt chars | Active rounds | Compressed rounds | Repeated reads | Pass rate | LLM calls | Fallback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `section_clipping_memory_on` | 825 | 0 | 0 | 3 | 50% | 0 | False |
| `section_clipping_memory_off` | 691 | 0 | 0 | 4 | 25% | 0 | False |
| `tool_round_compression_memory_on` | 973 | 2 | 16 | 0 | 100% | 1 | False |
| `tool_round_compression_memory_off` | 839 | 2 | 16 | 1 | 75% | 1 | False |

## 关键结论

- 真实 DeepSeek LLM compression 总调用数：2；fallback 次数：0。
- 最佳组是 `tool_round_compression_memory_on`：pass rate 100%，repeated reads 0。
- DeepSeek LLM tool-round compression 平均 pass rate 从 section clipping 的 37.5% 提升到 87.5%。
- 平均 repeated reads 从 3.5 降到 0.5。
- memory 仍然有独立价值：同样使用 LLM compression 时，memory on 的 pass rate 高于 memory off。

## 为什么还保留 deterministic compressor

真实 LLM compression 适合做效果实验和简历数据，但不适合直接放进所有单元测试：它有网络、费用、延迟、输出不稳定等问题。因此 P6 保留 deterministic compressor 作为 runtime 默认可测策略，同时在 benchmark 里增加真实 DeepSeek compression，用真实 API 调用验证效果。

## 测试结果

- P6 targeted tests: `python -m pytest tests/test_context_compression.py -q` -> `4 passed`。
- Real DeepSeek LLM experiment: `python scripts\run_context_compression_experiment.py --compression-mode llm --provider deepseek` -> `llm_calls=2, fallback=0`。

## 简历可用表述

> 设计并实现 coding agent 的三段式上下文压缩机制，将历史工具调用按 frozen / compressed / active 分区处理；使用 DeepSeek 对旧工具轮次进行 LLM compression，并将返回结果解析为结构化 breadcrumb，保留文件路径、命令、exit code 和失败状态。

> 构建 2x2 ablation benchmark 对比 section clipping 与 DeepSeek LLM tool-round compression、memory on/off 四组配置；真实 DeepSeek 压缩实验调用 2 次，fallback 0 次，将平均任务通过率从 37.5% 提升到 87.5%，平均 repeated reads 从 3.5 降到 0.5。

面试解释重点：P6 不是单纯把历史丢给模型总结，而是 `deterministic pre-filter + LLM structured compression + parser validation + fallback`。这样既能利用大模型做语义压缩，又能把结果变成可测试、可统计、可回放的结构化上下文。
