"""Rule registry.

Rules run independently and their findings are never deduplicated, merged, or
reduced to a primary type.
"""

from __future__ import annotations

from .base import ConfigError, Context, Option, Rule, validate_config
from .fusion import FusionRule
from .memory import MemoryRule, ScalarSetBuildRule
from .pipeline import PipelineRule
from .redundant import RedundantRule
from .suboptimal import SuboptimalRule
from .widening import WideningRule

ALL_RULES: list[Rule] = [
    RedundantRule(),
    SuboptimalRule(),
    WideningRule(),
    FusionRule(),
    MemoryRule(),
    ScalarSetBuildRule(),
    PipelineRule(),
]

__all__ = ["ALL_RULES", "ConfigError", "Context", "Option", "Rule", "validate_config"]
