"""Reparse function-like macro bodies.

tree-sitter leaves a macro body as an opaque `preproc_arg` with no children,
so nothing downstream can see the calls inside it. Each body is reparsed
inside a synthetic function wrapper, and every position maps back to the
original file by one constant offset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
    params: tuple[str, ...]
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


def reparse_macros(root: Node, source: bytes) -> list[ReparsedMacro]:
    """Reparse every function-like macro body in one file.

    A body that does not parse is returned with `ok=False` and is not guessed
    at from its text; callers treat it as neither an alias nor a unit.
    """
    macros: list[ReparsedMacro] = []
    for define in iter_nodes(root, "preproc_function_def"):
        name = node_text(define.child_by_field_name("name"), source)
        value = define.child_by_field_name("value")
        if not name or value is None:
            continue
        params = tuple(
            node_text(child, source)
            for child in (define.child_by_field_name("parameters") or define).named_children
            if child.type == "identifier"
        )
        body_start, body_end = _body_range(source, value)
        body = source[body_start:body_end]
        synthetic = _PREFIX + body + _SUFFIX
        tree = parse_source(synthetic)
        macros.append(
            ReparsedMacro(
                name=name,
                params=params,
                body_start_byte=value.start_byte,
                root=tree.root_node,
                source=synthetic,
                ok=not tree.root_node.has_error,
            )
        )
    return macros


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
    `_parameter_mapping` (which reads that same call's argument list) so the
    "single statement, single call, no nested call" shape is checked once.
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
    return macro.source[callee.start_byte : callee.end_byte].decode()


_IDENTIFIER_TOKEN = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")


def _parameter_mapping(macro: ReparsedMacro) -> str | None:
    """Normalized parameter-to-argument correspondence of a forwarding body.

    Meaningful only once `is_forwarding_alias` has already confirmed the
    body forwards to a single call (returns None otherwise, same as that
    function). Reads that call's argument-list source text and rewrites
    every token that spells one of the macro's own parameter names into a
    positional marker for that parameter's index in `macro.params` — plain
    text substitution over the argument list, not a value-flow analysis:
    `T((a), (b))` and `T((b), (a))` produce different strings (the markers
    swap position), and `T((a) + 1, (b))` differs from `T((a), (b))` (the
    `+ 1` has no counterpart on the other side). Every occurrence of a
    parameter name is rewritten, including a repeated one (`f((b), (b))`
    becomes two occurrences of the same marker), so a duplicated parameter
    and a single one used once are never mistaken for each other. The
    marker is `\x00<index>\x00` — a byte that cannot appear in C source —
    so it cannot collide with a real identifier or with an adjacent marker.

    Two definitions of the same name compare equal here exactly when they
    forward every parameter to the same position(s) of the same argument
    list shape, including argument count: a 1-parameter body that duplicates
    its single argument (`f(a, a)`) and a 2-parameter body that does not
    (`f(a, b)`) produce different marker sequences even though both are
    otherwise-faithful forwards, because the marker sequences themselves
    differ (`\x000\x00, \x000\x00` vs `\x000\x00, \x001\x00`).
    """
    expression = _forwarding_call(macro)
    if expression is None:
        return None
    arguments = expression.child_by_field_name("arguments")
    text = macro.source[arguments.start_byte : arguments.end_byte] if arguments is not None else b""
    index_by_name = {name: index for index, name in enumerate(macro.params)}

    def _replace(match: re.Match[bytes]) -> bytes:
        name = match.group(0).decode()
        index = index_by_name.get(name)
        return f"\x00{index}\x00".encode() if index is not None else match.group(0)

    return _IDENTIFIER_TOKEN.sub(_replace, text).decode(errors="replace")


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
    before this type existed. `definitions` is the `body_start_byte` (see
    `ReparsedMacro`) of every specific macro *definition* that fed a
    registered name; `extract.py`'s unit skip needs this rather than the
    name alone, because one name can have several definitions in a file —
    different `#if` branches — and only the definitions that actually agreed
    with each other and got registered may have their unit skipped. A
    same-named definition that disagreed is not in here even though its name
    is a key in `targets`, and keeps its own unit.

    Both fields are produced by the same registration pass in
    `build_alias_map` and must stay consistent with each other (every
    `targets` entry has at least one definition in `definitions`, and vice
    versa); splitting them across two functions is exactly what would let
    them drift apart, so they are returned together here instead.
    """

    targets: dict[str, str]
    definitions: frozenset[int]


def build_alias_map(macros: list[ReparsedMacro], knowledge: Knowledge) -> AliasMap:
    """Resolve forwarding aliases to the intrinsic at the end of their chain.

    A macro name can have more than one definition in a file — different
    `#if` branches, all read regardless of which one a real build would take
    (see `reparse_macros`). Pass 1 groups a name's definitions together and
    registers that name as a candidate only when *every* one of its
    definitions is itself a forwarding alias (`is_forwarding_alias` returns a
    callee for each), all of those callees agree once each is put through
    `knowledge.normalize` — the same single-step SIMDe-spelling resolution
    the final chain lookup below applies, so `simde_mm_cmpgt_epi64` and
    `_mm_cmpgt_epi64` count as the same target intrinsic even though they are
    different written names (a real case: VVenC's `DepQuantX86.h` defines
    `_my_cmpgt_epi64` this way, guarded by `#if USE_SSE41 &&
    defined(REAL_TARGET_X86)`) — and all of them have the same
    `_parameter_mapping`, the same normalized correspondence between the
    macro's own parameters and the forwarded call's argument positions. A
    name that fails any of those checks is not a candidate at all: none of
    its definitions register, all of them keep their own macro unit, and —
    since it is absent from `candidates` — a chain passing through it
    (another macro forwarding to this name) stops there rather than
    resolving past it. This agreement check is deliberately narrower than
    full chain resolution: two branches whose callees are different macro
    names that would themselves later resolve to the same intrinsic are
    *not* recognized as agreeing here, only a shared intrinsic or a shared
    `knowledge.normalize` result is.

    Pass 2 is unchanged from before this per-definition check existed: each
    candidate's callee is followed through the knowledge aliases and through
    other candidates. A chain that revisits a name is abandoned — a
    self-referential macro is legal C — and only chains ending at a
    recognized intrinsic are confirmed. Which of an agreeing name's several
    (already-agreeing) raw callees is stored as `candidates[name]` does not
    matter for this pass: `knowledge.normalize` maps every one of them to
    the same result by construction of the agreement check above.
    """
    by_name: dict[str, list[ReparsedMacro]] = {}
    for macro in macros:
        by_name.setdefault(macro.name, []).append(macro)

    candidates: dict[str, str] = {}
    definitions_by_name: dict[str, frozenset[int]] = {}
    for name, defs in by_name.items():
        callees = [is_forwarding_alias(macro) for macro in defs]
        if any(callee is None for callee in callees):
            continue
        normalized_targets = {knowledge.normalize(callee) for callee in callees}
        mappings = [_parameter_mapping(macro) for macro in defs]
        if len(normalized_targets) != 1 or len(set(mappings)) != 1:
            continue
        candidates[name] = callees[0]
        definitions_by_name[name] = frozenset(macro.body_start_byte for macro in defs)

    resolved: dict[str, str] = {}
    for name in candidates:
        seen = {name}
        current = candidates[name]
        while True:
            normalized = knowledge.normalize(current)
            if _is_intrinsic(normalized):
                resolved[name] = normalized
                break
            if current in seen or current not in candidates:
                break
            seen.add(current)
            current = candidates[current]

    definitions = frozenset(
        byte for name in resolved for byte in definitions_by_name[name]
    )
    return AliasMap(targets=resolved, definitions=definitions)
