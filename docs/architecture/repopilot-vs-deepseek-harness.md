# RepoPilot 与 DeepSeek Harness 对比

## 结论

RepoPilot 当前是一个轻量本地 coding agent：核心价值在于小、可读、可演示，并且已经具备仓库上下文、受限工具、会话状态、checkpoint、trace/report、轻量记忆和固定 benchmark。DeepSeek Harness 是生产级插件化 agent 平台：它把 LLM、工具、文件系统、shell、审批、沙箱、会话日志、UI、子 agent、技能、后台任务和测试支撑全部拆成可替换能力。

两者不应该按规模直接对齐。RepoPilot 最值得借鉴 DeepSeek 的不是完整 Cordis 插件树，而是四个工程原则：

1. **模型可见内容必须可回放**：任何进入模型请求的消息、工具结果、上下文注入，都应该能从持久事件日志重建。
2. **工具要 schema-first，并返回结构化结果**：面向模型的自然语言渲染不应是唯一结果，程序化结果、错误、展示元数据要分开。
3. **策略通过执行流水线挂载**：审批、权限、超时、沙箱、脱敏、metrics 不应散落在工具和 loop 里。
4. **能力按 seam 拆分**：先定义接口，再放 provider，再放面向模型或 CLI 的 consumer，避免新增能力都改主循环。

如果 RepoPilot 的目标是简历项目或教学项目，建议做“轻量 DeepSeek 化”：保留 Python 单包和终端 CLI，但引入事件日志、工具 schema/结果对象、工具执行 hook、配置 profile 和 keyless transcript snapshot。不要直接迁移到 TypeScript monorepo、Cordis、Web UI、100% 覆盖率门禁和完整插件市场，这会显著拉高维护成本。

## 对比范围

RepoPilot 参考对象：

- `repopilot/agent_loop.py`：主循环。
- `repopilot/runtime.py`：运行时装配、prompt、trace、memory、checkpoint、解析。
- `repopilot/tools.py` 与 `repopilot/tool_executor.py`：工具定义、校验、审批、执行、workspace diff。
- `repopilot/context_manager.py`：prompt section 与预算压缩。
- `repopilot/features/memory.py`：working memory 与 durable memory。
- `repopilot/evaluation/`、`benchmarks/coding_tasks.json`、`tests/`：固定 benchmark 和单元测试。

DeepSeek Harness 参考对象：

- `deepseek-harness-master/deepseek-harness-master/docs/architecture.zh.md`：插件化架构、事件域、turn/step 流程、能力 seam。
- `docs/tool-execution-pipeline.zh.md`：工具 pre/guard/execute/post/result 流水线。
- `docs/persistence-catalog.zh.md`：append-only session event log 与 surface projection。
- `docs/testing.zh.md`：单元、覆盖率、真实 API e2e、无密钥 snapshot、Web snapshot、构建产物 smoke。
- `docs/cookbook/adding-a-tool.zh.md`：schema-first 工具、规范 JSON 输出、presentation meta、后台任务。
- `AGENTS.md` 与 `packages/`：包分层、插件注册、配置、沙箱、技能、子 agent、UI、SDK。

## 架构对比

| 维度 | RepoPilot 当前做法 | DeepSeek Harness 做法 | 判断 |
| --- | --- | --- | --- |
| 总体架构 | Python 单包，`RepoPilot` runtime 持有模型、工具、session、memory、run store；主循环在 `AgentLoop`。 | TypeScript monorepo，Cordis 插件树，所有能力通过服务和插件注册。 | RepoPilot 简洁，适合展示；DeepSeek 可扩展，适合平台。 |
| 主循环 | “构建 prompt -> 模型返回文本 -> 解析 `<tool>`/`<final>` -> 执行工具 -> 写 trace/checkpoint”。 | turn/step 生命周期，持久 session event 与实时 agent/tools/能力事件并行。 | RepoPilot 易懂但扩展点少；DeepSeek 事件模型更适合恢复、fork、UI 和多 consumer。 |
| 工具协议 | 文本编码工具调用，JSON/XML 混合解析；工具结果是字符串加 metadata。 | schema-first 工具定义，参数校验、规范 JSON 返回、模型渲染、UI 展示元数据分离。 | RepoPilot 当前最该改的是工具协议和结果类型。 |
| 工具执行策略 | `ToolExecutor.execute()` 内串行处理 allowlist、参数校验、重复调用、审批、执行、diff、metadata。 | `tools/pre-execute`、guard、`tools/execute`、`tools/post-execute`、`tools/result` 分层，可由插件追加策略。 | RepoPilot 短期可引入轻量 hook pipeline，不必上 Cordis。 |
| 状态持久化 | session JSON 保存 history/memory/checkpoint；每次 run 输出 task_state、trace.jsonl、report.json。 | append-only session event log 是权威来源，surface projection 生成模型历史，未知必需事件拒绝恢复。 | RepoPilot 已有运行审计，但可恢复状态不是严格事件源。 |
| Prompt 上下文 | 固定 section：prefix、memory、relevant_memory、history、current_request，按预算裁剪。 | system prompt registry、工具 schema 组装、上下文注入、compaction、tool result pruner。 | RepoPilot 的 section 模型够用；可借鉴注册式 section 与模型无关压缩。 |
| Memory | working memory、file summaries、episodic notes、durable topic markdown。 | session log、compaction、session reference、skill/context 插件协作。 | RepoPilot 的 memory 对简历项目很有价值，但缺少“模型可见即已记录”的硬约束。 |
| Shell/文件系统安全 | 路径限制在 workspace 内，shell env allowlist，审批模式，执行后 snapshot diff。 | fs provider、subprocess provider、sandbox provider、approval seam、Windows ACL / local sandbox / E2B 等可替换后端。 | RepoPilot 已有安全意识，但隔离不是强沙箱。 |
| 子 agent | `delegate` 是受限只读 child agent，深度有限。 | subagent seam 支持 in-process、spawn、ACP、Codex、Claude Code 等 provider。 | RepoPilot 可保留简单 delegate，但应把 child 能力和权限显式记录。 |
| 配置 | CLI 参数 + `.env`，provider 代码中装配。 | profile、bundle、cordis patch、settings、credentials、agent presets。 | RepoPilot 不需要完整 profile 系统，但可以加轻量 profile YAML。 |
| UI/SDK | 终端 CLI，无 Web/SDK 协议。 | CLI、Web、ACP、JSON-RPC、Python SDK、UI 组件和会话 projection。 | 除非目标变成产品化，不建议 RepoPilot 做 Web UI。 |
| 测试 | pytest 单测、FakeModel benchmark、metrics/ablation、部分安全回归。 | 单元、100% gate、真实 API e2e、无密钥 transcript snapshot、Web snapshot、构建产物 smoke、doc-sync。 | RepoPilot 应借鉴 snapshot 和真实入口 smoke，而不是复制完整门禁。 |

## RepoPilot 当前优势

1. **学习成本低**  
   核心路径集中在少数 Python 文件里，用户能从 CLI 到 runtime 到 tools 读完整链路。这对简历展示和面试解释是优势。

2. **已经有可审计工件**  
   `.repopilot/runs/<run_id>/task_state.json`、`trace.jsonl`、`report.json` 能回答一次运行做了什么、为什么停、工具是否失败、workspace 是否变化。

3. **对上下文预算有明确处理**  
   `ContextManager` 不是简单拼历史，而是按 section 预算、floor、reduction order 处理，且把 prompt metadata 写入报告。

4. **安全边界不是空白**  
   工具有 risky 标记、approval policy、路径逃逸检测、shell 环境 allowlist、secret redaction、执行前后 workspace snapshot。

5. **有面向论文/简历的实验口径**  
   benchmark、memory/context/security/recovery ablation 让项目能讲“能力是否有效”，不只是 demo。

## RepoPilot 当前不足

### 1. 工具协议脆弱

RepoPilot 依赖模型输出 `<tool>...</tool>` 或 `<final>...</final>`，并兼容 JSON/XML 两种工具调用格式。这适合快速实现，但有几个问题：

- 参数类型、必填字段和结果结构没有统一 schema 作为单一事实源。
- 成功、失败、部分成功主要通过字符串和 metadata 约定表达。
- 后续如果接入 provider-native tool calling，需要重新设计解析、回放和测试。
- 工具结果面向模型、人类报告、程序化消费混在一起。

DeepSeek 的 schema-first 工具值得借鉴。即使保留文本 transport，也应先把工具定义升级为结构化 schema 和结构化 result，再由 renderer 生成模型可见文本。

### 2. 状态源不够统一

RepoPilot 同时有 session history、memory、checkpoint、run trace、report。它们都有价值，但没有一个“可恢复事实的权威日志”。这会导致：

- 恢复时要信任 session JSON 里的聚合状态。
- trace 能审计单次 run，但不是模型历史的权威来源。
- checkpoint、memory、history 之间的因果关系靠代码约定维持。
- 未来做 fork、跨设备同步、UI 回放、session query 会很难。

DeepSeek 的 append-only session event log 可以作为方向：先让用户消息、assistant 消息、tool call、tool result、approval decision、checkpoint created 成为同一类事件，再从事件投影出 history/memory/report。

### 3. 扩展点集中在主 runtime

RepoPilot 新增能力经常要改 `RepoPilot`、`ContextManager`、`ToolExecutor` 或 `tools.py`。这对小项目没问题，但能力增多后会出现：

- 运行时类越来越大。
- 工具策略和工具实现耦合。
- provider、memory、context、shell、安全策略之间难以替换。
- benchmark 需要为每个新功能手写特殊 setup。

DeepSeek 的能力 seam 很重，但其中“Service Definition / Provider / Consumer”这个拆法值得借鉴。RepoPilot 可以用 Python protocol/dataclass 做轻量版本。

### 4. 工具执行策略不可组合

当前 `ToolExecutor.execute()` 是固定顺序：allowlist、tool lookup、validate、repeat guard、approval、snapshot、run、diff、memory、metadata。问题不是顺序错，而是没有插槽：

- 想加超时策略、命令黑名单、敏感路径策略、dry-run、metrics exporter，都要改同一个函数。
- 策略之间很难测试“谁先拒绝、谁能改写结果、谁只观察结果”。
- 难以区分强制 guard 和可选 hook。

DeepSeek 的工具流水线可借鉴为 RepoPilot 的轻量 hook：

- `pre_execute(call) -> allow | deny | ask`
- `guard(call) -> allow | deny`
- `around_execute(call, next) -> result`
- `post_execute(call, result) -> result`
- `on_result(call, result) -> None`

### 5. 安全模型仍是“约束执行”，不是“隔离执行”

RepoPilot 限制路径、过滤环境变量、审批 risky 工具，并记录 diff。这能降低误操作，但 shell 仍在本机 workspace 里执行，`shell=True` 也扩大了命令解析面。它不具备：

- OS 级沙箱或 ACL。
- command segment 级策略。
- 持久进程/后台任务的生命周期管理。
- 远程 sandbox provider。

DeepSeek 的 sandbox/subprocess/fs/shell provider 拆分值得作为长期方向。短期可以先加命令策略和更细的 shell result 结构，不必立刻做 E2B 或 Windows ACL。

### 6. 测试缺少 transcript snapshot 和真实入口 smoke

RepoPilot 已经有 pytest 和 FakeModel benchmark，但还缺两类高价值测试：

- **无密钥 transcript snapshot**：固定一段模型脚本，断言最终 prompt、工具调用、工具结果、final answer 的可回放 transcript。
- **真实入口 smoke**：以安装后的 CLI 或 `python -m repopilot` 运行最小任务，验证发布路径不是只在源码导入下可用。

DeepSeek 的测试策略过于严格，不必复制 100% 覆盖率，但 snapshot + built entry smoke 对 RepoPilot 很划算。

## 可以借鉴 DeepSeek 的点

### A. 建立 append-only session event log

**借鉴内容**：把 session 的核心事实改成事件流，例如：

- `user/message`
- `assistant/message`
- `tool/call`
- `tool/result`
- `approval/asked`
- `approval/decided`
- `checkpoint/created`
- `memory/promoted`
- `context/compacted`

**为什么借鉴**：

- 恢复、审计、benchmark、回放可以共用同一来源。
- 后续做 fork、session query、UI 展示、跨轮 debugging 更自然。
- 能建立硬规则：进入模型的内容必须能从日志重建。

**其他选择**：

- 保持当前 session JSON + trace/report，只补 schema version 和一致性检查。成本最低，但后续扩展仍会累积债务。
- 使用 SQLite 存 events。查询强，但会增加部署复杂度。
- 使用 JSONL events。最适合 RepoPilot：简单、可 diff、可手工阅读。

**建议**：先新增 `.repopilot/sessions/<id>.events.jsonl`，不要马上删旧 session JSON。用 projection 生成现有 `history`，完成兼容迁移后再减少旧字段职责。

### B. 改造工具为 schema-first + structured result

**借鉴内容**：工具定义包含参数 schema、输出 schema、执行函数、模型渲染函数、可选报告/展示 metadata。

**为什么借鉴**：

- 模型工具说明、参数校验、测试 fixture 可以来自同一个定义。
- `run_shell` 不再靠文本中的 `exit_code:` 正则判断成功失败。
- benchmark 可以直接断言 result value，而不是解析自然语言。
- 后续接 provider-native tools 或 code-mode API 时不用推倒重来。

**其他选择**：

- 继续维护当前 `BASE_TOOL_SPECS` dict，只加更严格 validate。成本低，但协议债务还在。
- 引入 `pydantic`。类型和校验舒服，但会新增依赖。
- 使用 Python 标准库 dataclass + 手写轻量 schema。最贴合当前“无运行依赖”的项目策略。

**建议**：第一步定义 `ToolCall`、`ToolResult`、`ToolDefinition`，让所有工具返回结构化对象，再由 `render_tool_result()` 生成模型文本。

### C. 给工具执行加轻量 pipeline

**借鉴内容**：参考 DeepSeek 的 pre/guard/execute/post/result 分层，但用 Python 简化。

**为什么借鉴**：

- 审批、allowlist、重复调用、路径策略、shell 策略、metrics 不再挤在一个函数里。
- 每个策略能单测。
- 以后新增 dry-run、denylist、workspace dirty check、命令风险分级，不必改工具主体。

**其他选择**：

- 保持当前顺序，只拆私有函数。能改善可读性，但扩展能力有限。
- 上完整插件系统。扩展强，但对 RepoPilot 现阶段过重。

**建议**：实现一个固定 hook 列表即可，不需要动态插件加载。比如 `ToolPolicy` protocol 和 `ToolObserver` protocol。

### D. 引入轻量能力 seam

**借鉴内容**：把 LLM、FS、Shell、Approval、Memory、ContextSection 作为显式接口，而不是全部挂在 `RepoPilot` 上。

**为什么借鉴**：

- 可替换 provider 会更清晰。
- benchmark 能替换 FS/Shell/Approval，而不是构造整个 runtime。
- 项目复杂度上升时，主 runtime 不会持续膨胀。

**其他选择**：

- 保持单体 runtime。适合 1 到 2 个功能继续迭代。
- 直接迁移到第三方 agent framework。能快速接生态，但会削弱“自己实现 harness”的简历亮点。

**建议**：只抽当前已经有多个实现或明显会变的 seam：`ModelClient`、`ToolRegistry`、`SessionEventStore`、`ApprovalPolicy`、`ShellExecutor`。

### E. 增加 transcript snapshot 测试

**借鉴内容**：无密钥 snapshot 固定模型可见 transcript、工具调用、工具结果和最终输出。

**为什么借鉴**：

- Prompt、工具 schema、上下文压缩的变化会被看见。
- 比只测函数返回值更能证明 agent 产品行为没有漂移。
- 简历里可以明确讲“keyless replay snapshot 防止 harness 回归”。

**其他选择**：

- 继续只跑 FakeModel benchmark。已有价值，但对 transcript 变化不敏感。
- 只加 golden report JSON。能测报告，但不能覆盖模型实际看到什么。

**建议**：在 `tests/snapshots/` 下放 `.jsonl` 或 `.md` fixture，用规范化时间、run_id、路径后比较。

### F. 加 profile/preset，但保持轻量

**借鉴内容**：DeepSeek 用 profile/bundle/patch 组合 agent 能力。RepoPilot 可以做简化版 YAML/TOML profile：

- provider/model/base_url
- max_steps/max_new_tokens
- approval policy
- enabled tools
- feature flags
- context budgets
- shell policy

**为什么借鉴**：

- 不同实验、面试 demo、真实仓库使用可以复现。
- benchmark 可以引用 profile，减少命令行参数漂移。
- 用户不用改代码切换能力集合。

**其他选择**：

- 只用 CLI 参数和 `.env`。简单，但配置不可复现。
- 用 Python 配置文件。灵活但不利于审计。

**建议**：先支持 `--profile profiles/local-safe.json`，使用 JSON 避免新增 YAML 依赖。

## 不建议直接照搬的点

1. **不要直接迁移 Cordis 插件系统**  
   RepoPilot 目前没有那么多第三方扩展和 UI/SDK consumer。完整插件系统会让简历项目解释成本变高。

2. **不要拆成 TypeScript monorepo**  
   DeepSeek 的包分层服务于生产平台和前端生态。RepoPilot 当前 Python 单包更一致。

3. **不要追求 100% 覆盖率门禁**  
   对小项目而言，高质量路径测试、snapshot、benchmark 比机械覆盖率更有说服力。

4. **不要优先做 Web UI**  
   RepoPilot 的核心差距在 runtime 协议和可回放性，不在界面。

5. **不要立即做完整 sandbox provider**  
   可以先把 shell 执行结构化、加命令策略、减少 `shell=True` 使用，再评估 OS sandbox。

## 可选替代方案

### 方案 1：最小增强路线

保留现有架构，只做局部增强：

- 工具 result 结构化。
- session JSON 加 schema_version。
- trace 事件加 version 和 required fields。
- 增加 transcript snapshot。
- CLI smoke 测试。

适合短期投递和面试。缺点是长期扩展仍会遇到单体 runtime 问题。

### 方案 2：轻量 harness 路线

在 Python 内实现 DeepSeek 核心思想的轻量版：

- JSONL session events 作为权威源。
- projection 生成 history、memory、report。
- schema-first tools。
- tool pipeline hooks。
- profile JSON。
- transcript snapshot + benchmark + real provider self-skip e2e。

这是最推荐路线。它保留 RepoPilot 的可读性，同时把工程深度拉上来。

### 方案 3：平台化路线

向 DeepSeek 靠拢：

- 插件注册系统。
- 多 provider FS/Shell/Sandbox。
- 子 agent provider。
- Web/SDK/API。
- SQLite persistence。
- 背景任务和持久 terminal。

适合把 RepoPilot 做成长期产品。对当前项目而言投入大，容易稀释已有亮点。

### 方案 4：接入成熟框架

可以考虑 OpenAI Agents SDK、LangGraph、AutoGen、CrewAI 等。优点是生态和工具调用成熟，缺点是 RepoPilot 自己的 harness 设计会变成薄封装，不利于展示底层工程能力。

如果目标是“做一个能用的 agent 产品”，可以选成熟框架。如果目标是“展示自己理解 coding agent harness 的关键机制”，应继续自研轻量 harness。

## 推荐落地路线

### P0：文档与边界清理

- 明确 RepoPilot 定位：轻量本地 coding agent，不是 DeepSeek Harness 复刻。
- 在 README 或 architecture 文档中写下“不复制 Cordis、不做 Web UI、不做完整插件市场”的边界。
- 给现有 session/run artifact 补 schema_version。

### P1：工具结构化

- 新增 `ToolCall`、`ToolDefinition`、`ToolResult`。
- `run_shell` 返回 `{ exit_code, stdout, stderr, timed_out, duration_ms }`。
- `write_file`/`patch_file` 返回 `{ path, changed, diff_summary }`。
- `ToolExecutor` 不再从字符串里正则解析 exit code。

### P2：事件日志

- 新增 session events JSONL。
- 用户消息、assistant final、tool call、tool result、approval、checkpoint 都写事件。
- 用 projection 生成现有 `history_text()` 所需结构。
- 增加 invariant：模型 prompt 中的 history 必须能由 event log 重建。

### P3：工具 pipeline

- 抽出 allowlist、repeat guard、approval、workspace diff、memory update、metrics observer。
- 为每个 policy 写单测。
- 明确 guard 不可被 post hook 撤销。

### P4：测试升级

- 加 keyless transcript snapshot。
- 加 `python -m repopilot` 和安装后 console script smoke。
- 保留现有 FakeModel benchmark。
- 可选加真实 DeepSeek e2e，缺 key 自动 skip。

### P5：轻量 profile

- 支持 `--profile path/to/profile.json`。
- profile 记录 provider/model/tool allowlist/context budgets/feature flags。
- benchmark artifact 记录 profile hash，保证实验可复现。

## 优先级总表

| 优先级 | 建议 | 借鉴 DeepSeek 的原因 | 替代方案 |
| --- | --- | --- | --- |
| P1 | schema-first tools + structured result | 降低解析脆弱性，支持原生工具和可靠测试 | 继续增强现有 dict validate |
| P1 | transcript snapshot | 捕获模型可见行为漂移 | 只保留 benchmark report |
| P2 | append-only session events | 恢复、回放、fork、审计同源 | session JSON 加 version |
| P2 | tool pipeline hooks | 安全/审批/metrics 可组合 | `ToolExecutor` 拆私有函数 |
| P3 | profile JSON | 实验和 demo 可复现 | CLI 参数 + `.env` |
| P3 | shell result 结构化 | 不再从文本判断执行状态 | 保持当前文本输出 |
| P4 | lightweight seams | 控制 runtime 膨胀 | 继续单体 runtime |
| 暂缓 | Web UI/SDK | 当前核心价值不在 UI | 终端 CLI |
| 暂缓 | 完整插件系统 | 对项目规模过重 | Python registry/protocol |
| 暂缓 | 强 OS sandbox | 成本高，平台差异大 | 命令策略 + env/path 限制 |

## 最终建议

RepoPilot 现在的不足主要是“协议和状态模型还不够生产化”，不是“功能数量太少”。最值得借鉴 DeepSeek 的是可回放事件日志、schema-first 工具、工具执行流水线、能力 seam 和 snapshot 测试。这些能直接提升 RepoPilot 的可信度、可维护性和简历表达。

不建议把 DeepSeek 的完整架构搬过来。RepoPilot 应该走轻量 harness 路线：用 Python 保持可读性，用 DeepSeek 的工程原则补强关键机制。这样项目既不像玩具 demo，也不会变成维护不起的仿制平台。
