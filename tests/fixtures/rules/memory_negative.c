void kernel(const short *src) {
    __m128i v = _mm_setzero_si128();
    v = _mm_insert_epi16(v, src[0], 0);
    v = _mm_insert_epi16(v, src[1], 1);
    (void)v;
}
