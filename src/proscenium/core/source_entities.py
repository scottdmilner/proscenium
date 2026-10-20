"""Source-entity identifiers (interaction-contract.md, source-access.md#source-identity).

A source entity is identified by its prim path in the composed stage, persisted as the path
string. Inside native-instance contents that is the instance-proxy path, which carries the
instance context: two copies of a prototype's prim through different instances have different
identifiers. It is never a Hydra-generated path or an instancer index. The instance context and
the entity's floor are computed from a stage when needed, never stored, so an identifier resolves
against whichever generation is published next.
"""

from __future__ import annotations

from pxr import Sdf


def identifier(path: Sdf.Path) -> str:
    """The identifier of the entity at path. Raises ValueError if path can't name one."""
    _check(path, str(path))
    return str(path)


def entity_path(identifier: str) -> Sdf.Path:
    """The path an identifier names. Raises ValueError if it isn't one."""
    if not isinstance(identifier, str) or not Sdf.Path.IsValidPathString(identifier)[0]:
        raise ValueError(f"{identifier!r} is not a path")
    path = Sdf.Path(identifier)
    _check(path, identifier)
    return path


def _check(path: Sdf.Path, text: str) -> None:
    # An entity is a prim: not the pseudo-root, a property, or a variant selection, which is composition.
    if not path.IsAbsolutePath() or not path.IsPrimPath() or path.ContainsPrimVariantSelection():
        raise ValueError(f"{text!r} is not an absolute prim path")
    if str(path) != text:  # one spelling per entity, so equal entities have equal identifiers
        raise ValueError(f"{text!r} is not the path's own spelling, {str(path)!r}")
