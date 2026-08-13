"""Parser-independent intermediate representation.

Rules and reporters depend on this module and never on tree-sitter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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
    result_var: str | None = None


@dataclass(frozen=True)
class Definition:
    var: str
    line: int
    value: ValueRef


@dataclass
class FunctionUnit:
    name: str
    file: str
    start_line: int
    end_line: int
    calls: list[IntrinsicCall] = field(default_factory=list)
    definitions: dict[str, list[Definition]] = field(default_factory=dict)

    def add_definition(self, definition: Definition) -> None:
        bucket = self.definitions.setdefault(definition.var, [])
        bucket.append(definition)
        bucket.sort(key=lambda d: d.line)

    def definition_before(self, var: str, line: int) -> Definition | None:
        """Latest definition of `var` strictly before `line`."""
        candidates = [d for d in self.definitions.get(var, []) if d.line < line]
        return candidates[-1] if candidates else None

    def redefined_between(self, var: str, start_line: int, end_line: int) -> bool:
        """True if `var` is defined again strictly between the two lines."""
        return any(start_line < d.line < end_line for d in self.definitions.get(var, []))

    def call_by_id(self, call_id: int) -> IntrinsicCall | None:
        for call in self.calls:
            if call.id == call_id:
                return call
        return None
