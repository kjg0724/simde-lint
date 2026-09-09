// Two multiplies of the widening round-trip shape, and a compare with its
// consumer, each split across arms of an `if` that cannot both execute.
#include <stdint.h>

void widening_pair_split_across_arms(int t, __m128i a, __m128i b) {
    __m128i lo = _mm_setzero_si128();
    __m128i hi = _mm_setzero_si128();
    if (t)
        lo = _mm_mullo_epi16(a, b);
    else
        hi = _mm_mulhi_epi16(a, b);
    __m128i r = _mm_unpacklo_epi16(lo, hi);
    (void)r;
}

void compare_and_consumer_split_across_arms(int t, __m128i a, __m128i b) {
    __m128i c = _mm_setzero_si128();
    if (t)
        c = _mm_cmpgt_epi32(a, b);
    else
        c = _mm_and_si128(c, a);
    (void)c;
}
