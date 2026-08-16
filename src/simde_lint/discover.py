"""Input file collection."""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path
from typing import Iterable, Sequence

SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx"}


def _excluded(path: Path, root: Path | None, patterns: Sequence[str]) -> bool:
    """Match a pattern against the whole path or any tail of it.

    `fnmatch` anchors to the entire string, so a natural pattern like
    `tests/*` would match nothing whenever the scan root is absolute — and it
    would fail silently, which is worse than rejecting it. Matching the
    root-relative path as well, and allowing a leading `*/`, makes the pattern
    mean what a reader expects regardless of how the root was spelled.
    """
    candidates = {str(path)}
    if root is not None:
        try:
            candidates.add(str(path.relative_to(root)))
        except ValueError:
            pass
    return any(
        fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(candidate, f"*/{pattern}")
        for candidate in candidates
        for pattern in patterns
    )


def discover_files(paths: Iterable[Path | str], exclude: Sequence[str]) -> list[Path]:
    found: list[Path] = []
    for entry in paths:
        root = Path(entry)
        if not root.exists():
            # A typo'd path would otherwise look exactly like a clean sweep.
            print(f"warning: no such path: {root}", file=sys.stderr)
            continue
        if root.is_file():
            if root.suffix in SOURCE_SUFFIXES and not _excluded(root, root.parent, exclude):
                found.append(root)
            continue
        for candidate in sorted(root.rglob("*")):
            if (
                candidate.is_file()
                and candidate.suffix in SOURCE_SUFFIXES
                and not _excluded(candidate, root, exclude)
            ):
                found.append(candidate)
    return found
