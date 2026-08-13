#define _my_cmpgt_epi64(a, b) _mm_cmpgt_epi64(a, b)

void kernel(__m128i a, __m128i b, __m128i c) {
    __m128i mask = _my_cmpgt_epi64(a, b);
    __m128i sel = _mm_and_si128(c, mask);
    (void)sel;
}
