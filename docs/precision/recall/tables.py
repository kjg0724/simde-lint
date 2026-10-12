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
