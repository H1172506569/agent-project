# RepoPilot 项目快速掌握、简历写法与代码映射

本文档根据当前仓库源码、你的简历 `胡昕简历.pdf`、以及 `2-repopilot.pdf` 中更完整的项目介绍和实验数据重写。`2-repopilot.pdf` 第 2 页的 v2.0 项目描述质量更高，后文简历版本优先采用该口径；同时运行方式和 provider 细节以当前仓库代码为准。

注意：`2-repopilot.pdf` 中包含临时 API key 页面，本文档不会引用或复述任何 key。

## 1. 项目定位

**RepoPilot 是一个面向本地代码仓库长链路任务的代码智能体 Harness。**

它不是单纯的聊天机器人，也不是简单套一层大模型 API，而是把 coding agent 放进一个可控、可恢复、可审计、可评测的运行时系统里。核心关注点是：

- 模型如何接入
- 工具如何被安全调用
- 多轮任务上下文如何治理
- 任务中断后如何恢复
- 多轮记忆如何结构化管理
- 每次运行如何复盘和归因
- agent 行为如何用 benchmark 验证

一句话面试版：

> RepoPilot 面向代码仓库长链路任务开发本地代码 agent harness，围绕模型接入、工具调用、上下文管理、任务恢复、结构化记忆、运行审计和评测闭环做系统化设计，重点解决多轮任务里的 prompt 膨胀、重复读文件、状态丢失、工具副作用不可控和结果难复盘的问题。

## 2. 项目数据指标

**简历主口径必须使用 `2-repopilot.pdf` 第 2 页 version 2.0 的数据。** 这不是说当前仓库代码是 version 1.0；当前仓库已经包含 v2.0 的关键优化，尤其是结构化记忆、checkpoint/resume 和评测分层。仓库内 `benchmarks/results/main-resume-repro-2026-06-07/` 的 JSON/Markdown 结果用于面试时解释“数据怎么来的”和“怎么复现”，但简历 bullet 不要再混用旧版口径或当前复跑口径。

| 方向 | 可写进简历的数据 | 复现/证明位置 |
| --- | --- | --- |
| Agent Harness 能力 | 支持 2 类模型后端、7 类工具、3 类运行工件 | `repopilot/cli.py`、`repopilot/tools.py`、`repopilot/run_store.py` |
| 固定回归任务 | 12 个任务，pass rate 100%，within budget 100%，verifier pass rate 100% | `harness-regression-v2.json` |
| 上下文治理 | 12 组长上下文配置，平均 prompt 从 7082 压到 5664，平均压缩率 16.19%，最高压缩率 33.28%，保证当前请求不被裁坏 | `context-ablation-v2.json` |
| 记忆收益 | 12 个记忆依赖任务；follow-up 阶段重复读文件从 60 次降到 0 次，不再需要额外工具调用重新确认已知事实 | `memory-ablation-v2.json` |
| 恢复机制 | 覆盖 10 个恢复场景；workspace 漂移识别率 100%，没有出现误信旧状态继续执行的情况 | `recovery-ablation-v2.json` |
| 审计工件 | 每次运行落盘 `task_state.json`、`trace.jsonl`、`report.json` 三类工件 | `repopilot/run_store.py` |

补充说明：当前仓库复跑结果里，上下文治理指标是 `6994 -> 5576`、`16.36%`、`33.59%`。这可以作为面试解释“后续代码模板变化导致字符数略有差异”的补充，不应替代 version 2.0 简历 bullet。

## 3. Version 2.0 优化了什么

`2-repopilot.pdf` 里写得很明确：**version 2.0 优化记忆模块，支撑面试深度讲。** 但它不只是“多加一个 memory 字段”，而是把多轮 agent 的状态管理做得更系统。

### 3.1 相比 version 1.0 的核心变化

| 方向 | version 1.0 更偏向 | version 2.0 优化后 |
| --- | --- | --- |
| 项目定位 | 本地代码 Agent Harness，强调上下文、记忆、工具、安全、评测 | 本地代码智能体 Harness，进一步强调长链路任务中的状态恢复、结构化记忆、运行审计和评测分层 |
| 记忆模块 | 任务摘要、文件摘要、会话笔记，减少重复读取 | 任务摘要、文件摘要、过程笔记、相关记忆召回、长期记忆分层，专门解决 follow-up 重复确认已知事实 |
| 记忆数据 | 重复读文件从 8 次降到 3 次，平均工具步数从 0.67 降到 0.25，正确率从 66.7% 到 100% | follow-up 阶段重复读文件从 60 次降到 0 次，不再需要额外工具调用重新确认已知事实 |
| 上下文治理 | 12 组配置，平均 prompt 从 6964 压到 5418，平均压缩率 18.01%，最高 35.63% | 12 组配置，平均 prompt 从 7082 压到 5664，平均压缩率 16.19%，最高 33.28%，强调当前请求不被裁坏 |
| 恢复机制 | version 1.0 简历里不是主线 | version 2.0 明确加入 checkpoint / resume，覆盖 10 个恢复场景，workspace 漂移识别率 100% |
| 评测口径 | 固定 benchmark、运行审计、provider 对照实验 | 拆成 harness regression、上下文治理、记忆收益、恢复正确性，避免模型能力、系统能力和运行观测混成一个总分 |

### 3.2 v2.0 记忆模块具体优化

你面试时可以把 v2.0 的记忆优化讲成 5 点：

1. **工作记忆更结构化**：不再只保存聊天历史，而是单独维护当前任务摘要、最近文件、文件短摘要和过程笔记。
2. **文件摘要带 freshness 校验**：读文件后保存短摘要和内容指纹；文件被修改后旧摘要失效，避免误信过期信息。
3. **过程笔记独立出来**：把 partial_success、工具失败、下一步需要检查什么这类过程状态沉淀成短笔记，而不是混在长历史里。
4. **相关记忆召回更明确**：根据标签、关键词重叠和时间顺序召回当前请求相关的记忆，而不是把所有 notes 都塞进 prompt。
5. **长期记忆落盘**：把项目约定、关键决策、依赖事实、用户偏好这类稳定信息放到 `.repopilot/memory/`，和当前会话的临时工作记忆分开。

代码对应：

| v2.0 优化点 | 代码 |
| --- | --- |
| 默认 memory state 分层 | `repopilot/features/memory.py:43` |
| DurableMemoryStore 长期记忆 | `repopilot/features/memory.py:59` |
| 文件 freshness 校验 | `repopilot/features/memory.py:493` |
| read_file 结果摘要化 | `repopilot/features/memory.py:505` |
| 相关记忆召回 | `repopilot/features/memory.py:519` |
| memory 渲染进 prompt | `repopilot/features/memory.py:561` |
| LayeredMemory 对外接口 | `repopilot/features/memory.py:599` |
| 工具执行后更新记忆 | `repopilot/runtime.py:388` |
| 显式长期记忆 promotion | `repopilot/runtime.py:493` |
| 记忆收益实验 | `benchmarks/results/main-resume-repro-2026-06-07/memory-ablation-v2.json` |

### 3.3 你应该怎么回答“2.0 优化了哪些”

可以直接这样说：

> 2.0 主要优化的是记忆模块和围绕记忆的评测口径。1.0 里已经有上下文管理、工具安全和基础记忆，但 2.0 把记忆拆得更清楚：任务摘要、文件摘要、过程笔记、相关记忆召回和长期记忆分开管理；文件摘要还绑定 freshness，文件变了就不再信旧摘要。这样在 follow-up 任务里，agent 不需要反复读同一个文件确认已经知道的事实。实验上，12 个记忆依赖任务里，follow-up 阶段重复读文件从 60 次降到 0 次。同时 2.0 把 checkpoint/resume 和评测分层也写成了简历主线，能更深入地讲长任务恢复和 benchmark 闭环。

## 4. 技术栈

| 维度 | 内容 |
| --- | --- |
| 语言 | Python 3.10+ |
| 工程形式 | Python package + CLI |
| CLI 入口 | `repopilot = "repopilot.cli:main"` |
| 模型后端 | 当前代码支持 DeepSeek、OpenAI-compatible、Anthropic-compatible、Ollama |
| Agent 能力 | Tool Calling、Context Management、Checkpoint / Resume、Layered Memory、Run Trace |
| 测试与评测 | pytest、固定 benchmark、ablation experiments |
| 本地状态 | `.repopilot/sessions/`、`.repopilot/runs/`、`.repopilot/memory/` |

当前代码里 `DEFAULT_PROVIDER = "deepseek"`，这和 `2-repopilot.pdf` 部分安装说明里“默认 openai provider + Right Code”的说法有版本差异。简历和面试讲项目能力时不受影响；真正演示运行时以当前代码和 README 为准。

## 5. 项目主链路

一次用户请求进入 RepoPilot 后，大致链路如下：

```text
用户 CLI / REPL 输入
  -> cli.build_agent()
  -> RepoPilot runtime 装配 workspace / session / tools / model client
  -> AgentLoop.run()
  -> ContextManager.build() 拼接 prompt
  -> model_client.complete() 请求模型
  -> RepoPilot.parse() 解析 <tool> / <final>
  -> ToolExecutor.execute() 校验、审批、执行工具
  -> 更新 history / memory / task_state / trace / checkpoint
  -> 继续下一轮，或生成 final answer 和 report
```

核心文件：

| 环节 | 代码 |
| --- | --- |
| CLI 参数解析 | `repopilot/cli.py:273` `build_arg_parser()` |
| 启动入口 | `repopilot/cli.py:311` `main()` |
| provider 选择 | `repopilot/cli.py:68` `_effective_provider()`，`repopilot/cli.py:82` `_effective_model()` |
| model client 装配 | `repopilot/cli.py:121` `_build_model_client()` |
| runtime 装配 | `repopilot/cli.py:225` `build_agent()` |
| RepoPilot 门面 | `repopilot/runtime.py:53` `RepoPilot` |
| agent 主循环 | `repopilot/agent_loop.py:123` `AgentLoop.run()` |
| prompt 构造 | `repopilot/context_manager.py:78` `ContextManager.build()` |
| 模型请求 | `repopilot/agent_loop.py:44` `_request_model()` |
| tool/final 解析 | `repopilot/runtime.py:645` `RepoPilot.parse()` |
| 工具执行 | `repopilot/tool_executor.py:45` `ToolExecutor.execute()` |
| 成功收尾 | `repopilot/agent_loop.py:95` `_finish_success()` |
| report 生成 | `repopilot/runtime.py:550` `build_report()` |

## 6. 你应该如何快速掌握代码

### 6.1 先抓主线

先读这 5 个文件，不要一开始陷入所有测试和评测脚本：

| 顺序 | 文件 | 目标 |
| --- | --- | --- |
| 1 | `repopilot/cli.py` | 用户命令如何变成 agent runtime |
| 2 | `repopilot/runtime.py` | `RepoPilot` 持有哪些状态和能力 |
| 3 | `repopilot/agent_loop.py` | 多轮 agent loop 如何推进 |
| 4 | `repopilot/tools.py` | 模型能申请哪些工具 |
| 5 | `repopilot/tool_executor.py` | 工具调用如何被安全执行 |

读完后，你必须能不看资料讲出：

> CLI 怎么组装 agent，runtime 怎么进主循环，context 怎么拼 prompt，模型怎么返回 tool/final，工具怎么执行，记忆怎么更新，trace/report 怎么落盘。

### 6.2 再看四个亮点模块

| 模块 | 文件 | 面试价值 |
| --- | --- | --- |
| 长上下文治理 | `repopilot/context_manager.py` | 能讲 prompt 不是拼字符串，而是按预算调度 |
| 结构化记忆 | `repopilot/features/memory.py` | 能讲为什么减少重复读文件 |
| Checkpoint / Resume | `repopilot/checkpoint.py` | 能讲长任务恢复和旧状态校验 |
| Benchmark / Evaluation | `repopilot/evaluation/` | 能解释简历指标怎么来的 |

### 6.3 最后用测试反推边界

优先看这些测试：

| 测试 | 覆盖点 |
| --- | --- |
| `tests/test_repopilot.py:41` | 最小 agent 工具调用到 final 的闭环 |
| `tests/test_repopilot.py:272` | 重复工具调用拦截 |
| `tests/test_repopilot.py:1030` | run artifacts 持久化 |
| `tests/test_repopilot.py:1068` | secret 脱敏 |
| `tests/test_repopilot.py:1104` | prompt budget metadata |
| `tests/test_repopilot.py:1216` | checkpoint resume prompt |
| `tests/test_context_manager.py:39` | 上下文裁剪策略 |
| `tests/test_memory.py:93` | durable memory |
| `tests/test_safety_invariants.py:146` | shell env allowlist |
| `tests/test_safety_invariants.py:192` | delegate 只读 |
| `tests/test_evaluator.py:82` | benchmark 成功定义 |

## 7. 核心模块怎么讲

### 7.1 Agent Harness 架构

面试回答：

> 我把 RepoPilot 定位成本地代码 agent harness，而不是普通 agent demo。因为真实 coding agent 的难点不是让模型回答一次，而是把模型放到一个可控的执行系统里：要定义任务生命周期、工具权限、上下文预算、状态恢复、运行审计和评测方式。RepoPilot 的 runtime 负责把模型调用、工具执行、session 状态、checkpoint 和 run artifact 串起来，形成一条可复盘的执行链路。

代码映射：

| 点 | 代码 |
| --- | --- |
| Runtime 门面 | `repopilot/runtime.py:53` |
| 主循环 | `repopilot/agent_loop.py:123` |
| Task 状态 | `repopilot/task_state.py:28` |
| Session | `repopilot/session_store.py:7` |
| Run artifacts | `repopilot/run_store.py:18` |

### 7.2 长上下文治理

面试回答：

> 我没有把历史、工具结果和当前请求直接拼成一个大 prompt，而是把上下文拆成 prefix、memory、relevant_memory、history、current_request 几段。每段有预算和收缩顺序，超预算时优先压缩相关记忆和旧历史，最近历史保留更多细节，当前请求永远不裁。这样可以解决长链路任务里 prompt 膨胀和当前约束被裁坏的问题。

数据：

- 12 组长上下文配置
- 平均 prompt 从 7082 压到 5664
- 平均压缩率 16.19%
- 最高压缩率 33.28%
- 保证当前请求不被裁坏

代码映射：

| 点 | 代码 |
| --- | --- |
| section 与预算 | `repopilot/context_manager.py:60` |
| prompt 构造 | `repopilot/context_manager.py:78` |
| relevant memory 裁剪 | `repopilot/context_manager.py:243` |
| history 压缩 | `repopilot/context_manager.py:297` |
| 旧历史去重和摘要 | `repopilot/context_manager.py:361` |
| metadata 落盘 | `repopilot/context_manager.py:456` |
| 实验结果 | `benchmarks/results/main-resume-repro-2026-06-07/context-ablation-v2.json` |

### 7.3 结构化记忆系统

面试回答：

> RepoPilot 的记忆设计核心是让模型在多轮任务里别反复做已经做过的事。我把记忆拆成工作记忆、文件摘要、过程笔记和长期记忆。读文件后不把完整文件塞进记忆，而是保存短摘要和 freshness hash；文件被写入或 patch 后旧摘要会失效。召回相关记忆时先看标签命中，再看关键词重叠和新旧程度，保证机制透明可解释。

数据：

- 12 个记忆依赖任务
- 每个 variant 60 次 follow-up
- memory off / irrelevant：重复读文件 60 次
- memory on：重复读文件 0 次
- 平均工具步数从 1.0 降到 0
- 平均 attempts 从 2.0 降到 1.0
- memory on 正确率 100%

代码映射：

| 点 | 代码 |
| --- | --- |
| memory state | `repopilot/features/memory.py:43` |
| durable memory store | `repopilot/features/memory.py:59` |
| 文件摘要 freshness | `repopilot/features/memory.py:493` |
| read_file 摘要 | `repopilot/features/memory.py:505` |
| 相关记忆检索 | `repopilot/features/memory.py:519` |
| prompt 中 memory 渲染 | `repopilot/features/memory.py:561` |
| LayeredMemory 接口 | `repopilot/features/memory.py:599` |
| 工具执行后写入记忆 | `repopilot/runtime.py:388` |
| durable promotion | `repopilot/runtime.py:493` |
| 实验结果 | `benchmarks/results/main-resume-repro-2026-06-07/memory-ablation-v2.json` |

### 7.4 Checkpoint / Resume

面试回答：

> 长任务不能只靠聊天历史恢复。RepoPilot 会在工具执行、上下文压缩、任务结束等节点创建 checkpoint，记录当前目标、下一步、关键文件 freshness、runtime identity 和 workspace fingerprint。恢复时会判断 checkpoint 是 full-valid、partial-stale、workspace-mismatch 还是 schema-mismatch，避免误信旧状态继续执行。

数据：

- 覆盖 10 个 checkpoint / resume 场景
- resume enabled 成功率 90%
- stale reanchor rate 100%
- workspace drift detection 100%
- false accept rate 0%

代码映射：

| 点 | 代码 |
| --- | --- |
| checkpoint schema | `repopilot/checkpoint.py:8` |
| runtime identity | `repopilot/checkpoint.py:30` |
| resume 状态判断 | `repopilot/checkpoint.py:60` |
| checkpoint 渲染进 prompt | `repopilot/checkpoint.py:110` |
| checkpoint 创建 | `repopilot/checkpoint.py:145` |
| loop 中触发 checkpoint | `repopilot/agent_loop.py:123` |
| 实验结果 | `benchmarks/results/main-resume-repro-2026-06-07/recovery-ablation-v2.json` |

### 7.5 工具安全与运行治理

面试回答：

> RepoPilot 的工具系统是 fail-closed 的。模型不能直接碰文件系统或 shell，只能申请白名单里的工具。工具执行前会做参数校验、路径隔离、重复调用拦截和高风险审批；执行后会记录 affected paths、workspace_changed、diff_summary、tool_status。如果 shell 非零退出但工作区变了，会标成 partial_success，提醒后续先检查现场。

数据：

- 固定回归任务 12 个
- pass rate 100%
- within budget rate 100%
- verifier pass rate 100%

代码映射：

| 点 | 代码 |
| --- | --- |
| 工具白名单 | `repopilot/tools.py:14` |
| delegate 工具 | `repopilot/tools.py:47` |
| 工具注册 | `repopilot/tools.py:68` |
| 参数校验 | `repopilot/tools.py:86` |
| 文件/搜索/shell/写入/patch 工具 | `repopilot/tools.py:155` 到 `repopilot/tools.py:267` |
| 执行安全闸门 | `repopilot/tool_executor.py:45` |
| path escape 防护 | `repopilot/runtime.py:771` |
| delegate 只读 | `repopilot/runtime.py:588` |
| shell env allowlist | `repopilot/security.py:90` |
| 实验结果 | `benchmarks/results/main-resume-repro-2026-06-07/harness-regression-v2.json` |

### 7.6 评测与审计闭环

面试回答：

> 我没有把 agent 评测做成一个混在一起的总分，而是拆成 harness regression、上下文治理、记忆收益、恢复正确性几层。固定回归任务用 fixture repo、allowed tools、step budget、expected artifact 和 verifier 定义成功；ablation 实验分别验证 context、memory、recovery 的模块收益。每次运行还会落 task_state、trace 和 report，方便把失败归因到模型、工具、上下文还是恢复逻辑。

代码映射：

| 点 | 代码 |
| --- | --- |
| benchmark schema 校验 | `repopilot/evaluation/evaluator.py:164` |
| summary 指标 | `repopilot/evaluation/evaluator.py:245` |
| evaluator 主体 | `repopilot/evaluation/evaluator.py:376` |
| benchmark artifact 生成 | `repopilot/evaluation/evaluator.py:407` |
| 单任务 fixture/verifier | `repopilot/evaluation/evaluator.py:443` |
| run_fixed_benchmark | `repopilot/evaluation/evaluator.py:576` |
| harness regression v2 | `repopilot/evaluation/evaluator.py:603` |
| benchmark 任务定义 | `benchmarks/coding_tasks.json` |

## 8. 推荐写进你简历的版本

你的当前简历里第一项已经是“智能求职助手平台（AI简历投递与岗位分析Agent）”，和大模型开发方向匹配。RepoPilot 更偏底层 agent harness / runtime，技术深度更强。建议把 RepoPilot 放在项目经历第一或第二项；如果简历篇幅有限，可以压缩“高校数据分析与推荐平台”，把 RepoPilot 加进去。

### 项目标题

**RepoPilot：本地代码智能体 Harness | Python, Agent Harness, Tool Calling, Context Management, Checkpoint / Resume, Layered Memory, Run Trace**

### 项目描述

面向代码仓库长链路任务开发本地代码 agent harness，围绕模型接入、工具调用、上下文管理、任务恢复、结构化记忆、运行审计和评测闭环做系统化设计，重点解决多轮任务里的 prompt 膨胀、重复读文件、状态丢失、工具副作用不可控和结果难复盘的问题。

### 简历 bullet 推荐版

```text
- 设计并实现本地代码智能体 Harness，统一模型接入、工具执行、会话状态、checkpoint 恢复与运行工件落盘，支持 2 类模型后端、7 类工具和 3 类运行工件。
- 设计分层上下文管理与预算裁剪机制，在 12 组长上下文配置中将平均 prompt 从 7082 压到 5664，平均压缩率 16.19%，最高压缩率 33.28%，并保证当前请求不被裁坏。
- 实现结构化记忆系统，分层管理任务摘要、文件摘要、过程笔记和相关记忆召回；在 12 个记忆依赖任务中，将 follow-up 阶段重复读文件次数从 60 次降到 0 次。
- 构建 checkpoint / resume、安全工具执行与评测审计闭环，覆盖 10 个恢复场景，workspace 漂移识别率 100%；固定回归任务通过率、预算内完成率和 verifier 通过率均为 100%。
```

如果简历非常挤，可以压成 3 条：

```text
- 设计本地代码智能体 Harness，统一模型接入、7 类工具调用、会话状态、checkpoint 恢复和 task_state / trace / report 运行工件落盘。
- 优化长上下文治理与结构化记忆，在 12 组上下文配置中实现 16.19% 平均压缩率，并在 12 个记忆依赖任务中将 follow-up 重复读文件从 60 次降到 0 次。
- 构建安全工具执行和 benchmark 闭环，覆盖 10 个恢复场景，workspace 漂移识别率 100%；固定回归任务通过率、预算内完成率和 verifier 通过率均为 100%。
```

## 9. 每条简历对应哪些代码

| 简历 bullet | 主要代码 | 测试/数据 |
| --- | --- | --- |
| Agent harness 架构 | `repopilot/cli.py:225`、`repopilot/runtime.py:53`、`repopilot/agent_loop.py:123`、`repopilot/task_state.py:28`、`repopilot/run_store.py:18` | `tests/test_repopilot.py:41`、`tests/test_repopilot.py:1030` |
| 7 类工具与安全执行 | `repopilot/tools.py:14`、`repopilot/tools.py:68`、`repopilot/tools.py:86`、`repopilot/tool_executor.py:45`、`repopilot/runtime.py:771` | `tests/test_repopilot.py:272`、`tests/test_safety_invariants.py:146`、`tests/test_safety_invariants.py:192` |
| 上下文预算裁剪 | `repopilot/context_manager.py:60`、`repopilot/context_manager.py:78`、`repopilot/context_manager.py:297`、`repopilot/context_manager.py:456` | `tests/test_context_manager.py:39`、`context-ablation-v2.json` |
| 结构化记忆 | `repopilot/features/memory.py:43`、`repopilot/features/memory.py:493`、`repopilot/features/memory.py:519`、`repopilot/runtime.py:388`、`repopilot/runtime.py:493` | `tests/test_memory.py:93`、`memory-ablation-v2.json` |
| Checkpoint / Resume | `repopilot/checkpoint.py:8`、`repopilot/checkpoint.py:30`、`repopilot/checkpoint.py:60`、`repopilot/checkpoint.py:110`、`repopilot/checkpoint.py:145` | `tests/test_repopilot.py:1216`、`recovery-ablation-v2.json` |
| Provider adapter | `repopilot/cli.py:121`、`repopilot/providers/clients.py:33`、`repopilot/providers/clients.py:226`、`repopilot/providers/clients.py:379` | `tests/test_repopilot.py` 中 provider client 相关测试 |
| Benchmark / Evaluation | `repopilot/evaluation/evaluator.py:164`、`repopilot/evaluation/evaluator.py:245`、`repopilot/evaluation/evaluator.py:443`、`repopilot/evaluation/evaluator.py:576` | `tests/test_evaluator.py:82`、`benchmarks/coding_tasks.json`、`benchmarks/results/main-resume-repro-2026-06-07/` |
| 审计与脱敏 | `repopilot/run_store.py:49`、`repopilot/run_store.py:59`、`repopilot/security.py:62`、`repopilot/security.py:73`、`repopilot/runtime.py:550` | `tests/test_repopilot.py:1068` |

## 10. 面试高频追问

### Q1：为什么叫 harness，不叫普通 agent？

回答：

> 因为我关注的不是模型单次回答，而是把模型放到可控执行系统里。Harness 负责生命周期管理、工具权限、上下文预算、状态恢复、运行审计和 verifier。没有 harness，agent 只是会写代码；有 harness，系统才能知道它为什么这么做、哪里失败、能不能恢复、最后结果怎么验证。

对应代码：`repopilot/agent_loop.py`、`repopilot/tool_executor.py`、`repopilot/run_store.py`、`repopilot/evaluation/evaluator.py`。

### Q2：Prompt 是怎么构建的？

回答：

> Prompt 分成 prefix、memory、relevant_memory、history、current_request。prefix 放稳定规则、工具签名和 workspace 信息；memory 放当前任务摘要、最近文件和文件摘要；relevant_memory 只召回和当前请求相关的笔记；history 保留最近交互并压缩旧内容；current_request 永远最后放且不裁剪。

对应代码：`repopilot/context_manager.py:78`。

### Q3：记忆为什么能减少重复读文件？

回答：

> 因为 read_file 后会把短摘要、路径和 freshness hash 存起来。下一轮如果文件没变，就可以把摘要带进 prompt；如果文件变了，摘要会失效。这样模型不用每次都重新读同一个文件确认同一个事实，但也不会误信旧摘要。

对应代码：`repopilot/features/memory.py:493`、`repopilot/features/memory.py:505`、`repopilot/runtime.py:388`。

### Q4：怎么防止 agent 乱改文件？

回答：

> 第一，工具是白名单。第二，所有工具参数先校验。第三，文件路径 resolve 后必须仍在 workspace 里。第四，写文件、patch 和 shell 是 risky tool，要走 approval policy。第五，执行前后做 workspace snapshot diff，记录 changed paths。第六，delegate 子 agent 是只读的。

对应代码：`repopilot/tools.py`、`repopilot/tool_executor.py`、`repopilot/runtime.py:771`、`repopilot/runtime.py:588`。

### Q5：任务恢复具体怎么做？

回答：

> Checkpoint 里保存 current goal、next step、关键文件 freshness、workspace fingerprint 和 runtime identity。恢复时会比对这些信息，如果文件变了就是 partial-stale，如果 workspace 或工具签名等变了就是 workspace-mismatch，如果 schema 不兼容就是 schema-mismatch。这样不会只靠聊天历史继续执行。

对应代码：`repopilot/checkpoint.py:30`、`repopilot/checkpoint.py:60`。

### Q6：这些简历数据怎么来的？

回答：

> 这些不是线上流量数据，而是固定 benchmark 和 ablation 实验。固定回归任务用 fixture repo、allowed tools、step budget 和 verifier 检查最终工作区；上下文实验看 prompt 压缩前后的字符数和当前请求是否保留；记忆实验对比 memory on/off 的 follow-up 重复读文件次数；恢复实验覆盖 checkpoint、partial-stale、workspace-mismatch、schema-mismatch 等场景。每次运行都有 task_state、trace 和 report，所以能复盘。

对应文件：`benchmarks/coding_tasks.json`、`benchmarks/results/main-resume-repro-2026-06-07/`。

## 11. 建议你真正动手改的点

如果你要把这个项目讲成“自己的”，最好至少亲手改一个小点：

| 改造方向 | 可做内容 | 涉及文件 |
| --- | --- | --- |
| 上下文策略 | 调整 reduction order 或 section budgets，并补测试 | `repopilot/context_manager.py`、`tests/test_context_manager.py` |
| 记忆召回 | 增加更细的 tag/keyword scoring 或中文 token 规则 | `repopilot/features/memory.py`、`tests/test_memory.py` |
| 工具安全 | 增加 shell 命令黑名单/超时策略/输出预算测试 | `repopilot/tools.py`、`repopilot/tool_executor.py` |
| benchmark | 新增一个 path escape、partial success 或 resume 场景 | `benchmarks/coding_tasks.json`、`repopilot/evaluation/evaluator.py` |
| provider | 增加一个新的 compatible provider 配置路径 | `repopilot/cli.py`、`repopilot/providers/clients.py` |

改完其中一个点，你在面试里就可以从“我读过这个项目”变成“我理解并扩展过这个 agent harness”。
