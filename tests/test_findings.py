import json

import pytest

from repopilot.findings import Finding, parse_findings, render_findings


def test_parse_findings_reads_structured_finding_blocks():
    payload = {
        "path": "app.py",
        "line": 12,
        "severity": "high",
        "category": "bug",
        "snippet": "return value",
        "rationale": "The value is returned before validation.",
        "suggestion": "Validate before returning.",
    }

    findings = parse_findings(f"<finding>{json.dumps(payload)}</finding>")

    assert findings == [Finding.from_dict(payload)]
    assert "HIGH app.py:12" in render_findings(findings)


def test_parse_findings_uses_default_path_and_validates_required_fields():
    payload = {
        "line": 3,
        "severity": "medium",
        "category": "test",
        "rationale": "Missing assertion.",
        "suggestion": "Add an assertion.",
    }

    findings = parse_findings(f"<finding>{json.dumps(payload)}</finding>", default_path="tests/test_app.py")

    assert findings[0].path == "tests/test_app.py"

    with pytest.raises(ValueError, match="finding.line"):
        Finding.from_dict({"path": "x.py", "line": 0, "rationale": "bad", "suggestion": "fix"})
