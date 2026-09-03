// Regions a chain may not cross. Threshold is 3 throughout.

// 1. Braced if/else, two inserts per arm: exclusive, neither arm qualifies.
void braced_branches(__m128i d, short v, int t) {
    if (t) {
        d = _mm_insert_epi16(d, v, 0);
        d = _mm_insert_epi16(d, v, 1);
    } else {
        d = _mm_insert_epi16(d, v, 2);
        d = _mm_insert_epi16(d, v, 3);
    }
    (void)d;
}

// 2. Unbraced if/else: one statement per arm, so the arm is its own region.
void unbraced_branches(__m128i d, short v, int t) {
    if (t)
        d = _mm_insert_epi16(d, v, 0);
    else
        d = _mm_insert_epi16(d, v, 1);
    d = _mm_insert_epi16(d, v, 2);
    (void)d;
}

// 3. Switch arms share one enclosing block but are separate regions.
void switch_arms(__m128i d, short v, int t) {
    switch (t) {
    case 0:
        d = _mm_insert_epi16(d, v, 0);
        d = _mm_insert_epi16(d, v, 1);
        break;
    case 1:
        d = _mm_insert_epi16(d, v, 2);
        d = _mm_insert_epi16(d, v, 3);
        break;
    }
    (void)d;
}

// 4. Outer run then a loop body: two regions, each qualifying on its own.
void outer_then_loop(__m128i d, short v, int n) {
    d = _mm_insert_epi16(d, v, 0);
    d = _mm_insert_epi16(d, v, 1);
    d = _mm_insert_epi16(d, v, 2);
    while (n--) {
        d = _mm_insert_epi16(d, v, 3);
        d = _mm_insert_epi16(d, v, 4);
        d = _mm_insert_epi16(d, v, 5);
    }
    (void)d;
}

// 5. A loop body alone still reports: its own region qualifies.
void loop_body_only(__m128i d, short v, int n) {
    while (n--) {
        d = _mm_insert_epi16(d, v, 0);
        d = _mm_insert_epi16(d, v, 1);
        d = _mm_insert_epi16(d, v, 2);
    }
    (void)d;
}

// 6. Two sequences in one region with nothing between them: still one chain.
void same_region_twice(__m128i d, short v) {
    d = _mm_insert_epi16(d, v, 0);
    d = _mm_insert_epi16(d, v, 1);
    d = _mm_insert_epi16(d, v, 2);
    d = _mm_insert_epi16(d, v, 3);
    (void)d;
}

// 7. A bare nested block is its own region: the outer two do not chain into
//    the inner three, and only the inner run reaches the threshold.
void nested_block(__m128i d, short v) {
    d = _mm_insert_epi16(d, v, 0);
    d = _mm_insert_epi16(d, v, 1);
    {
        d = _mm_insert_epi16(d, v, 2);
        d = _mm_insert_epi16(d, v, 3);
        d = _mm_insert_epi16(d, v, 4);
    }
    (void)d;
}

// 8. A macro body must behave exactly as the same code in a function does.
//    `control_region` is a node id in the synthetic reparse there, so this is
//    what says that comparing two of them within one unit still works.
#define BUILD_IN_MACRO(dst, val) \
    dst = _mm_insert_epi16(dst, val, 0); \
    dst = _mm_insert_epi16(dst, val, 1); \
    dst = _mm_insert_epi16(dst, val, 2);
