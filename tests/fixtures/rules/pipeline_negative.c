void kernel(__m128i a, __m128i b, __m128i c, __m128i d) {
    __m128i mask = _mm_cmpgt_epi64(a, b);
    __m128i other = _mm_add_epi32(c, d);
    __m128i sel = _mm_and_si128(other, mask);
    (void)sel;
}

void overwritten(__m128i a, __m128i b, __m128i mask2) {
    __m128i mask = _mm_cmpgt_epi64(a, b);
    mask = mask2;
    __m128i sel = _mm_and_si128(mask2, mask);
    (void)sel;
}

void overwritten_by_call(__m128i a, __m128i b, __m128i c) {
    __m128i mask = _mm_cmpgt_epi64(a, b);
    mask = helper_load(c);
    __m128i sel = _mm_and_si128(c, mask);
    (void)sel;
}

// Issue #13, shape 1: `x += cmpgt(...)` must not read as the compare's
// direct result. Without the fix, current.result_var == "x" and P reports
// this pair even though x's new value depends on its own old value too, not
// only on the compare.
void compound_assignment_not_direct_result(__m128i a, __m128i b, __m128i x, __m128i c) {
    x += _mm_cmpgt_epi64(a, b);
    __m128i sel = _mm_and_si128(x, c);
    (void)sel;
}
