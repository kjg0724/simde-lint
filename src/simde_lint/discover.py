"""Input file collection."""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path
from typing import Iterable, Sequence

SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx"}


def _excluded(path: Path, root: Path | None, patterns: Sequence[str]) -> bool:
    """Match a pattern against the whole path or the root-relative tail of it.

    `fnmatch` anchors to the entire string, so a natural pattern like
    `tests/*` would match nothing whenever the scan root is absolute — and it
    would fail silently, which is worse than rejecting it. Matching the
    root-relative path as well, and allowing a leading `*/`, makes the pattern
    mean what a reader expects regardless of how the root was spelled.
    """
    relative: str | None = None
    if root is not None:
        try:
            relative = str(path.relative_to(root))
        except ValueError:
            relative = None

    for pattern in patterns:
        # The full path answers patterns the user anchored themselves, such as
        # `*.h` or an explicit `*/build/*`.
        if fnmatch.fnmatch(str(path), pattern):
            return True
        # Only the root-relative path gets the implicit `*/` arm. Applying it to
        # the absolute path would let a directory name sitting ABOVE the scan
        # root satisfy the pattern — `--exclude 'src/*'` under
        # `~/dev/src/project` would then exclude the entire tree, silently,
        # which is the failure this matcher exists to prevent.
        if relative is not None and (
            fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(relative, f"*/{pattern}")
        ):
            return True
    return False


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
