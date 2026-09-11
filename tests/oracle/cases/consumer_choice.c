// Choosing a consumer and filtering it are different steps. A candidate the
// rule rejects must not end the search: a later one may be valid.
#include <stdint.h>

// The multiplies sit in one arm. The unpack in the other arm cannot be
// theirs -- no execution has both -- and it comes first in source order. The
// unpack that follows the `if` is on a common path with them and is an
// unambiguous round-trip.
//
// Filtering the chosen candidate instead of choosing past it ends the search
// at the arm's unpack and reports nothing.
void a_rejected_candidate_precedes_a_valid_one(int t, __m128i a, __m128i b) {
    __m128i lo = _mm_setzero_si128();
    __m128i hi = _mm_setzero_si128();
    if (t) {
        lo = _mm_mullo_epi16(a, b);
        hi = _mm_mulhi_epi16(a, b);
    } else {
        __m128i r0 = _mm_unpacklo_epi16(lo, hi);
        (void)r0;
    }
    __m128i r1 = _mm_unpacklo_epi16(lo, hi);
    (void)r1;
}
