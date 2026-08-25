"""Large-file tail-answer probes for RepoPilot."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path

from ..runtime import RepoPilot, SessionStore
from ..workspace import WorkspaceContext


DEFAULT_FILENAME = "big_tail.txt"
DEFAULT_EXPECTED = "omega-tail-answer-7429"
READ_PAGE_SIZE = 200


class _TailProbeModelClient:
    supports_prompt_cache = False

    def __init__(self, expected, filename):
        self.expected = str(expected)
        self.filename = str(filename)
        self.prompts = []
        self.last_completion_metadata = {}
        self.read_file_calls = 0
        self.run_shell_calls = 0

    def _has_answer(self, prompt):
        return self.expected.lower() in str(prompt).lower()

    def _final_found(self):
        return f"<final>{self.expected}</final>"

    @staticmethod
    def _final_not_found():
        return "<final>not found</final>"


class HeadOnlyTailProbeClient(_TailProbeModelClient):
    """Reads the default head range once, then answers from available evidence."""

    def __init__(self, expected, filename):
        super().__init__(expected, filename)
        self.phase = "read_head"

    def complete(self, prompt, max_new_tokens, **kwargs):
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        self.last_completion_metadata = {}
        if self._has_answer(prompt):
            return self._final_found()
        if self.phase == "read_head":
            self.phase = "final"
            self.read_file_calls += 1
            return (
                f'<tool>{{"name":"read_file","args":{{"path":"{self.filename}",'
                f'"start":1,"end":{READ_PAGE_SIZE}}}}}</tool>'
            )
        return self._final_not_found()


class SequentialTailProbeClient(_TailProbeModelClient):
    """Pages through the file with read_file until answer or budget exhaustion."""

    def __init__(self, expected, filename):
        super().__init__(expected, filename)
        self.next_start = 1

    def complete(self, prompt, max_new_tokens, **kwargs):
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        self.last_completion_metadata = {}
        if self._has_answer(prompt):
            return self._final_found()
        if "tool budget is exhausted" in str(prompt).lower():
            return self._final_not_found()
        start = self.next_start
        end = start + READ_PAGE_SIZE - 1
        self.next_start = end + 1
        self.read_file_calls += 1
        return (
            f'<tool>{{"name":"read_file","args":{{"path":"{self.filename}",'
            f'"start":{start},"end":{end}}}}}</tool>'
        )


class ShellTailProbeClient(_TailProbeModelClient):
    """Uses run_shell tail-style reading to inspect the end of the file."""

    def __init__(self, expected, filename, tail_lines=5):
        super().__init__(expected, filename)
        self.tail_lines = int(tail_lines)
        self.phase = "tail"

    def complete(self, prompt, max_new_tokens, **kwargs):
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        self.last_completion_metadata = {}
        if self._has_answer(prompt):
            return self._final_found()
        if self.phase == "tail":
            self.phase = "final"
            self.run_shell_calls += 1
            command = (
                "python -c \"from pathlib import Path; "
                f"print(chr(10).join(Path('{self.filename}').read_text(encoding='utf-8').splitlines()[-{self.tail_lines}:]))\""
            )
            return (
                '<tool>{"name":"run_shell","args":{'
                f'"command":{json.dumps(command)},"timeout":20'
                "}}</tool>"
            )
        return self._final_not_found()


class DirectLineTailProbeClient(_TailProbeModelClient):
    """Reads the exact answer line, showing the tool can fetch it if the line is known."""

    def __init__(self, expected, filename, answer_line):
        super().__init__(expected, filename)
        self.answer_line = int(answer_line)
        self.phase = "read_line"

    def complete(self, prompt, max_new_tokens, **kwargs):
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        self.last_completion_metadata = {}
        if self._has_answer(prompt):
            return self._final_found()
        if self.phase == "read_line":
            self.phase = "final"
            self.read_file_calls += 1
            return (
                f'<tool>{{"name":"read_file","args":{{"path":"{self.filename}",'
                f'"start":{self.answer_line},"end":{self.answer_line}}}}}</tool>'
            )
        return self._final_not_found()


def write_large_tail_file(workspace_root, filename=DEFAULT_FILENAME, total_lines=2000, answer_line=None, expected=DEFAULT_EXPECTED):
    workspace_root = Path(workspace_root)
    answer_line = int(answer_line or total_lines)
    if answer_line < 1 or answer_line > total_lines:
        raise ValueError("answer_line must be inside the generated file")

    lines = []
    for number in range(1, int(total_lines) + 1):
        if number == answer_line:
            lines.append(f"{number:05d} FINAL ANSWER TOKEN: {expected}")
        else:
            lines.append(f"{number:05d} filler text; no answer token on this line")
    path = workspace_root / filename
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_tail_probe_agent(workspace_root, model_client, max_steps=6):
    workspace_root = Path(workspace_root)
    (workspace_root / "README.md").write_text("large tail probe workspace\n", encoding="utf-8")
    workspace = WorkspaceContext.build(workspace_root)
    return RepoPilot(
        model_client=model_client,
        workspace=workspace,
        session_store=SessionStore(workspace_root / ".repopilot" / "sessions"),
        approval_policy="auto",
        max_steps=int(max_steps),
    )


def _client_for_strategy(strategy, expected, filename, answer_line):
    if strategy == "head_only":
        return HeadOnlyTailProbeClient(expected, filename)
    if strategy == "sequential":
        return SequentialTailProbeClient(expected, filename)
    if strategy == "shell_tail":
        return ShellTailProbeClient(expected, filename)
    if strategy == "direct_line":
        return DirectLineTailProbeClient(expected, filename, answer_line)
    raise ValueError(f"unknown strategy: {strategy}")


def run_tail_probe(strategy, total_lines=2000, answer_line=None, max_steps=6, expected=DEFAULT_EXPECTED, filename=DEFAULT_FILENAME):
    answer_line = int(answer_line or total_lines)
    with tempfile.TemporaryDirectory(prefix="repopilot-tail-probe-") as temp_dir:
        workspace_root = Path(temp_dir)
        write_large_tail_file(
            workspace_root,
            filename=filename,
            total_lines=int(total_lines),
            answer_line=answer_line,
            expected=expected,
        )
        client = _client_for_strategy(strategy, expected, filename, answer_line)
        agent = build_tail_probe_agent(workspace_root, client, max_steps=max_steps)
        final_answer = agent.ask(
            f"Find the final answer token in {filename}. It is near the end of a large file."
        )
        history = list(agent.session["history"])
        read_ranges = [
            [int(item["args"].get("start", 1)), int(item["args"].get("end", READ_PAGE_SIZE))]
            for item in history
            if item.get("role") == "tool" and item.get("name") == "read_file"
        ]
        run_shell_calls = [
            item
            for item in history
            if item.get("role") == "tool" and item.get("name") == "run_shell"
        ]
        correct = expected.lower() in str(final_answer).lower()
        required_read_pages = math.ceil(answer_line / READ_PAGE_SIZE)
        return {
            "strategy": strategy,
            "total_lines": int(total_lines),
            "answer_line": answer_line,
            "answer_in_tail": answer_line > int(total_lines) - 50,
            "max_steps": int(max_steps),
            "read_page_size": READ_PAGE_SIZE,
            "required_read_pages_from_start": required_read_pages,
            "correct": bool(correct),
            "final_answer": final_answer,
            "status": agent.current_task_state.status,
            "stop_reason": agent.current_task_state.stop_reason,
            "attempts": int(agent.current_task_state.attempts),
            "tool_steps": int(agent.current_task_state.tool_steps),
            "read_file_calls": len(read_ranges),
            "run_shell_calls": len(run_shell_calls),
            "read_ranges": read_ranges,
        }


DEFAULT_SCENARIOS = (
    {"strategy": "head_only", "total_lines": 2000, "answer_line": 2000, "max_steps": 6},
    {"strategy": "sequential", "total_lines": 1000, "answer_line": 1000, "max_steps": 6},
    {"strategy": "sequential", "total_lines": 2000, "answer_line": 2000, "max_steps": 6},
    {"strategy": "sequential", "total_lines": 2000, "answer_line": 2000, "max_steps": 12},
    {"strategy": "direct_line", "total_lines": 2000, "answer_line": 2000, "max_steps": 6},
    {"strategy": "shell_tail", "total_lines": 2000, "answer_line": 2000, "max_steps": 6},
)


def run_default_tail_probes():
    return [run_tail_probe(**scenario) for scenario in DEFAULT_SCENARIOS]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run RepoPilot large-file tail-answer probes.")
    parser.add_argument("--strategy", choices=["all", "head_only", "sequential", "direct_line", "shell_tail"], default="all")
    parser.add_argument("--total-lines", type=int, default=2000)
    parser.add_argument("--answer-line", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args(argv)

    if args.strategy == "all":
        results = run_default_tail_probes()
    else:
        results = [
            run_tail_probe(
                args.strategy,
                total_lines=args.total_lines,
                answer_line=args.answer_line or args.total_lines,
                max_steps=args.max_steps,
            )
        ]
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
