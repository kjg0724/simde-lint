"""Machine-readable report."""

from __future__ import annotations

import json
from collections import Counter

from .. import __version__
from ..finding import Finding, SORT_KEYS


def render_json(findings: list[Finding], simde_version: str, *, sort: str = "benchmarked") -> str:
    # by_rule carries the mechanism, because a taxonomy type can have more than
    # one implemented mechanism and by_type alone would hide which one ran.
    mechanisms = {f.rule: f.rule_mechanism for f in findings}
    types = {f.rule: f.type for f in findings}
    by_rule = Counter(f.rule for f in findings)
    document = {
        # Read from the package rather than taken as a parameter: the value
        # a report claims for the tool that produced it must be the tool
        # that is actually running, not whatever a caller happened to pass,
        # so there is exactly one place this can drift from
        # `simde_lint.__version__` -- nowhere.
        "simde_lint_version": __version__,
        "simde_version": simde_version,
        "findings": [f.to_dict() for f in sorted(findings, key=SORT_KEYS[sort])],
        "summary": {
            "total": len(findings),
            "by_type": dict(sorted(Counter(f.type for f in findings).items())),
            "by_rule": {
                rule_id: {
                    "type": types[rule_id],
                    "count": count,
                    "mechanism": mechanisms[rule_id],
                }
                for rule_id, count in sorted(by_rule.items())
            },
            "by_evidence": dict(sorted(Counter(f.evidence.value for f in findings).items())),
        },
    }
    return json.dumps(document, indent=2)
