#ifdef USE_VARIANT_A
#define UNPACKX(a, b) \
    _mm_unpacklo_epi64(_mm_loadl_epi64(a), _mm_loadl_epi64(b))
#else
#define UNPACKX(a, b) \
    _mm_unpackhi_epi64(_mm_loadl_epi64(a), _mm_loadl_epi64(b))
#endif
