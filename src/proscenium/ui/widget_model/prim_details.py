"""What a widget reads of one prim, kept apart from drawing: what a row of it shows, and what its details say.

`RowDetails` is what a list row of a prim draws, cheap enough to read for each row on screen, and `PrimDetails` what
only one prim's tooltip, summary, or details panel says, its arcs' targets among them; `row_details_of` and
`prim_details_of` read them, uncached, so each widget caches them as it shows them. The children a widget lists are
those `CHILD_PREDICATE` filters: every child a stage editor shows, instance proxies included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pxr import Kind, Sdf, Usd

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from pxr import Pcp

# Every child a stage editor shows: inactive, unloaded, abstract (class), and undefined (over) prims, and the
# contents of native instances reached through instance proxies.
CHILD_PREDICATE = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)


def child_count(prim: Usd.Prim) -> int:
    """How many children a prim tree lists under a prim: its children as `CHILD_PREDICATE` filters them."""
    return len(prim.GetFilteredChildren(CHILD_PREDICATE))


@dataclass(frozen=True, slots=True)
class RowDetails:
    """What a row draws and its tooltip says, read from its prim."""

    path: Sdf.Path
    name: str
    display_name: str  # the prim's displayName metadata, or empty
    type_name: str
    model_kind: str  # the prim's kind metadata, or empty
    is_invalid_model: bool  # see _is_invalid_model
    child_count: int  # its children as the tree lists them, instance proxies included
    is_active: bool
    specifier: Sdf.Specifier
    # The composition arcs authored on the prim, as its badges show them.
    has_inherits: bool
    has_variants: bool
    has_variant_selection: bool  # whether any of its variant sets has a variant selected
    has_references: bool
    has_payload: bool
    is_loaded: bool  # false only under an unloaded payload, its own or an ancestor's
    has_specializes: bool
    is_instance: bool
    is_instanceable: bool  # instanceable metadata is set; without composition arcs, the prim isn't an instance
    is_instance_proxy: bool
    instance_path: Sdf.Path | None  # the instance an instance proxy is under
    # The outermost instance an instance proxy is under: the same, unless that one is inside another instance.
    outermost_instance_path: Sdf.Path | None

    @property
    def has_children(self) -> bool:
        """Whether the prim has any child the tree lists."""
        return self.child_count > 0

    @property
    def is_class(self) -> bool:
        """Whether the prim is a class: its strongest defining opinion is a class, not a def."""
        return self.specifier == Sdf.SpecifierClass

    @property
    def is_orphaned_over(self) -> bool:
        """Whether nothing defines the prim: a composed prim is an over only when every opinion on it is one."""
        return self.specifier == Sdf.SpecifierOver


@dataclass(frozen=True, slots=True)
class PrimDetails:
    """What the details panel and row tooltip say about one prim beyond its `RowDetails`, read when asked for."""

    inherit_paths: tuple[str, ...]
    reference_targets: tuple[str, ...]  # each as @asset@prim, or a bare prim path for an internal reference
    payload_targets: tuple[str, ...]
    specialize_paths: tuple[str, ...]
    variant_selections: tuple[tuple[str, str], ...]  # (variant set name, selection), the selection empty if unset
    prototype_path: Sdf.Path | None  # an instance's prototype
    authored_attribute_count: int


def _is_invalid_model(model_api: Usd.ModelAPI, model_kind: str) -> bool:
    """Whether a prim's kind is a model kind but USD doesn't count it a model, its ancestors not all being groups."""
    return bool(model_kind) and Kind.Registry.IsA(model_kind, Kind.Tokens.model) and not model_api.IsModel()


def row_details_of(prim: Usd.Prim) -> RowDetails:
    """A prim's `RowDetails`, read now and not cached: a tree caches its rows' (`PrimTree.details`)."""
    model_api = Usd.ModelAPI(prim)
    model_kind = str(model_api.GetKind())
    instance_path, outermost_instance_path = _instance_paths(prim)
    return RowDetails(
        path=prim.GetPath(),
        name=prim.GetName(),
        display_name=prim.GetDisplayName(),
        type_name=str(prim.GetTypeName()),
        model_kind=model_kind,
        is_invalid_model=_is_invalid_model(model_api, model_kind),
        child_count=child_count(prim),
        is_active=prim.IsActive(),
        specifier=prim.GetSpecifier(),
        has_inherits=prim.HasAuthoredInherits(),
        has_variants=prim.HasVariantSets(),
        has_variant_selection=_has_variant_selection(prim),
        has_references=prim.HasAuthoredReferences(),
        has_payload=prim.HasPayload(),
        is_loaded=prim.IsLoaded(),
        has_specializes=prim.HasAuthoredSpecializes(),
        is_instance=prim.IsInstance(),
        is_instanceable=prim.IsInstanceable(),
        is_instance_proxy=prim.IsInstanceProxy(),
        instance_path=instance_path,
        outermost_instance_path=outermost_instance_path,
    )


def _instance_paths(prim: Usd.Prim) -> tuple[Sdf.Path | None, Sdf.Path | None]:
    """The nearest and the outermost instance above an instance proxy, or Nones for a prim that isn't one."""
    if not prim.IsInstanceProxy():
        return None, None
    nearest_path: Sdf.Path | None = None
    outermost_path: Sdf.Path | None = None
    ancestor = prim.GetParent()
    while ancestor.IsInstanceProxy() or ancestor.IsInstance():  # an instance proxy is always under one
        if ancestor.IsInstance():
            nearest_path = nearest_path or ancestor.GetPath()
            outermost_path = ancestor.GetPath()
        ancestor = ancestor.GetParent()
    return nearest_path, outermost_path


def _has_variant_selection(prim: Usd.Prim) -> bool:
    if not prim.HasVariantSets():
        return False
    variant_sets = prim.GetVariantSets()
    return any(variant_sets.GetVariantSelection(name) for name in variant_sets.GetNames())


def _composition_nodes(node: Pcp.NodeRef) -> Iterator[Pcp.NodeRef]:
    """A prim index's nodes from a node down, in strength order."""
    yield node
    for child in node.children:
        yield from _composition_nodes(child)


@dataclass(frozen=True, slots=True)
class _ComposedArcs:
    """The arcs a prim's specs compose, a list per arc type, which a row's tooltip names."""

    inherit_paths: list[Sdf.Path]
    references: list[Sdf.Reference]
    payloads: list[Sdf.Payload]
    specialize_paths: list[Sdf.Path]


def _node_arcs(specs: list[Sdf.PrimSpec], field_key: str) -> list[Any]:
    """One composition node's items for an arc's list field (`Sdf.PrimSpec`'s key), from its specs, weakest first."""
    node_arcs: list[Any] = []
    for spec in specs:
        if spec.HasInfo(field_key):
            node_arcs = spec.GetInfo(field_key).ApplyOperations(node_arcs)
    return node_arcs


def _composed_arcs(prim: Usd.Prim) -> _ComposedArcs:
    """A prim's arcs, as Pcp composes them.

    Each composition node composes its own layer stack's list edits, weakest layer first, so a stronger layer's
    deletion or explicit list overrides a weaker one's; a node a reference brings in keeps its own arcs, which the
    referencing layers can't edit. One walk of the nodes and their specs serves every arc type.
    """
    arcs = _ComposedArcs(inherit_paths=[], references=[], payloads=[], specialize_paths=[])
    for node in _composition_nodes(prim.GetPrimIndex().rootNode):
        specs = [spec for layer in reversed(node.layerStack.layers) if (spec := layer.GetPrimAtPath(node.path))]
        arcs.inherit_paths.extend(_node_arcs(specs, Sdf.PrimSpec.InheritPathsKey))
        arcs.references.extend(_node_arcs(specs, Sdf.PrimSpec.ReferencesKey))
        arcs.payloads.extend(_node_arcs(specs, Sdf.PrimSpec.PayloadKey))
        arcs.specialize_paths.extend(_node_arcs(specs, Sdf.PrimSpec.SpecializesKey))
    return arcs


def _arc_targets(arcs: Sequence[Sdf.Reference | Sdf.Payload]) -> tuple[str, ...]:
    """The targets composed references or payloads name."""
    return tuple(f"@{arc.assetPath}@{arc.primPath}" if arc.assetPath else str(arc.primPath) for arc in arcs)


def _arc_paths(paths: list[Sdf.Path]) -> tuple[str, ...]:
    """The prim paths composed inherits or specializes name."""
    return tuple(str(path) for path in paths)


def prim_details_of(prim: Usd.Prim) -> PrimDetails:
    """A prim's `PrimDetails`, its arcs' targets among them, read now, uncached (`PrimTree.prim_details` caches)."""
    arcs = _composed_arcs(prim)
    variant_sets = prim.GetVariantSets()
    return PrimDetails(
        inherit_paths=_arc_paths(arcs.inherit_paths),
        reference_targets=_arc_targets(arcs.references),
        payload_targets=_arc_targets(arcs.payloads),
        specialize_paths=_arc_paths(arcs.specialize_paths),
        variant_selections=tuple((name, variant_sets.GetVariantSelection(name)) for name in variant_sets.GetNames()),
        prototype_path=prim.GetPrototype().GetPath() if prim.IsInstance() else None,
        authored_attribute_count=len(prim.GetAuthoredAttributes()),
    )
