void kernel(const unsigned char *src) {
    __m128i data = _mm_loadu_si128((const __m128i *)src);
    __m128i out = _mm_shuffle_epi32(data, 0x1B);
    (void)out;
}
