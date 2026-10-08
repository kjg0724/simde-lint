"""What a warning about an incomplete run says about itself.

Separate from `analyze` because `symbols` produces one and `analyze` imports
`symbols`, not the other way round.
"""

from __future__ import annotations


class Diagnostic(str):
    """A warning about an incomplete run, carrying why without ceasing to be
    a message.

    Two things go wrong in a sweep and they are not the same thing. A
    FAILURE is the tool breaking on input it should have handled: a file it
    could not read, an extraction that raised, a rule that raised. An
    UNPARSED is tree-sitter declining to parse a construct, recovering, and
    returning a tree anyway -- the tool worked, and the findings it produced
    are real; what is missing is the assurance that they are all of them.

    A SHADOWED is a third of the same kind as UNPARSED: a `#define` of a
    word the symbol index reads a declaration's meaning off, which withdraws
    every mask spelled with that word. The run is complete and the findings
    are real; what is missing is the resolution those declarations would
    otherwise have had, and grade C is the honest result.

    Only a FAILURE may set the exit code. Preprocessor-heavy C++ makes
    UNPARSED the normal case rather than the exceptional one -- 362 of
    SVT-AV1's 561 files at the pinned revision -- so an exit code that
    counted them would be 1 on nearly every real sweep and would say
    nothing.

    Subclassing `str` rather than wrapping it keeps every existing consumer
    working unchanged: these are still printed, still substring-matched,
    still collected into a plain list.
    """

    FAILURE = "failure"
    UNPARSED = "unparsed"
    SHADOWED = "shadowed"

    kind: str

    def __new__(cls, message: str, kind: str) -> "Diagnostic":
        diagnostic = super().__new__(cls, message)
        diagnostic.kind = kind
        return diagnostic


def is_failure(diagnostic: str) -> bool:
    """Whether a diagnostic means the tool broke, rather than that a file
    did not fully parse. A plain string counts as a failure: it predates the
    distinction, and treating an unlabelled warning as benign would be the
    unsafe direction."""
    return getattr(diagnostic, "kind", Diagnostic.FAILURE) == Diagnostic.FAILURE
