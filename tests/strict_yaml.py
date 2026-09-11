"""Fail-closed reading for every collection the evidence base is decided from.

Each of these files answers "does this test mean anything", and each answers
it by being a non-empty collection. Both halves of that can be lost quietly.

**A repeated key.** PyYAML resolves `a: 1` followed by `a: 2` to `2`, in
silence. In `tests/oracle/expected.yaml` a repeat inside a finding overwrites
half an expectation while the file still parses, and at case level it drops a
whole case while every completeness test still passes. In `tests/faults.yaml`
and `tests/runner_guards.yaml` a second top-level `faults:` discards the list
and the replay reports "all 0 mutations caught" as a success.

**An empty collection.** Every check here is a universal statement, and a
universal statement over nothing is true. An emptied `coverage.yaml` passes
"every cell is covered or a named gap" and "every mandatory combination is met"
without examining anything; an emptied catalogue passes the replay. Zero
attempted is zero evidence, whatever emptied it — a duplicate key, a bad
merge, a truncated edit.

The loader is shared rather than copied because the catalogue hole was opened
by writing a strict loader for `expected.yaml` and then reading the catalogue
with `safe_load` one file over. `require` exists for the same reason: the
rule belongs in one place, not in each caller's memory.
"""
from __future__ import annotations

import yaml


class StrictLoader(yaml.SafeLoader):
    """`yaml.SafeLoader` that raises on a duplicate key."""


def _mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.constructor.SafeConstructor.construct_mapping(loader, node, deep)


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load(text: str):
    """Parse `text`, raising `yaml.constructor.ConstructorError` on a duplicate."""
    return yaml.load(text, StrictLoader)


class EmptyCollection(Exception):
    """A collection the evidence base is decided from has nothing in it."""


def require(collection, what: str):
    """Return `collection`, refusing it when empty.

    Call this at every point a universal check is about to quantify over
    something loaded from disk. The check itself cannot tell "nothing violates
    this" from "there was nothing to violate it", and reports both as success.
    """
    if not collection:
        raise EmptyCollection(
            f"{what} is empty, so every check over it passes without examining "
            "anything. Zero entries is zero evidence, not agreement."
        )
    return collection
