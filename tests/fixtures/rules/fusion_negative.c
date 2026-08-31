void kernel(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_mullo_epi32(va, vb);
    prod = _mm_loadu_si128((const __m128i *)a);
    __m128i sum = _mm_add_epi32(acc, prod);
    (void)sum;
}

// Issue #13, shape 1: `x += mullo(...)` must not read as the multiply's
// direct result. Without the fix, mul.result_var == "x" and F reports this
// pair at Evidence A even though x's new value depends on its own old value
// too, not only on the multiply.
void compound_assignment_not_direct_result(__m128i a, __m128i b, __m128i x, __m128i c) {
    x += _mm_mullo_epi32(a, b);
    __m128i sum = _mm_add_epi32(x, c);
    (void)sum;
}

// Issue #13, shape 2: the compound write must still register as a
// redefinition of x, or F links the first multiply through a value the
// second, compound-assigned multiply actually overwrote. The second
// multiply's own right-hand side is deliberately a recognized call, not a
// plain variable: a fix that only stops result_var from naming "x" without
// also keeping `_record_plain_assignments` from skipping this line would
// drop the write's definition entirely, silently trading this false
// positive for a different one -- the first multiply reporting Evidence A
// unopposed, because redefined_between would no longer see any write to x
// between it and the add.
void compound_assignment_overwrites_result(
    __m128i a, __m128i b, __m128i other_a, __m128i other_b, __m128i c
) {
    __m128i x = _mm_mullo_epi32(a, b);
    x += _mm_mullo_epi32(other_a, other_b);
    __m128i sum = _mm_add_epi32(x, c);
    (void)sum;
}
