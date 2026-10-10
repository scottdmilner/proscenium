"""Inventory ALab's entry.usda under each payload policy.

    PROSCENIUM_ALAB_ROOT=/path/to/ALab uv run python tools/alab_inventory.py

Writes docs/testing/alab/inventory.md, which is committed, and the full counts with
the per-prototype list to build/alab/inventory-{load-all,load-none}.json, which are
not (docs/testing/acceptance.md#production-scale-validation-alab). Counts prim types,
applied schemas, kinds, and shader IDs over the default traversal (active,
loaded, defined, non-abstract prims). Native-instance prototypes are counted
apart from the rest of the stage, once each ("unique") and multiplied by the
number of times the composed scene uses them ("expanded", which counts nested
uses through the instances that contain them). Output is deterministic: no
timings, and prototypes are named by their first use in scene paths, not by
their generated /__Prototype_N paths.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pxr import Sdf, Usd, UsdShade

if TYPE_CHECKING:
    from collections.abc import Iterable

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "docs" / "testing" / "alab" / "inventory.md"
DETAIL = ROOT / "build" / "alab"  # gitignored
POLICIES = {"load-all": Usd.Stage.LoadAll, "load-none": Usd.Stage.LoadNone}


class _Counts:
    """Tallies over a set of prims: total, and per type, applied schema, kind, and shader ID."""

    def __init__(self) -> None:
        self.prims = 0
        self.types: Counter[str] = Counter()
        self.schemas: Counter[str] = Counter()
        self.kinds: Counter[str] = Counter()
        self.shaders: Counter[str] = Counter()

    def add(self, prim: Usd.Prim, times: int = 1) -> None:
        """Count one prim, `times` times."""
        self.prims += times
        self.types[str(prim.GetTypeName()) or "(typeless)"] += times
        for schema in prim.GetAppliedSchemas():
            self.schemas[schema] += times
        if kind := Usd.ModelAPI(prim).GetKind():
            self.kinds[kind] += times
        if prim.GetTypeName() == "Shader":
            self.shaders[_shader_id(UsdShade.Shader(prim))] += times

    def merge(self, other: _Counts, times: int) -> None:
        """Add another tally `times` times: a prototype's contents, once per use."""
        self.prims += other.prims * times
        for mine, theirs in [
            (self.types, other.types),
            (self.schemas, other.schemas),
            (self.kinds, other.kinds),
            (self.shaders, other.shaders),
        ]:
            for key, n in theirs.items():
                mine[key] += n * times

    def to_json(self) -> dict[str, Any]:
        """Plain dicts with sorted keys, so the output is stable across runs."""
        return {
            "prims": self.prims,
            "types": dict(sorted(self.types.items())),
            "applied_schemas": dict(sorted(self.schemas.items())),
            "kinds": dict(sorted(self.kinds.items())),
            "shader_ids": dict(sorted(self.shaders.items())),
        }


def _shader_id(shader: UsdShade.Shader) -> str:
    """info:id, or the implementation source for shaders defined by an asset or code instead."""
    if shader_id := shader.GetShaderId():
        return str(shader_id)
    return f"({shader.GetImplementationSource()})"  # sourceAsset or sourceCode, no info:id


def _containing_prototype(prim: Usd.Prim) -> Usd.Prim:
    """For a prim inside a prototype, that prototype: its root ancestor, /__Prototype_N."""
    return prim.GetStage().GetPrimAtPath(prim.GetPath().GetPrefixes()[0])


def inventory(entry: Path, load: Usd.Stage.InitialLoadSet) -> dict[str, Any]:
    """The inventory of one stage under one load policy, as JSON-compatible data.

    Counts the scene outside prototypes and each prototype's contents separately,
    works out how often the scene uses each prototype, and checks the totals
    against a traversal through instance proxies before returning.
    """
    # Opened outside any stage cache, so the counts reflect a fresh open of the files.
    with Usd.StageCacheContext(Usd.BlockStageCaches):
        stage = Usd.Stage.Open(str(entry), load)

    # Instances count only where the default traversal reaches them: under load-none,
    # instances below an unloaded payload still have prototypes, but are not loaded.
    reached: set[Sdf.Path] = set()

    def walk(prims: Iterable[Usd.Prim], counts: _Counts) -> None:
        for prim in prims:
            counts.add(prim)
            if prim.IsInstance():
                reached.add(prim.GetPath())

    # The default traversal stops at instance roots, so prototype contents are not in `scene`.
    scene = _Counts()
    walk(Usd.PrimRange.Stage(stage, Usd.PrimDefaultPredicate), scene)
    # Each prototype's contents, counted once; they are multiplied by their uses below.
    contents: dict[Sdf.Path, _Counts] = {}
    for proto in stage.GetPrototypes():
        contents[proto.GetPath()] = _Counts()
        prims = iter(Usd.PrimRange(proto, Usd.PrimDefaultPredicate))
        next(prims)  # the prototype root stands for the instance prim, already counted in its parent
        walk(prims, contents[proto.GetPath()])

    def instances(proto_path: Sdf.Path) -> list[Usd.Prim]:
        """The prototype's instances that the traversal reached, in the scene or in other prototypes."""
        return [i for i in stage.GetPrimAtPath(proto_path).GetInstances() if i.GetPath() in reached]

    @cache
    def uses(proto_path: Sdf.Path) -> int:
        """Times the loaded scene uses this prototype, through nested instances too."""
        # An instance inside another prototype is used once per use of that outer prototype.
        total = 0
        for instance in instances(proto_path):
            total += uses(_containing_prototype(instance).GetPath()) if instance.IsInPrototype() else 1
        return total

    @cache
    def first_use(proto_path: Sdf.Path) -> str:
        """The smallest scene path through which the prototype is reached.

        Prototype paths (/__Prototype_N) can differ between runs, so the listing names
        each prototype by a path in the scene instead: an instance's own path, or for a
        nested instance, the outer prototype's first use plus the path inside it.
        """
        paths = []
        for instance in instances(proto_path):
            if not instance.IsInPrototype():
                paths.append(str(instance.GetPath()))
            elif uses(outer := _containing_prototype(instance).GetPath()):
                paths.append(f"{first_use(outer)}/{instance.GetPath().MakeRelativePath(outer)}")
        assert paths, f"{proto_path} has uses but no reachable instance"  # uses() > 0 guarantees one
        return min(paths)

    unique, expanded, listing = _Counts(), _Counts(), []
    for path, counts in contents.items():
        if not (n := uses(path)):
            continue  # only below unloaded payloads: composed, but not displayed under this policy
        unique.merge(counts, 1)
        expanded.merge(counts, n)
        listing.append(
            {
                "first_use": first_use(path),
                "instances": len(instances(path)),
                "uses": n,
                "prims": counts.prims,
                "nested_instances": sum(i.IsInPrototype() for i in instances(path)),
            }
        )

    # Self-check: a traversal through instance proxies visits every prototype prim once per
    # use, so it must equal the scene count plus the expanded prototype count.
    proxied = sum(1 for _ in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)))
    if proxied != scene.prims + expanded.prims:
        raise RuntimeError(f"expanded count {scene.prims + expanded.prims} != instance-proxy traversal {proxied}")
    composed = Usd.TraverseInstanceProxies(Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract)
    return {
        "entry": entry.name,
        "usd_version": ".".join(map(str, Usd.GetVersion())),
        "load": "all" if load == Usd.Stage.LoadAll else "none",
        "stage": {
            "layers_used": len(stage.GetUsedLayers()),
            # Active, defined, non-abstract prims through instance proxies, loaded or not.
            "prims_ignoring_load": sum(1 for _ in Usd.PrimRange.Stage(stage, composed)),
            "prototypes_unreached": len(contents) - len(listing),
            "start_time_code": stage.GetStartTimeCode(),
            "end_time_code": stage.GetEndTimeCode(),
            "meters_per_unit": stage.GetMetadata("metersPerUnit"),
            "up_axis": stage.GetMetadata("upAxis"),
        },
        "outside_prototypes": scene.to_json(),
        "prototypes_unique": unique.to_json(),
        "prototypes_expanded": expanded.to_json(),
        "prototypes": sorted(listing, key=lambda p: p["first_use"]),
    }


# The three tallies in each inventory, and their column labels in inventory.md.
_PARTS = ("outside_prototypes", "prototypes_unique", "prototypes_expanded")
_LABELS = ("scene", "proto", "expanded")


def _table(title: str, key: str, results: dict[str, dict[str, Any]]) -> list[str]:
    """One row per name: outside prototypes / unique / expanded, for each policy."""
    names = sorted({n for r in results.values() for part in _PARTS for n in r[part][key]})
    head = " | ".join(f"{policy} {label}" for policy in results for label in _LABELS)
    lines = [f"### {title}", "", f"| Name | {head} |", "|---" * (1 + len(results) * len(_PARTS)) + "|"]
    for name in names:
        cells = [str(r[part][key].get(name, "")) for r in results.values() for part in _PARTS]
        lines.append(f"| `{name}` | {' | '.join(cells)} |")
    return [*lines, ""]


def summary(results: dict[str, dict[str, Any]]) -> str:
    """inventory.md: generated tables comparing the policies."""
    lines = [
        "# ALab inventory",
        "",
        "Generated by `tools/alab_inventory.py`; do not edit. The tree is pinned by [subtrees.sha256](subtrees.sha256)",
        "and described in [README.md](README.md). Full counts, with each prototype's first use and instance counts,",
        "are written to `build/alab/` (not committed).",
        "",
        "Columns per policy: **scene** counts prims outside native-instance prototypes; **proto** counts each",
        "prototype's contents once; **expanded** multiplies them by the number of times the composed scene uses",
        "each prototype, through nested instances too. Instance roots themselves are scene prims. Only prims",
        "the default traversal reaches (active, loaded, defined, non-abstract) are counted; scene plus expanded",
        "equals a traversal through instance proxies, which the script checks.",
        "",
        "| | " + " | ".join(results) + " |",
        "|---" * (1 + len(results)) + "|",
    ]
    # Overview rows: (label, value for one policy's inventory).
    rows = [
        ("Layers used", lambda r: r["stage"]["layers_used"]),
        ("Composed prims, loaded or not (through instance proxies)", lambda r: r["stage"]["prims_ignoring_load"]),
        ("Prims outside prototypes", lambda r: r["outside_prototypes"]["prims"]),
        ("Prototypes used by loaded instances", lambda r: len(r["prototypes"])),
        ("Prototypes only below unloaded payloads", lambda r: r["stage"]["prototypes_unreached"]),
        ("Instances inside other prototypes", lambda r: sum(p["nested_instances"] for p in r["prototypes"])),
        ("Prototype prims (unique)", lambda r: r["prototypes_unique"]["prims"]),
        ("Prototype prims (expanded)", lambda r: r["prototypes_expanded"]["prims"]),
    ]
    lines += [f"| {label} | " + " | ".join(str(get(r)) for r in results.values()) + " |" for label, get in rows]
    first = next(iter(results.values()))
    stage = first["stage"]
    lines += [
        "",
        f"USD {first['usd_version']}; time codes {stage['start_time_code']}–{stage['end_time_code']}; "
        f"metersPerUnit {stage['meters_per_unit']}; upAxis {stage['up_axis']}.",
        "",
    ]
    lines += _table("Prim types", "types", results)
    lines += _table("Applied schemas", "applied_schemas", results)
    lines += _table("Kinds", "kinds", results)
    lines += _table("Shader IDs", "shader_ids", results)
    return "\n".join(lines)


def inventories(entry: Path) -> dict[str, dict[str, Any]]:
    """The inventory under each payload policy."""
    return {policy: inventory(entry, load) for policy, load in POLICIES.items()}


def main() -> int:
    """Write the committed summary and the uncommitted JSON detail."""
    if not (alab := os.environ.get("PROSCENIUM_ALAB_ROOT")):
        raise SystemExit("set PROSCENIUM_ALAB_ROOT to the directory holding entry.usda")
    results = inventories(Path(alab) / "entry.usda")
    SUMMARY.write_text(summary(results), encoding="utf-8")
    DETAIL.mkdir(parents=True, exist_ok=True)
    for policy, result in results.items():
        (DETAIL / f"inventory-{policy}.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {SUMMARY.relative_to(ROOT)} and {DETAIL.relative_to(ROOT)}/inventory-{{{','.join(results)}}}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
