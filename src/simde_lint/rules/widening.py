"""Type W: the 16-to-32 widening multiply round-trip.

SSE2 has no direct 16-to-32 widening multiply, so x86 code computes the low
and high halves separately and interleaves them. NEON provides smull, which
does the whole job in one instruction.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding
from ..ir import AnalysisUnit, IntrinsicCall, ValueKind
from .base import Context, location_fields, own_availability, raw_name_if_aliased

_UNPACK = {"_mm_unpacklo_epi16", "_mm_unpackhi_epi16"}


def _operand_key(call: IntrinsicCall) -> tuple[str, ...]:
    return tuple(arg.text for arg in call.args)


def _all_direct_variables(call: IntrinsicCall) -> bool:
    return all(arg.kind is ValueKind.VARIABLE for arg in call.args)


class WideningRule:
    type = "W"
    rule_id = "W.mul16_widen_roundtrip"
    mechanism = "16-to-32 widening multiply round-trip"

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        cost = ctx.knowledge.cost(self.rule_id)
        by_position = lambda calls: sorted(calls, key=lambda c: c.start_byte)
        los = by_position(c for c in unit.calls if c.name == "_mm_mullo_epi16")
        his = by_position(c for c in unit.calls if c.name == "_mm_mulhi_epi16")
        unpacks = by_position(c for c in unit.calls if c.name in _UNPACK)

        # One finding per round-trip, not per matching pair. VVenC's DeQuant
        # repeats this sequence four times in one function reusing the same
        # variable names, so pairing every multiply with every other would
        # report sixteen findings for four round-trips. Each multiply claims
        # its nearest unclaimed partner and consumer.
        claimed_his: set[int] = set()
        claimed_unpacks: set[int] = set()

        for lo in los:
            hi = self._partner(his, claimed_his, lo)
            if hi is None or not lo.result_var or not hi.result_var:
                continue
            consumer = self._consumer(
                unpacks, claimed_unpacks, lo.result_var, hi.result_var, hi.start_byte
            )
            if consumer is None:
                continue
            if unit.redefined_between(
                lo.result_var, own_availability(unit, lo), consumer.start_byte
            ) or unit.redefined_between(
                hi.result_var, own_availability(unit, hi), consumer.start_byte
            ):
                # The unpack still names lo.result_var/hi.result_var, but one
                # of them was overwritten before the unpack runs, so the value
                # it consumes is not this multiply's product. Every other rule
                # that links a producer to a consumer by variable name already
                # guards against this; W is not exempt just because its
                # producer is a pair rather than a single call.
                continue
            claimed_his.add(hi.id)
            claimed_unpacks.add(consumer.id)
            direct = _all_direct_variables(lo) and _all_direct_variables(hi)
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                evidence=Evidence.A if direct else Evidence.B,
                file=unit.file,
                line=lo.line,
                **location_fields(unit),
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
                raw_name=raw_name_if_aliased(lo),
            )

    @staticmethod
    def _partner(
        his: list[IntrinsicCall], claimed: set[int], lo: IntrinsicCall
    ) -> IntrinsicCall | None:
        """Unclaimed mulhi nearest to this mullo that shares its operands."""
        candidates = [
            hi for hi in his if hi.id not in claimed and _operand_key(hi) == _operand_key(lo)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda hi: abs(hi.start_byte - lo.start_byte))

    @staticmethod
    def _consumer(
        unpacks: list[IntrinsicCall],
        claimed: set[int],
        lo_var: str,
        hi_var: str,
        after_position: int,
    ) -> IntrinsicCall | None:
        """First unclaimed unpack at or after the multiplies taking both results.

        This only matches by variable name and position, the same as the
        other rules' first pass over their candidate consumer. It does not
        itself verify that `lo_var`/`hi_var` still hold the multiplies'
        results at `consumer.line` — `match` does that afterward with
        `redefined_between`, exactly where `F` and `P` place the equivalent
        check. Folding it in here would mix "which unpack is the candidate"
        with "does the candidate actually see this value", the same
        separation the other rules keep.
        """
        for unpack in unpacks:
            if unpack.id in claimed or unpack.start_byte < after_position:
                continue
            texts = {arg.text for arg in unpack.args}
            if lo_var in texts and hi_var in texts:
                return unpack
        return None
