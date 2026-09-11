// The widening hop, and the one shuffle mask that is known and still unsafe.
#include <stdint.h>

// A product reaching its add through one widening conversion. Grade B: the
// path is resolved, one step less directly than a named product handed
// straight to the add.
void product_through_a_widening_hop(__m128i a, __m128i b, __m128i acc) {
    __m128i p = _mm_mullo_epi32(a, b);
    __m128i wide = _mm_cvtepi16_epi32(p);
    acc = _mm_add_epi32(acc, wide);
    (void)acc;
}

// Every mask lane is a literal written at the call, so nothing is unresolved
// — and lane 15 is 0x20, inside the [16,127] middle range where pshufb zeroes
// and tbl does not. The guard the rule reports is load-bearing, which is a
// different answer from "the mask could not be read".
//
// 0x80 would not do: a high bit means zeroing on both sides, so that lane is
// safe. The unsafe values are the middle ones.
void mask_known_and_out_of_range(__m128i data) {
    __m128i r = _mm_shuffle_epi8(
        data,
        _mm_setr_epi8(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 0x20));
    (void)r;
}
