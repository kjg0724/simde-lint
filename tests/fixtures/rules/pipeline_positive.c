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

// P1: DROP_FIRST's body drops its own first parameter -- it forwards only
// `b` (twice) to _mm_add_epi32, never `a`. If this were still registered as
// an alias, the call site's own args (cmp, x) -- built from the macro's
// parameter positions, since nothing maps the body's argument expressions
// back to the file -- would attach `cmp` to the resolved call even though
// the real _mm_add_epi32(x, x) never receives it, and P would report a
// false compare-consumed-by-next-call finding on a call that never
// happened. `is_forwarding_alias` must refuse to register DROP_FIRST at
// all, so this call site is not recognized as an intrinsic call and P has
// no following call to see.
#define DROP_FIRST(a, b) _mm_add_epi32((b), (b))

void dropped_parameter(__m128i x, __m128i y) {
    __m128i cmp = _mm_cmpgt_epi64(x, y);
    __m128i sel = DROP_FIRST(cmp, x);
    (void)sel;
}
