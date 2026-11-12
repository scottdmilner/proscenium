"""What an operation writes to Blender data, observed three ways, for tests that it writes nothing (AFF-03).

- The depsgraph's updated IDs: what Blender itself sees changed, gathered by a depsgraph_update_post handler over a view
  layer update after the operation, with one before it, so only the operation's changes are pending. ID-property
  writes don't reach the depsgraph, so records are observed apart.
- The record writes: calls to id_property_records' write, write_items, and remove, which every record write goes
  through, by schema name.
- The datablocks created: Blender gives each new ID the next session_uid, so a probe Text made before and one after
  are as many apart as IDs were made between them, removed ones included, as a staging collection is; the update after
  a removal takes one too, so a body that removes anything counts more, never fewer.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy

from proscenium.binding.persistence import id_property_records

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import pytest


@dataclass
class ObservedWrites:
    """What the observed operation wrote; filled in as the observation ends."""

    updated_ids: list[str] = field(default_factory=list)  # the depsgraph's updated IDs, as "<type>:<name>"
    record_writes: list[str] = field(default_factory=list)  # the schema names of the records written, in order
    created_id_count: int = 0  # IDs made meanwhile, removed ones included

    @property
    def wrote_nothing(self) -> bool:
        return not self.updated_ids and not self.record_writes and self.created_id_count == 0


@contextmanager
def observed_writes(monkeypatch: pytest.MonkeyPatch) -> Iterator[ObservedWrites]:
    """Observe what the body writes to Blender data."""
    observed = ObservedWrites()

    def recording(write: Callable[..., Any]) -> Callable[..., Any]:
        def record(id_: bpy.types.ID, key: str, schema: id_property_records.Schema[Any], *rest: Any) -> Any:
            observed.record_writes.append(schema.name)
            return write(id_, key, schema, *rest)

        return record

    def updated(_scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph) -> None:
        observed.updated_ids.extend(
            f"{type(i).__name__}:{i.name}" for u in depsgraph.updates if (i := u.id) is not None
        )

    view_layer = bpy.context.view_layer
    assert view_layer is not None
    # An update after a removal uses an ID's session_uid of its own, so what's pending is flushed before the first
    # probe, and the probes are removed only once both are made.
    view_layer.update()
    first = bpy.data.texts.new("Write probe")
    view_layer.update()  # so only the body's changes are pending
    try:
        with monkeypatch.context() as patch:
            for name in ("write", "write_items", "remove"):
                patch.setattr(id_property_records, name, recording(getattr(id_property_records, name)))
            bpy.app.handlers.depsgraph_update_post.append(updated)
            try:
                yield observed
                view_layer.update()
            finally:
                bpy.app.handlers.depsgraph_update_post.remove(updated)
        second = bpy.data.texts.new("Write probe")
        observed.created_id_count = second.session_uid - first.session_uid - 1
        bpy.data.batch_remove([second])
    finally:
        bpy.data.batch_remove([first])
