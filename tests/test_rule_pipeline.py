from simde_lint.finding import Evidence, Impact
from simde_lint.rules.pipeline import PipelineRule


def test_reports_a_compare_consumed_by_the_next_call(run_rule):
    findings = [f for f in run_rule(PipelineRule(), "pipeline_positive.c") if f.function == "kernel"]
    assert len(findings) == 1
    assert findings[0].type == "P"
    assert findings[0].evidence is Evidence.A
    assert findings[0].impact is Impact.DIAGNOSTIC
    assert findings[0].intrinsic == "_mm_cmpgt_epi64"
    # I: the fixture calls the VVenC-style macro alias `_my_cmpgt_epi64`, not
    # `_mm_cmpgt_epi64` directly, so a reader grepping the source for
    # `intrinsic` needs the raw spelling surfaced here to find the line.
    assert findings[0].raw_name == "_my_cmpgt_epi64"


def test_verdict_is_invariant_to_how_the_alias_forwards_its_operands(run_rule):
    """C1: P reads only operand membership, never the compare's own args.

    `_reversed_cmpgt_epi64` in the fixture hands its parameters to the real
    intrinsic in the opposite order from `_my_cmpgt_epi64`, but the call site
    still records its own args in macro-parameter order (a, b) either way --
    `is_forwarding_alias` discards the body's internal argument mapping
    entirely, keeping only the target name. P's verdict must be identical
    between the faithful and the unfaithful alias, because `PipelineRule.match`
    never reads `current.args`: it only checks whether `current.result_var`
    is a *member* of the following call's args, which neither a reversed
    operand nor a different arity inside the macro body can change.
    """
    findings = {
        f.function: f
        for f in run_rule(PipelineRule(), "pipeline_positive.c")
        if f.function in ("kernel", "unfaithful_forward")
    }
    assert set(findings) == {"kernel", "unfaithful_forward"}
    faithful, unfaithful = findings["kernel"], findings["unfaithful_forward"]
    assert faithful.intrinsic == unfaithful.intrinsic == "_mm_cmpgt_epi64"
    assert faithful.evidence == unfaithful.evidence == Evidence.A
    assert faithful.rule_mechanism == unfaithful.rule_mechanism
    assert unfaithful.raw_name == "_reversed_cmpgt_epi64"


def test_reports_nothing_when_the_consuming_alias_dropped_the_producers_result(run_rule):
    """P1: a dropped parameter on the *consumer* side, not the producer's.

    `DROP_FIRST(a, b)` never uses `a` -- it forwards only `b` (twice) to
    `_mm_add_epi32`. Before `is_forwarding_alias` rejected this shape,
    `DROP_FIRST(cmp, x)` resolved to `_mm_add_epi32` with args `(cmp, x)` --
    the call site's own args, in macro-parameter order -- so `cmp` still
    looked consumed even though the real `_mm_add_epi32(x, x)` never
    receives it. `DROP_FIRST` must not be registered as an alias at all, so
    this call site is not recognized as an intrinsic call and there is no
    following call for P to see.
    """
    findings = [f for f in run_rule(PipelineRule(), "pipeline_positive.c") if f.function == "dropped_parameter"]
    assert findings == []


def test_abstains_when_the_consumer_call_drops_a_parameters_value(run_rule):
    """P1 round 3: the registration predicate alone is not sound.

    `DROP_VALUE(a, b)`'s body is `_mm_add_epi32(((void)(a), (b)), (b))` --
    `a` (bound to `cmp`) appears in the argument subtree, inside a
    `(void)`-cast comma operand, so a text-appearance registration check
    (what `is_forwarding_alias` uses) still confirms this as an alias: a
    comma expression's value is its *last* operand and `(void)` explicitly
    discards the other, but neither position is pruned by scanning for
    identifiers. The real fix is that P declines to read `sel`'s args at
    all once `sel`'s call was resolved through a file-local macro alias
    (`PipelineRule.match`'s `following.is_macro_alias` check) -- it does not
    matter whether registration would have accepted or rejected this shape.
    """
    findings = [f for f in run_rule(PipelineRule(), "pipeline_positive.c") if f.function == "drop_value_consumer"]
    assert findings == []


def test_abstains_when_the_consumer_call_combines_a_parameter_with_itself(run_rule):
    """P1 round 3: the `(a) ^ (a)` residual the registration predicate cannot close.

    No syntactic rule distinguishes "combined with itself losslessly" from
    "genuinely used" -- `XOR_SELF`'s `a` is confirmed as used by every
    identifier-appearance check, precisely because it does appear, just in
    a position whose combined value happens to always come out the same
    regardless of `a`. P's abstention on a macro-resolved consumer call
    (`following.is_macro_alias`) does not depend on this distinction at
    all, which is why it catches this case too.
    """
    findings = [f for f in run_rule(PipelineRule(), "pipeline_positive.c") if f.function == "xor_self_consumer"]
    assert findings == []


def test_reports_when_the_consumer_is_a_direct_simde_spelled_call(run_rule):
    """P2: `raw_name != name` is not the same as "resolved through a macro".

    `IntrinsicCall.raw_name` differs from `.name` for two distinct reasons:
    a file-local `#define` forwarding alias (`DROP_VALUE`/`XOR_SELF` above,
    where the correspondence between the macro's parameters and the
    forwarded call's operands is opaque), and a direct call under its
    `simde_`-prefixed spelling, normalized through
    `knowledge/aliases.yaml` (`simde_mm_shuffle_epi8` -> `_mm_shuffle_epi8`
    here, with the identical signature by SIMDe's own naming convention --
    no macro body, no possibility of a dropped, duplicated or discarded
    parameter). Guarding on `raw_name != name` would abstain on both
    identically; guarding on `is_macro_alias` -- which extraction sets only
    for the first kind -- correctly still reports this one. This is the
    live P2 counterexample: identical code shape to `drop_value_consumer`
    above, opposite verdict, because the provenance differs.
    """
    findings = [
        f for f in run_rule(PipelineRule(), "pipeline_positive.c") if f.function == "simde_spelled_consumer"
    ]
    assert len(findings) == 1
    assert findings[0].intrinsic == "_mm_cmpgt_epi64"
    assert findings[0].evidence is Evidence.A


def test_reports_nothing_when_an_independent_call_separates_them(run_rule):
    findings = [f for f in run_rule(PipelineRule(), "pipeline_negative.c") if f.function == "kernel"]
    assert findings == []


def test_reports_nothing_when_the_compare_result_was_overwritten(run_rule):
    # A plain reassignment is not a call, so call adjacency alone still sees
    # these two as neighbours; only a redefinition check rejects it.
    findings = [
        f for f in run_rule(PipelineRule(), "pipeline_negative.c")
        if f.function == "overwritten"
    ]
    assert findings == []


def test_reports_nothing_when_the_compare_result_was_overwritten_by_a_call(run_rule):
    # I1: the overwrite is `mask = helper_load(c)`, a call to something that
    # isn't a recognized intrinsic. Extraction must still record it as a
    # definition so this redefinition is visible here, exactly as the plain
    # variable-to-variable overwrite above already is.
    findings = [
        f for f in run_rule(PipelineRule(), "pipeline_negative.c")
        if f.function == "overwritten_by_call"
    ]
    assert findings == []
