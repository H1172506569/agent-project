# RepoPilot 从 DeepSeek Harness 与 Alibaba OpenCodeReview 可借鉴的设计

## 结论

DeepSeek Harness、Alibaba OpenCodeReview 和 RepoPilot 的定位不同：

- **DeepSeek Harness** 是通用 agent 平台，强在插件化、事件日志、能力 seam、工具流水线、UI/SDK/多后端扩展。
- **Alibaba OpenCodeReview**  **是 code review 垂直产品**，强在确定性输入控制、规则匹配、per-file 并发分治、结构化评论、定位/过滤、manifest 覆盖率和可量化 benchmark。
- **RepoPilot** 是轻量本地 coding agent，强在小而完整、易读、可演示，已有受限工具、session、checkpoint、memory、trace/report 和 benchmark。

RepoPilot 最应该学习的不是“把两个项目的功能都搬进来”，而是：

1. 从 DeepSeek 学 **可扩展 harness 骨架**：事件日志、schema-first 工具、工具执行流水线、能力 seam、snapshot。
2. 从 Alibaba 学 **确定性任务工程**：任务切分、规则匹配、覆盖率 manifest、结构化输出、后处理验证、可量化指标。
3. 保留 RepoPilot 的轻量 Python 单包和 CLI，把这些思想做成“小型但完整”的机制。

如果要反映到简历，最有价值的路线是：把借鉴点落到可运行 benchmark 和 ablation 中，产出数据，例如 token 降低、resume 复用率、工具错误率下降、位置准确率提升、上下文压缩成功率、任务覆盖率、真实入口 smoke 通过率。

## 三者定位对比

| 维度 | DeepSeek Harness | Alibaba OpenCodeReview | RepoPilot |
| --- | --- | --- | --- |
| 定位 | 通用 agent harness / 平台 | AI code review 垂直 CLI 产品 | 轻量本地 coding agent |
| 主语言 | TypeScript + 少量 Python/native | Go + Node/npm + TS extension | Python |
| 核心目标 | 可扩展、可替换、可回放、多端集成 | 稳定、低噪声、低 token、行级 review | 小而完整、可解释、可实验 |
| 用户入口 | CLI、Web、ACP、SDK、插件 | CLI、CI、VS Code、Agent 插件 | CLI / REPL |
| LLM 职责 | 通用推理、工具调用、上下文处理 | 单文件 review 判断和上下文检索 | 通用仓库任务执行 |
| 工程职责 | 插件注册、事件、工具流水线、沙箱、UI | diff/scan、过滤、规则、分发、定位、manifest | workspace、prompt、工具、安全、memory、checkpoint |

## 框架区别

### DeepSeek Harness

DeepSeek 的框架核心是 Cordis 插件树。每项能力通过服务注册，并以插件副作用挂载。模型、工具、session、prompt、fs、shell、sandbox、subagent、skill、web、UI 都是可替换包。

框架特点：

- “Everything is a plugin”。
- session event log 是上下文和回放的来源。
- agent loop 只是默认驱动器，新行为应挂到事件或 seam。
- 工具执行有 pre/guard/execute/post/result 流水线。
- profile/bundle/patch 组合出不同运行形态。
- UI/SDK/API 都从同一 session projection 派生。

适用场景：长期平台、生态扩展、多端产品、复杂权限/沙箱。

### Alibaba OpenCodeReview

Alibaba OCR 的框架核心是垂直 review pipeline。它不追求通用 agent 平台，而是把 code review 的不确定性压缩到最小。

框架特点：

- Git diff 或 file scan 是输入源。
- 文件过滤和规则匹配由确定性代码负责。
- 每个文件是独立 subtask，可并发。
- LLM loop 只服务单文件 review。
- `code_comment` 是唯一评论输出通道。
- 评论位置由算法解析，不信任模型行号。
- session JSONL 和 run manifest 记录覆盖率与可恢复状态。

适用场景：CI code review、PR 审查、全量代码审计、低误报要求。

### RepoPilot

RepoPilot 的框架核心是一个本地 runtime + agent loop。它直接围绕当前 workspace 构建 prompt，通过受限工具读写文件、运行命令、维护 session 和 memory。

框架特点：

- Python 单包，核心路径短。
- prompt prefix + memory + history + current request。
- 文本工具协议，支持 JSON/XML 两种 `<tool>` 格式。
- 工具白名单、审批、路径校验、shell env allowlist。
- checkpoint、trace、report、benchmark 已具备。
- 适合展示完整 agent harness 的基础构成。

适用场景：简历项目、教学、轻量本地任务、agent harness 原型。

## 记忆系统区别

| 维度 | DeepSeek Harness | Alibaba OpenCodeReview | RepoPilot |
| --- | --- | --- | --- |
| 主要记忆形态 | append-only session log + projection + compaction | 单文件 message buffer + 三分区压缩 + session JSONL checkpoint | session history + working memory + durable memory + checkpoint |
| 权威来源 | 持久 session events | session JSONL + manifest + file checkpoint | session JSON + run trace/report/checkpoint |
| 长期记忆 | 可通过 skill/context/session reference 扩展 | 基本没有长期项目记忆，偏运行内压缩和 resume | 有 durable topic markdown |
| 压缩方式 | compaction 插件 / tool result pruner | frozen/compress/active 三分区，60% 异步、80% 同步 | section budget + history 压缩 + relevant memory |
| 恢复模型 | 从事件日志和 projection 恢复 | 按 fingerprint 复用已完成文件，manifest gate | checkpoint freshness/workspace identity 检测 |
| 核心优势 | 可回放、可 fork、可多端一致 | 单次 review 可恢复、覆盖率可审计 | 易懂，能展示 working/durable memory 效果 |
| 核心不足 | 体系重 | 不解决跨项目长期偏好和开放式任务记忆 | 状态源分散，不是严格 event-sourced |

### RepoPilot 应该怎么学

RepoPilot 应保留 durable memory，因为这是它区别于 Alibaba OCR 的优势。但要向 DeepSeek 和 Alibaba 学两点：

1. **把模型可见历史改成可回放事件投影**  
   用户消息、assistant 消息、tool call、tool result、checkpoint、memory promotion 都写入 session events，再由 projection 生成 prompt history。

2. **引入事件日志保真 + 投影层三分区压缩实验**  
   当前 `ContextManager` 主要是 section budget + hard clipping：在尽量保留当前用户请求和最近历史的前提下裁剪上下文。这个方案稳定便宜，但缺少语义判断，容易裁掉早期关键决策、失败原因或工具结果。更好的方向是：完整事件仍保存在 event log 中不删除，模型可见上下文由 projection 生成；当 projection 超过预算时，只对可压缩区域做 LLM 语义摘要。

   可以参考 Alibaba OpenCodeReview 的 frozen/compress/active 三分区设计：由代码确定哪些内容可压缩，LLM 只负责把 compressible 区域总结成结构化摘要，而不是让模型随意决定删除哪些事实。这样既保留 DeepSeek 式 event-sourced 可回放能力，又借鉴 Alibaba 的运行内上下文压缩策略。

3. **把长期记忆改成 candidate-promotion 机制**  
   RepoPilot 现有 durable memory 值得保留，但不应让长期记忆等同于压缩摘要，也不应让模型任意写入。更合适的做法是：event log 记录事实，projection 生成工作记忆和候选记忆，promotion policy 决定哪些候选能进入 durable memory。长期记忆必须稳定、可行动、可验证、足够简短，并绑定 evidence event ids。

## 工具系统区别

| 维度 | DeepSeek Harness | Alibaba OpenCodeReview | RepoPilot |
| --- | --- | --- | --- |
| 工具定义 | schema-first，规范 JSON output，render/presentation 分离 | JSON schema 定义 + Go provider 实现，输出多为字符串/结构化评论 | dict schema 字符串 + Python 函数 |
| 工具调用 | provider-native / Code Mode / pipeline | LLM native tool calls | 文本 `<tool>` 协议 |
| 执行策略 | pre/guard/execute/post/result | Runner 内执行，部分后处理专门化 | `ToolExecutor.execute()` 固定串行 |
| 输出 | value、render、presentation meta 分离 | `code_comment` 结构化，其他工具字符串 | content 字符串 + metadata |
| 可扩展性 | 插件注册 | registry + dynamic tool/MCP | 显式注册，较轻 |

### RepoPilot 应该怎么学

优先级最高的是把工具从“文本协议优先”改成“结构化定义优先”：

- `ToolDefinition`：name、description、args_schema、risk、execute、render。
- `ToolCall`：name、args、call_id。
- `ToolResult`：status、value、rendered_text、error_code、metadata。
- `run_shell` 返回结构化 `{exit_code, stdout, stderr, timed_out, duration_ms}`。
- `patch_file` 返回结构化 `{path, changed, old_hash, new_hash, diff_summary}`。

这样后续既能继续渲染 `<tool>` 文本，也能接 provider-native tool calling。

## 状态与持久化区别

| 维度 | DeepSeek Harness | Alibaba OpenCodeReview | RepoPilot |
| --- | --- | --- | --- |
| 事件粒度 | session events，区分 surface/log-only | JSONL records：request/response/tool/item/session | run trace events + session JSON |
| 状态投影 | 从 event log 派生模型历史、UI、telemetry | 从 JSONL 和 manifest 恢复 item 状态 | session 直接存 history/memory |
| 运行报告 | session projection / telemetry | run manifest + JSON output + retry report | task_state + trace + report |
| 覆盖率 | 通用 agent 不强调文件覆盖 | selected/completed/reused/failed/waived | 当前无覆盖率 manifest |

### RepoPilot 应该怎么学

RepoPilot 现在有 `trace.jsonl`，但 trace 是单次 run 审计，不是 session 权威来源。建议：

- 增加 `.repopilot/sessions/<id>.events.jsonl`。
- 增加 `session_manifest.json` 或把 manifest 写入 report。
- 对仓库任务增加“coverage-like”概念：planned files、touched files、verified files、failed files。
- 对 resume 记录 reused/invalidated/rerun 的数量。

## 任务切分区别

| 维度 | DeepSeek Harness | Alibaba OpenCodeReview | RepoPilot |
| --- | --- | --- | --- |
| 切分方式 | agent/subagent/workflow seam | per-file subtask，scan batch | delegate read-only child agent |
| 并发 | 可通过 jobs/subagent/workflow 扩展 | 文件级 goroutine 并发，默认 8 | 当前主循环串行 |
| 适合任务 | 通用长期任务 | 大 PR / 全量 scan | 小到中等仓库任务 |

### RepoPilot 应该怎么学

RepoPilot 不需要一开始就做通用并发 agent。但可以做一个确定性 task planner：

- 对“review/inspect/fix tests”类任务先列出候选文件。
- 按文件或模块做 bounded investigation。
- 每个子任务只读，生成结构化 finding。
- 主 agent 汇总 findings 再决定是否修改。

这比让模型在一个长 history 里自由搜索更稳定，也更容易测试。

## 规则系统区别

| 维度 | DeepSeek Harness | Alibaba OpenCodeReview | RepoPilot |
| --- | --- | --- | --- |
| 规则来源 | AGENTS/skills/profile/system prompt plugins | 四层 path rule chain + 内置语言规则 | prompt prefix + README/项目文档 + memory |
| 规则匹配 | 插件/上下文注入 | path glob 第一个匹配 | relevant memory 简单检索 |
| 优势 | 灵活、平台化 | 稳定、可解释 | 简单 |

### RepoPilot 应该怎么学

新增轻量项目规则机制：

- `.repopilot/rules.json`
- 支持 `include`、`exclude`、`rules: [{path, rule}]`
- 在 prompt 里只注入与当前任务/文件相关的规则。
- 增加 `repopilot rules check <path>` 或测试 helper，验证规则匹配。

这能让 RepoPilot 的项目上下文从“读 README 猜约定”变成“可测试的规则解析”。

## 安全区别

| 维度 | DeepSeek Harness | Alibaba OpenCodeReview | RepoPilot |
| --- | --- | --- | --- |
| Shell | sandbox/subprocess/shell provider | 基本只执行 Git 参数数组，不开放任意 shell | `run_shell` 任意命令 + approval |
| FS | fs provider + policy | 文件读取受 repo root 约束 | path resolver 限制 workspace |
| 凭据 | credentials seam | key 不落日志，endpoint 脱敏 | secret env redaction + shell env allowlist |
| Viewer/UI | 多端策略 | viewer host guard/security headers | 无 viewer |

### RepoPilot 应该怎么学

RepoPilot 有通用 `run_shell`，这比 OCR 风险更高。建议做三步：

1. `run_shell` 结构化输出，不再用字符串解析 exit code。
2. 增加 shell policy：允许命令前缀、拒绝危险命令、记录 risk classification。
3. 对常用操作提供专用工具，例如 `run_tests`、`git_diff`、`git_status`，减少任意 shell 依赖。

DeepSeek 的强沙箱是长期方向；OCR 的“避免 shell，使用参数化 git 命令”更适合 RepoPilot 近期落地。

## 测试体系区别

| 维度 | DeepSeek Harness | Alibaba OpenCodeReview | RepoPilot |
| --- | --- | --- | --- |
| 单元测试 | 包级 + 严格类型 | Go 包广覆盖 + CLI 测试 | pytest 单元较完整 |
| 覆盖率 | per-file 100% gate | 90% coverage gate | 无强覆盖率门槛 |
| Snapshot | transcript/UI snapshot | 部分输出/CLI/session 测试 | 缺 transcript snapshot |
| Real API | 自跳过 e2e | provider 连接/集成路径 | 主要 FakeModel |
| Benchmark | replay/snapshot/真实 API | AACR-Bench 指标：Precision/F1/token/time | 固定 FakeModel benchmark + ablation |

### RepoPilot 应该怎么学

不建议照搬覆盖率门槛。建议补三类更能服务简历的数据：

- keyless transcript snapshot。
- CLI installed-entry smoke。
- feature ablation benchmark。

## RepoPilot 可借鉴项总表

| 来源 | 可借鉴点 | 为什么值得借鉴 | 是否适合 RepoPilot |
| --- | --- | --- | --- |
| DeepSeek | append-only session event log | 统一恢复、回放、审计 | 高，建议轻量 JSONL |
| DeepSeek | schema-first tools | 降低文本协议脆弱性 | 高，优先做 |
| DeepSeek | tool pipeline hooks | 审批、guard、metrics 可组合 | 高，轻量实现 |
| DeepSeek | capability seam | 控制 runtime 膨胀 | 中，按需抽接口 |
| DeepSeek | transcript snapshot | 捕获模型可见行为变化 | 高 |
| DeepSeek | profile/preset | 配置可复现 | 中，JSON profile 即可 |
| DeepSeek/RepoPilot | candidate-promotion memory | 防止长期记忆被临时推理或幻觉污染 | 高，适合保留 RepoPilot 的 durable memory 优势 |
| Alibaba | deterministic file selection | 让模型少猜，提升覆盖 | 高，适合 review/inspect 类任务 |
| Alibaba | path-based rules | 规则注入更精准 | 高 |
| Alibaba | per-file subtask | 大仓库任务稳定 | 中，先做只读并发或串行 batch |
| Alibaba | structured finding/comment | 输出可评估 | 高 |
| Alibaba | line anchoring | 修复/评论定位可验证 | 中，适合 review 功能 |
| Alibaba | review filter/reflection | 降低误报 | 中，先做 verifier prompt 或 deterministic check |
| Alibaba | run manifest coverage | 简历数据好表达 | 高 |
| Alibaba | token/tool/time summary | 成本可观测 | 高 |

## 推荐实现路线

### P1：工具结构化与 transcript snapshot

目标：修复 RepoPilot 当前最脆弱的模型/工具边界。

实现：

- 新增 `ToolCall`、`ToolDefinition`、`ToolResult`。
- 工具统一返回结构化 value。
- `render_tool_result()` 生成模型可见文本。
- 增加 keyless transcript snapshot：固定 FakeModel 输出，比较 prompt/tool/result/final。

可测试数据：

- malformed tool call recovery rate。
- repeated call rejection count。
- tool result parse error count。
- snapshot case count。

简历表达：

> 重构工具协议为 schema-first + structured result，新增无密钥 transcript snapshot，覆盖模型可见 prompt、tool call、tool result 和 final answer，降低文本解析导致的工具执行失败。

### P2：Session Event Log

目标：让 session 恢复和模型历史有统一来源。

实现：

- `.repopilot/sessions/<id>.events.jsonl`
- events：`session_start`、`user_message`、`assistant_message`、`tool_call`、`tool_result`、`checkpoint_created`、`memory_promoted`、`session_end`
- projection 生成现有 history。
- invariant：prompt history 可由 events 重建。

可测试数据：

- event replay success rate。
- corrupted event handling。
- resume correctness。
- prompt/history mismatch count。

简历表达：

> 设计 append-only session event log 与 projection 层，使模型可见历史可回放、可审计，并通过 replay invariant 测试保证恢复一致性。

### P3：轻量规则系统

目标：把 RepoPilot 的项目约定注入从“读文档猜测”变为“按路径匹配”。

实现：

- `.repopilot/rules.json`
- `include`/`exclude`/`rules`
- `rules check` 测试 helper。
- 在 prompt metadata 中记录 matched rule。

可测试数据：

- rule match accuracy。
- prompt rule noise reduction。
- unsupported/excluded file skip count。

简历表达：

> 引入 path-based project rules，为不同文件类型注入最小必要上下文，减少无关 prompt 内容并提升任务约束稳定性。

### P4：Coverage Manifest

目标：让 RepoPilot 的一次任务有类似 OCR 的覆盖率报告。

实现：

- 在 task/run report 中新增 manifest：
  - planned_files。
  - inspected_files。
  - modified_files。
  - verified_files。
  - failed_files。
  - skipped_files。
  - terminal_state。
- `read_file/search/patch_file/run_shell` 更新 coverage state。

可测试数据：

- file coverage rate = inspected/planned。
- verification rate = verified/modified。
- failed/skipped classification counts。
- resume reused/rerun count。

简历表达：

> 为 agent run 增加 coverage manifest，量化任务覆盖率、验证率、失败分类和 resume 复用情况，使 agent 行为从自然语言结果升级为可审计工件。

### P5：Review/Inspect 专用模式

目标：从 Alibaba 学确定性分治，但不把 RepoPilot 变成纯 review 工具。

实现：

- 新增 `inspect` 或 `review` feature flag/command。
- 基于 `git diff` 或文件列表生成 planned files。
- 每个文件运行 bounded read-only subtask。
- 输出 structured finding：path、line/snippet、severity、category、rationale、suggestion。
- 可选 final filter。

可测试数据：

- finding precision。
- anchored finding rate。
- token per file。
- average tool calls per file。
- concurrency speedup。

简历表达：

> 借鉴 OpenCodeReview 的 deterministic pipeline，新增 per-file inspection mode，将文件选择、规则匹配、finding schema 和覆盖率统计工程化，提升大变更审查稳定性。

### P6：事件日志保真 + 投影层上下文压缩实验

目标：把 RepoPilot 当前的 hard clipping 升级为可对比的语义压缩实验。核心不是直接删除 history，而是完整保留 event log，再在 model-visible projection 层压缩旧上下文。

当前问题：

- `ContextManager` 通过 section budget 和字符/轮次裁剪控制 prompt 长度。
- 这种 hard clipping 不经过模型判断，优点是确定、便宜、不会引入额外 LLM 调用。
- 缺点是只按位置和预算裁剪，不理解哪些旧信息仍然关键，例如早期失败原因、用户约束、已尝试方案、关键工具结果。
- 如果直接裁剪 session history，后续 resume/debug/benchmark 很难说明“为什么上下文丢了”。

借鉴对象：

- **Alibaba OCR**：使用 frozen/compress/active 三分区，并在约 60% token budget 时触发异步压缩，在约 80% token budget 时触发同步压缩。它不是让模型随意裁剪，而是由代码决定哪些 message 属于可压缩区，再让 LLM 对这部分做摘要。
- **DeepSeek Harness**：更强调 session event log 和 projection。完整事实写入事件日志，模型看到的是从事件派生出的上下文视图。这个架构适合把压缩放在 projection 层，而不是破坏原始事件。

推荐实现：

- 保留当前 `ContextManager` 作为 baseline 和 fallback。
- 引入复用 P2 的 session event log，完整记录 `user_message`、`assistant_message`、`tool_call`、`tool_result`、`memory_update`、`final_answer`。
- 新增 `ContextProjection` 或在现有 context builder 中增加 compression strategy。
- 将模型可见上下文分为三类：
  - frozen：system/prefix、当前用户请求、安全规则、工具 schema、当前任务目标。
  - compressible：较早的 assistant 推理、旧 tool rounds、旧搜索结果、已完成子任务过程。
  - active：最近 N 轮消息、最近工具结果、当前正在处理的文件。
- token 使用量低于 60% 时不压缩。
- token 使用量达到 60% 时，对 compressible 区域启动异步压缩，当前 tool loop 继续运行；压缩结果成功后写成 `context_summary` 事件。
- token 使用量达到 80% 时，执行同步压缩，等待 summary 生成后再发起下一次 LLM 请求。
- 压缩失败时 fail-open 到当前 hard clipping，不能阻塞任务完成。
- 原始事件永远不删除；summary 只替代模型可见 projection 中的旧事件。

结构化 summary 建议：

```json
{
  "task_goal": "重构 RepoPilot 工具协议",
  "user_constraints": ["保持 CLI 行为兼容", "不要丢失最近一次用户请求"],
  "files_seen": ["repopilot/tools.py", "repopilot/tool_executor.py"],
  "decisions": [
    "run_shell 不应再依赖 exit_code 文本正则判断"
  ],
  "tool_findings": [
    "BASE_TOOL_SPECS 目前仍是给模型看的字符串 schema"
  ],
  "attempted_steps": [
    "已检查工具执行链路和 report/trace 写入路径"
  ],
  "open_questions": [
    "provider-native tool calling 尚未接入"
  ],
  "risks": [
    "修改 ToolResult 格式会影响 trace/report/snapshot"
  ]
}
```

可测试数据：

- prompt chars/tokens：对比 hard clipping 与 semantic compression 的上下文成本。
- task pass rate：压缩后任务是否仍能完成。
- repeated read count：如果压缩保留了关键事实，重复读同一文件的次数应下降。
- retained constraint rate：早期用户约束是否仍出现在 summary/projection 中。
- retained failure cause rate：早期工具失败原因是否被摘要保留。
- compression latency：60% 异步压缩是否减少阻塞，80% 同步压缩增加多少耗时。
- compression failure count：压缩失败时是否能 fallback 到 hard clipping。
- replay correctness：event log 能否重建未压缩事实，summary 只影响模型可见上下文。

实验分组：

- A 组：当前 section budget hard clipping。
- B 组：三分区 hard clipping，只按 frozen/compressible/active 裁剪，不调用 LLM。
- C 组：三分区 LLM semantic compression，60% 异步、80% 同步。
- D 组：三分区 LLM semantic compression + event-log replay 校验。

简历表达：

> 设计事件日志保真的上下文压缩实验，将完整会话事实保存在 append-only event log 中，仅在 model-visible projection 层进行三分区语义压缩；参考 OpenCodeReview 的 60% 异步/80% 同步压缩策略，在 benchmark 中对比 hard clipping、三分区裁剪和 LLM 摘要压缩的 token 成本、任务通过率、重复读取次数和约束保留率。

### P7：Memory Candidate + SAVE Promotion

完成状态：已在 `RepoPilotv2.0` 实现。核心代码位于 `repopilot/memory_promotion.py`，runtime 接入点位于 `repopilot/runtime.py` 的 `promote_memory_candidates()`，agent loop 在成功结束时触发候选评估；实验脚本位于 `scripts/run_memory_promotion_experiment.py`，结果写入 `docs/metrics/p7-memory-promotion-experiment.md` 和 `docs/metrics/p7-memory-promotion-experiment.json`。

目标：把 RepoPilot 的 durable memory 从“手工/文件式长期笔记”升级为可审计的长期记忆晋升机制。核心是：LLM 可以辅助生成 memory candidate，但不能直接把任意总结写进长期记忆；长期记忆必须经过 promotion policy、证据绑定、去重、冲突检测和敏感信息过滤。

为什么需要 P7：

- P2 的 event log 解决“事实从哪里来”。
- P6 的 context compression 解决“模型上下文太长怎么办”。
- P7 解决“哪些事实值得跨任务长期保存”。
- 压缩 summary 是为了省 token，可能有信息损失；durable memory 是为了长期复用，必须更稳定、更可验证。

方法论：SAVE

- Stable：事实稳定，不是一次临时状态或短期计划。
- Actionable：未来任务中能指导 agent 行动。
- Verifiable：能追溯到 event/tool result/user message 证据。
- Economical：足够短，不污染长期上下文。

适合晋升的例子：

- RepoPilot 主要使用 `pytest` 运行测试。
- 工具协议核心文件是 `repopilot/tools.py` 和 `repopilot/tool_executor.py`。
- 修改 `ToolResult` 格式时需要同步 trace/report/snapshot。
- 用户希望技术解释和面试表达使用中文。

不适合晋升的例子：

- 本轮 pytest 刚才失败了。
- 我下一步准备读取 `tools.py`。
- 这次任务调用了 7 次 `read_file`。
- 模型曾经猜测某个文件“可能有问题”。

推荐实现：

- 新增 `MemoryCandidate`：`text`、`kind`、`scope`、`source`、`evidence_event_ids`、`confidence`、`created_at`。
- 新增 `PromotionDecision`：`promote`、`reject`、`pending_confirmation`。
- 新增 `MemoryPromotionPolicy`：实现 SAVE 打分、hard reject、去重和冲突检测。
- 新增事件：`memory_candidate_created`、`memory_promoted`、`memory_rejected`、`memory_pending_confirmation`。
- durable memory 记录 evidence，不只保存自然语言文本。

候选生成时机：

- `session_end`：任务结束后，从完整 event log 中总结候选，这是最主要的生成点。
- 关键 `tool_result` 后：例如读取 `pyproject.toml`、`package.json`、README、测试配置、CI 配置后，提取项目事实候选。
- 用户显式偏好后：例如“以后都用中文解释”“先出方案再改代码”，生成用户偏好候选。

晋升触发时机：

- `task_success` 或 `session_end`：自动评估本轮 candidates。
- `checkpoint_created`：可以做轻量评估，但更适合生成 pending candidates。
- `memory review` 命令：人工查看 pending candidates 并确认是否写入长期记忆。

晋升规则：

- SAVE 总分达到阈值才允许自动晋升。
- 没有 `evidence_event_ids` 的 candidate 不晋升。
- 包含 secret/token/key/path credential 的 candidate 不晋升。
- 只描述临时计划、一次性工具输出、当前失败状态的 candidate 不晋升。
- 和已有 memory 冲突时不直接覆盖，进入 `pending_confirmation`。
- 用户偏好类 memory 如果影响未来行为较大，优先 pending，由用户确认。

结构化示例：

```json
{
  "text": "RepoPilot 的工具协议核心文件是 repopilot/tools.py 和 repopilot/tool_executor.py。",
  "kind": "project_fact",
  "scope": "repo",
  "source": "session_end_summary",
  "evidence_event_ids": ["evt_021", "evt_034"],
  "confidence": 0.91,
  "save_scores": {
    "stable": 2,
    "actionable": 2,
    "verifiable": 2,
    "economical": 2
  },
  "decision": "promote"
}
```

可测试数据：

- candidate precision：生成的候选中有多少是真正值得长期保存的。
- promotion precision：自动晋升的 memory 中有多少被人工判定正确。
- conflict detection rate：新候选与旧 memory 冲突时是否能拦截。
- evidence coverage：长期 memory 中带 evidence_event_ids 的比例。
- stale memory invalidation rate：项目变化后旧 memory 是否能被识别为过期。
- memory usefulness rate：后续任务中被检索出的 memory 是否真的参与了正确决策。

实验分组：

- A 组：无 durable memory，仅靠 history/context。
- B 组：现有文件式 durable memory。
- C 组：LLM 直接总结写入 memory。
- D 组：candidate + SAVE promotion + evidence binding。

当前实验结果：

| Group | Promoted | Rejected | Pending | Evidence coverage | Precision proxy | Sensitive leaks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A_no_durable_memory | 0 | 0 | 0 | 0% | 0% | 0 |
| B_file_style_durable_memory | 3 | 0 | 0 | 0% | 100% | 0 |
| C_llm_direct_summary_write | 6 | 0 | 0 | 0% | 67% | 1 |
| D_candidate_save_promotion | 2 | 3 | 1 | 100% | 100% | 0 |

结论：D 组最好。它不是保存最多，而是保存最稳：自动晋升 2 条可复用长期事实，拒绝 3 条噪声/敏感/重复候选，将 1 条冲突候选转人工确认；相比 C 组直接写 memory，把敏感泄露从 1 降到 0，并保持 100% evidence coverage。

简历表达：

> 设计 candidate-promotion 长期记忆机制，基于 append-only event log 生成 memory candidates，并使用 SAVE 策略、证据绑定、去重、冲突检测和敏感信息过滤控制长期记忆写入；在 6 类候选 benchmark 中实现 100% evidence coverage 和 100% promotion precision proxy，拦截敏感/临时/重复候选并将冲突候选转人工确认，避免模型临时推理污染 durable memory。

## 可量化实验设计

### 1. 工具协议鲁棒性实验

目标：证明 schema-first/structured result 比文本约定更稳。

任务集：

- 缺必填参数。
- 参数类型错误。
- shell 非零退出。
- patch old_text 多处匹配。
- repeated identical tool call。
- path escape。

指标：

- recovery pass rate。
- rejected invalid call count。
- partial_success classification accuracy。
- final answer rate。

简历可写：

> 构建 6 类工具异常 benchmark，覆盖参数缺失、路径逃逸、非零退出和重复调用；结构化工具协议上线后，异常分类准确率和恢复通过率可量化提升。

### 2. Event Replay / Resume 实验

目标：证明事件日志能稳定恢复。

任务集：

- 正常多工具会话。
- 中断后 resume。
- workspace fingerprint mismatch。
- stale file summary。
- corrupted optional event。
- corrupted required event。

指标：

- replay success rate。
- resume correctness。
- stale detection rate。
- mismatch detection rate。
- corrupted event fail-closed rate。

简历可写：

> 实现 session event replay benchmark，验证多工具会话、中断恢复、workspace drift 和 stale memory 的恢复一致性。

### 3. 规则注入降噪实验

目标：证明 path rules 能减少无关上下文。

任务集：

- Python/Go/JS 不同文件。
- package manifest。
- CI YAML。
- test/generated 文件。
- 自定义 project rule。

指标：

- matched rule accuracy。
- prompt rule chars。
- irrelevant rule count。
- task pass rate。

简历可写：

> 引入 path-based rule resolver，在多语言 fixture 中实现 100% 规则匹配测试，并统计 prompt 规则段长度下降。

### 4. Coverage Manifest 实验

目标：证明 agent 行为可审计。

任务集：

- 单文件修改。
- 多文件修改。
- 工具失败后恢复。
- 跳过不支持文件。
- 修改后验证测试。

指标：

- planned/inspected/modified/verified count。
- coverage rate。
- verification rate。
- failed classification count。
- terminal_state 分布。

简历可写：

> 为每次 run 输出 coverage manifest，统计文件覆盖率、修改验证率和失败分类，使 agent 执行过程可审计、可复盘。

### 5. Review Finding 定位实验

目标：借鉴 OCR 的 line anchoring，用数据证明位置更准。

任务集：

- 新增代码 bug。
- 删除代码导致兼容性问题。
- 重命名文件。
- 跨文件调用不一致。
- 缩进/空白变化。

指标：

- anchored finding rate。
- exact line match rate。
- unanchored count。
- false positive count。
- review filter removal count。

简历可写：

> 设计 structured finding + snippet anchoring 机制，在 review benchmark 中统计 exact line match rate 和 unanchored rate，系统性降低位置漂移。

### 6. Token/时间成本实验

目标：让工程优化可量化。

任务集：

- 大 history。
- 大 diff。
- 多文件任务。
- 有/无 memory。
- 有/无 compression。

指标：

- avg prompt tokens。
- avg output tokens。
- avg wall time。
- avg tool calls。
- cache hit rate。
- pass rate。

简历可写：

> 通过上下文压缩和确定性文件筛选，在固定 benchmark 上统计 token 成本、工具调用次数和通过率，量化 agent harness 的效率改进。

## 最终建议

RepoPilot 的升级方向应是“轻量通用 harness + 少量垂直模式”，而不是复制 DeepSeek 的平台规模或 Alibaba 的完整 review 产品。

优先做：

1. schema-first tools。
2. session event log。
3. transcript snapshot。
4. path-based rules。
5. coverage manifest。
6. review/inspect 专用 structured finding。
7. context compression ablation。
8. memory candidate + SAVE promotion。

暂缓做：

- Web UI。
- 完整插件系统。
- 完整 OS sandbox。
- 多端 SDK。
- 100% 覆盖率门槛。

这样 RepoPilot 能保持简历项目的可解释性，同时借鉴两个开源项目中最有工程含金量的部分：DeepSeek 的 harness 可扩展性，Alibaba 的确定性任务约束和可量化评审质量。

## 可以写进简历的最终版本

可以把未来改造后的 RepoPilot 表达为：

> 设计并实现轻量级本地 coding agent harness，支持 schema-first 工具协议、append-only session event log、checkpoint/resume、上下文压缩、项目规则注入、coverage manifest 和 candidate-promotion 长期记忆；借鉴 OpenCodeReview 的确定性文件筛选与结构化 finding 流水线，构建 keyless transcript snapshot 与多维 ablation benchmark，量化工具恢复率、上下文 token 成本、任务覆盖率和 resume 复用率。

更具体的数据占位可以是：

- `N` 个固定 benchmark task。
- `X%` task pass rate。
- `Y%` replay/resume success rate。
- `Z%` prompt token reduction。
- `A%` verification coverage。
- `B%` anchored finding rate。
- `M%` memory promotion precision。
- `C` 类安全/工具异常全部 fail-closed。

这些数字必须由测试产出后再填，不能提前写死。RepoPilot 目前已经有 benchmark 和 ablation 基础，下一步应把上述指标纳入 `repopilot/evaluation/metrics.py` 或新增实验脚本。



