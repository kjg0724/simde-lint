void kernel(const int *src) {
    __m128i a = _mm_loadu_si32(src);
    __m128i b = _mm_cvtsi32_si128(src[1]);
    (void)a;
    (void)b;
}
