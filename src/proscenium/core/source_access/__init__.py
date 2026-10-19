"""Source access: the stages a binding reads its source from (docs/spec/source-access.md).

The compiled core receives a stage from here; it never opens one.
"""

from .binding_source import BindingSource
from .sources import FileSource, SourceUnavailable

__all__ = [
    "BindingSource",
    "FileSource",
    "SourceUnavailable",
]
