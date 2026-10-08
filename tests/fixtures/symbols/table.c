static const unsigned char plain_mask[16] = {0, 1, 2, 3, 4, 5, 6, 7,
                                             8, 9, 10, 11, 12, 13, 14, 15};

DECLARE_ALIGNED(16, const uint8_t, wrapped_mask[2][16]) = {
    {0, 2, 4, 6, 8, 10, 12, 14, 1, 3, 5, 7, 9, 11, 13, 15},
    {0, 1, 3, 5, 7, 9, 11, 13, 0, 2, 4, 6, 8, 10, 12, 14}};

/* The spelling SVT-AV1 uses for its shuffle tables: a registered wrapper
   and an initializer, with writable storage. */
DECLARE_ALIGNED(16, uint8_t, even_odd_mask_x[2][16]) = {
    {0, 2, 4, 6, 8, 10, 12, 14, 1, 3, 5, 7, 9, 11, 13, 15},
    {0, 1, 3, 5, 7, 9, 11, 13, 0, 2, 4, 6, 8, 10, 12, 14}};

DECLARE_ALIGNED(16, const uint8_t, sentinel_mask[1][16]) = {
    {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
     0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff}};

DECLARE_ALIGNED(16, const unsigned short, wide_mask[1][8]) = {
    {0x1000, 0, 0, 0, 0, 0, 0, 0}};

/* Registered, and never reached: see
   test_a_wrapper_taking_no_alignment_argument_is_registered_and_unreachable. */
DECLARE_ALIGNED_16(const uint8_t, unreached_mask[1][16]) = {
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}};

/* Byte-sized type, const, initialized with lane-shaped values, and an array
   of addresses rather than of bytes -- in both spellings. */
static const unsigned char *pointer_mask[16] = {0, 1, 2, 3};

DECLARE_ALIGNED(16, const uint8_t *, wrapped_pointer_mask[16]) = {0, 1, 2, 3};

UNREGISTERED_MACRO(16, const uint8_t, hidden_mask[16]) = {0, 1, 2, 3};

static const unsigned char mixed_mask[4] = {0, 1, SOME_RUNTIME_CONSTANT, 3};
