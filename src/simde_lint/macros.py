"""Reparse function-like macro bodies.

tree-sitter leaves a macro body as an opaque `preproc_arg` with no children,
so nothing downstream can see the calls inside it. Each body is reparsed
inside a synthetic function wrapper, and every position maps back to the
original file by one constant offset.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tree_sitter import Node

from .knowledge import Knowledge
from .parser import iter_nodes, node_text, parse_source

_PREFIX = b"void __simde_lint_macro_body(void){\n"
_SUFFIX = b"\n;}\n"

_INTRINSIC_PREFIXES = ("_mm_", "_mm256_", "_mm512_")


def _is_intrinsic(name: str) -> bool:
    return name.startswith(_INTRINSIC_PREFIXES)


@dataclass(frozen=True)
class ReparsedMacro:
    name: str
    # Fixed (non-variadic) parameter names only — see `variadic` below for
    # the pack, which is deliberately not one of these even when it has its
    # own written name (a GNU named variadic).
    params: tuple[str, ...]
    # The name a variadic pack is referenced by *inside the body*, or None
    # if this macro takes no variadic parameter. `"__VA_ARGS__"` for the
    # standard `#define F(x, ...)` form; the macro's own given name for the
    # GNU named form, `#define F(x, args...)` — that form lets the body
    # refer to the pack as `args`, never as `__VA_ARGS__`. See
    # `_variadic_pack` for how this is read off the parameter list.
    variadic: str | None
    # Start of the whole `#define` construct (the `preproc_function_def`
    # node itself) — a stable, always-present per-*definition* key, unlike
    # `body_start_byte` below, which only exists when the definition has a
    # body at all. `build_alias_map`'s `AliasMap.definitions` and
    # `extract.py`'s unit skip are both keyed on this field, not on
    # `body_start_byte`, precisely so an empty-bodied definition (which
    # never reaches this dataclass — see `reparse_macros`, and
    # `macros._definition_positions` for the count that catches it anyway)
    # cannot be conflated with one that does.
    start_byte: int
    body_start_byte: int
    root: Node
    source: bytes
    ok: bool


def original_byte(macro: ReparsedMacro, parsed_byte: int) -> int:
    """Map a byte offset in the reparsed body back to the original file."""
    return macro.body_start_byte + parsed_byte - len(_PREFIX)


def line_column(source: bytes, byte: int) -> tuple[int, int]:
    """1-based line and column of a byte offset in the original source."""
    line = source.count(b"\n", 0, byte) + 1
    column = byte - (source.rfind(b"\n", 0, byte) + 1) + 1
    return line, column


def _body_range(source: bytes, value: Node) -> tuple[int, int]:
    r"""Source range of a macro body, following backslash continuations.

    tree-sitter's `preproc_arg` sometimes stops at the first physical line of
    a continued macro — or even mid-line, inside a `do { ... } while` body's
    scanner heuristics, a few characters into the *next* physical line — which
    would hand the parser a fragment (`do {` with no closing brace) and fail
    on input that is merely truncated, unless the fragment is grown to cover
    the whole continuation.

    A continuation is followed only when the line actually pending — the one
    starting wherever `end` currently sits, out to its own newline — ends in
    `\\` once trailing spaces/tabs/`\r` are stripped. This deliberately does
    not look at anything before `end` on that line, so it is unaffected by
    `end` landing mid-line rather than at a line boundary; it also does not
    look past that line's own newline, which is what the previous
    `rstrip().endswith(b"\\")` over the whole accumulated range got wrong — a
    blank or whitespace-only continuation target does not itself end in `\`,
    so it correctly stops the body right there instead of reading through it
    into whatever source happens to follow (a stray trailing backslash on an
    otherwise-finished `#define` must not pull in the next declaration).
    """
    end = value.end_byte
    while True:
        newline = source.find(b"\n", end)
        if newline < 0:
            # No further newline at all: the rest of the file is one final,
            # unterminated line and there is nothing more to pull in either
            # way.
            return value.start_byte, len(source)
        if not source[end:newline].rstrip(b" \t\r").endswith(b"\\"):
            return value.start_byte, newline + 1
        end = newline + 1


def _variadic_pack(parameters: Node | None, source: bytes) -> tuple[tuple[str, ...], str | None]:
    """Fixed parameter names and the variadic pack's own reference name.

    Reads the *raw* `preproc_params` child sequence, not the flattened,
    identifier-only view `reparse_macros` used to build `.params` from —
    that flattened view cannot tell a GNU named variadic's pack name apart
    from an ordinary fixed parameter, since both are plain `identifier`
    nodes; only the raw child sequence carries the trailing `...` that
    distinguishes them.

    Two forms, both measured directly against this project's grammar:

    - Standard `#define F(x, ...)`: the parameter list has a literal `...`
      child (node type `"..."`, unnamed). The pack has no name of its own —
      the body always refers to it as the reserved identifier
      `__VA_ARGS__`.
    - GNU named `#define F(x, args...)`: this grammar does not parse `...`
      immediately after a parameter name as part of any clean node type —
      it parses `args` as an ordinary `identifier` parameter and then hits
      an `ERROR` node for the trailing `...` (confirmed directly: the
      *file's* `root.has_error` is True for this form, though the
      individual macro's own body still reparses fine, since the error is
      confined to the parameter list). Detected here by finding the last
      `identifier` child and checking whether the very next non-`)` sibling
      spells exactly `...` — whatever node type tree-sitter gave it. That
      identifier is then the pack's own name, not a fixed parameter.

    A macro with no variadic parameter at all returns `(fixed_names, None)`,
    unchanged from before this distinction existed.
    """
    if parameters is None:
        return (), None
    children = parameters.children
    idents = [child for child in children if child.type == "identifier"]
    names = tuple(node_text(child, source) for child in idents)
    if any(child.type == "..." for child in children):
        return names, "__VA_ARGS__"
    if idents:
        last = idents[-1]
        last_index = next(i for i, child in enumerate(children) if child is last)
        for child in children[last_index + 1 :]:
            if child.type == ")":
                break
            if node_text(child, source).strip() == "...":
                return names[:-1], names[-1]
    return names, None


def reparse_macros(root: Node, source: bytes) -> list[ReparsedMacro]:
    """Reparse every function-like macro body in one file.

    A body that does not parse is returned with `ok=False` and is not guessed
    at from its text; callers treat it as neither an alias nor a unit. A
    definition with **no** body at all (`#define LD(p)`, nothing after the
    parameter list — tree-sitter's `value` field is `None`, not an empty
    node) is skipped entirely, same as before: there is no body byte range to
    reparse. It is not, however, invisible to `build_alias_map` — see
    `_definition_positions`, which enumerates `preproc_function_def` nodes
    directly rather than relying on this function's output, specifically to
    catch this case.
    """
    macros: list[ReparsedMacro] = []
    for define in iter_nodes(root, "preproc_function_def"):
        name = node_text(define.child_by_field_name("name"), source)
        value = define.child_by_field_name("value")
        if not name or value is None:
            continue
        params, variadic = _variadic_pack(define.child_by_field_name("parameters") or define, source)
        body_start, body_end = _body_range(source, value)
        body = source[body_start:body_end]
        synthetic = _PREFIX + body + _SUFFIX
        tree = parse_source(synthetic)
        macros.append(
            ReparsedMacro(
                name=name,
                params=params,
                variadic=variadic,
                start_byte=define.start_byte,
                body_start_byte=value.start_byte,
                root=tree.root_node,
                source=synthetic,
                ok=not tree.root_node.has_error,
            )
        )
    return macros


def _definition_positions(root: Node, source: bytes) -> dict[str, list[int]]:
    """Every function-like macro *definition*'s own start position, by name.

    Unlike `reparse_macros`, this counts every `preproc_function_def` node
    regardless of whether it has a body. `#define LD(p)` — nothing after the
    parameter list — has `value=None`, and `reparse_macros` skips it: there
    is no body to reparse. If `build_alias_map` only ever saw
    `reparse_macros`'s output, a name with an alias-shaped definition in one
    `#if` branch and this kind of empty definition in another would never
    learn the empty one exists, and would register the name as if every
    definition agreed — vacuously, over a definition it never saw. This
    function exists so `build_alias_map` can compare "how many definitions
    does this name really have" against "how many did `reparse_macros`
    reparse" and refuse to register when the two counts differ.

    Keyed by the *definition* node's own `start_byte` (see `ReparsedMacro`),
    not any measure of its body — an empty definition still gets a stable,
    distinct position this way.
    """
    positions: dict[str, list[int]] = {}
    for define in iter_nodes(root, "preproc_function_def"):
        name = node_text(define.child_by_field_name("name"), source)
        if not name:
            continue
        positions.setdefault(name, []).append(define.start_byte)
    return positions


_TRANSPARENT = {"parenthesized_expression", "cast_expression"}


def _unwrap(node: Node) -> Node:
    """Strip parentheses and casts, which do not change what a body computes."""
    while node.type in _TRANSPARENT:
        inner = [c for c in node.named_children if c.type != "type_descriptor"]
        if len(inner) != 1:
            return node
        node = inner[0]
    return node


def _identifiers(node: Node, source: bytes) -> set[str]:
    """Every name written as an identifier anywhere under `node`.

    Includes `type_identifier`, not only `identifier`: tree-sitter's C/C++
    grammar resolves `(BASE) + (0 * (S))`-shaped expressions as a cast —
    `BASE` parsed as a `type_descriptor`'s `type_identifier`, not as a
    parenthesized variable reference — whenever a parenthesized name is
    immediately followed by something that could be a unary operand.
    SVT-AV1's `LOAD8_S`/`LOAD4W_S` write exactly this shape with `BASE`, a
    macro parameter that is never actually a type. Counting only
    `identifier` would read `BASE` as unused and reject a macro that
    forwards every parameter faithfully — a false rejection from a grammar
    ambiguity, not a genuine dropped parameter.

    **This is a text-appearance search, not a value-flow analysis, and it is
    known-unsound for that reason:** `#define DROP_VALUE(a, b)
    _mm_add_epi32(((void)(a), (b)), (b))` has `a` appear right here, inside a
    `(void)`-cast comma operand — a position whose value provably never
    reaches the forwarded call, since a comma expression's value is its
    *last* operand and `(void)` explicitly discards one. `is_forwarding_alias`
    still confirms this as an alias on the strength of `a` merely appearing
    in the subtree. `(a) ^ (a)` is accepted the same way, for the same
    reason. Neither `F` nor `P` rely on this predicate for their own
    soundness (see `is_forwarding_alias`'s docstring); it is used for
    registration only, and a registered alias's `call.args` at its use sites
    should be read with that in mind.
    """
    names = {node_text(child, source) for child in iter_nodes(node, "identifier")}
    names |= {node_text(child, source) for child in iter_nodes(node, "type_identifier")}
    return names


def _forwarding_call(macro: ReparsedMacro) -> Node | None:
    """The body's single top-level `call_expression`, or None otherwise.

    Shared by `is_forwarding_alias` (which reads only the callee's name) and
    `_resolve_alias` (which reads that same call's argument list, through
    `_call_shape`) so the "single statement, single call, no nested call"
    shape is checked once.
    """
    if not macro.ok:
        return None
    body = [
        child
        for child in _statements(macro.root)
        if child.type not in ("comment",)
    ]
    if len(body) != 1:
        return None
    expression = _unwrap(body[0])
    if expression.type != "call_expression":
        return None
    if len(list(iter_nodes(expression, "call_expression"))) != 1:
        return None
    return expression


def is_forwarding_alias(macro: ReparsedMacro) -> str | None:
    """The single callee a body forwards to, or None if it does anything else.

    Only the written name is returned; resolving it through the knowledge
    tables and through other macros is `build_alias_map`'s job.

    A body that drops a parameter — writes it in the macro's own parameter
    list but never uses it in the forwarded call — is rejected here when the
    parameter's name does not appear anywhere in the forwarded call's
    argument list at all. Reordering (`_mm256_set_m128i((hi), (lo))`),
    duplication (`f((b), (b))`), and inserting non-parameter operands (an
    8-argument `_mm256_setr_epi32` fed by a 3-parameter macro) all leave
    every parameter present at least once, so none of those are rejected
    here.

    A declared variadic pack is held to the same standard as a fixed
    parameter: `macro.variadic`, when not None, must also appear (as its
    own reference — `"__VA_ARGS__"` or a GNU named pack's own name) among
    the identifiers written in the forwarded call's argument list, or this
    macro is rejected the same way a dropped fixed parameter is. Without
    this, `#define BAD(...) _mm_set_epi32(0, 0, 0, 0)` — a pack declared
    and never written anywhere in the body — passed `set(macro.params) <=
    used` vacuously (`macro.params` is empty for a pack-only parameter
    list) and registered `BAD` as forwarding to `_mm_set_epi32`, even
    though the call it actually forwards to receives four constants and no
    part of any call-site argument at all. This is "declared and never
    written in the body," not "expands to zero tokens": `#define
    V(...) _mm_setzero_si128(__VA_ARGS__)` writes `__VA_ARGS__` right here
    in its own body and must keep registering even though a call site with
    no pack arguments makes it expand to nothing — see
    `_VARIADIC_ZERO_EXTRA_ARGS_MATCHES_DIRECT` in the test suite. A fixed
    parameter still present alongside a dropped pack does not save the
    macro either: `#define V(x, ...) TGT(x)` is the same defect with `x`
    faithfully forwarded and `...` thrown away.

    **This check is a heuristic, not a soundness guarantee — see
    `_identifiers`'s docstring for `DROP_VALUE`, a confirmed alias whose
    body drops a parameter's value while the name still appears in the
    subtree.** `PipelineRule`/`FusionRule` do not rely on this predicate to
    keep their own membership judgment sound: they decline to read a
    *consumer* call's args at all when that call carries a `raw_name` (was
    itself resolved through a macro), regardless of what this function
    decided about it — see `rules/pipeline.py`/`rules/fusion.py` and
    `docs/verification.md`'s forwarding-alias section. This predicate still
    matters for the general correctness of a confirmed alias's recorded
    `call.args` beyond F and P, and for keeping this function's job honest:
    a name that never appears at all is a stronger sign of a body that does
    something other than forward than one that does.
    """
    expression = _forwarding_call(macro)
    if expression is None:
        return None
    callee = expression.child_by_field_name("function")
    if callee is None or callee.type != "identifier":
        return None
    arguments = expression.child_by_field_name("arguments")
    used = _identifiers(arguments, macro.source) if arguments is not None else set()
    if not set(macro.params) <= used:
        return None
    if macro.variadic is not None and macro.variadic not in used:
        return None
    return macro.source[callee.start_byte : callee.end_byte].decode()


def _splice_lines(text: bytes) -> bytes:
    r"""Delete backslash-newline sequences, mirroring C's own phase-2 splicing.

    A `\` immediately followed by an end-of-line — optionally with trailing
    spaces/tabs/`\r` between the `\` and the newline, matching this file's
    own continuation tolerance in `_body_range` — is deleted along with the
    newline, joining the two physical lines into one logical line. Without
    this, a call written with its argument list split across a
    backslash-continued macro body (the reparsed body still contains the raw
    `\` and newline bytes verbatim — tree-sitter does not splice them) would
    tokenize with a stray `\` token that the same call written on one
    physical line does not have, and the two would compare unequal for a
    reason that has nothing to do with what either macro forwards.

    A `\` that is not immediately (mod that trailing whitespace) followed by
    a newline — including one that opens a string escape like `"\n"` — is
    left untouched; this only ever fires on an actual line-continuation.
    """
    out = bytearray()
    i, n = 0, len(text)
    while i < n:
        if text[i] == 0x5C:  # \
            j = i + 1
            while j < n and text[j] in (0x20, 0x09, 0x0D):  # space, tab, CR
                j += 1
            if j < n and text[j] == 0x0A:  # \n
                i = j + 1
                continue
        out.append(text[i])
        i += 1
    return bytes(out)


def _byteset(text: bytes) -> frozenset[bytes]:
    """A frozenset of the single-byte slices `text` contains.

    Not `frozenset(text)`: iterating a `bytes` object directly yields
    `int`s, not length-1 `bytes`, and every membership test in this
    tokenizer compares against a `text[i : i + 1]` slice — a `bytes` object.
    An `int`-keyed set would silently never match any of them.
    """
    return frozenset(text[i : i + 1] for i in range(len(text)))


_WHITESPACE = _byteset(b" \t\n\r\v\f")
_IDENT_START = _byteset(bytes(range(0x41, 0x5B)) + bytes(range(0x61, 0x7B)) + b"_")
_DIGITS = _byteset(bytes(range(0x30, 0x3A)))
_IDENT_CONTINUE = _IDENT_START | _DIGITS
_EXPONENT_LETTERS = _byteset(b"eEpP")
_SIGNS = _byteset(b"+-")
_STRING_PREFIXES = (b"u8", b"u", b"U", b"L")


def _literal_start(text: bytes, i: int) -> int | None:
    """Byte offset of the opening quote at `i`, honoring an encoding prefix.

    Returns the offset of the `"` or `'` itself (which may be `i` with no
    prefix, or a few bytes past it for `u8"..."`/`u'...'`/`U"..."`/`L"..."`),
    or None if `text[i]` does not begin a string or character literal.

    Deliberately does not recognize a raw string (`R"..."`, optionally
    prefixed) — `_raw_string_start` below owns that, and must run first: a
    raw string's `R` would otherwise be lexed as a bare identifier, with
    the literal itself starting only at the quote that follows it.
    """
    n = len(text)
    if text[i : i + 1] in (b'"', b"'"):
        return i
    for prefix in _STRING_PREFIXES:
        end = i + len(prefix)
        if text[i:end] == prefix and end < n and text[end : end + 1] in (b'"', b"'"):
            return end
    return None


_RAW_STRING_PREFIXES = (b"u8", b"u", b"U", b"L", b"")


def _raw_string_start(text: bytes, i: int) -> int | None:
    """Byte offset right after the opening `R"` of a raw string at `i`.

    Honors an optional encoding prefix (`u8R"`, `uR"`, `UR"`, `LR"`, or bare
    `R"`), tried longest-first so `u8R"..."` is not mistaken for prefix `u`
    followed by a stray `8R"...`. Returns None if no raw string starts at
    `i` — including when `text[i]` is `R` immediately followed by anything
    other than `"` (an ordinary identifier that happens to start with `R`,
    which is by far the common case and must tokenize as a plain
    identifier, substitutable like any other).
    """
    n = len(text)
    for prefix in _RAW_STRING_PREFIXES:
        end = i + len(prefix)
        if text[i:end] == prefix and text[end : end + 2] == b'R"':
            return end + 2
    return None


def _scan_raw_string(text: bytes, delimiter_start: int) -> int | None:
    r"""End offset (exclusive) of a raw string, or None if malformed.

    `delimiter_start` is the byte right after the opening `R"`. A raw
    string's delimiter is every byte from there up to (not including) the
    first `(`; its closing sequence is `)` + that same delimiter + `"`,
    wherever it next occurs — not merely the first `)"`, since the
    delimiter can be non-empty specifically so the raw content can contain
    `)"` sequences of its own without ending the literal early (real C++
    restricts which bytes may appear in a delimiter; this scanner does not
    enforce that, which only means it might accept something a compiler
    would reject — never the reverse, and never a false *agreement* between
    two definitions, so it is not a soundness gap for this module's
    purpose). No escape processing happens inside a raw string — that is
    the entire point of "raw" — so a `\` here is only ever a literal
    backslash, never an escape.

    Returns None when no `(` is found at all (not a raw string's delimiter
    section, malformed) or when the matching closing sequence never
    occurs (unterminated) — both fail closed, same as every other literal
    kind this lexer handles.
    """
    paren = text.find(b"(", delimiter_start)
    if paren < 0:
        return None
    delimiter = text[delimiter_start:paren]
    closer = b")" + delimiter + b'"'
    end = text.find(closer, paren + 1)
    return None if end < 0 else end + len(closer)


def _scan_literal(text: bytes, quote_at: int) -> int | None:
    r"""End offset (exclusive) of the literal opening at `quote_at`, or None.

    `quote_at` is the position of the opening quote itself. A `\` inside the
    literal always escapes the next byte, whatever it is — including a
    second `\` or a matching quote — so an escaped quote never terminates
    the literal early. None means the literal runs off the end of `text`
    without a closing quote: malformed, unlexable input, which callers must
    treat as a hard failure rather than guess at.
    """
    quote = text[quote_at : quote_at + 1]
    n = len(text)
    j = quote_at + 1
    while j < n:
        c = text[j : j + 1]
        if c == b"\\":
            j += 2
            continue
        if c == quote:
            return j + 1
        j += 1
    return None


def _scan_block_comment_end(text: bytes, start: int) -> int | None:
    """End offset (exclusive) of a `/*` comment opening at `start`, or None."""
    end = text.find(b"*/", start + 2)
    return None if end < 0 else end + 2


# Every multi-character punctuator this lexer must not split into individual
# bytes, drawn from the C (C17 6.4.6) and C++ (C++23 [lex.operators]) grammars
# together — this project accepts both, and a body written in either must
# tokenize its operators correctly. Sorted longest-first below by
# `_scan_punctuator`, so a longer spelling is always tried before any shorter
# spelling that is one of its own prefixes: `<<=` before `<<` before `<`,
# `->*` before `->`, and so on. A single-character punctuator (`+`, `&`, `.`,
# `<`, ...) is not listed here at all -- it falls through to `_tokenize`'s own
# one-byte-at-a-time fallback, unchanged from before this set existed.
_PUNCTUATORS: tuple[bytes, ...] = tuple(
    sorted(
        {
            # C (and shared C/C++) multi-character punctuators.
            b"...",
            b"->",
            b"++",
            b"--",
            b"<<",
            b">>",
            b"<=",
            b">=",
            b"==",
            b"!=",
            b"&&",
            b"||",
            b"*=",
            b"/=",
            b"%=",
            b"+=",
            b"-=",
            b"&=",
            b"^=",
            b"|=",
            b"<<=",
            b">>=",
            b"##",
            # C99 digraphs -- alternate spellings of `[ ] { } # ##`.
            b"<:",
            b":>",
            b"<%",
            b"%>",
            b"%:",
            b"%:%:",
            # C++-only forms.
            b"::",
            b".*",
            b"->*",
            b"<=>",
        },
        key=len,
        reverse=True,
    )
)


def _scan_punctuator(text: bytes, i: int) -> bytes | None:
    """The longest punctuator spelling starting at `i`, or None if none matches.

    Tried in `_PUNCTUATORS`'s longest-first order, so `&&` is never split
    into two separate `&` tokens, and `<<=` is never mistaken for `<<`
    followed by a separate `=`. This is what keeps `a && b` (logical-and)
    and `a & &b` (bitwise-and applied to the address of `b`) from lexing to
    the same token sequence `a`, `&`, `&`, `b` -- before this function
    existed, `_tokenize`'s catch-all one-byte-per-punctuator fallback did
    exactly that, and two macro definitions differing only by that
    whitespace (one written `&&`, the other `& &`) compared as agreeing
    even though they specify different operators applied to different
    operands.

    One exception to plain longest-match, carved out before the general
    scan even starts: C++ [lex.pptoken]'s own `<::` rule. If the next three
    characters are `<::` and the fourth is neither `:` nor `>`, `<` is its
    own token here, not the first character of the `<:` digraph -- this is
    what makes a template argument list like `f<::N>` lex as `f`, `<`,
    `::`, `N`, `>` (a qualified name `::N`) rather than `f`, `<:`, `:N>` (a
    digraph `[` swallowing the first colon of `::`). Returning None here
    falls through to `_tokenize`'s own single-byte fallback for the `<`,
    and the very next call at `i + 1` finds `::` and matches it by ordinary
    longest match -- no separate bookkeeping needed for the rest of it.
    When the fourth character *is* `:` or `>` (`<::>`, `<:::`), or the next
    three characters are not `<::` at all (a bare `<:`, or `<:>`), this
    exception does not fire and the digraph is matched exactly as before.
    """
    if text[i : i + 3] == b"<::" and text[i + 3 : i + 4] not in (b":", b">"):
        return None
    for punct in _PUNCTUATORS:
        if text[i : i + len(punct)] == punct:
            return punct
    return None


def _tokenize(text: bytes) -> list[tuple[str, bytes]] | None:
    """Lex already-spliced `text` into `(kind, bytes)` tokens, or None if malformed.

    `kind` is `"ident"` for an identifier (a candidate for parameter
    substitution), or `"other"` for everything else that is kept
    (string/character literals as one opaque token each, pp-numbers, and
    punctuators). A punctuator is lexed by longest match against
    `_PUNCTUATORS` (`_scan_punctuator`) before falling back to a single
    byte, so a multi-character operator like `&&`, `<<=`, or `->*` is always
    kept as one token, the same as a real preprocessing-token lexer would
    keep it, and not split into its individual characters. Whitespace and
    comments are dropped entirely — neither carries meaning for comparing
    two forwarded call shapes.

    This is a plain byte-level lexer, deliberately independent of
    tree-sitter's own CST node classification: `(BASE) + (0 * (S))` parses
    as a cast in this project's grammar, with `BASE` read as a
    `type_identifier` rather than a parenthesized variable reference (see
    `_identifiers`'s docstring) — a distinction that would matter if
    substitution keyed off node type, but does not here, because `BASE`'s
    *lexical spelling* is the same identifier either way.

    A string or character literal (with an optional `u8`/`u`/`U`/`L` prefix)
    is kept as a single token covering its entire spelling, quotes included,
    and its *contents* are never inspected: `sizeof("a")` and `sizeof("x")`
    tokenize to different literal tokens, not to the same substituted
    parameter, even though `a` alone would otherwise be one of this macro's
    parameter names. An escaped quote (`"\""`) does not end the literal
    early, so `"\""` is one token, not a truncated one. A raw string
    (`R"..."`, optionally prefixed the same way) is handled the same way,
    through `_raw_string_start`/`_scan_raw_string` — checked *before* a
    plain identifier could claim its leading `R`, or `R"(x)"` would lex as
    an identifier `R` (substituted whenever some macro's own parameter
    happens to be named `R`) immediately followed by an unrelated literal
    `"(x)"`, corrupting the raw string's own spelling.

    Returns None when a string literal, character literal, raw string, or
    block comment is left unterminated at the end of `text` — malformed
    input fails closed: it can never make two definitions compare as
    agreeing.
    """
    tokens: list[tuple[str, bytes]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i : i + 1]
        if c in _WHITESPACE:
            i += 1
            continue
        if c == b"/" and text[i + 1 : i + 2] == b"/":
            end = text.find(b"\n", i)
            i = n if end < 0 else end
            continue
        if c == b"/" and text[i + 1 : i + 2] == b"*":
            end = _scan_block_comment_end(text, i)
            if end is None:
                return None
            i = end
            continue
        raw_delimiter_start = _raw_string_start(text, i)
        if raw_delimiter_start is not None:
            end = _scan_raw_string(text, raw_delimiter_start)
            if end is None:
                return None
            tokens.append(("other", text[i:end]))
            i = end
            continue
        quote_at = _literal_start(text, i)
        if quote_at is not None:
            end = _scan_literal(text, quote_at)
            if end is None:
                return None
            tokens.append(("other", text[i:end]))
            i = end
            continue
        if c in _IDENT_START:
            j = i + 1
            while j < n and text[j : j + 1] in _IDENT_CONTINUE:
                j += 1
            tokens.append(("ident", text[i:j]))
            i = j
            continue
        if c in _DIGITS or (c == b"." and text[i + 1 : i + 2] in _DIGITS):
            j = i + 1
            while j < n:
                d = text[j : j + 1]
                if d in _EXPONENT_LETTERS and text[j + 1 : j + 2] in _SIGNS:
                    j += 2
                    continue
                # C++14 digit separator: a `'` inside a pp-number is part of
                # the number itself, not the start of a character literal --
                # but only when immediately followed by a digit or an
                # identifier-nondigit (`1'000`, `0x1'ff`), per the grammar's
                # own `pp-number ' digit` / `pp-number ' nondigit`
                # productions. Consuming both bytes here (the `'` and the
                # character after it) in one step is enough: whatever that
                # character is, it is already one this loop's own
                # `_IDENT_CONTINUE`/exponent-sign checks know how to
                # continue from on the next iteration. A `'` *not* followed
                # by a digit or nondigit is not a separator at all -- the
                # loop breaks before it, same as before this case existed,
                # and the character literal scanning `_tokenize`'s own quote
                # branch performs on it next fails closed exactly as any
                # other malformed literal does.
                if d == b"'" and (
                    text[j + 1 : j + 2] in _DIGITS or text[j + 1 : j + 2] in _IDENT_START
                ):
                    j += 2
                    continue
                if d in _IDENT_CONTINUE or d == b".":
                    j += 1
                    continue
                break
            tokens.append(("other", text[i:j]))
            i = j
            continue
        punct = _scan_punctuator(text, i)
        if punct is not None:
            tokens.append(("other", punct))
            i += len(punct)
            continue
        tokens.append(("other", c))
        i += 1
    return tokens


def _marker(index: int) -> bytes:
    return f"\x00{index}\x00".encode()


_MARKER = re.compile(rb"\x00([0-9]+)\x00")

# The variadic pack's own marker — deliberately not `_marker(index)`-shaped
# (no digits), so `_marker_index` never confuses it with a fixed-parameter
# position and `_substitute_shape` can tell "substitute one argument" apart
# from "substitute the whole, possibly-empty, comma-joined remainder."
_VARIADIC_MARKER = b"\x00VA\x00"


def _marker_index(token: bytes) -> int | None:
    match = _MARKER.fullmatch(token)
    return int(match.group(1)) if match else None


def _normalized_tokens(
    text: bytes, params: tuple[str, ...], variadic: str | None = None
) -> tuple[bytes, ...] | None:
    """One argument's token sequence, its own macro's parameters marked.

    Splices backslash-newlines, lexes the result, and rewrites every
    `"ident"` token that exactly spells one of `params` into `_marker(index)`
    — a byte sequence (`\x00<index>\x00`) that cannot appear in C source, so
    it cannot collide with a real identifier or with an adjacent marker. An
    `"ident"` token spelling `variadic` (the macro's own variadic pack
    reference — `"__VA_ARGS__"` or a GNU named pack's own name; see
    `ReparsedMacro.variadic`) is rewritten to `_VARIADIC_MARKER` instead,
    never to a positional marker: the pack is not one parameter at one
    position, it is "whatever arguments an outer call supplies beyond the
    fixed ones," resolved only at composition time (`_substitute_shape`).
    Every occurrence is rewritten, including a repeated one, so `f(b, b)`
    keeps both markers distinct occurrences rather than being conflated with
    `f(b)`. Non-parameter identifiers, literals, numbers and punctuators
    pass through unchanged. Returns None when `text` fails to lex (see
    `_tokenize`) — malformed input fails closed.
    """
    tokens = _tokenize(_splice_lines(text))
    if tokens is None:
        return None
    index_by_name = {name: index for index, name in enumerate(params)}
    out: list[bytes] = []
    for kind, value in tokens:
        if kind != "ident":
            out.append(value)
            continue
        name = value.decode("ascii", errors="replace")
        if variadic is not None and name == variadic:
            out.append(_VARIADIC_MARKER)
            continue
        index = index_by_name.get(name)
        out.append(_marker(index) if index is not None else value)
    return tuple(out)


class _EmptyArgs:
    """Sentinel type for `_call_shape`'s ambiguous-empty-argument-list result.

    A single instance (`_EMPTY_ARGS`, below) is the only value of this type
    ever created; callers compare against it with `is`, never `==`, so it
    can never be mistaken for a real (possibly also empty) shape tuple —
    unlike a sentinel built from an ordinary tuple or string, which risks
    exactly that confusion if a caller ever slips and uses `==`.
    """

    __slots__ = ()


# Sentinel result of `_call_shape` for a call whose argument list is
# syntactically empty (`f()`) — distinct from `()` (also "no arguments," but
# only once the ambiguity is resolved). C gives `f()` no fixed meaning: it is
# how many argument slots the *callee's own* declared parameter list makes
# it into, not something the call site's own text can decide alone. A
# zero-parameter callee reads it as zero arguments; a one-parameter callee
# reads it as exactly one argument whose own spelling is empty. This is a
# real function call's own syntax that resolves it (unambiguously zero
# arguments) only for a callee that is a recognized intrinsic, never for a
# callee that is itself a macro — see `_resolve_alias`, the only place this
# sentinel is interpreted.
_EMPTY_ARGS = _EmptyArgs()


def _call_shape(
    macro: ReparsedMacro, arguments: Node | None
) -> tuple[tuple[bytes, ...], ...] | _EmptyArgs | None:
    """Per-argument normalized token shape of one forwarded call.

    One token tuple per positional argument (`arguments.named_children`),
    each produced by `_normalized_tokens` against `macro.params`/
    `macro.variadic` — so a marker in position `k` of argument `i` means
    "wherever this macro's parameter `k` is used inside its `i`th argument
    to the call it forwards to," and `_VARIADIC_MARKER` means "wherever its
    variadic pack is used there." Comparing two calls' shapes for equality
    is exactly comparing where each parameter (and the pack, as a whole)
    lands, argument count included: `f(a, a)` and `f(a, b)` (or `f(a)` and
    `f(a, b)`) have different shapes.

    Returns the `_EMPTY_ARGS` sentinel (see its own docstring) when the
    argument list is syntactically empty (`arguments.named_children` is
    empty) — this is ambiguous without knowing the callee's own arity, which
    only the caller (`_resolve_alias`) has. Returns None if any argument
    fails to lex (see `_normalized_tokens`) — malformed input fails closed,
    same as everywhere else in this module.
    """
    if arguments is None:
        return ()
    if not arguments.named_children:
        return _EMPTY_ARGS
    shape = []
    for arg in arguments.named_children:
        tokens = _normalized_tokens(macro.source[arg.start_byte : arg.end_byte], macro.params, macro.variadic)
        if tokens is None:
            return None
        shape.append(tokens)
    return tuple(shape)


def _substitute_shape(
    shape: tuple[tuple[bytes, ...], ...],
    replacements: tuple[tuple[bytes, ...], ...],
    variadic_start: int | None = None,
) -> tuple[tuple[bytes, ...], ...] | None:
    """Compose one call's shape with what an outer call actually supplies.

    `shape` is one macro's own forwarded-call shape, its markers referring
    to *that macro's* parameter positions (and, possibly, its variadic
    pack). `replacements` is one token tuple per argument the outer,
    composing call actually passes — the first `variadic_start` of them
    (all of them, if `variadic_start` is None) line up with `shape`'s
    positional markers; the rest, if any, are what flows into the pack.
    Every positional marker token in `shape` is replaced, in place, by the
    *entire* multi-token sequence `replacements` has for that index, so an
    intermediate that inserts extra tokens around a parameter
    (`X(p, q) -> TGT(p + 1, q)`) keeps the `+ 1` in the composed result
    rather than losing it to a plain position-for-position swap.
    An argument slot written as *only* the pack — its token tuple is
    exactly `(_VARIADIC_MARKER,)`, nothing else alongside it — expands to
    however many top-level argument slots `replacements[variadic_start:]`
    (the outer call's excess arguments) actually has: zero slots (the
    argument vanishes entirely — not kept as one empty-token argument),
    one slot (that single excess argument's own tokens, verbatim), or
    several slots, each its own separate entry in the composed result —
    never joined into one slot with a literal comma token stitched inside
    it, because that would not match how `_call_shape` itself represents a
    direct call's own top-level arguments (one tuple per argument, split
    at the syntactic top level, not by scanning for comma bytes inside a
    single argument's text). This is what makes
    `#define V(...) f(__VA_ARGS__)` called as `V()` compose to the same
    shape as `f()` written directly (zero arguments either way — see
    `_EMPTY_ARGS`'s resolution in `_resolve_alias`), and
    `#define B(x, ...) f(x, __VA_ARGS__)` called as `B(x, y, z)` compose to
    the same shape as `f(x, y, z)` written directly (three separate
    argument slots either way, not one slot holding `y, z` joined inline).

    A pack that shares its slot with other written tokens is different: a
    single-token comma-joined expansion *inside* that slot's own text is
    the correct behavior there — `target((__VA_ARGS__))`'s one argument
    stays one argument, whatever the pack expands to — since splitting a
    slot that also has its own surrounding tokens into several top-level
    arguments would not correspond to anything a direct call could have
    written.

    Returns None when `shape` references a parameter index `replacements`
    has no entry for (an arity mismatch the chain cannot resolve), or when
    it uses `_VARIADIC_MARKER` but `variadic_start` is None (this macro's
    own forwarded call has no variadic pack for the marker to mean anything
    against) — neither is treated as agreement either way.
    """
    composed: list[tuple[bytes, ...]] = []
    for arg_tokens in shape:
        if variadic_start is not None and arg_tokens == (_VARIADIC_MARKER,):
            composed.extend(replacements[variadic_start:])
            continue
        new_arg: list[bytes] = []
        for token in arg_tokens:
            if token == _VARIADIC_MARKER:
                if variadic_start is None:
                    return None
                for position, excess in enumerate(replacements[variadic_start:]):
                    if position:
                        new_arg.append(b",")
                    new_arg.extend(excess)
                continue
            index = _marker_index(token)
            if index is None:
                new_arg.append(token)
                continue
            if index >= len(replacements):
                return None
            new_arg.extend(replacements[index])
        composed.append(tuple(new_arg))
    return tuple(composed)


def _statements(root: Node) -> list[Node]:
    """The reparsed body's top-level expressions, minus the synthetic tail.

    The wrapper appends its own `;` after the body (`_SUFFIX = b"\n;}\n"`), so
    a body that already ends in `;` reparses with a doubled semicolon: the
    real statement, followed by an empty `expression_statement` with no named
    children. That trailing empty statement is an artifact of the wrapper,
    not anything the macro's own source contained, so it is dropped here
    rather than counted as a second statement.
    """
    for function in iter_nodes(root, "function_definition"):
        body = function.child_by_field_name("body")
        if body is None:
            continue
        return [
            child.named_children[0] if child.type == "expression_statement" and child.named_children else child
            for child in body.named_children
            if not (child.type == "expression_statement" and not child.named_children)
        ]
    return []


@dataclass(frozen=True)
class AliasMap:
    """Registered forwarding aliases, from one file's macros.

    `targets` is name -> resolved intrinsic, the map callers look up a call
    site's `raw_name` against — the same shape `build_alias_map` returned
    before this type existed. `definitions` is the `start_byte` (see
    `ReparsedMacro`) of every specific macro *definition* that fed a
    registered name; `extract.py`'s unit skip needs this rather than the
    name alone, because one name can have several definitions in a file —
    different `#if` branches — and only the definitions that actually agreed
    with each other and got registered may have their unit skipped. A
    same-named definition that disagreed is not in here even though its name
    is a key in `targets`, and keeps its own unit.

    The two fields answer different questions at different granularity, and
    it is worth being precise about which is which: *whether a name
    registers at all* is decided over the whole set of that name's
    definitions (every one of them has to agree — see `build_alias_map`),
    but *which specific definitions are exempt from getting their own unit*
    is then recorded per definition. A definition's membership in
    `definitions` therefore always implies its name is a key in `targets`,
    never the reverse in isolation.

    Both fields are produced by the same registration pass in
    `build_alias_map` and are read-only from here — so the claim that they
    cannot drift apart is enforced, not merely documented. That enforcement
    lives in `__post_init__`, not only in what `build_alias_map` happens to
    pass in: any caller can construct an `AliasMap` directly with a plain,
    mutable dict, so the defensive copy has to be this class's own
    invariant, not a courtesy `build_alias_map` extends to itself. Passing
    an already-immutable `MappingProxyType`/`frozenset` (as `build_alias_map`
    does) still goes through the same copy — a `dict(mapping_proxy)` before
    re-wrapping — which costs a little and buys not having two code paths
    to keep in sync.
    """

    targets: Mapping[str, str]
    definitions: frozenset[int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", MappingProxyType(dict(self.targets)))
        object.__setattr__(self, "definitions", frozenset(self.definitions))


def _callee_arity(callee_defs: list[ReparsedMacro]) -> tuple[int, int | None] | None:
    """`(fixed parameter count, variadic pack start index)` for one name.

    `variadic_start` is `None` when the name takes no variadic pack, or
    equal to the fixed count when it does (the pack begins right after the
    last fixed parameter) — passed straight through to `_substitute_shape`.

    Returns None when `callee_defs` (every `ReparsedMacro` for one name)
    does not unanimously agree on both the fixed parameter count and
    whether a variadic pack is present at all. This can only happen for a
    name with more than one `#if` definition; a name whose definitions
    disagree this concretely is certain to fail the composed-shape equality
    check in `_resolve_alias` anyway, but checking here first means a
    caller never has to pick one arbitrary definition's arity to resolve an
    ambiguous empty argument list (`f()`) against, which an unfaithful
    choice could resolve the wrong way.
    """
    fixed_counts = {len(macro.params) for macro in callee_defs}
    has_variadic = {macro.variadic is not None for macro in callee_defs}
    if len(fixed_counts) != 1 or len(has_variadic) != 1:
        return None
    fixed_count = next(iter(fixed_counts))
    variadic_start = fixed_count if next(iter(has_variadic)) else None
    return fixed_count, variadic_start


def _resolve_alias(
    name: str,
    seen: frozenset[str],
    macros_by_name: dict[str, list[ReparsedMacro]],
    definition_counts: dict[str, int],
    knowledge: Knowledge,
    cache: dict[str, tuple[str, tuple[tuple[bytes, ...], ...]] | None],
) -> tuple[str, tuple[tuple[bytes, ...], ...]] | None:
    """Resolve `name` to `(final intrinsic, composed shape)`, or None.

    `seen` is the set of names on the *active* recursion path — used only
    for cycle detection, and never written to `cache` while a name is in it,
    because being "in `seen`" is true only for as long as this particular
    call stack is inside it; caching that would wrongly answer an unrelated,
    non-cyclic query about the same name later. `cache` instead holds each
    name's final, path-independent outcome, written once its own resolution
    (below) actually completes.

    Registration is a per-*name* decision over the whole set of that name's
    definitions: `name` resolves only if every one of its definitions does,
    and all of them resolve to the *same* `(final intrinsic, composed
    shape)` pair. A definition resolves when:

    - it is a forwarding alias (`is_forwarding_alias` returns a callee), and
    - its own forwarded-call shape lexes cleanly (`_call_shape`), and
    - its callee is already a recognized intrinsic once put through
      `knowledge.normalize` (chain ends here, this definition's own shape
      *is* its composed shape) — or its callee is itself a name that
      resolves (recursively, through this same function, with `name` added
      to `seen`), in which case this definition's composed shape is that
      inner result's shape with each of *its* markers substituted by this
      definition's own per-argument shape (`_substitute_shape`) — i.e. what
      this definition actually supplies for each of the inner macro's
      parameters, still expressed in this definition's *own* parameter
      markers, so it stays comparable against this same name's other
      definitions.

    `definition_counts[name]` must equal the number of `ReparsedMacro`
    entries `macros_by_name` has for `name` — built from
    `_definition_positions`, which counts every `preproc_function_def` node
    regardless of whether it has a body, so a name with an empty-bodied
    definition among its `#if` branches never resolves: that definition
    never becomes a `ReparsedMacro` at all (see `reparse_macros`), and
    without this count check its absence from `macros_by_name[name]` would
    go unnoticed, registering the name as if every definition had agreed —
    vacuously, over a definition never seen.

    A cycle (a name that, through some chain, forwards back to itself), an
    unresolved intermediate (a callee that is neither a recognized intrinsic
    nor a name this function knows how to resolve), and an arity mismatch
    during composition (`_substitute_shape` returning None) all resolve to
    None — the alias is not registered, full stop; none of these is
    distinguished from a plain disagreement between definitions.
    """
    if name in cache:
        return cache[name]
    if name in seen:
        return None
    defs = macros_by_name.get(name)
    if not defs or len(defs) != definition_counts.get(name, -1):
        cache[name] = None
        return None

    next_seen = seen | {name}
    results: list[tuple[str, tuple[tuple[bytes, ...], ...]] | None] = []
    for macro in defs:
        callee = is_forwarding_alias(macro)
        if callee is None:
            results.append(None)
            continue
        arguments = _forwarding_call(macro).child_by_field_name("arguments")  # type: ignore[union-attr]
        shape = _call_shape(macro, arguments)
        if shape is None:
            results.append(None)
            continue
        normalized = knowledge.normalize(callee)
        if _is_intrinsic(normalized):
            # A real function call's own syntax settles `f()` unambiguously
            # (zero arguments) -- unlike a macro invocation, an intrinsic
            # has no parameter list on this side for `()` to be read
            # against, and this project tracks no arity for intrinsics to
            # consult even if it wanted to.
            results.append((normalized, () if shape is _EMPTY_ARGS else shape))
            continue
        callee_defs = macros_by_name.get(callee)
        if not callee_defs:
            results.append(None)
            continue
        arity = _callee_arity(callee_defs)
        if arity is None:
            results.append(None)
            continue
        fixed_count, variadic_start = arity
        if shape is _EMPTY_ARGS:
            # `callee()`: how many arguments this represents depends on
            # `callee`'s own declared parameter count, per C's macro
            # invocation syntax (measured directly against this project's
            # parser — see `_EmptyArgs`'s docstring). Handled for exactly
            # the two unambiguous shapes: no parameters at all (zero
            # arguments), or exactly one, no variadic pack (one argument,
            # itself empty). Anything else -- two or more fixed parameters,
            # or a variadic pack in the mix -- has no single agreed-on
            # meaning worth guessing at, so it fails closed like every other
            # uncertain case in this module.
            if fixed_count == 0:
                resolved_shape: tuple[tuple[bytes, ...], ...] = ()
            elif fixed_count == 1 and variadic_start is None:
                resolved_shape = ((),)
            else:
                results.append(None)
                continue
        else:
            # Arity at this step of the chain: how many arguments this
            # definition's call actually supplies to `callee` must match
            # how many *fixed* parameters every one of `callee`'s own
            # definitions declares -- at least that many when `callee` also
            # takes a variadic pack (the rest becomes the pack), exactly
            # that many otherwise, in *both* directions. `_substitute_shape`
            # below only ever catches a deficit among the fixed positions (a
            # marker `callee`'s own body references with no corresponding
            # argument here); it has no way to notice a *surplus* argument
            # to a non-variadic callee, since nothing in `callee`'s own
            # shape would ever reference the extra marker in the first
            # place, so the extra argument would otherwise be silently
            # discarded during composition rather than rejected. Checked
            # before recursing so it applies at every step of a chain, not
            # only the outermost call.
            if variadic_start is None:
                if len(shape) != fixed_count:
                    results.append(None)
                    continue
            elif len(shape) < fixed_count:
                results.append(None)
                continue
            resolved_shape = shape
        inner = _resolve_alias(callee, next_seen, macros_by_name, definition_counts, knowledge, cache)
        if inner is None:
            results.append(None)
            continue
        inner_target, inner_shape = inner
        composed = _substitute_shape(inner_shape, resolved_shape, variadic_start)
        results.append(None if composed is None else (inner_target, composed))

    if any(result is None for result in results) or len(set(results)) != 1:
        cache[name] = None
        return None
    cache[name] = results[0]
    return results[0]


def build_alias_map(root: Node, source: bytes, macros: list[ReparsedMacro], knowledge: Knowledge) -> AliasMap:
    """Resolve forwarding aliases to the intrinsic at the end of their chain.

    A macro name can have more than one definition in a file — different
    `#if` branches, all read regardless of which one a real build would take
    (see `reparse_macros`). Every name that has at least one `ReparsedMacro`
    entry is attempted through `_resolve_alias`, which is where the actual
    per-name agreement decision and chain composition live; see its
    docstring. Every name that resolves is registered under its resolved
    intrinsic, and *all* of its own definitions' `start_byte`s are recorded
    in `definitions` — including a name reached only as an intermediate step
    of some other name's chain (VVenC's `INNER`/`OUTER` shape: both register
    independently, `OUTER` by composing through `INNER`), since that name's
    own direct use sites and its own macro unit are governed by its own
    registration, not by whichever outer chain happened to reach it first.

    **What this does not know:** comparison throughout `_resolve_alias` is
    over each definition's *written token structure*, never over macro
    expansion. Two intermediates whose bodies are textually identical will
    always compare equal here even if one of them contains a further,
    separately-`#if`-redefined object-like macro that would make the two
    expand differently at compile time — this module has no model of the
    preprocessor beyond the one function-like macro layer it reparses.
    """
    macros_by_name: dict[str, list[ReparsedMacro]] = {}
    for macro in macros:
        macros_by_name.setdefault(macro.name, []).append(macro)
    definition_counts = {name: len(positions) for name, positions in _definition_positions(root, source).items()}

    cache: dict[str, tuple[str, tuple[tuple[bytes, ...], ...]] | None] = {}
    targets: dict[str, str] = {}
    definitions: set[int] = set()
    for name in macros_by_name:
        result = _resolve_alias(name, frozenset(), macros_by_name, definition_counts, knowledge, cache)
        if result is None:
            continue
        targets[name] = result[0]
        definitions.update(macro.start_byte for macro in macros_by_name[name])

    return AliasMap(targets=targets, definitions=definitions)
