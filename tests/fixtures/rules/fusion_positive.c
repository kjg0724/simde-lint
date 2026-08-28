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

// The widening hop on an intrinsic whose fused form is established. madd's
// hop in `kernel` now caps at C because no AArch64 fused form is known for
// it, so grade B needs a case where the transform is not in doubt.
void widening_known_cost(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_mullo_epi32(va, vb);
    __m128i wide = _mm_cvtepi32_epi64(prod);
    __m128i sum = _mm_add_epi64(acc, wide);
    (void)sum;
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

// P1: DROP_FIRST_MUL's body drops its own first parameter -- it forwards
// only `b` (twice) to _mm_add_epi32, never `a`. If this were still
// registered as an alias, the call site's own args (prod, acc) would attach
// `prod` to the resolved call even though the real _mm_add_epi32(acc, acc)
// never receives it, and F would report a false multiply-reaches-add
// finding on a call that never happened. `is_forwarding_alias` must refuse
// to register DROP_FIRST_MUL at all.
#define DROP_FIRST_MUL(a, b) _mm_add_epi32((b), (b))

void dropped_parameter(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_mullo_epi32(va, vb);
    __m128i sum = DROP_FIRST_MUL(prod, acc);
    (void)sum;
}

// P1 round 3: the registration predicate is a text-appearance search, not a
// value-flow analysis, and is known-unsound -- `a` (bound to `prod`)
// appears in this body's argument subtree even though its value never
// reaches _mm_add_epi32: a comma expression's value is its last operand,
// and (void) explicitly discards the first. DROP_VALUE_MUL is therefore
// still CONFIRMED as an alias, so this must be caught by F declining to
// read a consumer call's args at all once that call carries a raw_name,
// not by registration.
#define DROP_VALUE_MUL(a, b) _mm_add_epi32(((void)(a), (b)), (b))

void drop_value_consumer(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_mullo_epi32(va, vb);
    __m128i sum = DROP_VALUE_MUL(prod, acc);
    (void)sum;
}

// P1 round 3: no syntactic rule distinguishes "combined with itself
// losslessly" from "genuinely used" -- (a) ^ (a) still reads as using `a`,
// so this is confirmed as an alias too, by design left uncaught at
// registration. F must still abstain here for the same reason as
// DROP_VALUE_MUL: the consumer call carries a raw_name.
#define XOR_SELF_MUL(a, b) _mm_add_epi32((a) ^ (a), (b))

void xor_self_consumer(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_mullo_epi32(va, vb);
    __m128i sum = XOR_SELF_MUL(prod, acc);
    (void)sum;
}

// P2: `simde_mm_add_epi32` changes spelling on resolution (raw_name !=
// name, exactly like DROP_FIRST_MUL/DROP_VALUE_MUL/XOR_SELF_MUL above), but
// NOT through a macro -- it is a direct call whose canonical spelling
// knowledge/aliases.yaml normalizes, with the identical signature to
// `_mm_add_epi32` by SIMDe's own naming convention. F must still fire
// here: is_macro_alias is False for this call site.
void simde_spelled_consumer(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i prod = _mm_mullo_epi32(va, vb);
    __m128i sum = simde_mm_add_epi32(acc, prod);
    (void)sum;
}

// P2: the widening-hop guard (fusion.py:125) must apply the same
// provenance distinction as the direct add path above, not `raw_name !=
// name`. WRAP_WIDEN is a real file-local macro alias for
// _mm_cvtepi32_epi64 -- faithful or not does not matter, since the
// abstention is unconditional on any macro-resolved consumer -- so F must
// not claim the widening path through it.
#define WRAP_WIDEN(a) _mm_cvtepi32_epi64(a)

void widening_wrapper_intermediate(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i pair = _mm_madd_epi16(va, vb);
    __m128i wide = WRAP_WIDEN(pair);
    __m128i sum = _mm_add_epi64(acc, wide);
    (void)sum;
}

// P2: `simde_mm_cvtepi32_epi64` changes spelling on resolution but NOT
// through a macro. F must still claim the widening path here.
void widening_simde_intermediate(const int *a, const int *b, __m128i acc) {
    __m128i va = _mm_loadu_si128((const __m128i *)a);
    __m128i vb = _mm_loadu_si128((const __m128i *)b);
    __m128i pair = _mm_madd_epi16(va, vb);
    __m128i wide = simde_mm_cvtepi32_epi64(pair);
    __m128i sum = _mm_add_epi64(acc, wide);
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
