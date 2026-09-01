# RepoPilot v2.0 文件分区说明

当前分支：`RepoPilotv2.0`。

## 原始版本上修改的 tracked 文件

这些文件来自原始 RepoPilot 代码，在 v2.0 中被修改，属于需要 review/commit 的主体变更。

- `.gitignore`
- `repopilot/agent_loop.py`
- `repopilot/cli.py`
- `repopilot/context_manager.py`
- `repopilot/prompt_prefix.py`
- `repopilot/run_store.py`
- `repopilot/runtime.py`
- `repopilot/tool_executor.py`
- `repopilot/tools.py`
- `repopilot/workspace.py`
- `tests/test_agent_loop.py`
- `tests/test_context_manager.py`
- `tests/test_prompt_prefix.py`
- `tests/test_public_api_contract.py`
- `tests/test_run_store.py`
- `tests/test_tool_executor.py`

## v2.0 新增文件

这些是 v2.0 新增的功能、实验和测试文件。

- `repopilot/event_log.py`
- `repopilot/rules.py`
- `repopilot/coverage_manifest.py`
- `repopilot/findings.py`
- `repopilot/inspection.py`
- `repopilot/context_compression.py`
- `repopilot/evaluation/context_compression.py`
- `repopilot/evaluation/adaptive_context_compression.py`
- `repopilot/evaluation/large_file_tail.py`
- `scripts/run_context_compression_experiment.py`
- `scripts/run_adaptive_context_compression_experiment.py`
- `scripts/run_large_file_tail_experiment.py`
- `tests/test_rules.py`
- `tests/test_coverage_manifest.py`
- `tests/test_findings.py`
- `tests/test_inspection.py`
- `tests/test_context_compression.py`
- `tests/test_large_file_tail_experiment.py`

## v2.0 文档与实验结果

这些文档现在已从 `.gitignore` 中放开，属于 v2.0 分支成果，可以随代码一起提交。

- `docs/architecture/agent-harness-v1-overview.md`
- `docs/architecture/alibaba-open-code-review-analysis.md`
- `docs/architecture/repopilot-lessons-from-deepseek-and-alibaba.md`
- `docs/architecture/repopilot-vs-deepseek-harness.md`
- `docs/architecture/【详解】P1-P6修改详解.md`
- `docs/metrics/adaptive-context-compression-experiment.json`
- `docs/metrics/adaptive-context-compression-experiment.md`
- `docs/metrics/context-compression-p6-experiment.json`
- `docs/metrics/context-compression-p6-experiment.md`
- `docs/metrics/context-compression-p6-llm-experiment.json`
- `docs/metrics/context-compression-p6-llm-experiment.md`
- `docs/metrics/p1-p2-structured-tools-event-log-results.md`
- `docs/metrics/p1-p3-structured-tools-event-log-rules-results.md`
- `docs/metrics/p1-p4-structured-tools-event-log-rules-coverage-results.md`
- `docs/metrics/p1-p5-structured-tools-event-log-rules-coverage-inspect-results.md`
- `docs/metrics/p1-p6-context-compression-results.md`
- `docs/metrics/p2-event-log-source-of-truth-results.md`
- `docs/metrics/p6-5-adaptive-context-compression-results.md`

## 本地参考材料归档位置

以下材料已移动到 `IgnoreFile/local-reference/`，并由 `.gitignore` 忽略，不会被 `git add .` 上传。

- `IgnoreFile/local-reference/comparison-sources/`: DeepSeek Harness、Alibaba OCR 等解压后的对比源码。
- `IgnoreFile/local-reference/archives/`: 原始 zip 包。
- `IgnoreFile/local-reference/diagrams/`: drawio、png、drawio backup。
- `IgnoreFile/local-reference/local-docs/`: 根目录下的个人说明草稿。
- `IgnoreFile/local-reference/personal-files/`: PDF、CSV 等个人资料。
- `IgnoreFile/local-reference/tmp/`: 临时抽取文本。

## 仍需人工确认

- `PROJECT_ONBOARDING_AND_RESUME.md` 当前在 git status 中是 deleted。这个删除不是本次整理产生的；提交前需要确认是否真的要删除。
- `repopilot/cli.py` 和 `repopilot/workspace.py` 在开始整理前已经有改动，其中 `cli.py` 后续又叠加了 v2.0 的 `--inspect` 改动；提交前建议单独 review diff。

## 推荐提交方式

1. 先 review `.gitignore` 和本文件。
2. 确认 `PROJECT_ONBOARDING_AND_RESUME.md` 是否恢复或删除。
3. 使用 `git add` 只添加 v2.0 代码、测试、脚本和 docs，不要添加 `IgnoreFile/`。
