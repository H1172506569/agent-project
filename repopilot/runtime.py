"""Agent 运行时核心逻辑。

RepoPilot 就是包在模型外面的控制循环：负责组 prompt、解析模型输出、
校验并执行工具、写 trace、更新工作记忆，以及在合适的时候停下来。
"""

import json
import hashlib
import os
import threading
import re
import uuid
from datetime import datetime
from pathlib import Path

from . import checkpoint as checkpointlib
from .features import memory as memorylib
from . import security as securitylib
from .config import load_project_env, provider_env
from .context_compression import (
    render_llm_tool_round_compressed_history,
    render_tool_round_compressed_history,
)
from .context_manager import ContextManager
from .coverage_manifest import build_coverage_manifest
from .event_log import event_log_metrics, project_history
from .memory_promotion import MemoryPromotionPolicy, generate_memory_candidates, memory_promotion_metrics
from .checkpoint import CHECKPOINT_NONE_STATUS
from .prompt_prefix import build_prompt_prefix, tool_signature
from .providers.clients import AnthropicCompatibleModelClient
from .run_store import RunStore
from .session_store import SessionStore
from .tool_context import ToolContext
from .tool_executor import ToolExecutor
from . import tools as toolkit
from .workspace import IGNORED_PATH_NAMES, MAX_HISTORY, WorkspaceContext, clip, now

DEFAULT_SHELL_ENV_ALLOWLIST = (
    "ComSpec",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LOGNAME",
    "PATH",
    "PATHEXT",
    "PWD",
    "SHELL",
    "SystemRoot",
    "TERM",
    "TMPDIR",
    "TMP",
    "TEMP",
    "USER",
    "WINDIR",
)
DEFAULT_FEATURE_FLAGS = {
    "memory": True,
    "relevant_memory": True,
    "context_reduction": True,
    "prompt_cache": True,
    "tool_round_compression": False,
    "adaptive_context_compression": False,
    "llm_context_compression": True,
    "memory_candidate_promotion": True,
}
__all__ = ["RepoPilot", "SessionStore"]


class RepoPilot:
    def __init__(
        self,
        model_client,
        workspace,
        session_store,
        session=None,
        run_store=None,
        approval_policy="ask",
        max_steps=6,
        max_new_tokens=512,
        depth=0,
        max_depth=1,
        read_only=False,
        shell_env_allowlist=None,
        secret_env_names=None,
        feature_flags=None,
        allowed_tools=None,
        context_compression_model_client=None,
    ):
        self.model_client = model_client
        self.context_compression_model_client = context_compression_model_client
        self.workspace = workspace
        self.root = Path(workspace.repo_root)
        self.session_store = session_store
        self.approval_policy = approval_policy
        self.max_steps = max_steps
        self.max_new_tokens = max_new_tokens
        self.depth = depth
        self.max_depth = max_depth
        self.read_only = read_only
        self.shell_env_allowlist = tuple(shell_env_allowlist or DEFAULT_SHELL_ENV_ALLOWLIST)
        self.secret_env_names = {str(name).upper() for name in (secret_env_names or ())}
        self.feature_flags = dict(DEFAULT_FEATURE_FLAGS)
        if feature_flags:
            self.feature_flags.update({str(key): bool(value) for key, value in feature_flags.items()})
        self.allowed_tools = self._normalize_allowed_tools(allowed_tools)
        self.run_store = run_store or RunStore(Path(workspace.repo_root) / ".repopilot" / "runs")
        self.session = session or {
            "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "created_at": now(),
            "workspace_root": workspace.repo_root,
            "history": [],
            "memory": memorylib.default_memory_state(),
        }
        self._ensure_session_shape()
        self.memory = memorylib.LayeredMemory(
            self.session.setdefault("memory", memorylib.default_memory_state()),
            workspace_root=self.root,
        )
        self.session["memory"] = self.memory.to_dict()
        self.tools = self._apply_tool_allowlist(self.build_tools())
        self.tool_executor = ToolExecutor(self)
        self.prefix_state = self.build_prefix()
        self.prefix = self.prefix_state.text
        self.context_manager = ContextManager(self)
        self.resume_state = self.evaluate_resume_state()
        self.session_path = self.session_store.save(self.session)
        self.current_task_state = None
        self.current_run_dir = None
        self.last_prompt_metadata = {}
        self.last_completion_metadata = {}
        self.last_memory_candidates = []
        self.last_memory_promotion_decisions = []
        self.last_memory_promotion_metrics = memory_promotion_metrics([], [])
        self._last_tool_result_metadata = {}
        self._last_prefix_refresh = {
            "workspace_changed": False,
            "prefix_changed": False,
        }
        self._context_compression_lock = threading.Lock()
        self._context_compression_thread = None

    @classmethod
    def from_session(cls, model_client, workspace, session_store, session_id, **kwargs):
        return cls(
            model_client=model_client,
            workspace=workspace,
            session_store=session_store,
            session=session_store.load(session_id),
            **kwargs,
        )

    def _ensure_session_shape(self):
        self.session.setdefault("history", [])
        self.session.setdefault("memory", memorylib.default_memory_state())
        checkpoints = self.session.setdefault("checkpoints", {})
        if not isinstance(checkpoints, dict):
            checkpoints = {}
            self.session["checkpoints"] = checkpoints
        checkpoints.setdefault("current_id", "")
        checkpoints.setdefault("items", {})
        runtime_identity = self.session.setdefault("runtime_identity", {})
        if not isinstance(runtime_identity, dict):
            self.session["runtime_identity"] = {}
        resume_state = self.session.setdefault("resume_state", {})
        if not isinstance(resume_state, dict):
            self.session["resume_state"] = {}
        compression = self.session.setdefault("context_compression", {})
        if not isinstance(compression, dict):
            self.session["context_compression"] = {}

    def current_runtime_identity(self):
        return checkpointlib.current_runtime_identity(self)

    def checkpoint_state(self):
        return checkpointlib.checkpoint_state(self)

    def current_checkpoint(self):
        return checkpointlib.current_checkpoint(self)

    def invalidate_stale_memory(self):
        invalidated = self.memory.invalidate_stale_file_summaries()
        self.session["memory"] = self.memory.to_dict()
        return invalidated

    def evaluate_resume_state(self):
        return checkpointlib.evaluate_resume_state(self)

    def render_checkpoint_text(self):
        return checkpointlib.render_checkpoint_text(self)

    @staticmethod
    def remember(bucket, item, limit):
        if not item:
            return
        if item in bucket:
            bucket.remove(item)
        bucket.append(item)
        del bucket[:-limit]

    def build_tools(self):
        return toolkit.build_tool_registry(self.tool_context())

    @staticmethod
    def _normalize_allowed_tools(allowed_tools):
        if allowed_tools is None:
            return None
        normalized = tuple(str(name).strip() for name in allowed_tools)
        if not normalized or any(not name for name in normalized):
            raise ValueError("allowed_tools must be a non-empty sequence of tool names")
        return normalized

    def _apply_tool_allowlist(self, tools):
        if self.allowed_tools is None:
            return tools
        legal_names = toolkit.legal_tool_names()
        unknown = [name for name in self.allowed_tools if name not in legal_names]
        if unknown:
            raise ValueError(f"unknown allowed tool: {', '.join(unknown)}")
        allowed = set(self.allowed_tools)
        return {
            name: tool
            for name, tool in tools.items()
            if name in allowed
        }

    def tool_signature(self):
        return tool_signature(self.tools)

    def build_prefix(self):
        return build_prompt_prefix(workspace=self.workspace, tools=self.tools)

    def _apply_prefix_state(self, prefix_state):
        self.prefix_state = prefix_state
        self.prefix = prefix_state.text

    def refresh_prefix(self, force=False):
        previous_hash = getattr(getattr(self, "prefix_state", None), "hash", None)
        previous_workspace_fingerprint = getattr(getattr(self, "prefix_state", None), "workspace_fingerprint", None)

        # 工作区事实相对稳定，所以这里按整体刷新；
        # 只有这些事实真的变化了，才重建完整 prefix。
        refreshed_workspace = WorkspaceContext.build(self.root, repo_root_override=self.workspace.repo_root)
        refreshed_workspace_fingerprint = refreshed_workspace.fingerprint()
        workspace_changed = force or refreshed_workspace_fingerprint != previous_workspace_fingerprint
        if workspace_changed:
            self.workspace = refreshed_workspace

        prefix_state = self.build_prefix() if workspace_changed or force or previous_hash is None else self.prefix_state
        prefix_changed = force or previous_hash != prefix_state.hash
        if prefix_changed:
            self._apply_prefix_state(prefix_state)

        self._last_prefix_refresh = {
            "workspace_changed": workspace_changed,
            "prefix_changed": prefix_changed,
        }
        return dict(self._last_prefix_refresh)

    def memory_text(self):
        return self.memory.render_memory_text()

    def projected_history(self):
        """Return the canonical history projection for prompt-time reads.

        During a run, event_log.jsonl is the source of truth. session["history"]
        remains as a compatibility/cache surface for older sessions and non-run
        calls, but prompt construction should consume this accessor.
        """
        state = self.current_task_state
        if state is not None:
            events = self.run_store.load_events(state.run_id)
            history = project_history(events)
            if history or events:
                return history
        return list(self.session.get("history", []))

    def history_source(self):
        state = self.current_task_state
        if state is None:
            return "session"
        events = self.run_store.load_events(state.run_id)
        if events:
            return "event_log"
        return "session"

    def history_text(self):
        history = self.projected_history()
        if not history:
            return "- empty"

        lines = []
        seen_reads = set()
        recent_start = max(0, len(history) - 6)
        for index, item in enumerate(history):
            recent = index >= recent_start
            if item["role"] == "tool" and item["name"] == "read_file" and not recent:
                path = str(item["args"].get("path", ""))
                if path in seen_reads:
                    continue
                seen_reads.add(path)

            if item["role"] == "tool":
                limit = 900 if recent else 180
                lines.append(f"[tool:{item['name']}] {json.dumps(item['args'], sort_keys=True)}")
                lines.append(clip(item["content"], limit))
            else:
                limit = 900 if recent else 220
                lines.append(f"[{item['role']}] {clip(item['content'], limit)}")

        return clip("\n".join(lines), MAX_HISTORY)

    def feature_enabled(self, name):
        return bool(self.feature_flags.get(str(name), False))

    def prompt(self, user_message):
        prompt, _ = self._build_prompt_and_metadata(user_message)
        return prompt

    def record(self, item):
        self.session["history"].append(item)
        self.session_path = self.session_store.save(self.session)
        self.record_event("history_recorded", {"source": "history", "history": dict(item)})

    def record_event(self, event, payload=None, task_state=None):
        state = task_state or self.current_task_state
        if state is None:
            return None
        payload = self.redact_artifact(payload or {})
        payload["event"] = event
        payload["created_at"] = now()
        return self.run_store.append_event(state, payload)

    @staticmethod
    def looks_sensitive_env_name(name):
        return securitylib.looks_sensitive_env_name(name)

    def is_secret_env_name(self, name):
        return securitylib.is_secret_env_name(name, secret_env_names=self.secret_env_names)

    def configured_secret_env_items(self):
        return securitylib.configured_secret_env_items(secret_env_names=self.secret_env_names)

    def detected_secret_env_items(self):
        return securitylib.detected_secret_env_items(secret_env_names=self.secret_env_names)

    def secret_env_summary(self):
        return securitylib.secret_env_summary(secret_env_names=self.secret_env_names)

    def detected_secret_env_summary(self):
        return securitylib.detected_secret_env_summary(secret_env_names=self.secret_env_names)

    def redact_text(self, text):
        return securitylib.redact_text(text, secret_env_names=self.secret_env_names)

    def redact_artifact(self, value, key=None):
        return securitylib.redact_artifact(value, key=key, secret_env_names=self.secret_env_names)

    def shell_env(self):
        return securitylib.shell_env(allowlist=self.shell_env_allowlist, root=self.root)

    def prompt_metadata(self, user_message, prompt):
        _, metadata = self._build_prompt_and_metadata(user_message)
        return metadata

    def _build_prompt_and_metadata(self, user_message):
        refresh = self.refresh_prefix()
        self.resume_state = self.evaluate_resume_state()
        prompt, metadata = self.context_manager.build(user_message)
        prompt, metadata = self._maybe_apply_adaptive_context_compression(user_message, prompt, metadata)
        # 这里把“这轮 prompt 是怎么拼出来的”连同缓存相关状态一起记下来，
        # 后面 trace/report 才能解释清楚：为什么这一轮 prefix 变了、缓存有没有命中。
        metadata.update(
            {
                "prefix_chars": len(self.prefix),
                "workspace_chars": len(self.workspace.text()),
                "memory_chars": len(self.memory_text()),
                "history_chars": len(self.history_text()),
                "request_chars": len(user_message),
                "tool_count": len(self.tools),
                "workspace_docs": len(self.workspace.project_docs),
                "recent_commits": len(self.workspace.recent_commits),
                "prefix_hash": self.prefix_state.hash,
                "prompt_cache_key": self.prefix_state.hash,
                "workspace_fingerprint": self.prefix_state.workspace_fingerprint,
                "tool_signature": self.prefix_state.tool_signature,
                "workspace_changed": refresh["workspace_changed"],
                "prefix_changed": refresh["prefix_changed"],
                "prompt_cache_supported": bool(getattr(self.model_client, "supports_prompt_cache", False)),
                "resume_status": self.resume_state.get("status", CHECKPOINT_NONE_STATUS),
                "stale_summary_invalidations": int(self.resume_state.get("stale_summary_invalidations", 0)),
                "stale_paths": list(self.resume_state.get("stale_paths", [])),
                "runtime_identity_mismatch_fields": list(self.resume_state.get("runtime_identity_mismatch_fields", [])),
            }
        )
        metadata.update(self.detected_secret_env_summary())
        return prompt, metadata


    def _context_compression_budget(self, metadata=None):
        if metadata:
            section_budgets = metadata.get("section_budgets") or {}
            budget = section_budgets.get("history")
            if budget:
                return max(120, int(int(budget) * 0.65))
        return max(120, int(int(getattr(self.context_manager, "section_budgets", {}).get("history", 2400)) * 0.65))

    def _context_usage_ratio(self, metadata):
        budget = int(metadata.get("prompt_budget_chars") or 0)
        if budget <= 0:
            return 0.0
        return float(metadata.get("prompt_chars", 0)) / float(budget)

    def _maybe_apply_adaptive_context_compression(self, user_message, prompt, metadata):
        scheduler = {
            "enabled": self.feature_enabled("adaptive_context_compression"),
            "async_threshold": 0.60,
            "sync_threshold": 0.80,
            "usage_ratio": round(self._context_usage_ratio(metadata), 4),
            "action": "none",
        }
        if not scheduler["enabled"]:
            metadata["context_compression_scheduler"] = scheduler
            return prompt, metadata

        ratio = self._context_usage_ratio(metadata)
        if ratio >= scheduler["sync_threshold"]:
            before_chars = len(prompt)
            state = self._run_context_compression(
                mode="sync",
                trigger_ratio=ratio,
                history_budget=self._context_compression_budget(metadata),
            )
            prompt, metadata = self.context_manager.build(user_message)
            after_ratio = self._context_usage_ratio(metadata)
            scheduler.update(
                {
                    "action": "sync_compressed",
                    "before_prompt_chars": before_chars,
                    "after_prompt_chars": len(prompt),
                    "after_usage_ratio": round(after_ratio, 4),
                    "summary_status": state.get("status", ""),
                    "summary_rendered_chars": int(state.get("rendered_chars", 0)),
                    "summary_backend": state.get("backend", "deterministic"),
                    "llm_escalation": False,
                }
            )
            if after_ratio >= scheduler["sync_threshold"] and self.feature_enabled("llm_context_compression"):
                llm_state = self._run_llm_context_compression(
                    mode="sync_llm",
                    trigger_ratio=after_ratio,
                    history_budget=self._context_compression_budget(metadata),
                )
                scheduler.update(
                    {
                        "llm_escalation": True,
                        "llm_escalation_trigger_ratio": round(after_ratio, 4),
                        "llm_summary_status": llm_state.get("status", ""),
                        "llm_summary_rendered_chars": int(llm_state.get("rendered_chars", 0)),
                        "llm_failure": llm_state.get("failure", ""),
                    }
                )
                if llm_state.get("status") == "ready":
                    prompt, metadata = self.context_manager.build(user_message)
                    llm_after_ratio = self._context_usage_ratio(metadata)
                    scheduler.update(
                        {
                            "action": "sync_compressed_llm",
                            "summary_status": llm_state.get("status", ""),
                            "summary_backend": llm_state.get("backend", "deepseek_llm"),
                            "after_llm_prompt_chars": len(prompt),
                            "after_llm_usage_ratio": round(llm_after_ratio, 4),
                            "llm_call_count": int((llm_state.get("details") or {}).get("llm_call_count", 0) or 0),
                            "llm_input_tokens": (llm_state.get("details") or {}).get("llm_input_tokens"),
                            "llm_output_tokens": (llm_state.get("details") or {}).get("llm_output_tokens"),
                        }
                    )
            metadata["context_compression_scheduler"] = scheduler
            return prompt, metadata

        if ratio >= scheduler["async_threshold"]:
            action = self._schedule_async_context_compression(
                trigger_ratio=ratio,
                history_budget=self._context_compression_budget(metadata),
            )
            scheduler["action"] = action
            metadata["context_compression_scheduler"] = scheduler
            return prompt, metadata

        metadata["context_compression_scheduler"] = scheduler
        return prompt, metadata

    def _history_digest(self, history):
        payload = json.dumps(history, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _deepseek_context_compression_client(self):
        if self.context_compression_model_client is not None:
            return self.context_compression_model_client
        load_project_env(self.root)
        api_key = provider_env("REPOPILOT_DEEPSEEK_API_KEY", ("DEEPSEEK_API_KEY",))
        if not api_key:
            raise RuntimeError("DeepSeek context compression requires REPOPILOT_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY")
        model = provider_env("REPOPILOT_DEEPSEEK_MODEL", ("DEEPSEEK_MODEL",), "deepseek-v4-pro")
        base_url = provider_env("REPOPILOT_DEEPSEEK_API_BASE", ("DEEPSEEK_API_BASE",), "https://api.deepseek.com/anthropic")
        self.context_compression_model_client = AnthropicCompatibleModelClient(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=0.0,
            timeout=60,
            thinking={"type": "disabled"},
        )
        return self.context_compression_model_client

    def _run_llm_context_compression(self, mode, trigger_ratio, history_budget=None, history_snapshot=None):
        history = list(history_snapshot if history_snapshot is not None else self.projected_history())
        budget = int(history_budget or self._context_compression_budget())
        started_at = now()
        try:
            compressed = render_llm_tool_round_compressed_history(
                history,
                budget=budget,
                model_client=self._deepseek_context_compression_client(),
                max_new_tokens=450,
                active_tool_rounds=2,
            )
            details = dict(compressed.details or {})
            if details.get("llm_fallback_used"):
                raise RuntimeError(details.get("llm_error") or "LLM compression fallback used")
            details["context_compression_backend"] = "deepseek_llm"
            state = {
                "version": 1,
                "status": "ready",
                "mode": str(mode),
                "backend": "deepseek_llm",
                "trigger_ratio": round(float(trigger_ratio), 4),
                "source_history_length": len(history),
                "source_history_digest": self._history_digest(history),
                "raw_chars": len(compressed.raw),
                "rendered_chars": len(compressed.rendered),
                "rendered": compressed.rendered,
                "details": details,
                "started_at": started_at,
                "updated_at": now(),
                "failure": "",
            }
        except Exception as exc:
            state = {
                "version": 1,
                "status": "failed",
                "mode": str(mode),
                "backend": "deepseek_llm",
                "trigger_ratio": round(float(trigger_ratio), 4),
                "source_history_length": len(history),
                "source_history_digest": self._history_digest(history),
                "raw_chars": 0,
                "rendered_chars": 0,
                "rendered": "",
                "details": {},
                "started_at": started_at,
                "updated_at": now(),
                "failure": self.redact_text(str(exc)),
            }
        if state["status"] == "ready":
            with self._context_compression_lock:
                self.session["context_compression"] = state
                self.session_path = self.session_store.save(self.session)
        self.record_event(
            "context_compression_completed" if state["status"] == "ready" else "context_compression_failed",
            {
                "source": "context_compression",
                "mode": state["mode"],
                "backend": state["backend"],
                "status": state["status"],
                "trigger_ratio": state["trigger_ratio"],
                "source_history_length": state["source_history_length"],
                "raw_chars": state["raw_chars"],
                "rendered_chars": state["rendered_chars"],
                "failure": state["failure"],
            },
        )
        return state

    def _run_context_compression(self, mode, trigger_ratio, history_budget=None, history_snapshot=None):
        history = list(history_snapshot if history_snapshot is not None else self.projected_history())
        budget = int(history_budget or self._context_compression_budget())
        started_at = now()
        try:
            compressed = render_tool_round_compressed_history(history, budget=budget)
            state = {
                "version": 1,
                "status": "ready",
                "mode": str(mode),
                "backend": "deterministic",
                "trigger_ratio": round(float(trigger_ratio), 4),
                "source_history_length": len(history),
                "source_history_digest": self._history_digest(history),
                "raw_chars": len(compressed.raw),
                "rendered_chars": len(compressed.rendered),
                "rendered": compressed.rendered,
                "details": {**dict(compressed.details or {}), "context_compression_backend": "deterministic"},
                "started_at": started_at,
                "updated_at": now(),
                "failure": "",
            }
        except Exception as exc:
            state = {
                "version": 1,
                "status": "failed",
                "mode": str(mode),
                "backend": "deterministic",
                "trigger_ratio": round(float(trigger_ratio), 4),
                "source_history_length": len(history),
                "source_history_digest": self._history_digest(history),
                "raw_chars": 0,
                "rendered_chars": 0,
                "rendered": "",
                "details": {},
                "started_at": started_at,
                "updated_at": now(),
                "failure": self.redact_text(str(exc)),
            }
        with self._context_compression_lock:
            self.session["context_compression"] = state
            self.session_path = self.session_store.save(self.session)
        self.record_event(
            "context_compression_completed" if state["status"] == "ready" else "context_compression_failed",
            {
                "source": "context_compression",
                "mode": state["mode"],
                "backend": state.get("backend", "deterministic"),
                "status": state["status"],
                "trigger_ratio": state["trigger_ratio"],
                "source_history_length": state["source_history_length"],
                "raw_chars": state["raw_chars"],
                "rendered_chars": state["rendered_chars"],
                "failure": state["failure"],
            },
        )
        return state

    def _schedule_async_context_compression(self, trigger_ratio, history_budget=None):
        with self._context_compression_lock:
            existing = self.session.get("context_compression", {})
            if existing.get("status") == "pending":
                return "async_pending"
            history_snapshot = list(self.projected_history())
            digest = self._history_digest(history_snapshot)
            if existing.get("status") == "ready" and existing.get("source_history_digest") == digest:
                return "async_summary_fresh"
            pending = {
                "version": 1,
                "status": "pending",
                "mode": "async",
                "backend": "deterministic",
                "trigger_ratio": round(float(trigger_ratio), 4),
                "source_history_length": len(history_snapshot),
                "source_history_digest": digest,
                "raw_chars": 0,
                "rendered_chars": 0,
                "rendered": "",
                "details": {},
                "started_at": now(),
                "updated_at": now(),
                "failure": "",
            }
            self.session["context_compression"] = pending
            self.session_path = self.session_store.save(self.session)
        self.record_event(
            "context_compression_scheduled",
            {
                "source": "context_compression",
                "mode": "async",
                "backend": "deterministic",
                "trigger_ratio": round(float(trigger_ratio), 4),
                "source_history_length": len(history_snapshot),
            },
        )
        thread = threading.Thread(
            target=self._run_context_compression,
            kwargs={
                "mode": "async",
                "trigger_ratio": trigger_ratio,
                "history_budget": history_budget,
                "history_snapshot": history_snapshot,
            },
            daemon=True,
        )
        self._context_compression_thread = thread
        thread.start()
        return "async_scheduled"

    def wait_for_context_compression(self, timeout=5.0):
        thread = self._context_compression_thread
        if thread is None:
            return dict(self.session.get("context_compression", {}))
        thread.join(timeout=float(timeout))
        return dict(self.session.get("context_compression", {}))

    def compressed_history_summary(self):
        state = self.session.get("context_compression", {})
        if not isinstance(state, dict) or state.get("status") != "ready":
            return {}
        source_length = int(state.get("source_history_length", 0) or 0)
        history = self.projected_history()
        if source_length <= 0 or source_length > len(history):
            return {}
        prefix = list(history)[:source_length]
        if state.get("source_history_digest") != self._history_digest(prefix):
            return {}
        return dict(state)

    def emit_trace(self, task_state, event, payload=None):
        payload = self.redact_artifact(payload or {})
        payload["event"] = event
        payload["created_at"] = now()
        # trace 是运行中的逐事件时间线，适合回答“这一轮 agent 到底做了什么”。
        self.run_store.append_event(task_state, {**payload, "source": "trace"})
        self.run_store.append_trace(task_state, payload)
        return payload

    def capture_workspace_snapshot(self):
        snapshot = {}
        for path in self.root.rglob("*"):
            try:
                relative_parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            if any(part in IGNORED_PATH_NAMES for part in relative_parts):
                continue
            if not path.is_file():
                continue
            try:
                snapshot[path.relative_to(self.root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                continue
        return snapshot

    @staticmethod
    def diff_workspace_snapshots(before, after):
        changed_paths = []
        summaries = []
        all_paths = sorted(set(before) | set(after))
        for path in all_paths:
            if before.get(path) == after.get(path):
                continue
            changed_paths.append(path)
            if path not in before:
                summaries.append(f"created:{path}")
            elif path not in after:
                summaries.append(f"deleted:{path}")
            else:
                summaries.append(f"modified:{path}")
        return changed_paths, summaries

    def create_checkpoint(self, task_state, user_message, trigger):
        return checkpointlib.create_checkpoint(self, task_state, user_message, trigger)

    def infer_next_step(self, task_state):
        return checkpointlib.infer_next_step(task_state)

    def update_memory_after_tool(self, name, args, result):
        """把少量高价值工具结果沉淀到 working memory。

        为什么存在：
        并不是每个工具结果都值得长期带进下一轮 prompt。完整结果已经进了
        `history`，这里只挑少量“下一轮大概率还会用到”的事实做提纯，
        例如最近读写过哪些文件、某个文件读出来的短摘要。

        输入 / 输出：
        - 输入：工具名 `name`、参数 `args`、执行结果 `result`
        - 输出：无显式返回值，副作用是更新 `self.memory`

        在 agent 链路里的位置：
        它发生在 `run_tool()` 真正执行完工具之后、下一轮 prompt 组装之前。
        也就是说：工具结果先进入完整历史，再由这个函数择优沉淀成轻量记忆。
        """
        if not self.feature_enabled("memory"):
            return
        path = args.get("path")
        if not path:
            return

        canonical_path = self.memory.canonical_path(path)
        changed = False
        # 不是所有工具结果都进入工作记忆。
        # 读文件会生成摘要；写文件/patch 会让旧摘要失效，因为它们可能过期了。
        if name in {"read_file", "write_file", "patch_file"}:
            self.memory.remember_file(canonical_path)
            changed = True
        if name == "read_file":
            summary = memorylib.summarize_read_result(result)
            self.memory.set_file_summary(canonical_path, summary)
            self.memory.append_note(summary, tags=(canonical_path,), source=canonical_path)
            changed = True
        elif name in {"write_file", "patch_file"}:
            self.memory.invalidate_file_summary(canonical_path)
            changed = True
        if changed:
            self.session["memory"] = self.memory.to_dict()
            self.record_event(
                "memory_updated",
                {
                    "source": "memory",
                    "tool_name": name,
                    "path": canonical_path,
                    "memory_files": list(self.session["memory"].get("files", [])),
                },
            )

    def note_tool(self, name, args, result):
        self.update_memory_after_tool(name, args, result)

    def record_process_note_for_tool(self, name, metadata):
        status = str(metadata.get("tool_status", "")).strip()
        if status not in {"partial_success", "error", "rejected"}:
            return
        affected_paths = [str(path).strip() for path in metadata.get("affected_paths", []) if str(path).strip()]
        path_text = ", ".join(affected_paths) or "workspace"
        if status == "partial_success":
            text = f"{name} partial_success on {path_text}; inspect diff before retry"
        elif status == "error":
            text = f"{name} error on {path_text}; check the failure before retry"
        else:
            text = f"{name} rejected; choose a different action before retry"
        tags = ["process", status, *affected_paths]
        self.memory.append_note(text, tags=tuple(tags), source=name, kind="process")
        self.session["memory"] = self.memory.to_dict()

    def promote_memory_candidates(self, task_state=None):
        if not self.feature_enabled("memory") or not self.feature_enabled("memory_candidate_promotion"):
            self.last_memory_candidates = []
            self.last_memory_promotion_decisions = []
            self.last_memory_promotion_metrics = memory_promotion_metrics([], [])
            return dict(self.last_memory_promotion_metrics)
        state = task_state or self.current_task_state
        if state is None:
            return dict(self.last_memory_promotion_metrics)

        events = self.run_store.load_events(state.run_id)
        candidates = generate_memory_candidates(events)
        policy = MemoryPromotionPolicy()
        decisions = []
        for candidate in candidates:
            self.record_event(
                "memory_candidate_created",
                {"source": "memory", "candidate": candidate.to_dict()},
                task_state=state,
            )
            decision = policy.evaluate(candidate, self.memory, events=events)
            decisions.append(decision)
            payload = {
                "source": "memory",
                "decision": decision.to_dict(),
                "durable_topic": candidate.durable_topic,
            }
            if decision.promote:
                promoted, superseded = self.memory.promote_durable([(candidate.durable_topic, candidate.text)])
                self.session["memory"] = self.memory.to_dict()
                payload["promoted"] = promoted
                payload["superseded"] = superseded
                self.record_event("memory_promoted", payload, task_state=state)
            elif decision.reject:
                self.record_event("memory_rejected", payload, task_state=state)
            else:
                self.record_event("memory_pending_confirmation", payload, task_state=state)

        self.last_memory_candidates = [candidate.to_dict() for candidate in candidates]
        self.last_memory_promotion_decisions = [decision.to_dict() for decision in decisions]
        self.last_memory_promotion_metrics = memory_promotion_metrics(candidates, decisions)
        self.session_path = self.session_store.save(self.session)
        return dict(self.last_memory_promotion_metrics)

    def ask(self, user_message):
        from .agent_loop import AgentLoop

        return AgentLoop(self).run(user_message)

    def inspect(self, paths=None, max_files=20, max_steps=3):
        from .inspection import run_inspection

        return run_inspection(self, paths=paths, max_files=max_files, max_steps=max_steps)

    def execute_tool(self, name, args):
        result = self.tool_executor.execute(name, args)
        self._last_tool_result_metadata = dict(result.metadata)
        return result

    def run_tool(self, name, args):
        """执行一次工具调用，并在执行前后套上完整护栏。

        为什么存在：
        在 agent 系统里，真正危险的不是“模型会不会想调用工具”，而是
        “平台有没有在执行前把边界守住”。这个函数就是工具层的总闸口：
        所有工具调用都必须先经过它，不能让模型直接碰到底层函数。

        输入 / 输出：
        - 输入：工具名 `name`，参数字典 `args`
        - 输出：字符串结果。无论是成功结果还是错误信息，都会统一返回文本，
          这样模型下一轮都能继续消费这份反馈。

        在 agent 链路里的位置：
        它位于 `ask()` 的“模型决定要调用工具”之后，是控制循环里真正把模型
        意图落到外部世界的一步。因此这里串起了几乎所有安全与可控设计：
        工具是否存在、参数是否合法、是否重复、是否需要审批、执行结果是否裁剪、
        是否需要回写记忆。
        """
        return self.execute_tool(name, args).content

    def repeated_tool_call(self, name, args):
        # agent 很常见的一种坏循环，是在没有新信息的情况下反复发起同一调用。
        # 这里提前挡掉最简单的这种循环。
        tool_events = [item for item in self.projected_history() if item["role"] == "tool"]
        if len(tool_events) < 2:
            return False
        recent = tool_events[-2:]
        return all(item["name"] == name and item["args"] == args for item in recent)

    @staticmethod
    def new_task_id():
        return "task_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    @staticmethod
    def new_run_id():
        return "run_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

    def build_report(self, task_state):
        # report 是一次运行的最终摘要；
        # 和 trace 的区别在于，trace 关注过程，report 关注结果与关键指标。
        events = self.run_store.load_events(task_state.run_id)
        task_snapshot = task_state.to_dict()
        return {
            "run_id": task_state.run_id,
            "task_id": task_state.task_id,
            "status": task_state.status,
            "stop_reason": task_state.stop_reason,
            "final_answer": task_state.final_answer,
            "tool_steps": task_state.tool_steps,
            "attempts": task_state.attempts,
            "checkpoint_id": task_state.checkpoint_id,
            "resume_status": task_state.resume_status,
            "task_state": task_snapshot,
            "coverage_manifest": build_coverage_manifest(events, task_snapshot),
            "prompt_metadata": self.last_prompt_metadata,
            "memory_candidates": list(self.last_memory_candidates),
            "memory_promotion_decisions": list(self.last_memory_promotion_decisions),
            "memory_promotion_metrics": dict(self.last_memory_promotion_metrics),
            "redacted_env": self.detected_secret_env_summary(),
            "event_log_metrics": event_log_metrics(events),
            "projected_history": project_history(events),
            "history_source": "event_log",
        }

    def tool_example(self, name):
        return toolkit.tool_example(name)

    def validate_tool(self, name, args):
        """把通用工具校验和 runtime 级额外约束串起来。"""
        toolkit.validate_tool(self.tool_context(), name, args)

    def tool_context(self):
        return ToolContext(
            root=self.root,
            path_resolver=self.path,
            shell_env_provider=self.shell_env,
            depth=self.depth,
            max_depth=self.max_depth,
            spawn_delegate=self.spawn_delegate,
        )

    def spawn_delegate(self, args):
        task = str(args.get("task", "")).strip()
        child = RepoPilot(
            model_client=self.model_client,
            workspace=self.workspace,
            session_store=self.session_store,
            run_store=self.run_store,
            approval_policy="never",
            max_steps=int(args.get("max_steps", 3)),
            max_new_tokens=self.max_new_tokens,
            depth=self.depth + 1,
            max_depth=self.max_depth,
            read_only=True,
            secret_env_names=self.secret_env_names,
            shell_env_allowlist=self.shell_env_allowlist,
        )
        # 委派的目标是“调查”，不是“放权执行”。
        # 子 agent 以只读方式运行、步数更少，最后只把结论文本返回给父 agent。
        child.session["memory"]["task"] = task
        child.session["memory"]["notes"] = [clip(self.history_text(), 300)]
        return "delegate_result:\n" + child.ask(task)

    def tool_list_files(self, args):
        return toolkit.tool_list_files(self.tool_context(), args)

    def tool_read_file(self, args):
        return toolkit.tool_read_file(self.tool_context(), args)

    def tool_search(self, args):
        return toolkit.tool_search(self.tool_context(), args)

    def tool_run_shell(self, args):
        return toolkit.normalize_tool_output(toolkit.tool_run_shell(self.tool_context(), args)).content

    def tool_write_file(self, args):
        return toolkit.tool_write_file(self.tool_context(), args)

    def tool_patch_file(self, args):
        return toolkit.tool_patch_file(self.tool_context(), args)

    def tool_delegate(self, args):
        return toolkit.tool_delegate(self.tool_context(), args)

    def approve(self, name, args):
        if self.read_only:
            return False
        if self.approval_policy == "auto":
            return True
        if self.approval_policy == "never":
            return False
        try:
            answer = input(f"approve {name} {json.dumps(args, ensure_ascii=True)}? [y/N] ")
        except EOFError:
            return False
        return answer.strip().lower() in {"y", "yes"}

    @staticmethod
    def parse(raw):
        """把模型原始输出解析成 runtime 可执行的动作或最终答案。

        为什么存在：
        模型输出首先是自然语言文本，而 runtime 需要的是结构化决策：
        “这是工具调用”还是“这是最终答案”。如果没有这层解析，后面的工具校验、
        审批和执行链路就没法可靠工作。

        输入 / 输出：
        - 输入：模型返回的原始文本 `raw`
        - 输出：`(kind, payload)`，其中 `kind` 可能是 `tool`、`final`、`retry`

        在 agent 链路里的位置：
        它位于 `model_client.complete()` 之后、`run_tool()` 之前，是模型输出
        进入平台控制流的第一道结构化关口。
        """
        raw = str(raw)
        # 这里支持两种工具格式：
        # 1. <tool>...</tool> 里包 JSON，适合简短调用
        # 2. XML 风格属性/子标签，适合写文件这类多行内容
        if "<tool>" in raw and ("<final>" not in raw or raw.find("<tool>") < raw.find("<final>")):
            body = RepoPilot.extract(raw, "tool")
            try:
                payload = json.loads(body)
            except Exception:
                return "retry", RepoPilot.retry_notice("model returned malformed tool JSON")
            if not isinstance(payload, dict):
                return "retry", RepoPilot.retry_notice("tool payload must be a JSON object")
            if not str(payload.get("name", "")).strip():
                return "retry", RepoPilot.retry_notice("tool payload is missing a tool name")
            args = payload.get("args", {})
            if args is None:
                payload["args"] = {}
            elif not isinstance(args, dict):
                return "retry", RepoPilot.retry_notice()
            return "tool", payload
        if "<tool" in raw and ("<final>" not in raw or raw.find("<tool") < raw.find("<final>")):
            payload = RepoPilot.parse_xml_tool(raw)
            if payload is not None:
                return "tool", payload
            return "retry", RepoPilot.retry_notice()
        if "<final>" in raw:
            final = RepoPilot.extract(raw, "final").strip()
            if final:
                return "final", final
            return "retry", RepoPilot.retry_notice("model returned an empty <final> answer")
        raw = raw.strip()
        if raw:
            return "final", raw
        return "retry", RepoPilot.retry_notice("model returned an empty response")

    @staticmethod
    def retry_notice(problem=None):
        prefix = "Runtime notice"
        if problem:
            prefix += f": {problem}"
        else:
            prefix += ": model returned malformed tool output"
        return (
            f"{prefix}. Reply with a valid <tool> call or a non-empty <final> answer. "
            'For multi-line files, prefer <tool name="write_file" path="file.py"><content>...</content></tool>.'
        )

    @staticmethod
    def parse_xml_tool(raw):
        match = re.search(r"<tool(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", raw, re.S)
        if not match:
            return None
        attrs = RepoPilot.parse_attrs(match.group("attrs"))
        name = str(attrs.pop("name", "")).strip()
        if not name:
            return None

        body = match.group("body")
        args = dict(attrs)
        for key in ("content", "old_text", "new_text", "command", "task", "pattern", "path"):
            if f"<{key}>" in body:
                args[key] = RepoPilot.extract_raw(body, key)

        body_text = body.strip("\n")
        if name == "write_file" and "content" not in args and body_text:
            args["content"] = body_text
        if name == "delegate" and "task" not in args and body_text:
            args["task"] = body_text.strip()
        return {"name": name, "args": args}

    @staticmethod
    def parse_attrs(text):
        attrs = {}
        for match in re.finditer(r"""([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", text):
            attrs[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
        return attrs

    @staticmethod
    def extract(text, tag):
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = text.find(start_tag)
        if start == -1:
            return text
        start += len(start_tag)
        end = text.find(end_tag, start)
        if end == -1:
            return text[start:].strip()
        return text[start:end].strip()

    @staticmethod
    def extract_raw(text, tag):
        start_tag = f"<{tag}>"
        end_tag = f"</{tag}>"
        start = text.find(start_tag)
        if start == -1:
            return text
        start += len(start_tag)
        end = text.find(end_tag, start)
        if end == -1:
            return text[start:]
        return text[start:end]

    def reset(self):
        self.session["history"] = []
        self.session["memory"].clear()
        self.session["memory"].update(memorylib.default_memory_state())
        self.memory = memorylib.LayeredMemory(self.session["memory"], workspace_root=self.root)
        self.session_store.save(self.session)

    def path(self, raw_path):
        path = Path(raw_path)
        path = path if path.is_absolute() else self.root / path
        resolved = path.resolve()
        # 所有文件类工具都被锚定在 workspace root 之下。
        # 这样既能防住 "../" 逃逸，也能防住符号链接解析后跳出仓库。
        if os.path.commonpath([str(self.root), str(resolved)]) != str(self.root):
            raise ValueError(f"path escapes workspace: {raw_path}")
        return resolved



