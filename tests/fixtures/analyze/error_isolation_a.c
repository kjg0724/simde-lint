__m128i loads_in_a(const __m128i *p) {
    __m128i v = _mm_loadl_epi64(p);
    return v;
}
