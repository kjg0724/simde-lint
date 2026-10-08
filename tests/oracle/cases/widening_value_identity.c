// Rule W establishes a round-trip, and a round-trip is a claim about values,
// not about spelling. Each function below is spelled like the positive case
// and is not one. Every verdict here was decided by compiling the function
// and its proposed replacement against SIMDe 0.8.4 and comparing lanes, not
// by reading what the tool reports.

// The unpack takes the halves in the wrong order, so it does not rebuild the
// product: with every lane a=2, b=3 the source yields 0x00060000 where
// vmull_s16 yields 0x00000006.
void halves_in_the_wrong_order(__m128i a, __m128i b) {
    __m128i lo = _mm_mullo_epi16(a, b);
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r = _mm_unpacklo_epi16(hi, lo);
    (void)r;
}

// The same reversal hidden behind a file-local macro. The recorded arguments
// are the call site's own, in the order the ordering check wants, while the
// body swaps them -- which is why `docs/mechanisms.md` abstains on a
// macro-resolved consumer.
#define REVERSED_UNPACKLO(x, y) _mm_unpacklo_epi16((y), (x))
void the_reversal_behind_a_macro(__m128i a, __m128i b) {
    __m128i lo = _mm_mullo_epi16(a, b);
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r = REVERSED_UNPACKLO(lo, hi);
    (void)r;
}

// An input is rebound between the two multiplies, so the halves are halves of
// two different products. With a=2, b=3, c=32767 the source yields 65542;
// vmull_s16 yields 6 on the old inputs and 98301 on the new ones.
void an_input_rebound_between_the_multiplies(__m128i a, __m128i b, __m128i c) {
    __m128i lo = _mm_mullo_epi16(a, b);
    a = c;
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r = _mm_unpacklo_epi16(lo, hi);
    (void)r;
}

// The control: same shape, halves in order, operands untouched.
void the_round_trip_itself(__m128i a, __m128i b) {
    __m128i lo = _mm_mullo_epi16(a, b);
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r = _mm_unpacklo_epi16(lo, hi);
    (void)r;
}
