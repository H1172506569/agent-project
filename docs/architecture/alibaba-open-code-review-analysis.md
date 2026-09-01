# Alibaba OpenCodeReview 代码框架与特性分析

## 结论

Alibaba OpenCodeReview（下文简称 OCR）不是通用 coding agent，而是一个面向 code review 的垂直 agent 产品。它的核心设计是“确定性工程 × LLM agent”：用 Go 代码严格控制输入集合、文件过滤、规则匹配、任务分发、评论定位、会话持久化和输出格式，把 LLM 放在需要语义判断和上下文检索的位置。

它解决的问题不是“让模型自由探索仓库”，而是“稳定、低噪声、可恢复、可度量地审查 Git diff 或全量文件”。这和 RepoPilot 的通用本地 coding agent 定位不同，但对 RepoPilot 很有参考价值：尤其是**任务切分**、规则匹配、结构化评论、评论定位、**token 预算**、session manifest、resume 和可量化 benchmark。

## 项目结构

OCR 是 Go 主体 + Node 包装 + VS Code/网站/Agent 插件的组合。

主要目录：

| 路径 | 职责 |
| --- | --- |
| `cmd/opencodereview/` | CLI 命令入口：`review`、`scan`、`config`、`rules`、`session`、`viewer` 等。 |
| `internal/agent/` | diff review 编排：加载 diff、过滤、规则注入、per-file 并发分发、manifest 收尾。 |
| `internal/scan/` | full-file scan 编排：枚举文件、批处理、可选 plan/dedup/summary、复用 `llmloop.Runner`。 |
| `internal/llmloop/` | 单文件 LLM 工具调用循环、token 统计、上下文压缩、评论异步处理。 |
| `internal/tool/` | 工具实现和工具注册表：`code_comment`、`file_read`、`file_read_diff`、`file_find`、`code_search`。 |
| `internal/diff/` | Git diff 获取、解析、重命名/二进制/untracked 支持、行号定位。 |
| `internal/config/` | prompt template、工具 JSON schema、规则、文件类型 allowlist、连接测试。 |
| `internal/session/` | JSONL 会话、resume checkpoint、run manifest、coverage 状态。 |
| `internal/llm/` | 模型协议、provider 解析、retry metadata、usage/token 统计。 |
| `internal/telemetry/` | OpenTelemetry span/event/metrics。 |
| `internal/viewer/` | 本地 session viewer，包含 host guard 和 security headers。 |
| `plugins/open-code-review/` | Codex、Claude Code、Cursor、OpenCode 等 agent 集成。 |
| `extensions/vscode/` | VS Code 扩展和 Webview。 |
| `pages/` | 文档站和官网。 |
| `npm/`、`bin/` | npm 分发和平台二进制包装。 |

## 高层流水线

OCR 的 `review` 路径可以概括为：

1. CLI 解析参数和配置，解析 LLM provider/model/key。
2. 加载 prompt template、工具定义、系统规则和用户规则。
3. 从 Git 获取 diff：
   - workspace：staged + unstaged + untracked。
   - commit：单 commit 相对第一父提交。
   - range：`merge-base(from,to)..to`。
4. 过滤文件：
   - binary。
   - 用户 exclude。
   - 用户 include 绕过默认过滤。
   - unsupported extension。
   - default test/generated path。
5. 按文件生成子任务，受 `--concurrency` 控制并发。
6. 对大 diff 可选先做 plan。
7. 每个文件运行 main LLM tool loop。
8. `code_comment` 产生结构化评论。
9. 评论经过行号定位、跨文件重定位、可选 LLM re-location。
10. 可选 review filter 过滤误报。
11. 输出 text/JSON，并写 session JSONL 与 run manifest。

`scan` 路径不是 diff review，而是 full-file scan：先枚举文件，再按文件/语言/目录分批，复用同一个 `llmloop.Runner` 进行审查。

## 核心设计：确定性工程 × Agent

OCR 的 README 和架构文档反复强调：通用 agent 做 code review 时常见问题是覆盖不全、位置漂移、效果不稳定。OCR 的解决方式是把“不能错”的部分工程化：

- 文件选择由 Git/diff/filter 决定，不交给模型。
- 规则匹配由 path glob 和内置规则决定，不交给模型自由解释。
- 大变更按文件并发分治，不让模型一次吞完整 PR。
- 评论位置由 `existing_code` + diff 滑动窗口解析，不直接相信模型行号。
- 无法定位时再用 re-location LLM 作为回退。
- review filter 在最后再清理可证明为错的评论。
- session manifest 明确 selected/completed/reused/failed/waived，覆盖率可审计。

这是一种很强的产品化取舍：牺牲一部分自由探索和召回，换取更高 precision、更低噪声、更低 token 和可恢复性。

## Diff Provider

`internal/diff/git.go` 中的 `Provider` 支持三种模式：

| 模式 | 入口 | 实现要点 |
| --- | --- | --- |
| workspace | `ocr review` | 合并 tracked diff 和 untracked 文件 diff。 |
| commit | `ocr review --commit` | 使用 `git show`，merge commit 按 first parent 处理。 |
| range | `ocr review --from --to` | 先求 merge-base，再做 `base..to`。 |

值得注意的工程细节：

- Git 命令使用显式参数列表，不走 shell 拼接。
- diff 统一设置 `--no-ext-diff`、`--no-textconv`、`--find-renames`、`--no-color`。
- range/commit 会冻结 resolved base/head/exact range，用于 manifest 和 resume 身份。
- `vendor/`、`node_modules/`、`target/` 等噪声目录在 diff provider 层先过滤。
- `.gitignore` 处理遵循 last-match-wins 和 negation 规则。

## 文件过滤与规则匹配

OCR 的过滤是五重门：

1. binary：二进制文件排除。
2. user exclude：用户规则优先排除。
3. user include：若匹配，立即保留，绕过扩展名和默认测试文件过滤。
4. unsupported extension：扩展名不在 allowlist 则排除。
5. default path：测试文件、`__tests__` 等默认排除。

规则匹配是四层优先级：

1. CLI `--rule`。
2. 项目 `.opencodereview/rule.json`。
3. 用户全局 `~/.opencodereview/rule.json`。
4. 内嵌 `system_rules.json`。

规则是 path glob 到 rule text 的映射。系统内置覆盖 Java、Go、Python、TS/JS、Rust、Kotlin、SQL mapper、package manifest、CI YAML、Terraform、GraphQL、Prisma 等文件类型。

这套机制的价值在于：模型看到的 review criteria 是按文件类型和路径确定的，不是一个泛泛的“请认真审查代码”提示词。

## Prompt Template

OCR 的 review template 包含五类任务：

| Template key | 用途 |
| --- | --- |
| `PLAN_TASK` | 大 diff 的只读计划阶段。 |
| `MAIN_TASK` | 主审查循环，模型可调用工具。 |
| `MEMORY_COMPRESSION_TASK` | 对历史工具对话做摘要压缩。 |
| `REVIEW_FILTER_TASK` | 对生成评论做最终过滤。 |
| `RE_LOCATION_TASK` | 评论无法定位时重新锚定代码片段。 |

关键占位符：

- `{{system_rule}}`：当前文件匹配到的规则。
- `{{change_files}}`：本次变更中的其他文件。
- `{{diff}}`：当前文件 diff。
- `{{current_file_path}}`：当前文件路径。
- `{{plan_guidance}}`：plan 结果。
- `{{plan_tools}}`：plan 阶段可用工具的文本说明。
- `{{requirement_background}}`：用户提供的背景。
- `{{current_system_date_time}}`：当前时间。
- `{{context}}`：压缩任务要摘要的历史 XML。

模板加载后固定为内存中的 message 列表，CLI 主要通过配置、规则和工具定义间接影响 prompt。

## 工具系统

OCR 内置六个工具：

| 工具 | Plan | Main | 作用 |
| --- | --- | --- | --- |
| `task_done` | 否 | 是 | 结束当前文件的 main loop。 |
| `code_comment` | 否 | 是 | 生成结构化评审评论。 |
| `file_read` | 否 | 是 | 读取变更后文件片段，最多 500 行。 |
| `file_read_diff` | 是 | 是 | 读取本次变更中其他文件的 diff。 |
| `file_find` | 是 | 是 | 按文件名查找文件。 |
| `code_search` | 是 | 是 | 基于 Git 的全文搜索。 |

工具定义来自 `internal/config/toolsconfig/tools.json`，包含 OpenAI/Anthropic 风格的 JSON schema。实现层由 `internal/tool.Registry` 注册 `Provider`，registry 在运行前 `Freeze()`，并发读取时不再变。

几个重要取舍：

- plan 阶段只读，不能 `code_comment` 或 `task_done`。
- `code_comment` 是评论产出唯一入口，输出含 `content`、`existing_code`、`suggestion_code`、`category`、`severity`。
- 运行时会覆盖 `code_comment.path` 为当前文件，避免模型幻觉路径。
- `file_read_diff` 和 `code_search` 是上下文工具，不是让模型去评论其他文件。
- 工具计数会被汇总到 JSON 输出中的 `tool_calls`。

## LLM Loop

`internal/llmloop.Runner` 是 OCR 的单文件 agent loop。它被 diff review 和 scan 共用。

主循环行为：

1. 每轮向 LLM 发送 messages + tool definitions。
2. 如果没有 tool call，追加提醒消息后重试。
3. 逐个执行 tool call。
4. 如果 `task_done` 成功，结束。
5. 如果 `code_comment`，解析评论并进入异步/同步定位与收集。
6. 把 assistant tool call 和 tool result 加回 messages。
7. 检查 token，必要时压缩。

退出条件：

- `task_done`。
- `MaxToolRequestTimes` 用尽。
- 连续多轮没有可用工具结果。
- context cancel。
- 压缩后仍超过 warning threshold。

Runner 还聚合：

- input/output/cache tokens。
- tool call counts。
- warning 列表。
- background compression goroutine。

## 记忆压缩

OCR 的“记忆”主要是单文件 review 过程中的对话压缩，不是长期项目记忆。

它采用三分区：

- frozen：前两条消息，通常是 system + 初始 user。
- compress：中间较旧的 assistant/tool rounds。
- active：最近能放进预算的完整 rounds。

阈值：

- 60% `MaxTokens`：启动异步后台压缩。
- 80% `MaxTokens`：同步压缩，保证下一轮请求能放下。

压缩过程：

1. 把 compress 区序列化为 XML。
2. 调用 `MEMORY_COMPRESSION_TASK`。
3. 把摘要写回第二条 user message 的 `<previous_review_summary>`。
4. 保留 active 区原样。

这套设计适合长工具循环，因为它保护初始任务和最近工具结果，同时把中间历史摘要化。

## 评论定位与过滤

`code_comment` 不直接相信模型行号，而要求模型给 `existing_code`。OCR 再做定位：

1. 在当前文件 diff 的新侧 hunk 中匹配 context + added。
2. 失败后在旧侧 hunk 中匹配 context + deleted。
3. 对全新文件，扫描变更后完整内容。
4. 对跨文件误报，尝试在所有 reviewed diffs 里重定位。
5. 仍失败时，调用 `RE_LOCATION_TASK` 让模型重新锚定。
6. 最后仍失败则 `start_line/end_line = 0`，作为未锚定评论。

主循环结束后还有 `REVIEW_FILTER_TASK`，对累积评论和 diff 做对照，移除可证明错误的评论。顶层输出前还会再做一次 line resolution。

这是 OCR 最值得学习的垂直特性：让 LLM 负责“发现问题”，让确定性算法负责“把问题固定到正确位置”。

## Session、Resume 与 Manifest

OCR 使用 JSONL 保存 session，路径在用户 home 下：

`~/.opencodereview/sessions/<encoded-repo-path>/<session-id>.jsonl`

主要 record 类型：

- `session_start`
- `llm_request`
- `llm_response`
- `llm_error`
- `tool_call`
- `review_item_done`
- `review_item_reused`
- `review_item_failed`
- `resume_lineage`
- `session_end`

Resume 以文件级 fingerprint 为索引。对 review 来说，单个 checkpoint 记录不够，是否可复用还要看 parent manifest 是否把该 fingerprint 记为 completed 或 reused。

Run manifest 是 OCR 很重要的可审计工件，包含：

- schema version。
- run id / parent run id。
- operation。
- terminal state：complete、partial、failed、skipped。
- repository identity hash。
- frozen input identity。
- execution 信息：version、provider、model、concurrency、rule/runtime config hash。
- coverage：selected、completed、reused、failed、waived。
- run failure。
- elapsed ms。

这让 OCR 能回答“这次 review 覆盖了哪些文件、哪些复用了旧结果、哪些失败、为什么失败”。

## Scan 模式

`ocr scan` 面向无 diff 或全量审计场景。它和 review 的差异：

- 输入不是 Git diff，而是文件枚举。
- 支持最大文件大小。
- 可按语言或一级目录分 batch。
- 有独立 scan template。
- 可选 plan、dedup、summary。
- 每个 scan item 会被适配成 synthetic diff，复用评论定位逻辑。

这说明 OCR 的抽象边界比较清晰：单文件 LLM loop 是可复用核心，review 和 scan 只是上游输入不同。

## 输出与可观测性

OCR 支持 text 和 JSON 输出。JSON 输出包含：

- status。
- llm provider/model。
- trace id。
- summary：files reviewed、comments、tokens、elapsed、budget exceeded。
- tool_calls：总数和按工具计数。
- comments。
- warnings。
- project summary。
- resume 信息。
- session id。
- manifest。
- retry report。

此外 OCR 支持 OpenTelemetry，用 span 和 metrics 记录 diff parse、review started、LLM request、tool result 等过程。

## 安全设计

从 `ASSURANCE_CASE.md` 和源码可以看出 OCR 的安全重点：

- 外部命令主要是 Git，使用 `exec.Command` 参数数组，不做 shell 插值。
- Git 命令使用 `--end-of-options` 防 flag injection。
- LLM provider 通过 HTTPS。
- API key 不进入日志/输出。
- 文件路径通过 repo root 校验。
- viewer 默认 localhost，带 Host header guard 和安全响应头。
- Go + `CGO_ENABLED=0` 降低内存和 native 依赖风险。
- CI 中强调 `go vet`、`govulncheck`、race detector、coverage。

## 测试与工程质量

OCR 测试覆盖很广：

- Go 单元测试覆盖 diff parser、git provider、filter、rules、tool、llmloop、session、resume、manifest、viewer。
- CLI 命令测试覆盖 review/scan/session/config/provider 等。
- Node 脚本测试覆盖 npm/version/GitHub Actions helper。
- VS Code extension 有前端和服务测试。
- `make test` 设置 `LC_ALL=C`，避免 Git 输出语言影响测试。
- `make coverage` 有 90% 覆盖率门槛。
- 有 license header、英文源码检查、action pin 检查。

## OCR 的关键特性清单

| 类别 | 特性 | 价值 |
| --- | --- | --- |
| 输入控制 | workspace/commit/range/full scan | 覆盖常见 review 场景。 |
| 文件筛选 | 五重门过滤、preview | 降低 token 和噪声，避免遗漏/误审。 |
| 规则系统 | 四层规则优先级、按路径匹配 | 针对文件类型和项目约定定制审查重点。 |
| 分治 | per-file subtask、并发限制 | 大 PR 稳定，耗时可控。 |
| Plan | 大 diff 可选计划阶段 | 让模型先形成审查清单，降低盲查。 |
| 工具 | 场景化 review 工具集 | 比通用工具更稳定。 |
| 评论 | 结构化 `code_comment` | 输出可机器消费。 |
| 定位 | `existing_code` 滑动窗口 + re-location | 减少位置漂移。 |
| 过滤 | review filter | 降低误报。 |
| 记忆 | 三分区压缩 | 控制长循环上下文。 |
| 持久化 | JSONL session | 可回放、可 resume。 |
| Manifest | coverage sets + terminal state | 可审计、可度量。 |
| Resume | fingerprint + manifest gate | 可安全复用旧结果。 |
| 指标 | token、tool calls、elapsed、warnings | 成本和行为可观测。 |
| 集成 | GitHub/GitLab/Gerrit/Codeup/Bitbucket、agent plugin、VS Code | 产品化交付能力。 |

## 对 RepoPilot 的直接启发

RepoPilot 不应把 OCR 复制成 review-only 产品，但可以学习 OCR 的“确定性外壳”：

- 当任务可以被工程逻辑切分时，不要让 LLM 自己决定全部流程。
- 对输出位置、覆盖范围、状态复用等可验证事实，尽量用代码判定。
- 让 LLM 产出结构化结果，而不是一段自然语言。
- 对结果做后处理验证，例如定位、过滤、二次校验。
- 把运行覆盖率和成本变成 manifest/report 中的硬指标。

这会让 RepoPilot 从“会调用工具的本地 agent”升级为“能用工程约束保证部分质量的 agent harness”。
