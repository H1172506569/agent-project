"""Structured inspection findings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

FINDING_PATTERN = re.compile(r"<finding>(.*?)</finding>", re.S)
ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    severity: str
    category: str
    snippet: str
    rationale: str
    suggestion: str

    @classmethod
    def from_dict(cls, data, default_path=""):
        if not isinstance(data, dict):
            raise ValueError("finding must be a JSON object")
        path = str(data.get("path") or default_path or "").strip()
        if not path:
            raise ValueError("finding.path is required")
        line = int(data.get("line", 0))
        if line < 1:
            raise ValueError("finding.line must be >= 1")
        severity = str(data.get("severity", "medium") or "medium").strip().lower()
        if severity not in ALLOWED_SEVERITIES:
            raise ValueError(f"finding.severity must be one of: {', '.join(sorted(ALLOWED_SEVERITIES))}")
        category = str(data.get("category", "general") or "general").strip()
        snippet = str(data.get("snippet", "") or "").strip()
        rationale = str(data.get("rationale", "") or "").strip()
        suggestion = str(data.get("suggestion", "") or "").strip()
        if not rationale:
            raise ValueError("finding.rationale is required")
        if not suggestion:
            raise ValueError("finding.suggestion is required")
        return cls(
            path=path,
            line=line,
            severity=severity,
            category=category,
            snippet=snippet,
            rationale=rationale,
            suggestion=suggestion,
        )

    def to_dict(self):
        return {
            "path": self.path,
            "line": self.line,
            "severity": self.severity,
            "category": self.category,
            "snippet": self.snippet,
            "rationale": self.rationale,
            "suggestion": self.suggestion,
        }


def parse_findings(text, default_path=""):
    findings = []
    for match in FINDING_PATTERN.finditer(str(text or "")):
        body = match.group(1).strip()
        if not body:
            continue
        payload = json.loads(body)
        findings.append(Finding.from_dict(payload, default_path=default_path))
    return findings


def render_findings(findings):
    if not findings:
        return "No findings."
    lines = []
    for finding in findings:
        lines.append(
            f"{finding.severity.upper()} {finding.path}:{finding.line} "
            f"[{finding.category}] {finding.rationale} Suggestion: {finding.suggestion}"
        )
    return "\n".join(lines)
