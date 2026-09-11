// A producer feeding more than one consumer. The contract's counting unit is
// the consumer in both mechanisms, so each consumer is its own finding.
#include <stdint.h>

// Rule W: the pair rebuilds all eight lanes, four per unpack. Each unpack is
// replaced by its own widening multiply — vmull_s16 low, vmull_high_s16 high.
void one_pair_feeding_both_unpacks(__m128i a, __m128i b) {
    __m128i lo = _mm_mullo_epi16(a, b);
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r0 = _mm_unpacklo_epi16(lo, hi);
    __m128i r1 = _mm_unpackhi_epi16(lo, hi);
    (void)r0; (void)r1;
}

// Rule F: one product accumulated into two different accumulators. Each add
// is its own fusion opportunity, the same way two products into one add are
// one opportunity.
void one_product_reaching_two_adds(__m128i a, __m128i b, __m128i x, __m128i y) {
    __m128i p = _mm_mullo_epi32(a, b);
    x = _mm_add_epi32(x, p);
    y = _mm_add_epi32(y, p);
    (void)x; (void)y;
}

// The pair is redefined between the two unpacks, so the second unpack does
// not carry this pair's products and is not this pair's finding.
void pair_redefined_before_the_second_unpack(__m128i a, __m128i b, __m128i c) {
    __m128i lo = _mm_mullo_epi16(a, b);
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r0 = _mm_unpacklo_epi16(lo, hi);
    lo = _mm_mullo_epi16(a, c);
    __m128i r1 = _mm_unpackhi_epi16(lo, hi);
    (void)r0; (void)r1;
}
