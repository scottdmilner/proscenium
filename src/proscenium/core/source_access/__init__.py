"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one.
"""

from .binding_source import BindingSource
from .sources import AttachedSource, FileSource, SourceUnavailable

__all__ = [
    "AttachedSource",
    "BindingSource",
    "FileSource",
    "SourceUnavailable",
]
