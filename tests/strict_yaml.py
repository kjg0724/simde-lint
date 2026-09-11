"""A YAML loader that refuses a repeated key instead of keeping the last one.

PyYAML's default resolves `a: 1` followed by `a: 2` to `2`, silently. Every
file this repository uses to decide whether a test means anything is YAML, and
in each of them the silent resolution is a hole:

- in `tests/oracle/expected.yaml`, a repeated key inside a finding overwrites
  half an expectation while the file still parses, and at case level it drops
  a whole case's expectations while every completeness test still passes;
- in `tests/faults.yaml` and `tests/runner_guards.yaml`, a second top-level
  `faults:` discards the entire list, and the harness then reports "all 0
  mutations caught" as a success.

Shared rather than copied, because the second hole was opened by writing a
strict loader for the first and then reading the second with `safe_load`.
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
