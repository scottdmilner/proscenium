"""Versioned records in Blender ID properties (lifecycle.md#persistence).

The bottom tier of the Blender-facing code: it may import only the bpy-free code below the tiers. Code outside this
package uses what it exports: the records proscenium.binding.runtime, proscenium.api, and proscenium.addon read and
write, and the functions that read and write them. The modules below are reached only through it (checked by
tests/bpy_free/test_import_tiers.py); tests reach into them. The exception is manifests, which only the ownership index
uses until M5 synchronizes; it imports the module itself, so the manifests aren't part of this API before then.
"""

from .binding_records import (
    BindingConfig,
    BindingIndex,
    CreatedBinding,
    DestinationTag,
    WrittenIndex,
    create_binding,
    has_config,
    has_tag,
    index_texts,
    read_configs,
    read_index,
    read_tags,
    restore_index_entry,
    tagged_uids,
    write_config,
)
from .records import NAMESPACE, Loaded, RefusedRecord, RefusedRecordError

__all__ = [
    "NAMESPACE",
    "BindingConfig",
    "BindingIndex",
    "CreatedBinding",
    "DestinationTag",
    "Loaded",
    "RefusedRecord",
    "RefusedRecordError",
    "WrittenIndex",
    "create_binding",
    "has_config",
    "has_tag",
    "index_texts",
    "read_configs",
    "read_index",
    "read_tags",
    "restore_index_entry",
    "tagged_uids",
    "write_config",
]
