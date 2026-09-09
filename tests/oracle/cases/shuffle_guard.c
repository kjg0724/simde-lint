// Rule S grades on whether the shuffle mask's lanes are known to be safe.
#include <stdint.h>

// Every lane is a literal index inside 0..15, so the mask is fully known and
// entirely within the range where pshufb and tbl agree.
void mask_wholly_in_range(__m128i data) {
    __m128i mask = _mm_setr_epi8(0, 1, 2, 3, 4, 5, 6, 7,
                                 8, 9, 10, 11, 12, 13, 14, 15);
    __m128i r = _mm_shuffle_epi8(data, mask);
    (void)r;
}

// The mask arrives at runtime, so no lane can be read from the source.
void mask_from_memory(__m128i data, const void *p) {
    __m128i mask = _mm_loadu_si128((const __m128i *)p);
    __m128i r = _mm_shuffle_epi8(data, mask);
    (void)r;
}
