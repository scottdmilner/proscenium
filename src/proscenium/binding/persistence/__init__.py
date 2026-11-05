"""Versioned records in Blender ID properties (lifecycle.md#persistence).

The lower tier of proscenium.binding: it may import only the bpy-free code. Code outside this
package uses what it exports: the records proscenium.binding.runtime, proscenium.synchronization, proscenium.api, and
proscenium.addon read and write, and the functions that read and write them. The modules below are reached only
through it (checked by tests/bpy_free/test_import_tiers.py); tests reach into them.
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
from .ledger import (
    Ledger,
    LedgerEntry,
    OriginatingOperation,
    RetryStatus,
    new_ledger_key,
    read_ledger,
    write_ledger_entries,
)
from .manifests import (
    MANIFEST_KEY,
    CopyResourceIdentity,
    Manifest,
    ManifestEntry,
    RepresentationRole,
    dependents,
    entry_keys,
    new_entry_key,
    read_manifest,
    write_manifest,
    write_manifest_entries,
)
from .records import NAMESPACE, Loaded, RefusedRecord, RefusedRecordError

__all__ = [
    "MANIFEST_KEY",
    "NAMESPACE",
    "BindingConfig",
    "BindingIndex",
    "CopyResourceIdentity",
    "CreatedBinding",
    "DestinationTag",
    "Ledger",
    "LedgerEntry",
    "Loaded",
    "Manifest",
    "ManifestEntry",
    "OriginatingOperation",
    "RefusedRecord",
    "RefusedRecordError",
    "RepresentationRole",
    "RetryStatus",
    "WrittenIndex",
    "create_binding",
    "dependents",
    "entry_keys",
    "has_config",
    "has_tag",
    "index_texts",
    "new_entry_key",
    "new_ledger_key",
    "read_configs",
    "read_index",
    "read_ledger",
    "read_manifest",
    "read_tags",
    "restore_index_entry",
    "tagged_uids",
    "write_config",
    "write_ledger_entries",
    "write_manifest",
    "write_manifest_entries",
]
