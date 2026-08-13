void kernel(const int *src) {
    __m128i a = _mm_loadu_si128((const __m128i *)src);
    (void)a;
}
