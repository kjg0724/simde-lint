# Adjudicating rule M's instruction counts

Issue #74 asked whether rule M's recorded per-element counts hold against the
SIMDe source. They do not, and the reason is that a count read off a header's
idiom is not a count of instructions. These files are the measurement that
settled it; the conclusions are in `docs/mechanisms.md` under "What an
instruction count means".

## Running it

```
SIMDE=~/path/to/thirdparty/simde        # SIMDe 0.8.4, headers at $SIMDE/x86/
cc -O3 -c -I$SIMDE -o /tmp/idioms.o idioms.c
objdump -d /tmp/idioms.o | awk -f count.awk
```

Repeat with `-O2`, and with GCC on aarch64 for a second compiler:

```
docker run --rm --platform linux/arm64 -v "$PWD":/w -v "$SIMDE":/simde -w /w \
    gcc:13 sh -c 'gcc -O3 -c -I/simde -o /w/g.o /w/idioms.c &&
                  objdump -d /w/g.o | awk -f /w/count.awk'
```

`count.awk` counts each function body between its symbol header and its
`ret`, excluding the `ret`: every function here ends in exactly one, so
counting it would add the same constant to every row. A single `dup` reads as
1. Alignment padding after `ret` belongs to no function and is excluded too;
counting that inflated a first reading of the GCC results by two instructions
per function and made two sequences look different that are byte-identical.

Each function takes its vector and its scalars or pointer as parameters, so
the body is the idiom and not a prologue. `idioms.c` holds the insert chains
and a first pass at the set builds, `sets.c` the set builds against the
`vsetq_lane_*` chain the table used to name, and `shapes.c` the shapes the
corpora actually contain.

## What it found

Measured with Apple clang 21 (arm64-apple-darwin) and GCC 13.5.0 (aarch64
Linux). `-O2` and `-O3` agreed in every case, so one column each.

Insert chains, scalars strided in memory:

| idiom | SIMDe clang | `vld1q_lane` clang | SIMDe gcc | `vld1q_lane` gcc |
|---|---:|---:|---:|---:|
| `_mm_insert_epi32` x4 | 8 | 8 | 8 | 8 |
| `_mm_insert_epi32` x2 | 3 | 3 | 3 | 3 |
| `_mm_insert_epi16` x2 | 3 | 3 | 3 | 3 |
| `_mm_insert_epi64` x2 | 3 | 3 | 3 | 3 |

For the four-lane case the two sequences are byte-identical in both
compilers: each emits `ld1 {v0.s}[i], [xN]`, which is the instruction the
withdrawn suggestion named. With the scalars already in registers the chain
is 4 instructions for 4 lanes (`mov v0.s[i], wN`) and a lane load does not
apply.

Set builds, against the `vsetq_lane_*` chain:

| idiom | SIMDe clang | `vsetq_lane` clang | SIMDe gcc | `vsetq_lane` gcc |
|---|---:|---:|---:|---:|
| `_mm_set_epi32` x4 distinct, memory | 8 | 8 | 12 | 9 |
| `_mm_set_epi64x` x2, memory | 3 | 3 | 3 | 3 |
| `_mm_set_epi16` x8 distinct, memory | 20 | 19 | 25 | 17 |
| `_mm_set_epi32` x4, registers | 4 | 4 | 4 | 5 |

The shapes the corpora contain:

| shape | SIMDe clang | SIMDe gcc | `vdupq_n` | `vsetq_lane` chain |
|---|---:|---:|---:|---:|
| `_mm_set_epi16(w x8)` | 1 | 1 | 1 / 1 | 1 clang, 9 gcc |
| `_mm_set_epi32(o x4)` | 1 | 1 | 1 / 1 | -- |
| `_mm_set_epi32(r1, r1, r1, r0)` | 4 | 2 | 4 / 2 | -- |
| `_mm_set_epi64x` of two strided `u64` loads | 3 | 3 | -- | 3 / 3 |

No measured case performs the trip through memory the table's note described:
clang folds every argument into a lane load, GCC loads into FP registers
(`ldr h_n`, `ldr s_n`) and moves into lanes. The local array in the header is
a candidate for scalar replacement and neither compiler kept it.

The `vsetq_lane_*` chain is recorded here as a candidate that was evaluated,
not as a recommendation. It is equal under clang, better under GCC on the two
wider distinct cases, one instruction worse under GCC when the scalars are
already in registers, and eight instructions worse under GCC for a
broadcast -- which is why no rule M finding names a replacement.

## What it does not establish

These are standalone functions. They do not prove that every call site in a
corpus emits the same code, that the local array can never materialize, or
that another compiler or version agrees. They establish that the counts the
table recorded cannot be derived from the SIMDe source, which is the claim
the table was making.
