"""Rule registry.

Rules run independently and their findings are never deduplicated, merged, or
reduced to a primary type.
"""

from __future__ import annotations

from .base import Context, Rule
from .fusion import FusionRule
from .redundant import RedundantRule
from .suboptimal import SuboptimalRule
from .widening import WideningRule

ALL_RULES: list[Rule] = [RedundantRule(), SuboptimalRule(), WideningRule(), FusionRule()]

__all__ = ["ALL_RULES", "Context", "Rule"]
