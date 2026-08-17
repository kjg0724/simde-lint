void kernel(__m128i a, __m128i b) {
    __m128i mask = _mm_cmpgt_epi64(a, b); __m128i sel = _mm_shuffle_epi8(mask, _mm_setr_epi8(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15));
    (void)sel;
}
