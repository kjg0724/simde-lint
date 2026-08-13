void kernel(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_mullo_epi32(va, vb);
    prod = _mm_loadu_si128((const __m128i *)a);
    __m128i sum = _mm_add_epi32(acc, prod);
    (void)sum;
}
