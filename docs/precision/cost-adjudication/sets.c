#include <stdint.h>
#include <arm_neon.h>
#include "x86/sse4.1.h"

/* M.scalar_set_build's suggestion as recorded: a vsetq_lane chain replacing
   one set_* call. Measured against the SIMDe call it would replace. */

/* --- set_epi32, four strided scalars */
simde__m128i s32_simde(const int32_t *p, int s) {
    return simde_mm_set_epi32(p[3*s], p[2*s], p[1*s], p[0*s]);
}
int32x4_t s32_vsetq(const int32_t *p, int s) {
    int32x4_t v = vdupq_n_s32(0);
    v = vsetq_lane_s32(p[0*s], v, 0);
    v = vsetq_lane_s32(p[1*s], v, 1);
    v = vsetq_lane_s32(p[2*s], v, 2);
    v = vsetq_lane_s32(p[3*s], v, 3);
    return v;
}
/* --- set_epi64x, two strided scalars */
simde__m128i s64_simde(const int64_t *p, int s) {
    return simde_mm_set_epi64x(p[1*s], p[0*s]);
}
int64x2_t s64_vsetq(const int64_t *p, int s) {
    int64x2_t v = vdupq_n_s64(0);
    v = vsetq_lane_s64(p[0*s], v, 0);
    v = vsetq_lane_s64(p[1*s], v, 1);
    return v;
}
/* --- set_epi16, eight strided scalars */
simde__m128i s16_simde(const int16_t *p, int s) {
    return simde_mm_set_epi16(p[7*s], p[6*s], p[5*s], p[4*s],
                              p[3*s], p[2*s], p[1*s], p[0*s]);
}
int16x8_t s16_vsetq(const int16_t *p, int s) {
    int16x8_t v = vdupq_n_s16(0);
    v = vsetq_lane_s16(p[0*s], v, 0);
    v = vsetq_lane_s16(p[1*s], v, 1);
    v = vsetq_lane_s16(p[2*s], v, 2);
    v = vsetq_lane_s16(p[3*s], v, 3);
    v = vsetq_lane_s16(p[4*s], v, 4);
    v = vsetq_lane_s16(p[5*s], v, 5);
    v = vsetq_lane_s16(p[6*s], v, 6);
    v = vsetq_lane_s16(p[7*s], v, 7);
    return v;
}
/* --- the same three with the scalars already in registers */
simde__m128i s32_simde_reg(int32_t a, int32_t b, int32_t c, int32_t d) {
    return simde_mm_set_epi32(d, c, b, a);
}
int32x4_t s32_vsetq_reg(int32_t a, int32_t b, int32_t c, int32_t d) {
    int32x4_t v = vdupq_n_s32(0);
    v = vsetq_lane_s32(a, v, 0);
    v = vsetq_lane_s32(b, v, 1);
    v = vsetq_lane_s32(c, v, 2);
    v = vsetq_lane_s32(d, v, 3);
    return v;
}
simde__m128i s64_simde_reg(int64_t a, int64_t b) { return simde_mm_set_epi64x(b, a); }
int64x2_t s64_vsetq_reg(int64_t a, int64_t b) {
    int64x2_t v = vdupq_n_s64(0);
    v = vsetq_lane_s64(a, v, 0);
    v = vsetq_lane_s64(b, v, 1);
    return v;
}
