// Rule F's spellings. The mechanism is one multiply reaching one add; how the
// product is written should not change whether it is found.
#include <stdint.h>

void product_bound_to_a_name(__m128i a, __m128i b, __m128i acc) {
    __m128i p = _mm_mullo_epi32(a, b);
    acc = _mm_add_epi32(acc, p);
    (void)acc;
}

void product_written_as_the_operand(__m128i a, __m128i b, __m128i acc) {
    acc = _mm_add_epi32(acc, _mm_mullo_epi32(a, b));
    (void)acc;
}

// One add is one fusion opportunity, however many products reach it.
void two_products_one_add(__m128i a, __m128i b, __m128i c, __m128i d) {
    __m128i s = _mm_add_epi32(_mm_mullo_epi32(a, b), _mm_mullo_epi32(c, d));
    (void)s;
}

// The product is never added: a multiply on its own is not a fusion miss.
void multiply_with_no_add(__m128i a, __m128i b) {
    __m128i p = _mm_mullo_epi32(a, b);
    (void)p;
}

// Float. The fused form exists and is not an exact substitution.
void float_multiply_add(__m128 a, __m128 b, __m128 acc) {
    acc = _mm_add_ps(acc, _mm_mul_ps(a, b));
    (void)acc;
}
