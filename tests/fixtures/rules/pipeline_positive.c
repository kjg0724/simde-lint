#define _my_cmpgt_epi64(a, b) _mm_cmpgt_epi64(a, b)
// Unfaithful forward: the macro's own parameter order does not match the
// order the aliased call records at the call site (C1 invariance case) --
// the call site's args are (a, b) in macro-parameter order, but the body
// hands them to the real intrinsic reversed. P must reach the same verdict
// as `kernel` below regardless, because it never reads this call's own args.
#define _reversed_cmpgt_epi64(a, b) _mm_cmpgt_epi64(b, a)

void kernel(__m128i a, __m128i b, __m128i c) {
    __m128i mask = _my_cmpgt_epi64(a, b);
    __m128i sel = _mm_and_si128(c, mask);
    (void)sel;
}

void unfaithful_forward(__m128i a, __m128i b, __m128i c) {
    __m128i mask = _reversed_cmpgt_epi64(a, b);
    __m128i sel = _mm_and_si128(c, mask);
    (void)sel;
}
