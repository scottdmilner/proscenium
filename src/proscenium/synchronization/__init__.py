"""Synchronization: the transaction that makes one attempt, and the application layer it applies plans with.

docs/spec/pipeline.md#synchronization-transaction. proscenium.api calls it; it imports proscenium.binding's units
and proscenium.core, using what each package exports.
"""

from .transaction import synchronize

__all__ = ["synchronize"]
