// Nesting is not exclusivity. In each of these the producer and the consumer
// sit in different innermost regions, and on any path where the inner one
// runs, both run.
#include <stdint.h>

void consumer_nested_below_the_producer(int t, __m128i a, __m128i b, __m128i acc) {
    __m128i p = _mm_mullo_epi32(a, b);
    if (t) {
        acc = _mm_add_epi32(acc, p);
    }
    (void)acc;
}

void producer_nested_below_the_consumer(int t, __m128i a, __m128i b, __m128i acc) {
    __m128i p = _mm_setzero_si128();
    if (t) {
        p = _mm_mullo_epi32(a, b);
    }
    acc = _mm_add_epi32(acc, p);
    (void)acc;
}

void widening_consumer_nested(int t, __m128i a, __m128i b) {
    __m128i lo = _mm_mullo_epi16(a, b);
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r = _mm_setzero_si128();
    if (t) {
        r = _mm_unpacklo_epi16(lo, hi);
    }
    (void)r;
}
