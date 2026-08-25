"""Path-based project rule resolution."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


RULES_RELATIVE_PATH = Path(".repopilot") / "rules.json"
PATH_TOKEN_PATTERN = re.compile(r"(?<![\w./\\-])([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_+\-]+)(?![\w./\\-])")


def _normalize_path(path):
    text = str(path or "").strip().strip("'\"`.,;:()[]{}")
    text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _as_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _glob_match(pattern, path):
    pattern = _normalize_path(pattern)
    path = _normalize_path(path)
    if fnmatch.fnmatchcase(path, pattern):
        return True
    # Treat ** as zero-or-more path segments, so tests/**/*.py also matches tests/test_file.py.
    if "/**/" in pattern and fnmatch.fnmatchcase(path, pattern.replace("/**/", "/")):
        return True
    return False


@dataclass(frozen=True)
class ProjectRule:
    path: str
    rule: str


@dataclass(frozen=True)
class RuleContext:
    candidate_paths: list[str] = field(default_factory=list)
    excluded_paths: list[str] = field(default_factory=list)
    matched_rules: list[dict] = field(default_factory=list)
    all_rule_chars: int = 0

    @property
    def rendered_chars(self):
        return len(self.render())

    def render(self):
        if not self.matched_rules:
            return ""
        lines = ["Project rules:"]
        for item in self.matched_rules:
            lines.append(f"- {item['path']} ({item['pattern']}): {item['rule']}")
        return "\n".join(lines)


class RuleResolver:
    def __init__(self, include=None, exclude=None, rules=None):
        self.include = tuple(_as_list(include))
        self.exclude = tuple(_as_list(exclude))
        self.rules = tuple(
            ProjectRule(path=str(item.get("path", "")).strip(), rule=str(item.get("rule", "")).strip())
            for item in (rules or [])
            if isinstance(item, dict) and str(item.get("path", "")).strip() and str(item.get("rule", "")).strip()
        )

    @classmethod
    def empty(cls):
        return cls()

    @classmethod
    def from_workspace(cls, root):
        path = Path(root) / RULES_RELATIVE_PATH
        if not path.exists():
            return cls.empty()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("rules.json must contain a JSON object")
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data):
        return cls(
            include=data.get("include", []),
            exclude=data.get("exclude", []),
            rules=data.get("rules", []),
        )

    @property
    def all_rule_chars(self):
        return sum(len(rule.rule) for rule in self.rules)

    def is_excluded(self, path):
        return any(_glob_match(pattern, path) for pattern in self.exclude)

    def is_included(self, path):
        if self.is_excluded(path):
            return False
        if not self.include:
            return True
        return any(_glob_match(pattern, path) for pattern in self.include)

    def match_path(self, path):
        normalized = _normalize_path(path)
        if not normalized or not self.is_included(normalized):
            return []
        return [
            {"path": normalized, "pattern": rule.path, "rule": rule.rule}
            for rule in self.rules
            if _glob_match(rule.path, normalized)
        ]

    def match_context(self, user_message, history=None):
        candidates = extract_candidate_paths(user_message, history or [])
        excluded = [path for path in candidates if self.is_excluded(path)]
        matched = []
        seen = set()
        for path in candidates:
            for item in self.match_path(path):
                key = (item["path"], item["pattern"], item["rule"])
                if key in seen:
                    continue
                seen.add(key)
                matched.append(item)
        return RuleContext(
            candidate_paths=candidates,
            excluded_paths=excluded,
            matched_rules=matched,
            all_rule_chars=self.all_rule_chars,
        )


def extract_candidate_paths(user_message, history=None):
    paths = []

    def add(path):
        normalized = _normalize_path(path)
        if normalized and normalized not in {".", ".."} and normalized not in paths:
            paths.append(normalized)

    for match in PATH_TOKEN_PATTERN.finditer(str(user_message or "")):
        add(match.group(1))

    for item in history or []:
        if not isinstance(item, dict):
            continue
        args = item.get("args") or {}
        if isinstance(args, dict):
            add(args.get("path", ""))
        for path in item.get("affected_paths", []) if isinstance(item.get("affected_paths"), list) else []:
            add(path)

    return paths
