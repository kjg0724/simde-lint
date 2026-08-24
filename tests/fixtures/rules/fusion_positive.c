void kernel(const int *a, const int *b, __m128i acc, __m256i acc256) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_mullo_epi32(va, vb);
    __m128i sum = _mm_add_epi32(acc, prod);

    __m128i pair = _mm_madd_epi16(va, vb);
    __m128i wide = _mm_cvtepi32_epi64(pair);
    __m128i sum64 = _mm_add_epi64(acc, wide);

    __m256i big = _mm256_madd_epi16(acc256, acc256);
    __m256i sum256 = _mm256_add_epi32(acc256, big);
    (void)sum; (void)sum64; (void)sum256;
}

void two_products(const int *a, const int *b) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i p1 = _mm_mullo_epi32(va, vb);
    __m128i p2 = _mm_mullo_epi32(vb, va);
    __m128i sum = _mm_add_epi32(p1, p2);
    (void)sum;
}

// C1 invariance case: the macro forwards its operands to the real
// intrinsic in the opposite order from how the call site wrote them. F must
// reach the same verdict as `kernel`'s first multiply regardless, because it
// never reads the multiply's own args -- only `mul.result_var` membership in
// the following add's args.
#define _my_mullo_epi32(a, b) _mm_mullo_epi32(b, a)

void unfaithful_forward(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _my_mullo_epi32(va, vb);
    __m128i sum = _mm_add_epi32(acc, prod);
    (void)sum;
}

void reused_name(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_madd_epi16(va, vb);
    __m128i wide = _mm_cvtepi32_epi64(prod);
    prod = _mm_madd_epi16(vb, va);
    __m128i sum = _mm_add_epi64(acc, wide);
    (void)sum;
}
