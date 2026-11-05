"""Synchronization: the transaction that makes one attempt, and the application layer it applies plans with.

docs/spec/pipeline.md#synchronization-transaction. proscenium.api calls it. It exports the transaction's module;
the application layer and prepared work are the transaction's own.
"""

from . import transaction

__all__ = ["transaction"]
