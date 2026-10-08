#include <stdint.h>
#include <arm_neon.h>
#include "x86/sse4.1.h"

/* The shape VVenC and VVdeC actually write: one scalar, already in a
   register, repeated across every lane. IntraPredX86.h:588 is
   _mm_set_epi16(wT,wT,wT,wT,wT,wT,wT,wT). */
simde__m128i bcast16_simde(int16_t w) {
    return simde_mm_set_epi16(w, w, w, w, w, w, w, w);
}
int16x8_t bcast16_vdup(int16_t w) { return vdupq_n_s16(w); }
int16x8_t bcast16_vsetq(int16_t w) {           /* the recorded suggestion */
    int16x8_t v = vdupq_n_s16(0);
    v = vsetq_lane_s16(w, v, 0); v = vsetq_lane_s16(w, v, 1);
    v = vsetq_lane_s16(w, v, 2); v = vsetq_lane_s16(w, v, 3);
    v = vsetq_lane_s16(w, v, 4); v = vsetq_lane_s16(w, v, 5);
    v = vsetq_lane_s16(w, v, 6); v = vsetq_lane_s16(w, v, 7);
    return v;
}
simde__m128i bcast32_simde(int32_t o) { return simde_mm_set_epi32(o, o, o, o); }
int32x4_t bcast32_vdup(int32_t o) { return vdupq_n_s32(o); }

/* av1_quantize_sse4_1.c:435 -- three lanes one value, one lane another. */
simde__m128i mostly32_simde(int32_t r1, int32_t r0) {
    return simde_mm_set_epi32(r1, r1, r1, r0);
}
int32x4_t mostly32_vdup_set(int32_t r1, int32_t r0) {
    return vsetq_lane_s32(r0, vdupq_n_s32(r1), 0);
}
/* blend_a64_mask_avx2.c:1007 -- two u64 loads, one strided. */
simde__m128i two64_simde(const uint8_t *m, int stride) {
    return simde_mm_set_epi64x(*(const int64_t *)(m + stride), *(const int64_t *)m);
}
int64x2_t two64_vld_lane(const uint8_t *m, int stride) {
    int64x2_t v = vdupq_n_s64(0);
    v = vld1q_lane_s64((const int64_t *)m, v, 0);
    v = vld1q_lane_s64((const int64_t *)(m + stride), v, 1);
    return v;
}
