"""Memory candidate generation and SAVE-based durable promotion."""

from dataclasses import asdict, dataclass, field
import re
from typing import Iterable

from .features.memory import RESIDENT_TIER, RETRIEVAL_TIER, durable_topic_tier
from .workspace import clip, now

SENSITIVE_TEXT_PATTERN = re.compile(r"(?i)(\b(api[_ -]?key|token|secret|password)\b|sk-[A-Za-z0-9_-]{6,})")
TRANSIENT_TEXT_PATTERN = re.compile(
    r"(?i)(\bnext step\b|\bcurrent goal\b|\bcurrent blocker\b|\bjust failed\b|\bfailed this turn\b|"
    r"\bthis task\b|\bcalled\s+\d+\s+times\b|\bstdout\b|\bstderr\b|\btraceback\b|\bexit_code\b|"
    r"下一步|当前目标|当前卡点|刚刚失败|本轮|这次任务|调用了?\d+次)"
)
# 只留情态词：actionable 问的是“这条记忆会不会改变未来某次运行的行为”，
# 那是情态问题。原先的词表里混着 pytest / pnpm / ci / workflow 这类技术名词，
# 等于把“可执行”偷换成“提到了 pytest”——换个构建工具就判不出来了。
ACTIONABLE_TEXT_PATTERN = re.compile(
    r"(?i)(\balways\b|\bnever\b|\bprefer\b|\bshould\b|\bmust\b|"
    r"\bavoid\b|\brequired\b|\bdo not\b|\bdon't\b|"
    r"以后|总是|必须|不要|不应|优先|应当|应该)"
)
# stable 不再看措辞，改看证据来自哪里。文本词表判 stable 有三个毛病：
# 依赖措辞（换个构建工具就漏判）、中英文词表重合导致双阈值在中文下退化成
# 单阈值、以及可以被模型自评操纵。证据来源是客观的，三个毛病一次解决。
STABLE_EVIDENCE_PATH_PATTERN = re.compile(
    r"(?i)(pyproject\.toml|setup\.cfg|setup\.py|requirements[^/]*\.txt|"
    r"package\.json|pnpm-workspace\.yaml|tsconfig\.json|"
    r"pytest\.ini|tox\.ini|makefile|justfile|dockerfile|"
    r"cargo\.toml|go\.mod|\.github/workflows/)"
)
# 只收“跨会话”标记，不收 must / should 这类祈使词：
# “you should fix this bug” 是本次任务的指令，不是长期约定。判据是**作用范围**，
# 不是语气强度——分不清这两者，就会把一次性指令当成永久记忆。
USER_PREFERENCE_PATTERN = re.compile(
    r"(?i)(\balways\b|\bnever\b|\bprefer\b|\bby default\b|"
    r"\bfrom now on\b|\bgoing forward\b|\bwhenever\b|\bevery time\b|"
    r"\beach time\b|\bas a rule\b|"
    r"以后|今后|往后|总是|始终|一律|统一|默认|每次|每当|凡是|记住|不要|别|用中文|中文解释)"
)

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
    # 模型给出的主语。`_subject_key()` 只认少数几种句式（X should/uses/is ...），
    # 自由表述会大面积绕过它，导致同义重复堆积、冲突检测失效。让模型直接给主语，
    # 是采用 LLM 提议之后最要紧的一件事。留空则退回从文本里猜。
    subject: str = ""
    # 模型只能主张 `actionable`，不能主张 `stable`——stable 由证据来源客观判定。
    # 需要这条主张是因为情态词表在自然语言上仍有漏判：
    # “Project verification runs through the Makefile check target.” 显然会改变
    # 未来运行的行为，却一个情态词都不命中。而它碰不到任何一道硬门。
    claimed_actionable: bool = False

    def __post_init__(self):
        object.__setattr__(self, "text", clip(str(self.text).strip(), 500))
        object.__setattr__(self, "kind", str(self.kind).strip() or "project_convention")
        object.__setattr__(self, "scope", str(self.scope).strip() or "project")
        object.__setattr__(self, "source", str(self.source).strip() or "event_log")
        object.__setattr__(self, "evidence_event_ids", tuple(str(item).strip() for item in self.evidence_event_ids if str(item).strip()))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))
        object.__setattr__(self, "created_at", str(self.created_at).strip() or now())
        object.__setattr__(self, "subject", _normalize_text(self.subject))

    def to_dict(self):
        payload = asdict(self)
        payload["evidence_event_ids"] = list(self.evidence_event_ids)
        return payload

    @property
    def conflict_subject(self):
        """冲突检测用的主语：模型给了就用模型的，否则从文本里猜。"""
        return self.subject or _subject_key(self.text)

    @property
    def durable_topic(self):
        return KIND_TO_TOPIC.get(self.kind, "project-conventions")

    @property
    def durable_tier(self):
        """这条候选该进常驻层还是检索层。

        判据不是重要性，而是可召回性：kind 已经隐含了「这条记忆有没有能出现在
        用户 query 里的锚点」——偏好和全局约定没有锚点，检索对它们结构性失效，
        只能常驻；依赖事实和决策锚在路径/模块上，交给检索。
        """
        return durable_topic_tier(self.durable_topic)


@dataclass(frozen=True)
class PromotionDecision:
    action: str
    reason: str
    score: int
    save: dict
    candidate: MemoryCandidate
    duplicate_of: str = ""
    conflict_with: str = ""
    tier: str = RETRIEVAL_TIER

    @property
    def promote(self):
        return self.action == "promote"

    @property
    def reject(self):
        return self.action == "reject"

    @property
    def pending_confirmation(self):
        return self.action == "pending_confirmation"

    @property
    def requires_confirmation(self):
        """常驻记忆的冲突必须走强确认，而不是静默挂起。

        一条错误的检索记忆只在被召回时有害；一条错误的常驻记忆会污染之后的
        每一轮，所以它的撤销要由用户显式拍板（见 `RepoPilot.confirm_memory_conflict`）。
        """
        return self.pending_confirmation and self.reason == "resident_conflict"

    def to_dict(self):
        return {
            "action": self.action,
            "reason": self.reason,
            "score": self.score,
            "save": dict(self.save),
            "candidate": self.candidate.to_dict(),
            "duplicate_of": self.duplicate_of,
            "conflict_with": self.conflict_with,
            "tier": self.tier,
            "requires_confirmation": self.requires_confirmation,
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
    store = getattr(memory, "durable_store", None)
    if store is not None:
        for topic in store.topic_slugs():
            for note in store.load_topic_notes(topic):
                texts.append(str(note.get("text", "")))
    return [text for text in texts if text.strip()]


class ExistingMemoryTexts:
    """批量晋升时共享的“现有长期记忆文本”快照。

    为什么存在：
    去重和冲突检测都要拿 candidate 和已有的长期记忆比对，而这份列表要把每个
    durable topic 的 markdown 从磁盘读回来。按 candidate 逐个重读，N 个候选就是
    N 次全量磁盘读取，而这期间记忆只在晋升成功时才会变化。这里读一次，然后由
    调用方在每次晋升后显式同步，把 O(N) 次磁盘读降成 1 次。

    同步必须显式做：晋升成功后调用 `record_promotion()`，它复刻
    `DurableMemoryStore.promote()` 的行为——按 subject 覆盖同主语的旧笔记，
    否则同一批里语义重复的候选会漏掉去重。
    """

    def __init__(self, memory):
        self._texts = _existing_memory_texts(memory)
        store = getattr(memory, "durable_store", None)
        self._subject_key = getattr(store, "subject_key", None)

    def texts(self):
        return self._texts

    def record_promotion(self, note_text):
        note_text = str(note_text).strip()
        if not note_text:
            return
        subject = self._subject_key(note_text) if self._subject_key is not None else None
        if subject:
            self._texts = [
                text for text in self._texts if self._subject_key(text) != subject
            ]
        elif note_text in self._texts:
            return
        self._texts.append(note_text)


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


def _find_conflict(candidate_text, existing_texts, subject=None):
    text = str(candidate_text).lower()
    # 模型给了主语就用它；否则退回从句式里猜。
    subject = subject or _subject_key(candidate_text)
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
    """SAVE 裁决，按目标层用不同门槛。

    双阈值的理由是误报代价不对称：一条错误的检索记忆只在被召回时有害，
    一条错误的常驻记忆会污染之后的每一轮。

    两层共享同一组硬门，**证据校验也在其中**——`verifiable` 对常驻层和检索层
    一视同仁，没有任何一层可以跳过它，也没有“用户直接说出就免检”的后门。
    用户消息本身就是一个 event，从用户消息抽出的候选，它的
    `evidence_event_ids` 指向的就是那条 event，所以它是正常通过校验的，
    不是被豁免的。

    分数只在所有硬门都通过之后才起作用，**检索层同样有分数门槛，不是过硬门即可**。
    而走到打分那一步时，`economical`（第 4 步）和 `verifiable`（第 7 步）
    已经被硬门保证为 True，所以恒有 `score = 2 + stable + actionable`。
    两个阈值因此等价于：

    - 检索层（>= 3）：`stable` 和 `actionable` 至少命中一个
    - 常驻层（>= 4）：`stable` 和 `actionable` 都要命中
    """

    def __init__(self, require_both_for_resident=True):
        self.require_both_for_resident = bool(require_both_for_resident)

    def _meets_tier_requirement(self, tier, save):
        """候选够不够格进它所属的那一层。

        注意这里判的是**准入门槛**，不是选层：层在候选出生时就由 kind 定死了，
        `stable` / `actionable` 不参与选层。没过常驻层门槛的候选也不会被降级到
        检索层，而是进 pending——一条没有锚点的用户偏好降到检索层等于永远召不
        回来，降级就是静默作废。
        """
        if tier == RESIDENT_TIER and self.require_both_for_resident:
            return bool(save["stable"]) and bool(save["actionable"])
        return bool(save["stable"]) or bool(save["actionable"])

    def evaluate(self, candidate, memory, events=None, existing_texts=None):
        """对单个 candidate 做 SAVE 裁决。

        `existing_texts` 是去重/冲突检测要比对的现有长期记忆文本。批量评估
        同一批 candidate 时，调用方应当只读一次（见 `ExistingMemoryTexts`），
        否则每个 candidate 都会把 durable topic 的 markdown 重新读一遍磁盘。
        不传则退回到按需读取，保持单次调用的行为不变。
        """
        events = list(events or [])
        tier = candidate.durable_tier
        text = candidate.text.strip()
        evidence_indexes = [_event_index_from_id(item) for item in candidate.evidence_event_ids]
        evidence_verified = bool(evidence_indexes) and all(index is not None and 0 <= index < len(events) for index in evidence_indexes)
        transient = bool(TRANSIENT_TEXT_PATTERN.search(text))
        # stable 由证据来源客观判定，模型碰不到；actionable 可以由模型主张，
        # 但主张只影响这一项，绕不过任何一道硬门。
        # 抽取器的候选是从事件里长出来的，用户消息天然支撑它；模型提议的候选只是
        # 引用了一条消息，不能靠它换稳定性。
        trust_user_statement = candidate.source != "model_proposal"
        stable_evidence = evidence_verified and all(
            evidence_is_stable(events[_event_index_from_id(item)], trust_user_statement=trust_user_statement)
            for item in candidate.evidence_event_ids
        )
        save = {
            "stable": stable_evidence and not transient,
            "actionable": bool(ACTIONABLE_TEXT_PATTERN.search(text)) or bool(candidate.claimed_actionable),
            "verifiable": evidence_verified,
            "economical": 0 < len(text) <= 220,
        }
        # score 仅作报告用，真正的准入判据是下面的 `_meets_tier_requirement()`。
        # 走到判定那一步时 economical 和 verifiable 已被硬门保证为真，把它们算进
        # 分数只会让门槛看起来像“四项全过”，实际是“两项恒真 + 两项在判”。
        score = sum(1 for value in save.values() if value)

        if not text:
            return PromotionDecision("reject", "empty", score, save, candidate, tier=tier)
        if SENSITIVE_TEXT_PATTERN.search(text):
            return PromotionDecision("reject", "sensitive", score, save, candidate, tier=tier)
        if TRANSIENT_TEXT_PATTERN.search(text):
            return PromotionDecision("reject", "transient", score, save, candidate, tier=tier)
        if not save["economical"]:
            return PromotionDecision("reject", "too_long", score, save, candidate, tier=tier)

        if existing_texts is None:
            existing_texts = _existing_memory_texts(memory)
        else:
            existing_texts = list(existing_texts)
        duplicate = _find_duplicate(text, existing_texts)
        if duplicate:
            return PromotionDecision(
                "reject", "duplicate", score, save, candidate, duplicate_of=duplicate, tier=tier
            )
        conflict = _find_conflict(text, existing_texts, subject=candidate.conflict_subject)
        if conflict:
            # 常驻层的冲突要走强确认：撤销一条每轮都在生效的约定，得由用户拍板。
            reason = "resident_conflict" if tier == RESIDENT_TIER else "conflict"
            return PromotionDecision(
                "pending_confirmation", reason, score, save, candidate, conflict_with=conflict, tier=tier
            )
        if not save["verifiable"]:
            return PromotionDecision("pending_confirmation", "missing_evidence", score, save, candidate, tier=tier)
        if self._meets_tier_requirement(tier, save):
            return PromotionDecision("promote", "save_passed", score, save, candidate, tier=tier)
        return PromotionDecision(
            "pending_confirmation", "save_score_below_threshold", score, save, candidate, tier=tier
        )


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


MODEL_CANDIDATE_LIMIT = 8


def _event_facets(event):
    """把 event 归一成 `(role, tool_name, args, text)`。

    同一次工具调用会以两种形态出现在事件流里：trace 的 `tool_executed`，和
    history 里的一条 tool 记录。不归一的话，证据解析命中哪一种，稳定性判定就
    会给出不同答案——这正是一个候选被判 stable 与否取决于运气的来源。
    """
    if not isinstance(event, dict):
        return "", "", {}, ""
    history = event.get("history")
    if isinstance(history, dict):
        args = history.get("args") if isinstance(history.get("args"), dict) else {}
        return (
            str(history.get("role", "")),
            str(history.get("name", "")),
            args,
            str(history.get("content", "")),
        )
    args = event.get("args") if isinstance(event.get("args"), dict) else {}
    return "", str(event.get("name", "")), args, str(event.get("result", ""))


def resolve_evidence_seq(seq, events):
    """把模型引用的事件编号解析成 run event 列表里的下标，解析不了就返回 None。

    模型引用的是事件写入时固定的 `seq`（history 渲染成 `[e6]` 给它看），不是
    列表位置——位置会随过滤条件和新增事件类型整体错位。

    只接受 `source=history` 的事件：内部 trace（run_started / prompt_built / …）
    模型根本看不到，也不该被引用。可见集合 == 可引用集合，这条不用额外维护。
    """
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        return None
    for index, event in enumerate(events):
        if event.get("source") != "history":
            continue
        if event.get("seq") is not None and int(event["seq"]) == seq:
            return index
    return None


def evidence_is_stable(event, trust_user_statement=True):
    """这条证据支撑的是不是一个跨会话仍然成立的事实。

    判据是证据的来源，不是候选的措辞：
    - 读配置文件（依赖/构建/CI 声明）：配置本身就是长期契约 -> 稳定
    - 用户陈述跨会话偏好：用户说的“以后”就是跨会话 -> 稳定
    - run_shell 的一次输出：这次通过不代表长期成立 -> 不稳定
    - 读普通源码文件：随代码改动，够不上长期事实 -> 不稳定

    `trust_user_statement=False` 用于模型提议的候选，此时用户消息不再赋予稳定性。
    区别在于**候选和消息的关系**：抽取器的偏好候选**就是从那条消息里切出来的片段**，
    消息当然支撑它；而模型引用一条用户消息，只是断言“这条消息说了 X”——一句
    “Always run the linter first. Also check pyproject.” 会让任何蹭上它的结论
    都拿到 stable，包括“发布前必须跳过测试”这种凭空捏造的约定。
    """
    role, name, args, text = _event_facets(event)
    if role == "user":
        if not trust_user_statement:
            return False
        # 用户“说过话”不等于“陈述了一条长期偏好”：一句“看一下 pyproject.toml，
        # 把测试跑通”是本次任务的指令，不是跨会话约定。
        return bool(USER_PREFERENCE_PATTERN.search(text))
    if name != "read_file":
        return False
    path = str(args.get("path", "")).replace(chr(92), "/")
    return bool(STABLE_EVIDENCE_PATH_PATTERN.search(path))


def model_memory_candidates(payloads, events, limit=MODEL_CANDIDATE_LIMIT):
    """把模型提出的候选转成 `MemoryCandidate`，并在 runtime 侧核实证据。

    为什么需要这条通路：
    `generate_memory_candidates()` 是硬编码 extractor，只认 pytest / CI 那几种
    路径模式，任何叫别的名字的约定（Makefile、tox.ini、“改 schema 前先跑迁移检查”）
    召回率都是 0。瓶颈在 recall，而规则的价值在 precision 和 safety。所以让模型
    负责提出，规则负责否决——模型提出的候选走的是和 extractor 完全相同的
    SAVE 硬门与双阈值，不因为“是模型说的”而放宽任何一档。
    """
    candidates = []
    events = list(events or [])
    for payload in list(payloads or [])[:limit]:
        if not isinstance(payload, dict):
            continue
        text = clip(str(payload.get("text", "")).strip(), 500)
        kind = str(payload.get("kind", "")).strip()
        if not text or kind not in KIND_TO_TOPIC:
            continue
        # 模型引用的是它在 history 里看到的事件编号，运行时按 seq 精确查找。
        # 引用不到（编号不存在、指向内部 trace、或压根没给）就没有证据，
        # `verifiable` 判 False，最多停在 pending。
        evidence_index = resolve_evidence_seq(payload.get("evidence"), events)
        evidence_ids = () if evidence_index is None else (event_evidence_id(evidence_index),)
        candidates.append(
            MemoryCandidate(
                text=text,
                kind=kind,
                scope="user" if kind == "user_preference" else "project",
                source="model_proposal",
                evidence_event_ids=evidence_ids,
                subject=str(payload.get("subject", "")),
                # 默认 False：不主张即不加分。默认 True 的话，模型只要省掉这个
                # 字段就自动加分，等于给常驻层开一条不用说理由的直通车。
                claimed_actionable=bool(payload.get("actionable", False)),
            )
        )
    return candidates


def merge_memory_candidates(*groups):
    """合并多路候选，按归一化文本去重；先到的优先。"""
    merged = []
    seen = set()
    for group in groups:
        for candidate in group or []:
            key = _normalize_text(candidate.text)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
    return merged


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
        "conflict_detection_count": sum(
            1 for item in pending if item.reason in {"conflict", "resident_conflict"}
        ),
        "resident_promoted_count": sum(1 for item in promoted if item.tier == RESIDENT_TIER),
        "retrieval_promoted_count": sum(1 for item in promoted if item.tier == RETRIEVAL_TIER),
        "resident_confirmation_required_count": sum(1 for item in pending if item.requires_confirmation),
        # 存进长期记忆的条目里，有多少条的 stable 是由证据来源客观判定的。
        # 这一项是可以为 0 的：它衡量的是“我们存下来的东西有多少是有客观依据的”，
        # 不是构造上恒真的自证指标。
        "objective_stable_promoted_count": sum(1 for item in promoted if item.save.get("stable")),
        "model_proposed_candidate_count": sum(1 for item in candidates if item.source == "model_proposal"),
        "model_proposed_promoted_count": sum(
            1 for item in promoted if item.candidate.source == "model_proposal"
        ),
        "evidence_coverage": (len(evidence_bound) / len(decisions)) if decisions else 0.0,
        # 存进去的条目里，有多少条的“长期性”是有客观依据的（stable 来自证据来源）。
        # 旧定义是 `score >= 4`，而 score 里有两项恒真，等于在数一个构造上必然成立
        # 的东西；换成这个之后它衡量的是真实的东西，也因此可以不等于 1。
        "promotion_precision_proxy": (
            sum(1 for item in promoted if item.save.get("stable")) / len(promoted)
        ) if promoted else 0.0,
        "stale_memory_invalidation_rate": 0.0,
        "memory_usefulness_rate": (len(promoted) / len(candidates)) if candidates else 0.0,
    }
