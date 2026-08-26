"""Memory candidate generation and SAVE-based durable promotion."""

from dataclasses import asdict, dataclass, field
import re
from typing import Iterable

from .workspace import clip, now

SENSITIVE_TEXT_PATTERN = re.compile(r"(?i)(\b(api[_ -]?key|token|secret|password)\b|sk-[A-Za-z0-9_-]{6,})")
TRANSIENT_TEXT_PATTERN = re.compile(
    r"(?i)(\bnext step\b|\bcurrent goal\b|\bcurrent blocker\b|\bjust failed\b|\bfailed this turn\b|"
    r"\bthis task\b|\bcalled\s+\d+\s+times\b|\bstdout\b|\bstderr\b|\btraceback\b|\bexit_code\b|"
    r"下一步|当前目标|当前卡点|刚刚失败|本轮|这次任务|调用了?\d+次)"
)
ACTIONABLE_TEXT_PATTERN = re.compile(
    r"(?i)(\balways\b|\bnever\b|\bprefer\b|\buse\b|\buses\b|\bshould\b|\bmust\b|"
    r"\bpytest\b|\bpnpm\b|\bnpm\b|\bci\b|\bworkflow\b|\btool protocol\b|"
    r"以后|总是|不要|优先|使用|采用|约定|偏好|测试|工具协议|依赖|工作流)"
)
STABLE_TEXT_PATTERN = re.compile(
    r"(?i)(\bproject\b|\brepository\b|\brepo\b|\bconvention\b|\bdecision\b|\bdependency\b|"
    r"\bpreference\b|\buses\b|\bpytest\b|\bpackage.json\b|\bpyproject.toml\b|"
    r"项目|仓库|约定|决策|依赖|偏好|长期|稳定|以后|总是)"
)
USER_PREFERENCE_PATTERN = re.compile(r"(?i)(\balways\b|\bnever\b|\bprefer\b|以后|以后都|总是|不要|别|用中文|中文解释)")

USER_PREFERENCE_SPLIT_PATTERN = re.compile(r"(?:\r?\n|;+)")

KIND_TO_TOPIC = {
    "project_convention": "project-conventions",
    "decision": "key-decisions",
    "dependency_fact": "dependency-facts",
    "user_preference": "user-preferences",
}


@dataclass(frozen=True)
class MemoryCandidate:
    text: str
    kind: str
    scope: str = "project"
    source: str = "event_log"
    evidence_event_ids: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 1.0
    created_at: str = ""

    def __post_init__(self):
        object.__setattr__(self, "text", clip(str(self.text).strip(), 500))
        object.__setattr__(self, "kind", str(self.kind).strip() or "project_convention")
        object.__setattr__(self, "scope", str(self.scope).strip() or "project")
        object.__setattr__(self, "source", str(self.source).strip() or "event_log")
        object.__setattr__(self, "evidence_event_ids", tuple(str(item).strip() for item in self.evidence_event_ids if str(item).strip()))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))
        object.__setattr__(self, "created_at", str(self.created_at).strip() or now())

    def to_dict(self):
        payload = asdict(self)
        payload["evidence_event_ids"] = list(self.evidence_event_ids)
        return payload

    @property
    def durable_topic(self):
        return KIND_TO_TOPIC.get(self.kind, "project-conventions")


@dataclass(frozen=True)
class PromotionDecision:
    action: str
    reason: str
    score: int
    save: dict
    candidate: MemoryCandidate
    duplicate_of: str = ""
    conflict_with: str = ""

    @property
    def promote(self):
        return self.action == "promote"

    @property
    def reject(self):
        return self.action == "reject"

    @property
    def pending_confirmation(self):
        return self.action == "pending_confirmation"

    def to_dict(self):
        return {
            "action": self.action,
            "reason": self.reason,
            "score": self.score,
            "save": dict(self.save),
            "candidate": self.candidate.to_dict(),
            "duplicate_of": self.duplicate_of,
            "conflict_with": self.conflict_with,
        }


def event_evidence_id(index):
    return f"event:{int(index)}"


def _event_index_from_id(value):
    match = re.match(r"^event:(\d+)$", str(value or ""))
    if not match:
        return None
    return int(match.group(1))


def _normalize_text(text):
    return " ".join(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", str(text).lower()))


def _existing_memory_texts(memory):
    texts = []
    state = memory.to_dict() if hasattr(memory, "to_dict") else {}
    for note in state.get("episodic_notes", []):
        if isinstance(note, dict) and note.get("kind") == "durable":
            texts.append(str(note.get("text", "")))
    store = getattr(memory, "durable_store", None)
    if store is not None:
        for topic in store.topic_slugs():
            for note in store.load_topic_notes(topic):
                texts.append(str(note.get("text", "")))
    return [text for text in texts if text.strip()]


def _subject_key(text):
    lowered = _normalize_text(text)
    patterns = (
        r"^(.+?) should (?:not )?.+$",
        r"^(.+?) must (?:not )?.+$",
        r"^(project|repo|repository) uses? (.+)$",
        r"^(.+?) uses? .+$",
        r"^(.+?) is .+$",
        r"^(.+?)不应.+$",
        r"^(.+?)不要.+$",
        r"^(.+?)应该.+$",
        r"^(.+?)使用.+$",
        r"^(.+?)是.+$",
    )
    for pattern in patterns:
        match = re.match(pattern, lowered)
        if match:
            return match.group(1).strip() or match.group(2).strip()
    return " ".join(lowered.split()[:5])


def _find_duplicate(candidate_text, existing_texts):
    normalized = _normalize_text(candidate_text)
    for existing in existing_texts:
        if _normalize_text(existing) == normalized:
            return existing
    return ""


def _find_conflict(candidate_text, existing_texts):
    text = str(candidate_text).lower()
    subject = _subject_key(candidate_text)
    candidate_positive = bool(re.search(r"(?i)\b(always|use|uses|should|must)\b|使用|应该|总是", text))
    candidate_negative = bool(re.search(r"(?i)\b(never|do not|don't|avoid|should not|must not|not use)\b|不要|禁止|避免", text))
    if not subject or not (candidate_positive or candidate_negative):
        return ""
    for existing in existing_texts:
        existing_text = existing.lower()
        if _subject_key(existing) != subject:
            continue
        existing_positive = bool(re.search(r"(?i)\b(always|use|uses|should|must)\b|使用|应该|总是", existing_text))
        existing_negative = bool(re.search(r"(?i)\b(never|do not|don't|avoid|should not|must not|not use)\b|不要|禁止|避免", existing_text))
        if (candidate_positive and existing_negative) or (candidate_negative and existing_positive):
            return existing
    return ""


def _user_preference_fragments(content):
    fragments = USER_PREFERENCE_SPLIT_PATTERN.split(str(content or ""))
    for fragment in fragments:
        text = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", fragment).strip()
        if text and USER_PREFERENCE_PATTERN.search(text):
            yield clip(text, 220)


class MemoryPromotionPolicy:
    def __init__(self, threshold=4):
        self.threshold = int(threshold)

    def evaluate(self, candidate, memory, events=None):
        events = list(events or [])
        text = candidate.text.strip()
        evidence_indexes = [_event_index_from_id(item) for item in candidate.evidence_event_ids]
        evidence_verified = bool(evidence_indexes) and all(index is not None and 0 <= index < len(events) for index in evidence_indexes)
        save = {
            "stable": bool(STABLE_TEXT_PATTERN.search(text)) and not bool(TRANSIENT_TEXT_PATTERN.search(text)),
            "actionable": bool(ACTIONABLE_TEXT_PATTERN.search(text)),
            "verifiable": evidence_verified,
            "economical": 0 < len(text) <= 220,
        }
        score = sum(1 for value in save.values() if value)

        if not text:
            return PromotionDecision("reject", "empty", score, save, candidate)
        if SENSITIVE_TEXT_PATTERN.search(text):
            return PromotionDecision("reject", "sensitive", score, save, candidate)
        if TRANSIENT_TEXT_PATTERN.search(text):
            return PromotionDecision("reject", "transient", score, save, candidate)
        if not save["economical"]:
            return PromotionDecision("reject", "too_long", score, save, candidate)

        existing_texts = _existing_memory_texts(memory)
        duplicate = _find_duplicate(text, existing_texts)
        if duplicate:
            return PromotionDecision("reject", "duplicate", score, save, candidate, duplicate_of=duplicate)
        conflict = _find_conflict(text, existing_texts)
        if conflict:
            return PromotionDecision("pending_confirmation", "conflict", score, save, candidate, conflict_with=conflict)
        if not save["verifiable"]:
            return PromotionDecision("pending_confirmation", "missing_evidence", score, save, candidate)
        if score >= self.threshold:
            return PromotionDecision("promote", "save_passed", score, save, candidate)
        return PromotionDecision("pending_confirmation", "save_score_below_threshold", score, save, candidate)


def generate_memory_candidates(events):
    candidates = []
    seen = set()

    def add(text, kind, scope, source, event_index, confidence=1.0):
        normalized = _normalize_text(text)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        candidates.append(
            MemoryCandidate(
                text=text,
                kind=kind,
                scope=scope,
                source=source,
                evidence_event_ids=(event_evidence_id(event_index),),
                confidence=confidence,
            )
        )

    for index, event in enumerate(events):
        if event.get("source") == "history":
            item = event.get("history") if isinstance(event.get("history"), dict) else {}
            if item.get("role") == "user":
                content = str(item.get("content", "")).strip()
                for fragment in _user_preference_fragments(content):
                    add(fragment, "user_preference", "user", "user_message", index, confidence=0.9)
            continue

        if event.get("source") != "trace" or event.get("event") != "tool_executed":
            continue
        name = event.get("name")
        args = event.get("args") if isinstance(event.get("args"), dict) else {}
        result = str(event.get("result", ""))
        if name == "read_file":
            path = str(args.get("path", "")).replace("\\", "/")
            lowered_path = path.lower()
            lowered_result = result.lower()
            if lowered_path.endswith("pyproject.toml") and "pytest" in lowered_result:
                add("Project uses pytest configuration from pyproject.toml.", "dependency_fact", "project", path, index)
            elif lowered_path.endswith("pytest.ini"):
                add("Project uses pytest.ini for pytest configuration.", "dependency_fact", "project", path, index)
            elif lowered_path.endswith("package.json") and '"test"' in lowered_result:
                add("Project package.json defines a test script.", "dependency_fact", "project", path, index)
            elif ".github/workflows/" in lowered_path or lowered_path.startswith(".github/workflows/"):
                add(f"Project has a CI workflow at {path}.", "project_convention", "project", path, index)
        elif name == "run_shell":
            command = str(args.get("command", ""))
            if "pytest" in command.lower() and int(event.get("exit_code", 0) or 0) == 0:
                add("Project verification can run with pytest.", "dependency_fact", "project", "run_shell", index, confidence=0.85)
    return candidates


def memory_promotion_metrics(candidates, decisions):
    decisions = list(decisions)
    candidates = list(candidates)
    promoted = [item for item in decisions if item.promote]
    rejected = [item for item in decisions if item.reject]
    pending = [item for item in decisions if item.pending_confirmation]
    evidence_bound = [item for item in decisions if item.save.get("verifiable")]
    return {
        "candidate_count": len(candidates),
        "promoted_count": len(promoted),
        "rejected_count": len(rejected),
        "pending_count": len(pending),
        "rejected_sensitive_candidate_count": sum(1 for item in rejected if item.reason == "sensitive"),
        "duplicate_candidate_suppression_count": sum(1 for item in rejected if item.reason == "duplicate"),
        "conflict_detection_count": sum(1 for item in pending if item.reason == "conflict"),
        "evidence_coverage": (len(evidence_bound) / len(decisions)) if decisions else 0.0,
        "promotion_precision_proxy": (sum(1 for item in promoted if item.score >= 4) / len(promoted)) if promoted else 0.0,
        "stale_memory_invalidation_rate": 0.0,
        "memory_usefulness_rate": (len(promoted) / len(candidates)) if candidates else 0.0,
    }
