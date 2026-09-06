"""多步 agent 运行时使用的轻量工作记忆。

session history 负责保存完整事件流；这个模块只保存更小的一层工作集：
当前任务摘要、最近接触的文件、文件短摘要，以及少量跨轮笔记。
这样下一轮 prompt 还能接上上一轮，但不会被整段历史塞满。
"""

import hashlib
from datetime import datetime
import re
from pathlib import Path

from ..workspace import clip, now

WORKING_FILE_LIMIT = 8
FILE_SUMMARY_LIMIT = 6

# 长期记忆分两层，判据是「这条记忆有没有能出现在用户 query 里的锚点」：
# - resident：没有锚点。用户说“帮我改下这个函数”时，query 里没有任何 token 能
#   召回“以后都用中文解释”，检索对这类记忆是结构性失效的，所以必须每轮常驻。
# - retrieval：有锚点（路径 / 模块 / 包名 / 命令）。它们随仓库规模增长，
#   全带会挤掉 history，交给检索按需召回。
RESIDENT_TIER = "resident"
RETRIEVAL_TIER = "retrieval"

# 只由这些词组成的“主语”不足以判定两条笔记讲的是同一件事——
# 见 `DurableMemoryStore._subject_key()`。
GENERIC_SUBJECT_TOKENS = frozenset(
    {"project", "repo", "repository", "codebase", "code", "it", "this", "that", "the", "we", "our",
     "项目", "仓库", "代码", "团队", "我们"}
)

# 常驻层每轮都进 prompt，所以必须有天花板，否则跑几个月后会把 history 的预算吃光。
# 上限按 topic 算，而不是按整层算：整层上限会让某一个 topic（比如用户偏好）
# 把另一个饿死，而且写入端和读取端很难对「谁更旧」达成一致——topic 文件里没有
# 逐条时间戳，只有各自的追加顺序。按 topic 算则两端完全一致：写入时淘汰谁，
# 读取时就一定看不到谁。整层上界 = 每 topic 上限 × 常驻 topic 数。
# 两个上限先到先算；淘汰结果会回报给调用方记录 trace，而不是静默丢弃。
RESIDENT_TOPIC_NOTE_LIMIT = 8
RESIDENT_TOPIC_CHAR_LIMIT = 750

DURABLE_TOPIC_DEFAULTS = {
    "project-conventions": {
        "title": "Project Conventions",
        "summary": "Stable repository conventions.",
        "tags": ["convention"],
        "tier": RESIDENT_TIER,
    },
    "key-decisions": {
        "title": "Key Decisions",
        "summary": "Long-lived decisions and rationale anchors.",
        "tags": ["decision"],
        "tier": RETRIEVAL_TIER,
    },
    "dependency-facts": {
        "title": "Dependency Facts",
        "summary": "Stable dependency and environment facts.",
        "tags": ["dependency"],
        "tier": RETRIEVAL_TIER,
    },
    "user-preferences": {
        "title": "User Preferences",
        "summary": "Stable user preferences.",
        "tags": ["preference"],
        "tier": RESIDENT_TIER,
    },
}


def durable_topic_tier(topic):
    """返回某个 durable topic 属于哪一层。

    未知 topic 一律按 retrieval 处理：常驻层是每轮都要付费的位置，
    默认值应当是保守的那一边。
    """
    meta = DURABLE_TOPIC_DEFAULTS.get(str(topic).strip(), {})
    return meta.get("tier", RETRIEVAL_TIER)


def resident_topic_slugs():
    return [slug for slug in DURABLE_TOPIC_DEFAULTS if durable_topic_tier(slug) == RESIDENT_TIER]


NOTE_SUBJECT_PATTERN = re.compile(r"\s*<!--\s*subject:\s*(?P<subject>.*?)\s*-->\s*$")


def _split_note_subject(line):
    """把笔记行拆成 `(正文, 主语)`。

    主语必须跟着笔记一起落盘，否则它只在单次写入调用内有效——下次再写时，
    旧笔记的主语只能从正文里重新猜，显式给的主语就丢了，覆盖判定跟着失效。
    用 HTML 注释承载，是因为它在 markdown 里不可见，人读文件时不受干扰。
    """
    match = NOTE_SUBJECT_PATTERN.search(line)
    if not match:
        return line.strip(), ""
    return line[: match.start()].strip(), match.group("subject").strip()


def _format_note_line(note):
    if isinstance(note, dict):
        text, subject = str(note.get("text", "")).strip(), str(note.get("subject", "")).strip()
    else:
        text, subject = str(note).strip(), ""
    return f"{text} <!-- subject: {subject} -->" if subject else text


def _resident_note_text(note):
    return str(note.get("text", "")) if isinstance(note, dict) else str(note)


def _apply_resident_cap(notes, text_of=_resident_note_text):
    """按 cap 截断单个常驻 topic 的笔记，返回 `(kept, evicted)`。

    笔记在 topic 文件里是按晋升顺序追加的，所以最旧的在前面。超出上限时从
    前面淘汰，保留最新的。两个上限（条数、字符数）先到先算；至少保留一条，
    避免单条超长笔记把整层清空。
    """
    keep_count = 0
    used_chars = 0
    for note in reversed(notes):
        if keep_count >= RESIDENT_TOPIC_NOTE_LIMIT:
            break
        text_length = len(text_of(note))
        if keep_count and used_chars + text_length > RESIDENT_TOPIC_CHAR_LIMIT:
            break
        used_chars += text_length
        keep_count += 1
    split = len(notes) - keep_count
    return notes[split:], notes[:split]


def default_memory_state():
    # 用一个小而结构化的状态，而不是一大段自由文本摘要。
    return {
        "working": {
            "task_summary": "",
            "recent_files": [],
        },
        "file_summaries": {},
        "task": "",
        "files": [],
    }


class DurableMemoryStore:
    def __init__(self, root):
        self.root = Path(root)
        self.index_path = self.root / "MEMORY.md"
        self.topics_dir = self.root / "topics"

    def topic_slugs(self):
        return [topic["topic"] for topic in self.load_index()]

    def load_index(self):
        if not self.index_path.exists():
            return []
        lines = self.index_path.read_text(encoding="utf-8").splitlines()
        topics = []
        current = None
        for raw in lines:
            line = raw.strip()
            match = re.match(r"- \[([^\]]+)\]\([^)]+\):\s*(.+)", line)
            if match:
                current = {
                    "topic": match.group(1).strip(),
                    "title": match.group(2).strip(),
                    "summary": "",
                    "tags": [],
                }
                topics.append(current)
                continue
            if current is None:
                continue
            summary_match = re.match(r"- summary:\s*(.+)", line)
            if summary_match:
                current["summary"] = summary_match.group(1).strip()
                continue
            tags_match = re.match(r"- tags:\s*(.+)", line)
            if tags_match:
                current["tags"] = [tag.strip() for tag in tags_match.group(1).split(",") if tag.strip()]
        return topics

    def load_topic_notes(self, topic):
        path = self.topics_dir / f"{topic}.md"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        notes = []
        capture = False
        updated_at = ""
        tags = []
        for raw in lines:
            line = raw.strip()
            if line.startswith("- tags:"):
                tags = [tag.strip() for tag in line.split(":", 1)[1].split(",") if tag.strip()]
            elif line.startswith("- updated_at:"):
                updated_at = line.split(":", 1)[1].strip()
            elif line == "## Notes":
                capture = True
            elif capture and line.startswith("- "):
                text, subject = _split_note_subject(line[2:].strip())
                notes.append(
                    {
                        "text": text,
                        "subject": subject,
                        "tags": tags,
                        "source": topic,
                        "created_at": updated_at or now(),
                        "kind": "durable",
                    }
                )
        return notes

    @classmethod
    def subject_key(cls, text):
        """公开的主语抽取入口，供晋升流水线复用同一套覆盖判定。"""
        return cls._subject_key(text)

    @staticmethod
    def _normalized_subject(subject):
        """归一化显式给出的主语；只有通用词组成时同样判为不可用。"""
        tokens = _tokenize(subject)
        if not tokens - GENERIC_SUBJECT_TOKENS:
            return None
        return " ".join(sorted(tokens))

    @staticmethod
    def _subject_key(text):
        """抽出用于“同一件事更新了”判定的主语；抽不出可靠主语时返回 None。

        两个坑都在这个函数里踩过：

        1. **不能拼 set**。`_tokenize()` 返回的是集合，`" ".join(集合)` 的顺序由
           字符串哈希决定，而 Python 默认开哈希随机化——同一条笔记在不同进程里会
           得到不同的主语，覆盖行为因此跨进程不可复现。必须排序。

        2. **光秃秃的通用词不能当主语**。模式是非贪婪的，`Project uses X` 抽出来
           永远是 `project`，于是 "Project uses pytest" / "Project uses pnpm" /
           "Project uses ruff" 三条互不相关的事实主语全相同，后写的会把前面的静默
           覆盖掉。主语必须至少带一个有区分度的词，否则宁可不覆盖——重复条目还能靠
           cap 和冲突检测收拾，被删掉的事实是找不回来的。
        """
        text = str(text).strip()
        patterns = (
            r"^(.+?)\s+is\s+.+$",
            r"^(.+?)\s+are\s+.+$",
            r"^(.+?)\s+uses?\s+.+$",
            r"^(.+?)\s+should\s+.+$",
            r"^(.+?)是.+$",
            r"^(.+?)使用.+$",
        )
        for pattern in patterns:
            match = re.match(pattern, text, re.I)
            if not match:
                continue
            tokens = _tokenize(match.group(1))
            if not tokens - GENERIC_SUBJECT_TOKENS:
                return None
            return " ".join(sorted(tokens))
        return None

    def resident_notes(self):
        """返回常驻层的全部笔记，按 cap 截断。

        常驻层不经过检索：它装的正是「无法从 query 推出相关性」的那类记忆，
        所以它整体拼进 `memory` 段，每轮都在。cap 超出时保留最新的，
        因为 topic 文件里笔记是按晋升顺序追加的。
        """
        notes = []
        for topic in self.load_index():
            if durable_topic_tier(topic["topic"]) != RESIDENT_TIER:
                continue
            # 和 `promote()` 用同一套按 topic 的截断，两端必须一致：
            # 否则会出现写入时没被报告淘汰、读取时却被悄悄丢掉的笔记。
            notes.extend(_apply_resident_cap(self.load_topic_notes(topic["topic"]))[0])
        return notes

    def retrieval_candidates(self, query, limit=3):
        query_tokens = _tokenize(query)
        ranked = []
        for topic in self.load_index():
            # 常驻层已经整体进了 prompt，再让它参与检索只会占掉检索名额。
            if durable_topic_tier(topic["topic"]) != RETRIEVAL_TIER:
                continue
            notes = self.load_topic_notes(topic["topic"])
            for note in notes:
                note_tags = {tag.lower() for tag in note.get("tags", [])}
                note_tokens = _tokenize(note.get("text", "")) | _tokenize(topic.get("title", "")) | note_tags
                exact_tag_match = int(bool(query_tokens & note_tags))
                keyword_overlap = len(query_tokens & note_tokens)
                if exact_tag_match == 0 and keyword_overlap == 0:
                    continue
                recency = _parse_timestamp(note.get("created_at"))
                ranked.append(((exact_tag_match, keyword_overlap, recency), note))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [note for _, note in ranked[:limit]]

    def _write_index(self, topics):
        self.root.mkdir(parents=True, exist_ok=True)
        self.topics_dir.mkdir(parents=True, exist_ok=True)
        lines = ["# Durable Memory Index", ""]
        for topic in topics:
            lines.append(f"- [{topic['topic']}](topics/{topic['topic']}.md): {topic['title']}")
            lines.append(f"  - summary: {topic['summary']}")
            lines.append(f"  - tags: {', '.join(topic['tags'])}")
        self.index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _write_topic(self, topic, notes):
        self.topics_dir.mkdir(parents=True, exist_ok=True)
        meta = DURABLE_TOPIC_DEFAULTS[topic]
        lines = [
            f"# {meta['title']}",
            "",
            f"- topic: {topic}",
            f"- summary: {meta['summary']}",
            f"- tags: {', '.join(meta['tags'])}",
            f"- updated_at: {now()}",
            "",
            "## Notes",
        ]
        for note in notes:
            lines.append(f"- {_format_note_line(note)}")
        (self.topics_dir / f"{topic}.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def revoke(self, topic, note_text):
        """从某个 topic 删除一条笔记，返回是否真的删掉了。

        常驻记忆每轮都在影响模型，所以撤销必须是一个显式动作：用户确认某条
        常驻约定已经作废时，由这里把它从磁盘上抹掉，而不是靠新笔记去覆盖。
        """
        topic = str(topic).strip()
        note_text = str(note_text).strip()
        if not topic or not note_text:
            return False
        topics = {item["topic"]: item for item in self.load_index()}
        if topic not in topics:
            return False
        topic_notes = {
            slug: [
                {"text": note["text"], "subject": note.get("subject", "")}
                for note in self.load_topic_notes(slug)
            ]
            for slug in topics
        }
        existing = topic_notes.get(topic, [])
        if not any(item["text"] == note_text for item in existing):
            return False
        topic_notes[topic] = [item for item in existing if item["text"] != note_text]
        self._write_index([topics[slug] for slug in sorted(topics)])
        for slug, notes in topic_notes.items():
            self._write_topic(slug, notes)
        return True

    def promote(self, promotions):
        if not promotions:
            return [], [], []
        topics = {topic["topic"]: topic for topic in self.load_index()}
        topic_notes = {
            slug: [
                {"text": note["text"], "subject": note.get("subject", "")}
                for note in self.load_topic_notes(slug)
            ]
            for slug in topics
        }
        results = []
        superseded = []
        for promotion in promotions:
            # 支持 (topic, text) 和 (topic, text, subject) 两种形态。显式 subject
            # 来自模型提议的候选，比从句子里猜主语可靠得多。
            topic, note_text = promotion[0], promotion[1]
            explicit_subject = promotion[2] if len(promotion) > 2 else ""
            meta = DURABLE_TOPIC_DEFAULTS[topic]
            topics.setdefault(
                topic,
                {
                    "topic": topic,
                    "title": meta["title"],
                    "summary": meta["summary"],
                    "tags": list(meta["tags"]),
                },
            )
            existing = topic_notes.setdefault(topic, [])
            if any(item["text"] == note_text for item in existing):
                continue
            new_subject = self._normalized_subject(explicit_subject) or self._subject_key(note_text)
            entry = {"text": note_text, "subject": new_subject or ""}
            replaced = False
            if new_subject:
                for index, old in enumerate(list(existing)):
                    # 旧笔记优先用落盘的主语；没有才从正文里猜。
                    old_subject = self._normalized_subject(old.get("subject", "")) or self._subject_key(old["text"])
                    if old_subject == new_subject:
                        superseded.append(f"{topic}: {old['text']} -> {note_text}")
                        existing[index] = entry
                        replaced = True
                        break
            if not replaced:
                existing.append(entry)
            results.append(f"{topic}: {note_text}")
        # 常驻层有 cap：写盘前先按上限淘汰最旧的，并把淘汰结果回报给调用方，
        # 让它进 trace，而不是静默消失。
        evicted = []
        for slug, notes in topic_notes.items():
            if durable_topic_tier(slug) != RESIDENT_TIER:
                continue
            kept, dropped = _apply_resident_cap(notes)
            if not dropped:
                continue
            topic_notes[slug] = kept
            evicted.extend(f"{slug}: {_resident_note_text(item)}" for item in dropped)
        self._write_index([topics[slug] for slug in sorted(topics)])
        for topic, notes in topic_notes.items():
            self._write_topic(topic, notes)
        return results, superseded, evicted


def _ensure_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _dedupe_preserve_order(items):
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def resolve_workspace_path(raw_path, workspace_root=None):
    path = Path(str(raw_path))
    if workspace_root is None:
        return path

    root = Path(workspace_root).resolve()
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def canonicalize_path(raw_path, workspace_root=None):
    resolved = resolve_workspace_path(raw_path, workspace_root)
    if resolved is None:
        return Path(str(raw_path)).as_posix()
    if workspace_root is None:
        return Path(str(raw_path)).as_posix()
    root = Path(workspace_root).resolve()
    return resolved.relative_to(root).as_posix()


def file_freshness(raw_path, workspace_root=None):
    resolved = resolve_workspace_path(raw_path, workspace_root)
    if resolved is None or not resolved.exists() or not resolved.is_file():
        return None
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


CJK_RUN_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


def _cjk_tokens(text):
    """把中文按字符二元组切开。

    晋升侧的偏好抽取本来就支持中文，但若这里只切 ASCII，中文 query 分词后是
    空集合，任何候选都匹配不上，检索层对中文恒为空。这里不引入分词器：整段
    中文当成一个 token 一样匹配不上，单字又太噪，二元组是不带词典的折中。
    """
    tokens = set()
    for run in CJK_RUN_PATTERN.findall(str(text)):
        if len(run) == 1:
            tokens.add(run)
            continue
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def _tokenize(text):
    text = str(text)
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+", text)} | _cjk_tokens(text)


def _parse_timestamp(value):
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return 0.0


def normalize_memory_state(state, workspace_root=None):
    if state is None:
        state = default_memory_state()
    elif not isinstance(state, dict):
        raise TypeError("memory state must be a mapping")

    # 规范化层的作用，是把“磁盘里可能长得不太一样的旧状态”
    # 统一整理成当前 runtime 可直接使用的紧凑结构。
    working = state.get("working")
    if not isinstance(working, dict):
        working = {}
    working.setdefault("task_summary", "")
    working.setdefault("recent_files", [])
    working["task_summary"] = clip(str(working.get("task_summary", "")).strip(), 300)
    working["recent_files"] = _dedupe_preserve_order(
        [
            canonicalize_path(path, workspace_root)
            for path in _ensure_list(working.get("recent_files", []))
            if str(path).strip()
        ]
    )[-WORKING_FILE_LIMIT:]
    state["working"] = working

    if not str(working["task_summary"]).strip() and state.get("task"):
        working["task_summary"] = clip(str(state.get("task", "")).strip(), 300)
    if not working["recent_files"] and state.get("files"):
        working["recent_files"] = _dedupe_preserve_order(
            [
                canonicalize_path(path, workspace_root)
                for path in _ensure_list(state.get("files", []))
                if str(path).strip()
            ]
        )[-WORKING_FILE_LIMIT:]

    # episodic 层已移除。磁盘上的旧 session 可能还带着这些字段，这里直接丢弃：
    # 它装的内容要么和 file_summaries 重复（read_file 摘要），要么和 history
    # 压缩保留的失败工具轮重复（process note），而且没有 freshness，
    # 文件被改写后仍会把过期摘要召回给模型。
    for legacy_key in ("episodic_notes", "notes", "next_note_index"):
        state.pop(legacy_key, None)

    file_summaries = state.get("file_summaries")
    if not isinstance(file_summaries, dict):
        file_summaries = {}
    normalized_file_summaries = {}
    for path, summary in file_summaries.items():
        path = canonicalize_path(path, workspace_root)
        if isinstance(summary, dict):
            text = clip(str(summary.get("summary", "")).strip(), 500)
            created_at = str(summary.get("created_at", "")).strip() or now()
            freshness = summary.get("freshness")
            freshness = None if freshness in (None, "") else str(freshness).strip() or None
        else:
            text = clip(str(summary).strip(), 500)
            created_at = now()
            freshness = None
        if not path or not text:
            continue
        normalized_file_summaries[path] = {
            "summary": text,
            "created_at": created_at,
            "freshness": freshness,
        }
    state["file_summaries"] = normalized_file_summaries

    state["task"] = working["task_summary"]
    state["files"] = list(working["recent_files"])
    durable_root = Path(workspace_root) / ".repopilot" / "memory" if workspace_root is not None else None
    durable_store = DurableMemoryStore(durable_root) if durable_root is not None else None
    state["durable_topics"] = durable_store.topic_slugs() if durable_store is not None else []
    return state


def set_task_summary(state, summary, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    state["working"]["task_summary"] = clip(str(summary).strip(), 300)
    state["task"] = state["working"]["task_summary"]
    return state


def remember_file(state, path, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    path = canonicalize_path(path, workspace_root).strip()
    if not path:
        return state
    files = [item for item in state["working"]["recent_files"] if item != path]
    files.append(path)
    state["working"]["recent_files"] = files[-WORKING_FILE_LIMIT:]
    state["files"] = list(state["working"]["recent_files"])
    return state


def set_file_summary(state, path, summary, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    path = canonicalize_path(path, workspace_root).strip()
    summary = clip(str(summary).strip(), 500)
    if not path or not summary:
        return state
    state["file_summaries"][path] = {
        "summary": summary,
        "created_at": now(),
        "freshness": file_freshness(path, workspace_root),
    }
    return state


def invalidate_file_summary(state, path, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    path = canonicalize_path(path, workspace_root).strip()
    if not path:
        return state
    state["file_summaries"].pop(path, None)
    return state


def invalidate_stale_file_summaries(state, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    invalidated = []
    for path, summary in list(state["file_summaries"].items()):
        current_freshness = file_freshness(path, workspace_root)
        if summary.get("freshness") == current_freshness:
            continue
        invalidated.append(path)
        state["file_summaries"].pop(path, None)
    return state, invalidated


def summarize_read_result(result, limit=180):
    # 我们不会把完整文件内容塞进记忆层，
    # 这里只保留足够提醒下一轮“刚刚读到了什么”的短摘要。
    lines = [line.strip() for line in str(result).splitlines() if line.strip()]
    if not lines:
        return "(empty)"
    if lines[0].startswith("# "):
        lines = lines[1:]
    if not lines:
        return "(empty)"
    summary = " | ".join(lines[:3])
    return clip(summary, limit)


def retrieval_candidates(state, query, limit=3, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    query_tokens = _tokenize(query)
    ranked = []
    # 召回源只有检索层 durable 笔记。召回逻辑故意保持简单透明：
    # 先看 tag 精确命中，再看关键词重叠，最后看新旧程度。这里不引入 embedding。
    if workspace_root is not None:
        durable_store = DurableMemoryStore(Path(workspace_root) / ".repopilot" / "memory")
        for note in durable_store.retrieval_candidates(query, limit=limit):
            note_tags = {tag.lower() for tag in note.get("tags", [])}
            note_tokens = _tokenize(note.get("text", "")) | _tokenize(note.get("source", "")) | note_tags
            exact_tag_match = int(bool(query_tokens & note_tags))
            keyword_overlap = len(query_tokens & note_tokens)
            recency = _parse_timestamp(note.get("created_at"))
            ranked.append(((exact_tag_match, keyword_overlap, recency, -1), note))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [note for _, note in ranked[:limit]]


def retrieval_view(state, query, limit=3, workspace_root=None):
    candidates = retrieval_candidates(state, query, limit=limit, workspace_root=workspace_root)
    lines = ["Relevant memory:"]
    if not candidates:
        lines.append("- none")
        return "\n".join(lines)
    for note in candidates:
        lines.append(f"- {note['text']}")
    return "\n".join(lines)


def resident_notes_for(workspace_root):
    """读取常驻层正文。

    刻意不放进 `normalize_memory_state`：那是热路径（每次 remember_file / to_dict
    都会走），在那里读 topic 文件等于把磁盘 I/O 摊到每一次记忆写入上。
    常驻层每轮只在组装 prompt 时需要一次。
    """
    if workspace_root is None:
        return []
    store = DurableMemoryStore(Path(workspace_root) / ".repopilot" / "memory")
    return [note["text"] for note in store.resident_notes()]


def render_resident_memory_text(workspace_root=None):
    """渲染常驻层正文，作为独立的一段。

    它单独成段而不是并进 `Memory:`，是因为两者的变化频率完全不同：
    工作集（task / recent_files / file_summaries）每轮都在变，常驻层一次 run
    只在晋升时变一次。放在 prompt 里紧跟 prefix 的位置，可缓存前缀才能把它
    一起包进去——夹在易变内容后面的话，这段再稳定也复用不到。
    """
    notes = resident_notes_for(workspace_root)
    lines = ["Durable memory:"]
    lines.extend(f"- {text}" for text in notes) if notes else lines.append("- none")
    return "\n".join(lines)


def render_memory_text(state, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    # 这里渲染的是给模型看的紧凑“仪表盘”，不是完整回放。
    # 常驻层正文在下面展开；检索层的正文只在被召回时由 Relevant memory 段带出。
    lines = [
        "Memory:",
        f"- task: {state['working']['task_summary'] or '-'}",
        f"- recent_files: {', '.join(state['working']['recent_files']) or '-'}",
    ]

    summaries = []
    for path in state["working"]["recent_files"][:FILE_SUMMARY_LIMIT]:
        summary = state["file_summaries"].get(path, {})
        current_freshness = file_freshness(path, workspace_root)
        if summary.get("summary", "") and summary.get("freshness") == current_freshness:
            summaries.append(f"- {path}: {summary['summary']}")
    if summaries:
        lines.append("- file_summaries:")
        lines.extend(f"  {line}" for line in summaries)
    else:
        lines.append("- file_summaries: -")

    durable_topics = state.get("durable_topics", [])
    lines.append(f"- durable_topics: {', '.join(durable_topics) or '-'}")
    return "\n".join(lines)


def is_effectively_empty(state, workspace_root=None):
    state = normalize_memory_state(state, workspace_root)
    return (
        not str(state["working"]["task_summary"]).strip()
        and not state["working"]["recent_files"]
        and not state["file_summaries"]
    )


class LayeredMemory:
    def __init__(self, state=None, workspace_root=None):
        self.workspace_root = workspace_root
        self.state = normalize_memory_state(state, workspace_root)
        self.durable_store = DurableMemoryStore(Path(workspace_root) / ".repopilot" / "memory") if workspace_root is not None else None

    def to_dict(self):
        self.state = normalize_memory_state(self.state, self.workspace_root)
        return self.state

    def canonical_path(self, path):
        return canonicalize_path(path, self.workspace_root)

    def set_task_summary(self, summary):
        self.state = set_task_summary(self.state, summary, self.workspace_root)
        return self

    def remember_file(self, path):
        self.state = remember_file(self.state, path, self.workspace_root)
        return self

    def set_file_summary(self, path, summary):
        self.state = set_file_summary(self.state, path, summary, self.workspace_root)
        return self

    def invalidate_file_summary(self, path):
        self.state = invalidate_file_summary(self.state, path, self.workspace_root)
        return self

    def invalidate_stale_file_summaries(self):
        self.state, invalidated = invalidate_stale_file_summaries(self.state, self.workspace_root)
        return invalidated

    def retrieval_candidates(self, query, limit=3):
        return retrieval_candidates(self.state, query, limit=limit, workspace_root=self.workspace_root)

    def retrieval_view(self, query, limit=3):
        return retrieval_view(self.state, query, limit=limit, workspace_root=self.workspace_root)

    def render_memory_text(self):
        return render_memory_text(self.state, self.workspace_root)

    def promote_durable(self, promotions):
        if self.durable_store is None:
            return [], [], []
        self.state = normalize_memory_state(self.state, self.workspace_root)
        promoted, superseded, evicted = self.durable_store.promote(promotions)
        self.state = normalize_memory_state(self.state, self.workspace_root)
        return promoted, superseded, evicted

    def revoke_durable(self, topic, note_text):
        if self.durable_store is None:
            return False
        revoked = self.durable_store.revoke(topic, note_text)
        self.state = normalize_memory_state(self.state, self.workspace_root)
        return revoked

    def resident_notes(self):
        return resident_notes_for(self.workspace_root)

    def render_resident_memory_text(self):
        return render_resident_memory_text(self.workspace_root)
