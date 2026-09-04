"""Shared rule interface.

A rule sees only the IR plus the knowledge tables and the symbol index. Rules
never import each other, and the registry never merges their output: one
source location may legitimately produce several findings of different types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from ..finding import Finding
from ..ir import AnalysisUnit, IntrinsicCall
from ..knowledge import Knowledge
from ..symbols import SymbolIndex


def location_fields(unit: AnalysisUnit) -> dict[str, str | None]:
    """The three `Finding` fields every rule must copy from its unit, together.

    `CONTRIBUTING.md`'s enumeration of what a rule reads from `AnalysisUnit`
    once omitted `function_name`/`macro_name` — the two members every rule
    actually needs, because every `Finding` construction site hand-writes
    `function=unit.function_name, scope=unit.scope, macro=unit.macro_name`.
    A rule that instead reached for `unit.name` (following the shorter list
    literally) silently produced `scope='function', function=<macro name>,
    macro=None` on a macro unit — indistinguishable from a real function
    finding in the text report, and `Finding.__post_init__` does not catch
    it (it enforces internal consistency between `scope`/`function`/`macro`,
    not correspondence with the unit that produced them).

    Splatting this into every `Finding(...)` call makes the omission
    structurally impossible instead of merely undocumented: there is no
    "unit.name" to reach for by mistake once these three always travel
    together.
    """
    return {
        "function": unit.function_name,
        "scope": unit.scope,
        "macro": unit.macro_name,
    }


@dataclass
class Context:
    symbols: SymbolIndex
    knowledge: Knowledge
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Option:
    """One `--config` key a rule accepts, declared rather than parsed.

    Data, not behaviour: the rule states what it takes and the validator
    enforces it, so nothing outside a rule has to know that rule's options and
    no rule has to implement a hook that exists only for validation.

    `minimum` is inclusive. A rule reads the validated value straight out of
    `ctx.config` and does not re-parse it -- two interpretations of the same
    key is how a validated config and an executed one drift apart.
    """

    name: str
    type: type
    default: object
    minimum: int | None = None


class Rule(Protocol):
    type: str
    rule_id: str
    mechanism: str
    # Every registered rule declares this, even when empty, so the union of
    # accepted keys is knowable without asking each rule in turn.
    options: tuple[Option, ...]

    def match(self, unit: AnalysisUnit, ctx: Context) -> Iterator[Finding]: ...


def own_availability(unit: AnalysisUnit, call: IntrinsicCall) -> int:
    """Byte offset after which `call`'s own bound result becomes available.

    A rule asking `redefined_between(call.result_var, call.start_byte, ...)`
    means "did something else overwrite this after `call` produced it" — but
    `call.start_byte` is where the call begins, not where its result becomes
    available, and the binding `Definition` it creates always has a later
    `available_after_byte`. Anchoring at `call.start_byte` therefore makes
    that same definition look like a redefinition of itself. The producing
    call and its binding definition share `start_byte` (extraction sets the
    definition's `start_byte` from the call's), so that identity finds the
    right definition and its `available_after_byte` is the correct anchor.
    """
    for definition in unit.definitions.get(call.result_var, ()):
        if definition.start_byte == call.start_byte:
            return definition.available_after_byte
    return call.start_byte


def raw_name_if_aliased(call: IntrinsicCall) -> str | None:
    """The call's original spelling, when the rule matched it under an alias.

    A finding's `intrinsic` field is always the resolved canonical name, so
    grepping the source for that exact spelling finds nothing at a
    macro-aliased call site (VVenC's `_my_cmpgt_epi64`, for instance, which
    resolves to `_mm_cmpgt_epi64`). Returns None when the raw spelling and
    the resolved name are the same, so an unaliased finding carries no
    redundant field.
    """
    return call.raw_name if call.raw_name != call.name else None


class ConfigError(ValueError):
    """A `--config` value the tool will not act on.

    Raised before any source is read. A config that cannot be honoured must
    not produce a report: a run that silently ignored what it was asked to do
    looks exactly like one that did it.
    """


def validate_config(config: dict, rules) -> dict:
    """Check `config` against what `rules` declare, and fill in defaults.

    Unknown keys are an error rather than a warning. An older version that
    quietly accepts a newer option claims to have honoured a configuration it
    did not implement; failing tells the reader to upgrade instead. Ignoring
    requested behaviour is not forward compatibility.
    """
    declared: dict[str, Option] = {}
    for rule in rules:
        for option in getattr(rule, "options", ()):
            if option.name in declared:
                raise ConfigError(
                    f"{option.name} is declared by more than one rule; "
                    "config keys must be unique across rules"
                )
            declared[option.name] = option

    if not isinstance(config, dict):
        raise ConfigError(
            f"config must be a JSON object, not {type(config).__name__}"
        )

    for key in config:
        if key not in declared:
            known = ", ".join(sorted(declared)) or "none"
            raise ConfigError(f"unsupported option {key!r}; this version accepts: {known}")

    resolved: dict[str, object] = {}
    for name, option in declared.items():
        if name not in config:
            resolved[name] = option.default
            continue
        value = config[name]
        # `bool` is a subclass of `int`, and `true` is not a threshold.
        if isinstance(value, bool) or type(value) is not option.type:
            raise ConfigError(
                f"{name} must be {option.type.__name__}, "
                f"not {type(value).__name__}"
            )
        if option.minimum is not None and value < option.minimum:
            raise ConfigError(f"{name} must be at least {option.minimum}, not {value}")
        resolved[name] = value
    return resolved
