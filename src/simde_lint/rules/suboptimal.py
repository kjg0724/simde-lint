"""Type S: the pshufb-to-tbl index guard.

x86 pshufb zeroes a lane when bit 7 of the index is set; ARM tbl zeroes a lane
when the index exceeds the table size. SIMDe bridges the gap with a guard on
every call. When the mask is known and never sets bit 7 on an in-range index,
the guard is dead work.

This rule covers only that mechanism. The taxonomy's Type S also includes
transpose and blend sequences, which are out of scope for v1.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding, Impact, Reason
from ..ir import AnalysisUnit, ValueKind, ValueRef
from .base import Context, raw_name_if_aliased

_TARGETS = frozenset({"_mm_shuffle_epi8", "_mm256_shuffle_epi8"})


def _lane_is_safe(lane: int) -> bool:
    """A lane is safe when tbl and pshufb agree on it.

    In range [0,15] both select the same byte. With bit 7 set both produce
    zero: pshufb by its MSB rule, tbl because the index exceeds the table.
    Lanes in [16,127] are the unsafe middle: pshufb has one table operand
    and, with bit 7 clear, masks the index down to its low 4 bits before
    indexing it — an index like 20 behaves as index 4, not as an
    out-of-range access. Plain tbl applies no such masking and zeroes any
    index >= 16. SIMDe's guard reproduces pshufb's low-4-bit masking before
    the tbl runs (`vandq_u8(b, vdupq_n_u8(0x8F))` in x86/ssse3.h), which is
    exactly why the guard is load-bearing, not dead work, for a mask lane in
    this range. 256-bit shuffles apply this per 128-bit half, which this
    byte-level check already expresses since every lane value is masked to a
    single byte first.
    """
    lane &= 0xFF
    return lane <= 15 or lane >= 0x80


def _lanes_are_safe(lanes: tuple[int, ...]) -> bool:
    return all(_lane_is_safe(lane) for lane in lanes)


class SuboptimalRule:
    type = "S"
    rule_id = "S.pshufb_guard"
    mechanism = "pshufb->tbl guard only"

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        for call in unit.calls:
            if call.name not in _TARGETS or len(call.args) < 2:
                continue
            cost = ctx.knowledge.cost(self.rule_id, call.name)
            evidence, rationale, mask_source, reason = self._grade(
                call.args[1], unit, call.start_byte, ctx
            )
            # Only grade A confirms every mask lane lies in a range tbl and
            # pshufb agree on. B leaves the lane values unpinned and C is
            # either unresolvable or a confirmed unsafe lane — neither
            # supports claiming the guard is dead work, so the suggestion and
            # the instruction counts are withheld rather than printed next to
            # a rationale that says the opposite.
            supported = evidence is Evidence.A
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                evidence=evidence,
                impact=Impact.CONFIRMED,
                file=unit.file,
                line=call.line,
                function=unit.name,
                intrinsic=call.name,
                rationale=f"{rationale} ({cost.source})",
                simde_insns=cost.simde_insns if supported else None,
                native_insns=cost.native_insns if supported else None,
                suggestion=cost.suggestion if supported else None,
                mask_source=mask_source,
                reason=reason,
                raw_name=raw_name_if_aliased(call),
            )

    def _literal_origin(
        self, ref: ValueRef, unit: AnalysisUnit, position: int, seen: set[int]
    ) -> str | None:
        """Name of the operation a value reaches a byte literal through.

        VVenC builds its shuffle masks in several steps — an add against a
        literal, then a blend — so a single hop back finds only the last
        operation and misses the literal behind it. Walking the definitions
        and call operands within the function finds it. Returns None when no
        literal is reachable.
        """
        if ref.kind is ValueKind.LITERAL_VECTOR:
            return None
        if ref.kind is ValueKind.VARIABLE:
            definition = unit.definition_before(ref.text, position)
            if definition is None:
                return None
            if definition.value.kind is ValueKind.LITERAL_VECTOR:
                return definition.value.text
            return self._literal_origin(definition.value, unit, definition.start_byte, seen)
        if ref.kind is ValueKind.CALL_RESULT and ref.call_id is not None:
            if ref.call_id in seen:
                return None
            seen.add(ref.call_id)
            source = unit.call_by_id(ref.call_id)
            if source is None:
                return None
            if any(a.kind is ValueKind.LITERAL_VECTOR for a in source.args):
                return source.name
            for argument in source.args:
                found = self._literal_origin(argument, unit, source.start_byte, seen)
                if found is not None:
                    return source.name
        return None

    def _grade(
        self, mask: ValueRef, unit: AnalysisUnit, position: int, ctx: Context
    ) -> tuple[Evidence, str, dict | None, Reason | None]:
        guard = f"SIMDe {ctx.knowledge.simde_version} guards the tbl index on every call"

        if mask.kind is ValueKind.LITERAL_VECTOR and mask.lanes:
            if _lanes_are_safe(mask.lanes):
                return Evidence.A, f"{guard}; inline mask lanes are all in [0,15] or 0xFF", None, None
            return (
                Evidence.C,
                f"{guard}; inline mask has a lane in the unsafe [16,127] middle range",
                None,
                Reason.GUARD_REQUIRED,
            )

        if mask.kind is ValueKind.SYMBOL and mask.symbol:
            array = ctx.symbols.lookup(mask.symbol)
            if array and all(_lanes_are_safe(row) for row in array.rows):
                return (
                    Evidence.A,
                    f"{guard}; mask resolved via {array.name}, all {len(array.rows)} "
                    f"row(s) have lanes in [0,15] or 0xFF",
                    {
                        "symbol": array.name,
                        "defined_at": array.defined_at,
                        "resolution": "all_rows" if len(array.rows) > 1 else "single_row",
                    },
                    None,
                )
            if array:
                return (
                    Evidence.C,
                    f"{guard}; {array.name} has a row with a lane in the unsafe "
                    "[16,127] middle range",
                    {"symbol": array.name, "defined_at": array.defined_at, "resolution": "unsafe_row"},
                    Reason.GUARD_REQUIRED,
                )
            return (
                Evidence.C,
                f"{guard}; mask symbol {mask.symbol} is not defined in the scanned inputs",
                None,
                Reason.UNRESOLVED,
            )

        if mask.kind is ValueKind.VARIABLE:
            definition = unit.definition_before(mask.text, position)
            if (
                definition is not None
                and definition.value.kind is ValueKind.LITERAL_VECTOR
                and definition.value.lanes
                and len(unit.definitions.get(mask.text, ())) == 1
            ):
                # A local constant: assigned a byte literal once and never
                # reassigned, so the lanes are as certain as an inline literal.
                #
                # The count spans the whole function on purpose, including
                # writes that appear after this use. Def-use here is
                # line-ordered and models no control flow, so a later line is
                # not a later execution: inside a loop, a write below the use
                # reaches it on the next iteration. Narrowing this to prior
                # definitions would grade such a mask A on the strength of a
                # value it no longer holds. Grading B instead under-claims,
                # which is the direction this tool errs in by design.
                if _lanes_are_safe(definition.value.lanes):
                    return (
                        Evidence.A,
                        f"{guard}; mask is the local constant {mask.text}, whose lanes "
                        "are all in [0,15] or 0xFF",
                        None,
                        None,
                    )
                return (
                    Evidence.C,
                    f"{guard}; local constant {mask.text} sets bit 7 on an in-range index",
                    None,
                    Reason.GUARD_REQUIRED,
                )
            origin = self._literal_origin(mask, unit, position, set())
            if origin is not None:
                return (
                    Evidence.B,
                    f"{guard}; mask derives from a literal through {origin}, "
                    "so the final lane values are not pinned",
                    None,
                    None,
                )
            return (
                Evidence.C,
                f"{guard}; mask variable {mask.text} is not traced to a literal",
                None,
                Reason.UNRESOLVED,
            )

        if mask.kind is ValueKind.CALL_RESULT:
            return (
                Evidence.C,
                f"{guard}; mask is produced by a call with unknown lanes",
                None,
                Reason.UNRESOLVED,
            )

        return Evidence.C, f"{guard}; mask is runtime data", None, Reason.UNRESOLVED
