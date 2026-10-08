// Rule S grades on the mask bytes a shuffle actually reads. Three shapes make
// an initializer look like those bytes and are not them. Every verdict here
// was decided by compiling the call and the instruction the rule proposes and
// comparing lanes: pshufb reads index 16 as lane 0 and returns the source
// byte, unguarded tbl returns zero.

// Written after it is initialized, so the initializer is not the value.
alignas(16) unsigned char written_after_init[16] = {0};
void the_mask_is_written_after_it_is_initialized(__m128i a) {
    written_after_init[0] = 16;
    __m128i r = _mm_shuffle_epi8(a, *(__m128i*)written_after_init);
    (void)r;
}

// Elements wider than a byte. 0x1000 occupies two bytes, so lane 1 holds 0x10
// on a little-endian target; reading the element value as one lane called an
// unsafe mask safe.
alignas(16) const unsigned short wide_elements[8] = {0x1000, 0, 0, 0, 0, 0, 0, 0};
void the_elements_are_wider_than_a_byte(__m128i a) {
    __m128i r = _mm_shuffle_epi8(a, *(__m128i*)wide_elements);
    (void)r;
}

// The table is inside arithmetic, so the operand is a value computed from it
// rather than the table. With every bias lane 16 every index is out of range.
alignas(16) const unsigned char inside_arithmetic[16] = {0};
void the_table_is_inside_an_expression(__m128i a, __m128i bias) {
    __m128i r = _mm_shuffle_epi8(a, bias ^ *(__m128i*)inside_arithmetic);
    (void)r;
}

// The control: const, byte-sized, a plain load, every lane in [0,15].
alignas(16) const unsigned char all_lanes_in_range[16] =
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15};
void a_table_the_rule_can_establish(__m128i a) {
    __m128i r = _mm_shuffle_epi8(a, *(__m128i*)all_lanes_in_range);
    (void)r;
}
