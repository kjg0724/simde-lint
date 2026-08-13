void kernel(const short *src, int stride) {
    __m128i v = _mm_setzero_si128();
    v = _mm_insert_epi16(v, src[0], 0);
    v = _mm_insert_epi16(v, src[stride], 1);
    v = _mm_insert_epi16(v, src[2 * stride], 2);
    v = _mm_insert_epi16(v, src[3 * stride], 3);
    (void)v;
}

void reused_name(const short *src, const short *other) {
    __m128i v = _mm_setzero_si128();
    v = _mm_insert_epi16(v, src[0], 0);
    v = _mm_insert_epi16(v, src[1], 1);
    v = _mm_insert_epi16(v, src[2], 2);
    v = _mm_insert_epi16(v, src[3], 3);
    (void)v;

    v = _mm_setzero_si128();
    v = _mm_insert_epi16(v, other[0], 0);
    v = _mm_insert_epi16(v, other[1], 1);
    v = _mm_insert_epi16(v, other[2], 2);
    (void)v;
}

void through_temp(const short *src) {
    __m128i v = _mm_setzero_si128();
    __m128i t = _mm_insert_epi16(v, src[0], 0);
    t = _mm_insert_epi16(t, src[1], 1);
    t = _mm_insert_epi16(t, src[2], 2);
    (void)t;
}

void strided_rows(long long m2, long long m5, int a, int b, int c, int d) {
    __m128i org = _mm_set_epi64x(m2, m5);
    __m128i idx = _mm_set_epi32(a, b, c, d);
    __m128i konst = _mm_set_epi32(0, 1, 2, 3);
    (void)org; (void)idx; (void)konst;
}

void mixed_scalars(long long m5, int a) {
    __m128i pair = _mm_set_epi64x(0, m5);
    __m128i quad = _mm_set_epi32(a, 0, a, 0);
    (void)pair; (void)quad;
}
