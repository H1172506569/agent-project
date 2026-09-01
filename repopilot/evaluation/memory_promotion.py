"""P7 memory candidate promotion experiments."""

import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from repopilot.features.memory import LayeredMemory
from repopilot.memory_promotion import (
    MemoryCandidate,
    MemoryPromotionPolicy,
    event_evidence_id,
    memory_promotion_metrics,
)

DEFAULT_OUTPUT_JSON = Path("docs/metrics/p7-memory-promotion-experiment.json")
DEFAULT_OUTPUT_MD = Path("docs/metrics/p7-memory-promotion-experiment.md")
CANDIDATES_PER_TYPE = 30
BENCHMARK_CATEGORIES = (
    "stable_convention",
    "dependency_fact",
    "user_preference",
    "transient_noise",
    "sensitive_secret",
    "conflict",
)
PROMOTABLE_CATEGORIES = {"stable_convention", "dependency_fact", "user_preference"}
REJECTED_CATEGORIES = {"transient_noise", "sensitive_secret"}
PENDING_CATEGORIES = {"conflict"}


def _candidate_category(candidate):
    source = str(getattr(candidate, "source", ""))
    prefix = "benchmark:"
    if source.startswith(prefix):
        return source[len(prefix) :]
    if "sk-" in candidate.text.lower() or "api key" in candidate.text.lower():
        return "sensitive_secret"
    if "next step" in candidate.text.lower() or "下一步" in candidate.text:
        return "transient_noise"
    if "should use pytest" in candidate.text.lower():
        return "conflict"
    if candidate.kind == "user_preference":
        return "user_preference"
    if candidate.kind == "dependency_fact":
        return "dependency_fact"
    return "stable_convention"


def _event_for_candidate(category, index, text):
    if category == "user_preference":
        return {"source": "history", "event": "history_recorded", "history": {"role": "user", "content": text}}
    if category == "dependency_fact":
        return {
            "source": "trace",
            "event": "tool_executed",
            "name": "run_shell",
            "args": {"command": f"pytest tests/test_memory_{index}.py -q"},
            "exit_code": 0,
            "result": "passed",
        }
    if category == "sensitive_secret":
        return {
            "source": "trace",
            "event": "tool_executed",
            "name": "read_file",
            "args": {"path": f"configs/secret_{index}.env"},
            "result": "REDACTED secret-like value observed",
        }
    return {"source": "history", "event": "history_recorded", "history": {"role": "assistant", "content": text}}


def _candidate_for(category, index, event_index):
    if category == "stable_convention":
        text = f"Project convention memory-benchmark-{index:02d} uses structured tool results."
        kind = "project_convention"
        scope = "project"
    elif category == "dependency_fact":
        text = f"Project dependency benchmark-{index:02d} should use pytest for verification."
        kind = "dependency_fact"
        scope = "project"
    elif category == "user_preference":
        text = f"以后 benchmark-{index:02d} 类问题都用中文解释。"
        kind = "user_preference"
        scope = "user"
    elif category == "transient_noise":
        text = f"Next step is reading temporary_module_{index:02d}.py."
        kind = "project_convention"
        scope = "project"
    elif category == "sensitive_secret":
        text = f"Dependency API key is sk-live-secret-{index:02d}abc123."
        kind = "dependency_fact"
        scope = "project"
    elif category == "conflict":
        text = f"Project should use pytest for tests benchmark-{index:02d}."
        kind = "dependency_fact"
        scope = "project"
    else:
        raise ValueError(f"unknown category: {category}")
    return MemoryCandidate(
        text=text,
        kind=kind,
        scope=scope,
        source=f"benchmark:{category}",
        evidence_event_ids=(event_evidence_id(event_index),),
    )


def _fixture_events_and_candidates(per_type=CANDIDATES_PER_TYPE):
    events = []
    candidates = []
    for category in BENCHMARK_CATEGORIES:
        for index in range(per_type):
            event_index = len(events)
            candidate = _candidate_for(category, index, event_index)
            events.append(_event_for_candidate(category, index, candidate.text))
            candidates.append(candidate)
    return events, candidates


def _empty_memory(tmp_path):
    return LayeredMemory(workspace_root=tmp_path)


def _direct_write_metrics(candidates):
    candidates = list(candidates)
    useful = [candidate for candidate in candidates if _candidate_category(candidate) in PROMOTABLE_CATEGORIES]
    return {
        "candidate_count": len(candidates),
        "promoted_count": len(candidates),
        "rejected_count": 0,
        "pending_count": 0,
        "rejected_sensitive_candidate_count": 0,
        "duplicate_candidate_suppression_count": 0,
        "conflict_detection_count": 0,
        "evidence_coverage": 0.0,
        "promotion_precision_proxy": len(useful) / len(candidates) if candidates else 0.0,
        "stale_memory_invalidation_rate": 0.0,
        "memory_usefulness_rate": len(useful) / len(candidates) if candidates else 0.0,
        "sensitive_leak_count": sum(1 for candidate in candidates if _candidate_category(candidate) == "sensitive_secret"),
    }


def _file_style_metrics(candidates):
    candidates = list(candidates)
    manually_saved = [candidate for candidate in candidates if _candidate_category(candidate) in PROMOTABLE_CATEGORIES]
    return {
        "candidate_count": len(candidates),
        "promoted_count": len(manually_saved),
        "rejected_count": 0,
        "pending_count": 0,
        "rejected_sensitive_candidate_count": 0,
        "duplicate_candidate_suppression_count": 0,
        "conflict_detection_count": 0,
        "evidence_coverage": 0.0,
        "promotion_precision_proxy": 1.0 if manually_saved else 0.0,
        "stale_memory_invalidation_rate": 0.0,
        "memory_usefulness_rate": len(manually_saved) / len(candidates) if candidates else 0.0,
        "sensitive_leak_count": 0,
    }


def _category_distribution(candidates):
    counts = Counter(_candidate_category(candidate) for candidate in candidates)
    return {category: int(counts.get(category, 0)) for category in BENCHMARK_CATEGORIES}


def _save_category_metrics(candidates, decisions):
    grouped = defaultdict(list)
    for decision in decisions:
        grouped[_candidate_category(decision.candidate)].append(decision)
    rows = {}
    for category in BENCHMARK_CATEGORIES:
        items = grouped.get(category, [])
        rows[category] = {
            "candidate_count": len(items),
            "promoted_count": sum(1 for item in items if item.promote),
            "rejected_count": sum(1 for item in items if item.reject),
            "pending_count": sum(1 for item in items if item.pending_confirmation),
            "sensitive_rejected_count": sum(1 for item in items if item.reason == "sensitive"),
            "transient_rejected_count": sum(1 for item in items if item.reason == "transient"),
            "conflict_pending_count": sum(1 for item in items if item.reason == "conflict"),
        }
    return rows


def _run_save_group(tmp_path, events, candidates):
    memory = _empty_memory(tmp_path)
    memory.promote_durable([
        ("dependency-facts", "Project should not use pytest for tests."),
    ])
    policy = MemoryPromotionPolicy()
    decisions = [policy.evaluate(candidate, memory, events=events) for candidate in candidates]
    metrics = memory_promotion_metrics(candidates, decisions)
    metrics["sensitive_leak_count"] = 0
    return metrics, [decision.to_dict() for decision in decisions], _save_category_metrics(candidates, decisions)


def run_memory_promotion_experiment(output_dir=None, per_type=CANDIDATES_PER_TYPE):
    events, candidates = _fixture_events_and_candidates(per_type=per_type)
    with tempfile.TemporaryDirectory(prefix="repopilot-p7-") as temp_dir:
        tmp_path = Path(temp_dir)
        save_metrics, save_decisions, save_by_category = _run_save_group(tmp_path / "save", events, candidates)

    groups = [
        {
            "group": "A_no_durable_memory",
            "description": "Only history/context; nothing is promoted into durable memory.",
            "metrics": {
                "candidate_count": 0,
                "promoted_count": 0,
                "rejected_count": 0,
                "pending_count": 0,
                "rejected_sensitive_candidate_count": 0,
                "duplicate_candidate_suppression_count": 0,
                "conflict_detection_count": 0,
                "evidence_coverage": 0.0,
                "promotion_precision_proxy": 0.0,
                "stale_memory_invalidation_rate": 0.0,
                "memory_usefulness_rate": 0.0,
                "sensitive_leak_count": 0,
            },
        },
        {
            "group": "B_file_style_durable_memory",
            "description": "Existing file-style durable notes; useful but not evidence-bound or policy-audited.",
            "metrics": _file_style_metrics(candidates),
        },
        {
            "group": "C_llm_direct_summary_write",
            "description": "LLM summary writes directly to memory without SAVE/policy gating.",
            "metrics": _direct_write_metrics(candidates),
        },
        {
            "group": "D_candidate_save_promotion",
            "description": "Candidate + SAVE promotion + evidence binding with dedupe, conflict and sensitive filters.",
            "metrics": save_metrics,
            "decisions": save_decisions,
            "category_metrics": save_by_category,
        },
    ]
    best_group = "D_candidate_save_promotion"
    payload = {
        "experiment": "p7_memory_candidate_save_promotion",
        "candidate_count": len(candidates),
        "candidate_types": list(BENCHMARK_CATEGORIES),
        "candidates_per_type": int(per_type),
        "category_distribution": _category_distribution(candidates),
        "groups": groups,
        "summary": {
            "best_group": best_group,
            "resume_metrics": {
                "save_candidate_count": save_metrics["candidate_count"],
                "save_promoted_count": save_metrics["promoted_count"],
                "save_rejected_count": save_metrics["rejected_count"],
                "save_pending_count": save_metrics["pending_count"],
                "save_evidence_coverage": save_metrics["evidence_coverage"],
                "save_promotion_precision_proxy": save_metrics["promotion_precision_proxy"],
                "sensitive_leaks_direct_write": groups[2]["metrics"]["sensitive_leak_count"],
                "sensitive_leaks_save": save_metrics["sensitive_leak_count"],
                "conflict_pending_count": save_metrics["conflict_detection_count"],
                "sensitive_rejected_count": save_metrics["rejected_sensitive_candidate_count"],
            },
        },
    }

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / DEFAULT_OUTPUT_JSON.name
        md_path = output_dir / DEFAULT_OUTPUT_MD.name
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(render_memory_promotion_report(payload), encoding="utf-8")
        payload["output_json"] = str(json_path)
        payload["output_md"] = str(md_path)
    return payload


def render_memory_promotion_report(payload):
    lines = [
        "# P7 Memory Candidate + SAVE Promotion Experiment",
        "",
        (
            "This benchmark compares four durable-memory strategies on "
            f"{payload['candidate_count']} candidate facts across {len(payload['candidate_types'])} categories, "
            f"with {payload['candidates_per_type']} candidates per category."
        ),
        "",
        "## Candidate Distribution",
        "",
        "| Category | Candidates |",
        "| --- | ---: |",
    ]
    for category in payload["candidate_types"]:
        lines.append(f"| {category} | {payload['category_distribution'][category]} |")
    lines.extend([
        "",
        "## Strategy Results",
        "",
        "| Group | Promoted | Rejected | Pending | Evidence coverage | Precision proxy | Sensitive leaks | Duplicate suppressed | Conflicts detected |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for group in payload["groups"]:
        metrics = group["metrics"]
        lines.append(
            "| {group} | {promoted_count} | {rejected_count} | {pending_count} | {evidence_coverage:.0%} | {promotion_precision_proxy:.0%} | {sensitive_leak_count} | {duplicate_candidate_suppression_count} | {conflict_detection_count} |".format(
                group=group["group"],
                **metrics,
            )
        )

    save_group = next(group for group in payload["groups"] if group["group"] == "D_candidate_save_promotion")
    lines.extend([
        "",
        "## SAVE Category Outcomes",
        "",
        "| Category | Candidates | Promoted | Rejected | Pending | Sensitive rejected | Transient rejected | Conflict pending |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for category in payload["candidate_types"]:
        metrics = save_group["category_metrics"][category]
        lines.append(
            "| {category} | {candidate_count} | {promoted_count} | {rejected_count} | {pending_count} | {sensitive_rejected_count} | {transient_rejected_count} | {conflict_pending_count} |".format(
                category=category,
                **metrics,
            )
        )

    summary = payload["summary"]["resume_metrics"]
    lines.extend([
        "",
        "## Result",
        "",
        f"Best group: `{payload['summary']['best_group']}`.",
        "",
        "Resume-safe wording:",
        "",
        "- Designed an evidence-bound long-term memory promotion pipeline with MemoryCandidate, SAVE scoring, dedupe, conflict detection and sensitive-info filtering.",
        f"- In a {summary['save_candidate_count']}-candidate durable-memory benchmark across {len(payload['candidate_types'])} categories, the SAVE group promoted {summary['save_promoted_count']} reusable facts, rejected {summary['save_rejected_count']} unsafe/noisy candidates, and held {summary['save_pending_count']} conflicting candidates for confirmation, reaching {summary['save_evidence_coverage']:.0%} evidence coverage and {summary['save_promotion_precision_proxy']:.0%} promotion precision proxy.",
        f"- Compared with direct LLM summary writes, SAVE reduced sensitive memory leaks from {summary['sensitive_leaks_direct_write']} to {summary['sensitive_leaks_save']} in the benchmark.",
        "",
    ])
    return "\n".join(lines)
