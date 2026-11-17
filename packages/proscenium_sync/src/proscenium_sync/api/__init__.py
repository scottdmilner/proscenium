"""What callers use: the binding handle and the process's bindings (source-access.md#synchronization-api).

It exports its module, bindings, which the synchronizer's registration and the extension's temporary UI import.
"""

from . import bindings

__all__ = ["bindings"]
