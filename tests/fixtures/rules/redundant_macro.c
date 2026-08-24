#define LOAD_PAIR(a, b) \
    _mm_unpacklo_epi64(_mm_loadl_epi64(a), _mm_loadl_epi64(b))
