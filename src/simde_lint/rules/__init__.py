"""Rule registry.

Rules run independently and their findings are never deduplicated, merged, or
reduced to a primary type.
"""

from __future__ import annotations

from .base import Context, Rule
from .redundant import RedundantRule

ALL_RULES: list[Rule] = [RedundantRule()]

__all__ = ["ALL_RULES", "Context", "Rule"]
