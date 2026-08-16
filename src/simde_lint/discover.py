"""Input file collection."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable, Sequence

SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx"}


def _excluded(path: Path, patterns: Sequence[str]) -> bool:
    text = str(path)
    return any(fnmatch.fnmatch(text, pattern) for pattern in patterns)


def discover_files(paths: Iterable[Path | str], exclude: Sequence[str]) -> list[Path]:
    found: list[Path] = []
    for entry in paths:
        root = Path(entry)
        if root.is_file():
            if root.suffix in SOURCE_SUFFIXES and not _excluded(root, exclude):
                found.append(root)
            continue
        for candidate in sorted(root.rglob("*")):
            if (
                candidate.is_file()
                and candidate.suffix in SOURCE_SUFFIXES
                and not _excluded(candidate, exclude)
            ):
                found.append(candidate)
    return found
