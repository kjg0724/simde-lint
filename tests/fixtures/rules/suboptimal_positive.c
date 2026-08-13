DECLARE_ALIGNED(16, uint8_t, table_mask[2][16]) = {
    {0, 2, 4, 6, 8, 10, 12, 14, 1, 3, 5, 7, 9, 11, 13, 15},
    {0, 1, 3, 5, 7, 9, 11, 13, 0, 2, 4, 6, 8, 10, 12, 14}};

void kernel(const unsigned char *src, int shift) {
    __m128i data = _mm_loadu_si128((const __m128i *)src);
    __m128i inline_mask = _mm_shuffle_epi8(
        data, _mm_setr_epi8(0, 0, 1, 1, 2, 2, 3, 3, -1, -1, -1, -1, -1, -1, -1, -1));
    const __m128i local_mask = _mm_setr_epi8(0, 4, 8, 12, -1, -1, -1, -1,
                                             -1, -1, -1, -1, -1, -1, -1, -1);
    __m128i via_local = _mm_shuffle_epi8(data, local_mask);
    __m128i derived = _mm_add_epi8(
        data, _mm_setr_epi8(0, 0, 0, 0, 4, 4, 4, 4, 8, 8, 8, 8, 12, 12, 12, 12));
    __m128i blended = _mm_blendv_epi8(derived, data, data);
    __m128i via_two_hops = _mm_shuffle_epi8(data, blended);
    __m128i via_derived = _mm_shuffle_epi8(data, derived);
    __m128i via_table = _mm_shuffle_epi8(data, *(__m128i *)table_mask[shift]);
    __m128i via_runtime = _mm_shuffle_epi8(data, _mm_loadu_si128((const __m128i *)src));
    (void)inline_mask; (void)via_local; (void)via_two_hops; (void)via_derived;
    (void)via_table; (void)via_runtime; (void)blended;
}
