void kernel(const short *a, const short *b) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i lo = _mm_mullo_epi16(va, vb);
    __m128i hi = _mm_mulhi_epi16(va, vb);
    __m128i wide = _mm_unpacklo_epi16(lo, hi);
    (void)wide;
}

void repeated(const short *a, const short *b) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i lo = _mm_mullo_epi16(va, vb);
    __m128i hi = _mm_mulhi_epi16(va, vb);
    __m128i wide = _mm_unpacklo_epi16(lo, hi);
    lo = _mm_mullo_epi16(va, vb);
    hi = _mm_mulhi_epi16(va, vb);
    wide = _mm_unpacklo_epi16(lo, hi);
    (void)wide;
}
