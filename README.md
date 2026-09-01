# RepoPilot

RepoPilot is a lightweight local coding agent for working directly inside a Git repository. It runs in the terminal, lets a language model request bounded tools, records every step locally, and keeps enough runtime state to resume investigation across turns.

The project is intentionally small: it does not depend on LangGraph or a heavy orchestration framework. The runtime keeps the agent loop explicit so tool execution, approvals, event logging, context budgeting, and recovery behavior can be tested as ordinary Python code.

## Screenshots

Startup screen:

![RepoPilot startup](assets/screenshots/start.png)

Interactive help:

![RepoPilot help](assets/screenshots/help.png)

## What It Does

- Understands a local workspace before answering repository questions.
- Uses a bounded tool set for file listing, file reading, search, shell commands, file writes, patching, and delegated read-only investigation.
- Shows live terminal feedback while the model is thinking or a tool is running.
- Persists session history, memory, checkpoints, traces, reports, and coverage artifacts under `.repopilot/`.
- Supports resumable sessions through `--resume latest` or a specific session id.
- Supports DeepSeek, OpenAI-compatible, Anthropic-compatible, and Ollama model backends.

## Why This Exists

Most coding-agent demos hide the runtime behind natural-language prompts. RepoPilot focuses on the engineering boundary around the model:

- Tool calls have explicit schemas and validation.
- Tool results carry structured metadata for trace/report generation.
- Repeated equivalent tool calls are rejected before they waste tool budget.
- Shell output is captured as bytes and decoded explicitly, avoiding Windows GBK/UTF-8 failures on Chinese source files or logs.
- Runtime history is projected from an append-only session event log instead of relying only on mutable in-memory state.

That makes the system easier to inspect, test, resume, and explain.

## Core Architecture

```text
CLI
  -> Workspace snapshot
  -> Model client
  -> AgentLoop
       -> build prompt from projected history + memory + context budget
       -> request model action
       -> parse tool call or final answer
       -> validate and execute tool
       -> append event log + trace + checkpoint
       -> continue until final answer or step limit
```

Important modules:

| Area | Files |
| --- | --- |
| CLI and provider setup | `repopilot/cli.py`, `repopilot/providers/` |
| Agent loop | `repopilot/agent_loop.py`, `repopilot/runtime.py` |
| Tool protocol | `repopilot/tools.py`, `repopilot/tool_executor.py`, `repopilot/tool_context.py` |
| Context management | `repopilot/context_manager.py`, `repopilot/context_compression.py` |
| Event log and run artifacts | `repopilot/session_log.py`, `repopilot/event_log.py`, `repopilot/run_store.py` |
| Checkpoint and resume | `repopilot/checkpoint.py`, `repopilot/task_state.py` |
| Memory promotion | `repopilot/memory_promotion.py`, `repopilot/features/memory.py` |
| Evaluation scripts | `scripts/`, `repopilot/evaluation/`, `docs/metrics/` |

## Key Features

### Schema-First Tool Boundary

RepoPilot exposes a small allowlisted set of tools. Each tool declares a parameter schema, validates arguments before execution, and returns model-facing text plus machine-readable metadata. This keeps the runtime from depending on fragile string parsing for status, exit codes, or reporting.

### Append-Only Event Log

Current run history, trace records, and report data are projected from local append-only events. This gives the agent a source of truth that can be replayed, audited, and tested without trusting a mutable prompt string as the only record of what happened.

### Context Budgeting

The context manager builds prompts from workspace facts, projected history, memory, and the current request. Under long-context pressure it preserves the latest user request while reducing older or lower-priority context.

Latest deterministic long-context stress matrix:

| Metric | Result |
| --- | ---: |
| Configurations | 12 |
| Average raw prompt | 6,959 chars |
| Average managed prompt | 5,541 chars |
| Average reduction | 16.43% |
| Max reduction | 33.72% |
| Current request preserved | 100% |

Source: `docs/metrics/latest-long-context-stress.md`.

### Durable Memory Promotion

RepoPilot separates candidate memory extraction from durable memory writes. Candidate facts are scored, deduplicated, checked for conflicts, and filtered for sensitive content before promotion.

Memory promotion benchmark:

| Metric | Result |
| --- | ---: |
| Candidate facts | 180 |
| Categories | 6 |
| Promoted reusable facts | 90 |
| Rejected unsafe/noisy facts | 60 |
| Conflicting facts held for confirmation | 30 |
| Sensitive leaks in SAVE strategy | 0 |

Source: `docs/metrics/p7-memory-promotion-experiment.md`.

### Checkpoint and Resume

RepoPilot writes local checkpoints after meaningful runtime events. A later session can resume with the previous history, memory, context-compression state, and workspace drift information.

```bash
uv run repopilot --resume latest
```

## Installation

RepoPilot requires Python 3.10+.

```bash
uv sync
```

Or install in editable mode:

```bash
pip install -e .
```

## Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Fill only the provider keys you use. `.env` is ignored by Git.

Default provider selection:

```text
CLI --provider > REPOPILOT_PROVIDER > deepseek
```

Supported providers:

| Provider | Example |
| --- | --- |
| DeepSeek Anthropic-compatible | `uv run repopilot --provider deepseek` |
| OpenAI-compatible Responses API | `uv run repopilot --provider openai` |
| Anthropic-compatible Messages API | `uv run repopilot --provider anthropic` |
| Ollama local model | `uv run repopilot --provider ollama --model qwen3.5:4b` |

## Usage

Start the interactive terminal agent:

```bash
uv run repopilot
```

Use a specific workspace:

```bash
uv run repopilot --cwd /path/to/repo
```

Run a one-shot task:

```bash
uv run repopilot "inspect the failing tests and propose a fix"
```

Increase the maximum tool/model iterations for larger repository questions:

```bash
uv run repopilot --max-steps 10
```

Resume the latest saved session:

```bash
uv run repopilot --resume latest
```

Useful REPL commands:

| Command | Purpose |
| --- | --- |
| `/help` | Show built-in commands |
| `/memory` | Show distilled working memory |
| `/session` | Print the current saved session path |
| `/reset` | Clear current session history and memory |
| `/exit` | Exit the REPL |

## Local Artifacts

RepoPilot writes runtime artifacts under `.repopilot/`:

```text
.repopilot/sessions/        saved sessions
.repopilot/runs/<run_id>/   task_state.json, trace.jsonl, report.json
```

These files are local-only and ignored by Git. Personal notes, imported comparison repositories, resumes, local scratch folders, and provider secrets are also ignored.

## Development

Run the test suite:

```bash
uv run pytest tests -q
```

Run focused checks while working on the runtime boundary:

```bash
uv run pytest tests/test_tools.py tests/test_tool_executor.py tests/test_agent_loop.py -q
```

Run the long-context experiment:

```bash
uv run python scripts/run_large_scale_experiments.py
```

Run the memory-promotion experiment:

```bash
uv run python scripts/run_memory_promotion_experiment.py
```

## Project Status

RepoPilot is a portfolio-scale agent runtime. It is designed to make the engineering around a coding agent visible: tool safety, structured execution results, event-log replay, context budgeting, memory promotion, checkpoint/resume, and measurable regression behavior.
