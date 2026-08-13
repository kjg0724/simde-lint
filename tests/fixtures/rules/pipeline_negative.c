void kernel(__m128i a, __m128i b, __m128i c, __m128i d) {
    __m128i mask = _mm_cmpgt_epi64(a, b);
    __m128i other = _mm_add_epi32(c, d);
    __m128i sel = _mm_and_si128(other, mask);
    (void)sel;
}
