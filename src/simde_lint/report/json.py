"""Machine-readable report."""

from __future__ import annotations

import json
from collections import Counter

import simde_lint

from ..finding import Finding, SORT_KEYS


def render_json(findings: list[Finding], simde_version: str, *, sort: str = "benchmarked") -> str:
    # by_rule carries the mechanism, because a taxonomy type can have more than
    # one implemented mechanism and by_type alone would hide which one ran.
    mechanisms = {f.rule: f.rule_mechanism for f in findings}
    types = {f.rule: f.type for f in findings}
    by_rule = Counter(f.rule for f in findings)
    document = {
        # Dereferenced here, not taken as a parameter and not imported by
        # value: the version a report claims must be the one actually
        # running. `from .. import __version__` would bind the string when
        # this module is first imported, which is a copy -- the very thing
        # this is meant not to have. Reaching through the module leaves no
        # place for the two to disagree, and a monkeypatch test can prove
        # it, which a by-value import makes impossible to distinguish from
        # a stale duplicate.
        "simde_lint_version": simde_lint.__version__,
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
