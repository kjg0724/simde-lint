static const unsigned char plain_mask[16] = {0, 1, 2, 3, 4, 5, 6, 7,
                                             8, 9, 10, 11, 12, 13, 14, 15};

DECLARE_ALIGNED(16, uint8_t, even_odd_mask_x[2][16]) = {
    {0, 2, 4, 6, 8, 10, 12, 14, 1, 3, 5, 7, 9, 11, 13, 15},
    {0, 1, 3, 5, 7, 9, 11, 13, 0, 2, 4, 6, 8, 10, 12, 14}};

DECLARE_ALIGNED(16, uint8_t, sentinel_mask[1][16]) = {
    {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
     0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff}};

UNREGISTERED_MACRO(16, uint8_t, hidden_mask[16]) = {0, 1, 2, 3};
