// _mm256_mullo_epi16 has no NEON branch in SIMDe 0.8.4: it falls through to a
// portable per-element loop carrying SIMDE_VECTORIZE. What the compiler emits
// from that loop cannot be read from the SIMDe source, so a rationale for
// this call site must not assert which machine instructions appear.
#include <stdint.h>

void portable_fallback_multiply_add(__m256i a, __m256i b, __m256i acc) {
    acc = _mm256_add_epi16(acc, _mm256_mullo_epi16(a, b));
    (void)acc;
}

// The same intrinsic against an accumulator of another width. The recorded
// instruction does not fit, and the concession about what is emitted still
// has to hold -- there is no NEON branch here either.
void portable_fallback_at_a_mismatched_width(__m256i a, __m256i b, __m256i acc) {
    acc = _mm256_add_epi32(acc, _mm256_mullo_epi16(a, b));
    (void)acc;
}
