"""The frozen name tables `docs/precision/grammar.md` declares.

Transcribed by hand from the rules' published descriptions, not read from
`simde_lint`. An enumerator built over the grammar imports these and nothing
from the tool: if the tool registers a new family these do not move until the
grammar is edited, and that edit says which published figure it invalidates.

Checked against the grammar by `tests/test_recall_tables.py`, which compares
this module with the markdown rather than with the tool -- the two have to
agree with each other, and neither is allowed to agree with `simde_lint` by
construction.
"""

F_MULTIPLIES = frozenset({
    "_mm_mullo_epi16", "_mm_mullo_epi32", "_mm_madd_epi16", "_mm_mul_epi32",
    "_mm_mul_ps",
    "_mm256_mullo_epi16", "_mm256_mullo_epi32", "_mm256_madd_epi16",
    "_mm256_mul_epi32", "_mm256_mul_ps",
})
F_ADDS = frozenset({
    "_mm_add_epi16", "_mm_add_epi32", "_mm_add_epi64", "_mm_add_ps",
    "_mm256_add_epi16", "_mm256_add_epi32", "_mm256_add_epi64", "_mm256_add_ps",
})
F_WIDENING = frozenset({
    "_mm_cvtepi16_epi32", "_mm_cvtepi32_epi64",
    "_mm256_cvtepi16_epi32", "_mm256_cvtepi32_epi64",
})

W_PRODUCER = "_mm_mullo_epi16"
W_PARTNER = "_mm_mulhi_epi16"
W_CONSUMERS = frozenset({"_mm_unpacklo_epi16", "_mm_unpackhi_epi16"})

M_INSERTS = frozenset({
    "_mm_insert_epi16", "_mm_insert_epi32", "_mm_insert_epi64",
    "_mm256_insert_epi16", "_mm256_insert_epi32", "_mm256_insert_epi64",
})

P_COMPARES = frozenset({
    "_mm_cmpeq_epi32", "_mm_cmpeq_epi64",
    "_mm_cmpgt_epi8", "_mm_cmpgt_epi16", "_mm_cmpgt_epi32", "_mm_cmpgt_epi64",
    "_mm256_cmpgt_epi32", "_mm256_cmpgt_epi64",
})

# Rule S's and rule R's families, transcribed for completeness. Nothing here
# orders over them: `recognized` below is a prefix test, not a union.
S_SHUFFLES = frozenset({"_mm_shuffle_epi8", "_mm256_shuffle_epi8"})
R_PARTIAL_LOADS = frozenset({
    "_mm_loadu_si32", "_mm_loadu_si64", "_mm_loadl_epi64",
    "_mm_cvtsi32_si128", "_mm_cvtsi64_si128",
})

#: Rule P orders over every recognized call, and its own notion of one is
#: every intrinsic call rather than every call in a registered family. A
#: narrower set would make the enumeration diverge from the rule by
#: construction: `_mm_blendv_epi8` consumes a compare in VVenC and belongs to
#: no family, so calling it unrecognized would exclude a relation the rule
#: reports. The test is a prefix on the spelling, which reads no table.
_INTRINSIC_PREFIXES = ("_mm_", "_mm256_", "_mm512_")


def recognized(name: str) -> bool:
    return name.startswith(_INTRINSIC_PREFIXES)

# The rule's documented default, taken as a constant. Reading the tool's
# configuration for it would make the enumerator agree with the tool by
# construction on the one number that decides whether a run is a finding.
M_THRESHOLD = 3

#: Calls that cannot mutate an argument, because every vector parameter of
#: every name here is passed by value. That is fixed by the x86 intrinsic
#: signatures, not inferred from any corpus.
#:
#: This list exists for clause 4 and nothing else. It happens to hold the same
#: names as the family tables, and it is kept separate on purpose: the
#: families answer "is this an anchor or a consumer", and relying on them for
#: a by-value guarantee would give a table maintained for one question a
#: second meaning nobody checks when it changes.
#:
#: Why it is needed, measured: VVdeC writes the eight-lane rebuild as a
#: `mullo`/`mulhi` pair feeding `unpacklo` and then `unpackhi`. The rule's
#: unit is one consuming unpack, so that is two findings, and without this
#: list the second was excluded every time -- the `unpacklo` on the line
#: between passes the binding to a call, and clause 4 excludes rather than
#: deciding whether the call mutates it. Nine of W's thirty prospective
#: relations on the holdout, all of them the high half of a rebuild.
BY_VALUE = frozenset(
    F_MULTIPLIES | F_ADDS | F_WIDENING | {W_PRODUCER, W_PARTNER}
    | W_CONSUMERS | M_INSERTS | P_COMPARES | S_SHUFFLES | R_PARTIAL_LOADS
)
