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
