"""
MemIris: A Python package for long-term memory management in large language models.
"""

from importlib.metadata import PackageNotFoundError, version  # pragma: no cover

try:
    dist_name = "MemIris"
    __version__ = version(dist_name)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"
finally:
    del version, PackageNotFoundError
