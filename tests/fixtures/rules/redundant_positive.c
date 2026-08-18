void kernel(const int *src, const long long *src64) {
    __m128i a = _mm_loadu_si32(src);
    __m128i b = _mm_cvtsi32_si128(src[1]);
    __m128i c = _mm_loadl_epi64((const __m128i *)src64);
    __m128i d = _mm_loadu_si64(src64);
    (void)a;
    (void)b;
    (void)c;
    (void)d;
}
