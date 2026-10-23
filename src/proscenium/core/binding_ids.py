"""BindingId, a binding's persistent identifier (source-access.md#synchronization-api).

A NewType, so the checker tells a binding identifier from any other string, such as a source key or a
resource identifier, while at runtime it is the str that records store.
"""

from typing import NewType

BindingId = NewType("BindingId", str)
