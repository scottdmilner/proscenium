"""What callers use: the binding handle and the process's bindings (source-access.md#synchronization-api).

It exports its module, bindings, which proscenium.addon imports.
"""

from . import bindings

__all__ = ["bindings"]
