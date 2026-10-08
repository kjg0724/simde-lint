#include <stdint.h>
#include <arm_neon.h>
#include "x86/sse4.1.h"

/* ---- insert_epi32: four lanes, scalars strided in memory (rule M's shape) */
simde__m128i i32_simde_mem(simde__m128i v, const int32_t *p, int s) {
    v = simde_mm_insert_epi32(v, p[0*s], 0);
    v = simde_mm_insert_epi32(v, p[1*s], 1);
    v = simde_mm_insert_epi32(v, p[2*s], 2);
    v = simde_mm_insert_epi32(v, p[3*s], 3);
    return v;
}
int32x4_t i32_native_mem(int32x4_t v, const int32_t *p, int s) {
    v = vld1q_lane_s32(p + 0*s, v, 0);
    v = vld1q_lane_s32(p + 1*s, v, 1);
    v = vld1q_lane_s32(p + 2*s, v, 2);
    v = vld1q_lane_s32(p + 3*s, v, 3);
    return v;
}
/* ---- insert_epi32: scalars already in registers */
simde__m128i i32_simde_reg(simde__m128i v, int32_t a, int32_t b, int32_t c, int32_t d) {
    v = simde_mm_insert_epi32(v, a, 0);
    v = simde_mm_insert_epi32(v, b, 1);
    v = simde_mm_insert_epi32(v, c, 2);
    v = simde_mm_insert_epi32(v, d, 3);
    return v;
}
/* ---- a partial chain: two lanes only, the rest of v preserved */
simde__m128i i32_simde_partial(simde__m128i v, const int32_t *p, int s) {
    v = simde_mm_insert_epi32(v, p[0*s], 0);
    v = simde_mm_insert_epi32(v, p[1*s], 1);
    return v;
}
int32x4_t i32_native_partial(int32x4_t v, const int32_t *p, int s) {
    v = vld1q_lane_s32(p + 0*s, v, 0);
    v = vld1q_lane_s32(p + 1*s, v, 1);
    return v;
}
/* ---- insert_epi16 */
simde__m128i i16_simde_mem(simde__m128i v, const int16_t *p, int s) {
    v = simde_mm_insert_epi16(v, p[0*s], 0);
    v = simde_mm_insert_epi16(v, p[1*s], 1);
    return v;
}
int16x8_t i16_native_mem(int16x8_t v, const int16_t *p, int s) {
    v = vld1q_lane_s16(p + 0*s, v, 0);
    v = vld1q_lane_s16(p + 1*s, v, 1);
    return v;
}
/* ---- insert_epi64 (recorded unknown, but has a NEON branch) */
simde__m128i i64_simde_mem(simde__m128i v, const int64_t *p, int s) {
    v = simde_mm_insert_epi64(v, p[0*s], 0);
    v = simde_mm_insert_epi64(v, p[1*s], 1);
    return v;
}
int64x2_t i64_native_mem(int64x2_t v, const int64_t *p, int s) {
    v = vld1q_lane_s64(p + 0*s, v, 0);
    v = vld1q_lane_s64(p + 1*s, v, 1);
    return v;
}
/* ---- set_epi32: four strided scalars, vs a lane-load build */
simde__m128i set32_simde_mem(const int32_t *p, int s) {
    return simde_mm_set_epi32(p[3*s], p[2*s], p[1*s], p[0*s]);
}
int32x4_t set32_native_mem(const int32_t *p, int s) {
    int32x4_t v = vdupq_n_s32(0);
    v = vld1q_lane_s32(p + 0*s, v, 0);
    v = vld1q_lane_s32(p + 1*s, v, 1);
    v = vld1q_lane_s32(p + 2*s, v, 2);
    v = vld1q_lane_s32(p + 3*s, v, 3);
    return v;
}
/* ---- set_epi32 from registers */
simde__m128i set32_simde_reg(int32_t a, int32_t b, int32_t c, int32_t d) {
    return simde_mm_set_epi32(d, c, b, a);
}
