// The same two shapes with nothing split: both are real instances.
#include <stdint.h>

void widening_pair_in_one_region(__m128i a, __m128i b) {
    __m128i lo = _mm_mullo_epi16(a, b);
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r = _mm_unpacklo_epi16(lo, hi);
    (void)r;
}

void compare_and_consumer_in_one_region(__m128i a, __m128i b) {
    __m128i c = _mm_cmpgt_epi32(a, b);
    __m128i d = _mm_and_si128(c, a);
    (void)d;
}
