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
