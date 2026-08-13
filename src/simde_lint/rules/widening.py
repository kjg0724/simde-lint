"""Type W: the 16-to-32 widening multiply round-trip.

SSE2 has no direct 16-to-32 widening multiply, so x86 code computes the low
and high halves separately and interleaves them. NEON provides smull, which
does the whole job in one instruction.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Impact
from ..ir import FunctionUnit, IntrinsicCall, ValueKind
from .base import Context

_UNPACK = {"_mm_unpacklo_epi16", "_mm_unpackhi_epi16"}


def _operand_key(call: IntrinsicCall) -> tuple[str, ...]:
    return tuple(arg.text for arg in call.args)


def _all_direct_variables(call: IntrinsicCall) -> bool:
    return all(arg.kind is ValueKind.VARIABLE for arg in call.args)


class WideningRule:
    type = "W"
    rule_id = "W.mul16_widen_roundtrip"
    mechanism = "16-to-32 widening multiply round-trip"

    def match(self, unit: FunctionUnit, ctx: Context) -> Iterator[Finding]:
        cost = ctx.knowledge.cost(self.rule_id)
        los = [c for c in unit.calls if c.name == "_mm_mullo_epi16"]
        his = [c for c in unit.calls if c.name == "_mm_mulhi_epi16"]
        unpacks = [c for c in unit.calls if c.name in _UNPACK]

        for lo in los:
            for hi in his:
                if _operand_key(lo) != _operand_key(hi):
                    continue
                if not lo.result_var or not hi.result_var:
                    continue
                consumer = self._consumer(unpacks, lo.result_var, hi.result_var)
                if consumer is None:
                    continue
                direct = _all_direct_variables(lo) and _all_direct_variables(hi)
                yield Finding(
                    type=self.type,
                    rule=self.rule_id,
                    rule_mechanism=self.mechanism,
                    evidence=Evidence.A if direct else Evidence.B,
                    impact=Impact.CONFIRMED,
                    file=unit.file,
                    line=lo.line,
                    function=unit.name,
                    intrinsic="_mm_mullo_epi16",
                    rationale=(
                        f"_mm_mullo_epi16 at line {lo.line} and _mm_mulhi_epi16 at line "
                        f"{hi.line} share operands and feed {consumer.name} at line "
                        f"{consumer.line}; NEON computes this with a single widening "
                        f"multiply ({cost.source})"
                    ),
                    simde_insns=cost.simde_insns,
                    native_insns=cost.native_insns,
                    suggestion=cost.suggestion,
                )

    @staticmethod
    def _consumer(
        unpacks: list[IntrinsicCall], lo_var: str, hi_var: str
    ) -> IntrinsicCall | None:
        for unpack in unpacks:
            texts = {arg.text for arg in unpack.args}
            if lo_var in texts and hi_var in texts:
                return unpack
        return None
