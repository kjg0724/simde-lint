// Rule R matches calls to the intrinsics registered in redundant.yaml. It
// never inspects the consumer, so every call is a finding and the grade is
// always C.
#include <stdint.h>

void registered_partial_loads(const void *p) {
    __m128i a = _mm_loadu_si32(p);
    __m128i b = _mm_loadl_epi64((const __m128i *)p);
    (void)a; (void)b;
}

// A full-width load has no zero-init to be redundant: nothing to report.
void full_width_load(const void *p) {
    __m128i a = _mm_loadu_si128((const __m128i *)p);
    (void)a;
}
