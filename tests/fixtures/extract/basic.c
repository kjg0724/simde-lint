#define _my_cmpgt_epi64(a, b) _mm_cmpgt_epi64(a, b)

static const unsigned char file_mask[16] = {0, 1, 2, 3, 4, 5, 6, 7,
                                            8, 9, 10, 11, 12, 13, 14, 15};

void kernel(const short *src, int stride) {
    __m128i shuf = _mm_setr_epi8(0, 0, 1, 1, 2, 2, 3, 3, -1, -1, -1, -1, -1, -1, -1, -1);
    __m128i data = _mm_loadu_si32(src);
    __m128i out = _mm_shuffle_epi8(data, shuf);
    __m128i cmp = _my_cmpgt_epi64(out, data);
    __m128i sel = _mm_and_si128(cmp, out);
    out = _mm_shuffle_epi8(data, _mm_setr_epi8(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15));
}
