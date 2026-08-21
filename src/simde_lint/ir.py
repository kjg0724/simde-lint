"""Parser-independent intermediate representation.

Rules and reporters depend on this module and never on tree-sitter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class ValueKind(str, Enum):
    LITERAL_VECTOR = "literal_vector"
    CALL_RESULT = "call_result"
    VARIABLE = "variable"
    SYMBOL = "symbol"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ValueRef:
    kind: ValueKind
    text: str
    lanes: tuple[int, ...] | None = None
    call_id: int | None = None
    symbol: str | None = None


@dataclass(frozen=True)
class IntrinsicCall:
    id: int
    name: str
    raw_name: str
    args: tuple[ValueRef, ...]
    line: int
    column: int
    start_byte: int
    result_var: str | None = None


@dataclass(frozen=True)
class Definition:
    var: str
    line: int
    start_byte: int
    available_after_byte: int
    value: ValueRef


class AnalysisUnit(Protocol):
    """What a rule may read from a unit of analysis.

    `FunctionUnit` and `MacroUnit` are the two implementations. A rule takes
    this protocol, not either concrete class, so a rule written against
    function bodies works unchanged against macro bodies.
    """

    name: str
    file: str
    scope: str
    calls: list[IntrinsicCall]
    definitions: dict[str, list[Definition]]

    def definition_before(self, var: str, position: int) -> Definition | None: ...
    def redefined_between(self, var: str, start: int, end: int) -> bool: ...
    def call_by_id(self, call_id: int) -> IntrinsicCall | None: ...


class MutableAnalysisUnit(AnalysisUnit, Protocol):
    """What extraction additionally needs, beyond what a rule may read."""

    def add_definition(self, definition: Definition) -> None: ...


@dataclass(kw_only=True)
class _UnitBase:
    """Def-use machinery shared by `FunctionUnit` and `MacroUnit`.

    Both units order definitions the same way and answer the same queries;
    keeping the body here means the two implementations of `AnalysisUnit`
    cannot drift apart from each other.

    `kw_only=True` on this class and both subclasses is deliberate: before it,
    `FunctionUnit`'s constructor accepted `(name, file, start_line, end_line,
    ...)` positionally, and this refactor changed that order to
    `(name, file, calls, definitions, start_line, end_line, scope)` with
    `start_line`/`end_line` now defaulted. A caller still passing positionally
    would silently assign `calls=<int>, definitions=<int>` instead of raising.
    Keyword-only construction makes that hazard impossible instead of merely
    unlikely.
    """

    name: str
    file: str
    calls: list[IntrinsicCall] = field(default_factory=list)
    definitions: dict[str, list[Definition]] = field(default_factory=dict)

    def add_definition(self, definition: Definition) -> None:
        bucket = self.definitions.setdefault(definition.var, [])
        bucket.append(definition)
        bucket.sort(key=lambda d: d.available_after_byte)

    def definition_before(self, var: str, position: int) -> Definition | None:
        """Latest definition of `var` available strictly before `position`.

        Positions are byte offsets, not lines. A definition becomes available
        only once its right-hand side has been evaluated, so `x = f(x, ...)`
        does not see itself, and two definitions on one physical line stay
        ordered.
        """
        candidates = [d for d in self.definitions.get(var, []) if d.available_after_byte < position]
        return candidates[-1] if candidates else None

    def redefined_between(self, var: str, start: int, end: int) -> bool:
        """True if `var` is redefined strictly between two byte offsets."""
        return any(start < d.available_after_byte < end for d in self.definitions.get(var, []))

    def call_by_id(self, call_id: int) -> IntrinsicCall | None:
        for call in self.calls:
            if call.id == call_id:
                return call
        return None


@dataclass(kw_only=True)
class FunctionUnit(_UnitBase):
    start_line: int = 0
    end_line: int = 0
    scope: str = "function"


@dataclass(kw_only=True)
class MacroUnit(_UnitBase):
    """A `#define` function-like macro body whose calls are analysed.

    Symbol state is never shared with a `FunctionUnit`: a variable named
    `tmp` inside a macro and a `tmp` inside a function query separate
    `definitions` dicts and cannot satisfy each other's def-use lookups.
    `name` holds the macro's name, same as `macro_name` — a rule that reports
    `unit.name` therefore needs no special case for macro-scoped findings.
    """

    macro_name: str = ""
    scope: str = "macro"
