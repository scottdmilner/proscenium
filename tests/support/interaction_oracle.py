"""Expected interaction results, from USD's own APIs on the composed stage (interaction-contract.md).

M2 provides it with the interaction fixtures (fixtures/interaction.py); M4 writes the
checks of each representation's headless functions against it, and M7 and M10 reuse them.

Nothing here reads a display: hierarchy and kinds come from the stage (Usd.ModelAPI,
Kind.Registry), and what the viewport displays from UsdGeom.Imageable's effective visibility
for each prim's purpose, with instance-proxy traversal. Paths are strings. Inside native-instance
contents an entity is named by its instance-proxy path, which carries its instance
context; checks translate to and from the implementation's encoding.
"""

from __future__ import annotations

from dataclasses import dataclass

from pxr import Kind, Sdf, Tf, Usd, UsdGeom

GPRIM = Tf.Type.Find(UsdGeom.Gprim)
# The viewport's purposes (visibility.md#visibility-and-purpose). A guide is in it only when explicitly visible, which
# effective visibility gives: guideVisibility falls back to invisible, unlike proxyVisibility.
VIEWPORT_PURPOSES = frozenset({UsdGeom.Tokens.default_, UsdGeom.Tokens.proxy, UsdGeom.Tokens.guide})


def all_paths(stage: Usd.Stage) -> list[str]:
    """Every composed prim, including instance proxies, inactive, unloaded, and abstract prims."""
    prims = Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate))
    return [str(prim.GetPath()) for prim in prims]


def display_elements(stage: Usd.Stage, time: float) -> frozenset[str]:
    """Gprims with a viewport display element at `time`, one per copy through instancing.

    Unsupported gprim types count: they display as placeholders or empty markers
    (visibility.md#models-and-unsupported-content).
    """
    found = set()
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)):
        if not prim.IsA(GPRIM):
            continue
        imageable = UsdGeom.Imageable(prim)
        purpose = imageable.ComputePurposeInfo().purpose
        if purpose not in VIEWPORT_PURPOSES:
            continue
        if imageable.ComputeEffectiveVisibility(purpose, Usd.TimeCode(time)) != UsdGeom.Tokens.invisible:
            found.add(str(prim.GetPath()))
    return frozenset(found)


def floor(stage: Usd.Stage, path: str) -> str:
    """The outermost native-instance root enclosing `path`, or `path` itself outside instance contents."""
    for prefix in Sdf.Path(path).GetPrefixes():
        if stage.GetPrimAtPath(prefix).IsInstance():
            return str(prefix)
    return path


@dataclass(frozen=True)
class Generation:
    """What the contract expects of one published generation of a stage at a time code."""

    time: float
    elements: frozenset[str]  # display elements (instance-proxy paths inside instance contents)
    floors: dict[str, str]  # element -> its floor
    universe: frozenset[str]

    def beneath(self, target: str) -> frozenset[str]:
        """Display elements of the target's subtree, or none when the target is not in the universe."""
        if target not in self.universe:
            return frozenset()
        root = Sdf.Path(target)
        return frozenset(e for e in self.elements if Sdf.Path(e).HasPrefix(root))


def generation(stage: Usd.Stage, time: float) -> Generation:
    """The expected generation of `stage` at `time`: its display elements, their floors, and the universe."""
    elements = display_elements(stage, time)
    floors = {e: floor(stage, e) for e in elements}
    universe = {str(p) for f in floors.values() for p in Sdf.Path(f).GetPrefixes()}
    return Generation(time, elements, floors, frozenset(universe))


def kind_target(stage: Usd.Stage, floor_path: str, level: str | None) -> str:
    """The selection target of a floor: itself at the prim level (None), else its nearest kind match.

    At a kind level, the nearest ancestor-or-self on the stage whose kind is `level`
    or derives from it; the floor when there is none or the floor is absent.
    """
    prim = stage.GetPrimAtPath(floor_path)
    if level is None or not prim:
        return floor_path
    while prim and not prim.IsPseudoRoot():
        kind = Usd.ModelAPI(prim).GetKind()
        if kind and Kind.Registry.IsA(kind, level):
            return str(prim.GetPath())
        prim = prim.GetParent()
    return floor_path


def levels() -> list[str | None]:
    """Every selection level: the prim level (None) and each registered model kind."""
    return [None, *sorted(Kind.Registry.GetAllKinds())]
