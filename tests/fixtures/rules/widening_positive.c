void kernel(const short *a, const short *b) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i lo = _mm_mullo_epi16(va, vb);
    __m128i hi = _mm_mulhi_epi16(va, vb);
    __m128i wide = _mm_unpacklo_epi16(lo, hi);
    (void)wide;
}

void repeated(const short *a, const short *b) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i lo = _mm_mullo_epi16(va, vb);
    __m128i hi = _mm_mulhi_epi16(va, vb);
    __m128i wide = _mm_unpacklo_epi16(lo, hi);
    lo = _mm_mullo_epi16(va, vb);
    hi = _mm_mulhi_epi16(va, vb);
    wide = _mm_unpacklo_epi16(lo, hi);
    (void)wide;
}

void overwritten(const short *a, const short *b, const short *c) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i lo = _mm_mullo_epi16(va, vb);
    __m128i hi = _mm_mulhi_epi16(va, vb);
    lo = _mm_loadu_si128((const __m128i *)c);
    __m128i wide = _mm_unpacklo_epi16(lo, hi);
    (void)wide;
}

void same_line_decoy(const short *a, const short *b) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i lo, hi;
    // Everything below sits on one physical line so `.line` cannot order it.
    // `decoy` names `lo`/`hi` but runs before either multiply, so it cannot
    // be their consumer; `wide` runs after both and is the real one.
    __m128i decoy = _mm_unpackhi_epi16(lo, hi); lo = _mm_mullo_epi16(va, vb); hi = _mm_mulhi_epi16(va, vb); __m128i wide = _mm_unpacklo_epi16(lo, hi);
    (void)decoy; (void)wide;
}

// The high unpack rebuilds lanes 4-7, so the replacement is
// vmull_high_s16 and not the vmull_s16 the knowledge table holds. Neither
// pinned corpus contains this shape -- all 18 corpus W findings consume
// _mm_unpacklo_epi16 -- so nothing but this fixture exercises it.
void high_half(const short *a, const short *b) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i lo = _mm_mullo_epi16(va, vb);
    __m128i hi = _mm_mulhi_epi16(va, vb);
    __m128i wide = _mm_unpackhi_epi16(lo, hi);
    (void)wide;
}

// The pair sits inside a construct the consumer does not, so a pass that
// skips it still reaches the unpack and consumes whatever `lo` held. The
// round-trip is real on the taken pass, so the finding stands; the
// replacement is withdrawn because an instruction placed at the unpack runs
// on the skipping pass too.
void producer_inside_a_branch_the_consumer_is_outside(__m128i a, __m128i b, __m128i c, int flag) {
    __m128i lo = c;
    __m128i hi = c;
    if (flag) {
        lo = _mm_mullo_epi16(a, b);
        hi = _mm_mulhi_epi16(a, b);
    }
    __m128i r = _mm_unpacklo_epi16(lo, hi);
    (void)r;
}

// An input rebound between the two multiplies: the halves belong to different
// products, so one widening multiply reproduces neither.
void an_operand_rebound_between_the_multiplies(__m128i a, __m128i b, __m128i c) {
    __m128i lo = _mm_mullo_epi16(a, b);
    a = c;
    __m128i hi = _mm_mulhi_epi16(a, b);
    __m128i r = _mm_unpacklo_epi16(lo, hi);
    (void)r;
}

// Operands that are not plain variables. The pair is still the round-trip and
// the unpack still rebuilds it, but the operands are expressions rather than
// names, so their stability rests on the spelling matching rather than on a
// definition the rule can read -- grade B, which is what B is for here.
void operands_that_are_not_plain_variables(const int16_t *p, const int16_t *q) {
    __m128i lo = _mm_mullo_epi16(_mm_loadu_si128((const __m128i *)p),
                                 _mm_loadu_si128((const __m128i *)q));
    __m128i hi = _mm_mulhi_epi16(_mm_loadu_si128((const __m128i *)p),
                                 _mm_loadu_si128((const __m128i *)q));
    __m128i r = _mm_unpacklo_epi16(lo, hi);
    (void)r;
}
