// Rule M's two mechanisms.
#include <stdint.h>

// A same-target insert chain at the default threshold of three.
void insert_chain_of_three(__m128i v, int x, int y, int z) {
    v = _mm_insert_epi32(v, x, 0);
    v = _mm_insert_epi32(v, y, 1);
    v = _mm_insert_epi32(v, z, 2);
    (void)v;
}

// Two inserts is below the threshold.
void insert_chain_of_two(__m128i v, int x, int y) {
    v = _mm_insert_epi32(v, x, 0);
    v = _mm_insert_epi32(v, y, 1);
    (void)v;
}

// A vector assembled from runtime scalars.
void set_from_runtime_scalars(int a, int b, int c, int d) {
    __m128i v = _mm_set_epi32(a, b, c, d);
    (void)v;
}

// All-literal: a constant vector, not scalar assembly.
void set_from_literals(void) {
    __m128i v = _mm_set_epi32(1, 2, 3, 4);
    (void)v;
}

// One runtime value in every lane. Not all-literal, and not an assembly of
// separate scalars either: this is a broadcast, and SIMDe compiles it to a
// single `dup`. VVenC and VVdeC write it as `_mm_set_epi16(wT, ..., wT)`.
void set_from_one_repeated_scalar(int w) {
    __m128i v = _mm_set_epi32(w, w, w, w);
    (void)v;
}

// Two distinct values, so still an assembly even though one repeats. The
// exclusion above is every argument the same, not merely some.
void set_from_two_values(int a, int b) {
    __m128i v = _mm_set_epi32(a, a, a, b);
    (void)v;
}

// The 256-bit insert family. epi16 was registered and epi32/epi64 were not,
// with no difference in the mechanism: all three store a scalar into a lane.
void wide_insert_chain(__m256i v, long long x, long long y, long long z) {
    v = _mm256_insert_epi64(v, x, 0);
    v = _mm256_insert_epi64(v, y, 1);
    v = _mm256_insert_epi64(v, z, 2);
    (void)v;
}
