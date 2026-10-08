"""Type M: a vector assembled from scalars instead of a structured load.

Two mechanisms live here, and both report structure rather than cost.
`MemoryRule` catches a chain of scalar inserts: SIMDe has no counterpart for
ARM's structured and lane-wise loads, so a strided read is written as a chain
of single-lane inserts. `ScalarSetBuildRule` catches a vector built in one
call from runtime scalars (`_mm_set_epi64x`/`_mm_set_epi32`/`_mm_set_epi16`),
whose NEON branch writes each argument into a local array and loads the
vector from it.

Neither carries an instruction count. Issue #74 adjudicated the recorded
counts against SIMDe 0.8.4 by compiling each idiom: the local array is a
candidate for scalar replacement and no compiler measured kept it, and an
insert chain compiles to the same instructions as the lane-load chain that
was offered as its replacement. What the cost turns on is where the operands
live and what the optimizer does, neither of which this branch states, so
both counts are withheld.

This rule has the highest false-positive risk of the six; the chain length
threshold is configurable through `ctx.config["memory_chain_threshold"]`.
"""

from __future__ import annotations

from typing import Iterator

from ..finding import Evidence, Finding
from ..ir import AnalysisUnit, IntrinsicCall, ValueKind
from ..symbols import parse_int_literal
from .base import Context, Option, location_fields, own_availability, raw_name_if_aliased

# The 256-bit epi32 and epi64 forms were missing while epi16 was registered,
# with no reason in the mechanism for the split: all three store a scalar into
# a lane, and all three expand without a NEON branch. SVT-AV1's pickrst builds
# two chains out of `_mm256_insert_epi64` that went unreported.
_INSERTS = {
    "_mm_insert_epi16",
    "_mm_insert_epi32",
    "_mm_insert_epi64",
    "_mm256_insert_epi16",
    "_mm256_insert_epi32",
    "_mm256_insert_epi64",
}
_DEFAULT_THRESHOLD = 3
_SCALAR_SETS = {"_mm_set_epi64x", "_mm_set_epi32", "_mm_set_epi16"}


def _is_integer_literal(text: str) -> bool:
    return parse_int_literal(text) is not None


def _is_a_broadcast(args) -> bool:
    """Whether every argument is the same expression as written.

    `_mm_set_epi32(offset, offset, offset, offset)` names one value four
    times. Comparison is on the text exactly as recorded, which carries no
    surrounding whitespace, so a wrapped argument list reads the same as a
    single-line one. Nothing is normalized beyond that: two spellings of one
    value stay two arguments, and the error that leaves -- reporting an
    assembly where a reader sees a broadcast -- is the direction that does
    not withdraw a finding.
    """
    return len({arg.text for arg in args}) == 1


class MemoryRule:
    type = "M"
    rule_id = "M.scalar_insert_chain"
    mechanism = "scalar insert chain"
    options = (
        Option("memory_chain_threshold", int, _DEFAULT_THRESHOLD, minimum=1),
    )

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        # Read, not parsed. `validate_config` has already checked the type
        # and filled the default; an `int(...)` here would be a second
        # interpretation of the same key, and the two would drift.
        threshold = ctx.config["memory_chain_threshold"]

        # Grouped by the assignment target as written, not by the variable
        # name. `dd[0]` and `dd[1]` are different vectors, and a lane load
        # replaces one of them, so inserts into different elements are
        # different chains however adjacent they sit in the source. Keying on
        # `result_var` merged them: SVT-AV1's pickrst_sse4.c has three places
        # where two runs of two became one run of four and cleared the
        # threshold that neither reached.
        by_target: dict[str, list[IntrinsicCall]] = {}
        for call in sorted(unit.calls, key=lambda c: c.start_byte):
            if call.name not in _INSERTS or not (call.result_lvalue or call.result_var):
                continue
            by_target.setdefault(call.result_lvalue or call.result_var, []).append(call)

        for target, calls in by_target.items():
            # Splitting still asks about the *variable*: `redefined_between`
            # tracks a name, and a write to `dd` breaks a chain on `dd[0]`
            # just as surely as one to `dd[0]` does.
            variable = calls[0].result_var or target
            for chain in self._split_chains(unit, variable, calls):
                if len(chain) < threshold:
                    continue
                yield self._finding(unit, ctx, target, chain)

    @staticmethod
    def _split_chains(
        unit: AnalysisUnit, target: str, calls: list[IntrinsicCall]
    ) -> Iterator[list[IntrinsicCall]]:
        """Split same-variable inserts into runs unbroken by an intervening write.

        Source reuses a vector variable name across unrelated blocks -- a reset
        and rebuild later in the same function, for instance. Grouping by
        result_var alone would merge those into one oversized chain spanning
        code that has nothing to do with the first. A write to `target`
        between two inserts (any definition strictly between their lines)
        means the later insert cannot be extending the earlier one's result,
        so it starts a new chain instead.

        A change of `control_region` breaks a chain for a different reason,
        and the two shapes it covers are not equally strong.

        Exclusive arms are the clear case: four inserts split two-and-two
        across an `if`/`else` were reported as a chain of four that no
        execution path assembles, at evidence A, with the costs summed over
        both arms.

        A loop or nested-block boundary is weaker. An outer run and the first
        iteration of a loop below it *can* run consecutively, so a chain
        crossing that boundary may well execute. Splitting there is not a
        claim that it cannot: this rule has no model of repetition, so it
        confines a reported chain to one syntactic region rather than
        aggregating costs across code whose execution count it does not know.
        That is a definition of the analysis unit, not a proof about runtime.

        Equality only, never nesting. Fail-closed in both directions: a
        cross-region chain that really does execute is split and its finding
        lost, which costs coverage. The alternative reports a chain and a cost
        the IR cannot support.
        """
        chain: list[IntrinsicCall] = []
        for call in calls:
            if chain and (
                unit.redefined_between(
                    target, own_availability(unit, chain[-1]), call.start_byte
                )
                or call.control_region != chain[-1].control_region
            ):
                yield chain
                chain = []
            chain.append(call)
        if chain:
            yield chain

    def _finding(
        self, unit: AnalysisUnit, ctx: Context, target: str, calls: list[IntrinsicCall]
    ) -> Finding:
        direct = all(
            call.args and call.args[0].kind is ValueKind.VARIABLE and call.args[0].text == target
            for call in calls
        )
        first = calls[0]
        last = calls[-1]
        first_cost = ctx.knowledge.cost(self.rule_id, first.name)
        simde_total, native_total = self._sum_costs(ctx, calls)
        return Finding(
            type=self.type,
            rule=self.rule_id,
            rule_mechanism=self.mechanism,
            evidence=Evidence.A if direct else Evidence.B,
            file=unit.file,
            line=first.line,
            **location_fields(unit),
            intrinsic=first.name,
            rationale=(
                f"{len(calls)} scalar insert operations assemble {target} between "
                f"lines {first.line} and {last.line}; consider whether a native "
                f"load or vector-construction idiom better expresses the "
                f"surrounding access pattern ({first_cost.source})"
            ),
            simde_insns=simde_total,
            native_insns=native_total,
            # Representative: chains observed so far are one insert intrinsic
            # throughout, so the first call's suggestion stands for the whole
            # chain. If the first element's own cost is unknown, no fused
            # instruction is offered for the chain either.
            suggestion=first_cost.suggestion,
            raw_name=raw_name_if_aliased(first),
        )

    def _sum_costs(
        self, ctx: Context, calls: list[IntrinsicCall]
    ) -> tuple[int | None, int | None]:
        simde_total = 0
        native_total = 0
        for call in calls:
            cost = ctx.knowledge.cost(self.rule_id, call.name)
            if cost.simde_insns is None or cost.native_insns is None:
                # One unknown element makes the chain total unknown: there is
                # no honest number to add it to.
                return None, None
            simde_total += cost.simde_insns
            native_total += cost.native_insns
        return simde_total, native_total


class ScalarSetBuildRule:
    """Type M, second mechanism: a vector assembled from runtime scalars.

    On NEON, SIMDe's set constructors write each argument into a local array
    and load the whole vector from it. That is the source idiom; it is not the
    emitted code, and no compiler measured for issue #74 kept the array. What
    this rule reports is the structure at the call site -- separate runtime
    scalars assembled into one vector -- and not a cost, because the emitted
    cost turns on argument shape and on the optimizer. VVenC's LoopFilter
    reads strided pixel rows this way, which is where the paper's LoopFilter
    Type M instances come from.
    """

    type = "M"
    rule_id = "M.scalar_set_build"
    mechanism = "vector built from runtime scalars"
    options = ()

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]:
        for call in unit.calls:
            if call.name not in _SCALAR_SETS or not call.args:
                continue
            if all(_is_integer_literal(arg.text) for arg in call.args):
                # A constant vector, not a scalar assembly.
                continue
            if _is_a_broadcast(call.args):
                # Every lane the same expression. The mechanism this rule
                # names is assembling a vector out of separate scalars, and
                # one value repeated is not that: SIMDe compiles
                # `_mm_set_epi16(w, w, w, w, w, w, w, w)` to a single `dup`
                # on both compilers measured, so there is no scalar assembly
                # at the call site to report. The comparison is textual on
                # purpose -- equal expressions, not equal values, which would
                # need the propagation this rule does not do.
                continue
            cost = ctx.knowledge.cost(self.rule_id, call.name)
            # The count the rationale states is of runtime arguments, not of
            # arguments: `_mm_set_epi64x(0, m5)` assembles one, and saying two
            # was a false quantitative claim about a call the rule reports.
            runtime = sum(1 for arg in call.args if not _is_integer_literal(arg.text))
            direct = all(arg.kind is ValueKind.VARIABLE for arg in call.args)
            simde_total = cost.simde_insns * len(call.args) if cost.simde_insns is not None else None
            native_total = (
                cost.native_insns * len(call.args) if cost.native_insns is not None else None
            )
            yield Finding(
                type=self.type,
                rule=self.rule_id,
                rule_mechanism=self.mechanism,
                evidence=Evidence.A if direct else Evidence.B,
                file=unit.file,
                line=call.line,
                **location_fields(unit),
                intrinsic=call.name,
                rationale=(
                    f"{call.name} assembles {runtime} runtime scalar "
                    f"argument(s) of {len(call.args)} into one vector through "
                    f"SIMDe's set-constructor path; emitted cost depends on "
                    f"argument shape and compiler optimization ({cost.source})"
                ),
                simde_insns=simde_total,
                native_insns=native_total,
                suggestion=cost.suggestion,
                raw_name=raw_name_if_aliased(call),
            )
