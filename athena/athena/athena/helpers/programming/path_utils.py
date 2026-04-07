from pathlib import Path
from typing import Union


def ensure_safe_path(root: Path, relative: Union[str, Path], ignore_git: bool = True) -> Path:
    """
    Resolve a candidate path under `root` and ensure it does not escape the root
    directory and, optionally, does not traverse into .git internals.

    - Returns the resolved absolute Path if safe.
    - Raises ValueError if the path escapes `root` or violates `ignore_git`.
    """
    resolved_root = root.resolve()
    candidate = (resolved_root / Path(relative)).resolve()

    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Path escapes repository root: {relative!r}") from exc

    if ignore_git and any(part.lower() == ".git" for part in candidate.parts):
        raise ValueError(f"Path targets .git internals: {relative!r}")

    return candidate
