"""One prim's properties as the rows a property list shows: each property, and under it its targets while it's expanded.

Every property the prim has shows, its schema's unauthored ones too, in the prim's property order. A relationship's
targets, and an attribute's connections, are its targets: a property that has any has a chevron, and expanding it
splices a row for each target in after its own. What a row draws (`PropertyDetails`) is read from the property when
the row is first drawn, at the list's time code, and what only the metadata panel shows (`PropertyMetadata`) when
first asked for; both are cached until the stage or the time code changes. These two records are all the list reads of
a property: what it says about one (property_descriptions) is worded from them alone.

A list holds its prim and never its stage, so it never keeps a stage alive. It's rebuilt, not refreshed, when the
stage recomposes: a prim's property count is small, and a recomposed prim is a new `Usd.Prim`.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pxr import Gf, Sdf, Usd, UsdGeom

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


@dataclass(frozen=True, slots=True)
class PropertyRow:
    """One visible row: a property's own, or one of its targets' under it."""

    name: str  # the property's
    target_path: Sdf.Path | None = None  # a target row's target; None on the property's own row

    @property
    def is_target(self) -> bool:
        """Whether the row is a target's, under its property's row."""
        return self.target_path is not None

    @property
    def depth(self) -> int:
        """How deep the row sits: 0 for a property, 1 for a target under it."""
        return 0 if self.target_path is None else 1


class ValueSource(enum.Enum):
    """Where an attribute's value at a time code comes from, as `Usd.ResolveInfo` resolves it there.

    FALLBACK and DEFAULT are distinct: a fallback is the schema's, for an attribute no layer has a value for, and a
    default is a value a layer authored, which holds at every time code no animation overrides.
    """

    NONE = "no value"
    FALLBACK = "schema fallback"
    DEFAULT = "authored default value"
    TIME_SAMPLES = "time samples"
    VALUE_CLIPS = "value clips"
    SPLINE = "spline"


_ANIMATION_SOURCES = (ValueSource.TIME_SAMPLES, ValueSource.VALUE_CLIPS, ValueSource.SPLINE)
# Each USD resolve source's, by its name: pxr's type stubs lack ResolveInfoSourceSpline.
_VALUE_SOURCES_BY_USD_NAME = {
    "ResolveInfoSourceNone": ValueSource.NONE,
    "ResolveInfoSourceFallback": ValueSource.FALLBACK,
    "ResolveInfoSourceDefault": ValueSource.DEFAULT,
    "ResolveInfoSourceTimeSamples": ValueSource.TIME_SAMPLES,
    "ResolveInfoSourceValueClips": ValueSource.VALUE_CLIPS,
    "ResolveInfoSourceSpline": ValueSource.SPLINE,
}


@dataclass(frozen=True, slots=True)
class PropertyDetails:
    """What a property's row draws and its tooltip says, read from the property at the list's time code."""

    path: Sdf.Path
    name: str
    is_relationship: bool
    type_name: str  # an attribute's value type as a layer writes it (float3[]), empty for a relationship
    is_uniform: bool  # an attribute's variability is uniform: it holds one value for all time
    is_custom: bool  # not one of the prim's schemas' properties
    is_authored: bool  # some layer has an opinion on it; else it shows its schema's fallback, or nothing
    value: Any  # an attribute's value at the time code, as pxr gives it, or None; a relationship's is None
    value_source: ValueSource  # where an attribute's value at the time code comes from; NONE for a relationship
    is_blocked: bool  # an attribute's value is blocked: authored as None, so only a fallback shows
    # Whether an animated value has a key at the time code: a time sample, a value clip's sample, or a spline's knot.
    has_key_at_time_code: bool
    time_sample_count: int
    is_time_varying: bool  # whether its value might differ from one time code to another
    # A relationship's targets, or an attribute's connections, as the stage composes them, and those the stage has
    # no prim or property at.
    target_paths: tuple[Sdf.Path, ...]
    missing_target_paths: frozenset[Sdf.Path]
    interpolation: str  # a primvar's interpolation, or empty for any other property

    @property
    def has_targets(self) -> bool:
        """Whether the property has any target, so its row has a chevron."""
        return bool(self.target_paths)

    @property
    def is_animated(self) -> bool:
        """Whether its value comes from animation: time samples, value clips, or a spline."""
        return self.value_source in _ANIMATION_SOURCES


@dataclass(frozen=True, slots=True)
class PropertyMetadata:
    """What the metadata panel says about one property beyond its `PropertyDetails`, read when asked for."""

    documentation: str
    display_group: str
    # The layers with an opinion on it, strongest first, by identifier: its property stack at the time code.
    opinion_layer_identifiers: tuple[str, ...]
    first_time_sample: float | None
    last_time_sample: float | None
    element_size: int  # a primvar's, how many values make one element; 1 for any other property


class PropertyList:
    """One prim's visible property rows, by a query's filter and the expanded properties' targets."""

    rows: list[PropertyRow]
    version: int  # counts changes to rows, so a widget can cache what it computes from them
    property_count: int  # every property the prim has, filtered or not
    time_code: Usd.TimeCode
    _prim: Usd.Prim
    _expanded_names: set[str]  # the view's: shared, so expansion outlives the list
    _shows_property: Callable[[Usd.Property], bool]
    _details_by_name: dict[str, PropertyDetails]
    _metadata_by_name: dict[str, PropertyMetadata]

    def __init__(
        self,
        prim: Usd.Prim,
        time_code: Usd.TimeCode,
        expanded_names: set[str],
        shows_property: Callable[[Usd.Property], bool] | None = None,
    ) -> None:
        """A list of a prim's properties that shows_property passes, the expanded_names showing their targets."""
        self._prim = prim
        self.time_code = time_code
        self._expanded_names = expanded_names
        self._shows_property = shows_property or (lambda _prop: True)
        self._details_by_name = {}
        self._metadata_by_name = {}
        self.version = 0
        self.property_count = 0
        self.rows = []
        self._rebuild_rows()

    @property
    def shown_property_count(self) -> int:
        """How many properties the rows show, their targets' rows not counted."""
        return sum(1 for row in self.rows if not row.is_target)

    @property
    def prim_path(self) -> Sdf.Path:
        """The path of the prim whose properties the list shows."""
        return self._prim.GetPath()

    def is_expired(self) -> bool:
        """Whether the prim can no longer be read: its stage was released, or the prim removed or recomposed."""
        return not self._prim.IsValid()

    def details(self, name: str) -> PropertyDetails | None:
        """What a property's row draws, read on first use; None if the prim has no property of that name."""
        found = self._details_by_name.get(name)
        if found is None:
            prop = self._property(name)
            if prop is None:
                return None
            found = self._details_by_name[name] = _read_details(prop, self.time_code)
        return found

    def row_details(self, row: PropertyRow) -> PropertyDetails | None:
        """The details of a row's property, for its own row or a target's."""
        return self.details(row.name)

    def metadata(self, name: str) -> PropertyMetadata | None:
        """A property's `PropertyMetadata`, read on first use; None if the prim has no property of that name."""
        found = self._metadata_by_name.get(name)
        if found is None:
            prop = self._property(name)
            if prop is None:
                return None
            found = self._metadata_by_name[name] = _read_metadata(prop, self.time_code)
        return found

    def is_expanded(self, name: str) -> bool:
        """Whether a property's targets are showing."""
        return name in self._expanded_names

    def row_index(self, row: PropertyRow) -> int | None:
        """The index of a visible row, or None if it has none."""
        return next((i for i, shown in enumerate(self.rows) if shown == row), None)

    def property_row_index(self, row_index: int) -> int:
        """The index of a row's property's own row: itself, or for a target's, the row it's under."""
        while self.rows[row_index].is_target:
            row_index -= 1
        return row_index

    def toggle(self, row_index: int, every_property: bool = False) -> None:
        """Expand or collapse a property's row, or the property a target's row is under; or every property, to match."""
        name = self.rows[row_index].name
        if every_property:
            self.set_all_expanded(not self.is_expanded(name))
        else:
            self.set_expanded(name, not self.is_expanded(name))

    def set_expanded(self, name: str, expand: bool) -> None:
        """Show or hide a property's targets; a property with none has no rows to show."""
        if expand:
            self._expanded_names.add(name)
        else:
            self._expanded_names.discard(name)
        row_index = self.row_index(PropertyRow(name))
        if row_index is None:
            return
        end = row_index + 1
        while end < len(self.rows) and self.rows[end].is_target:
            end += 1
        self.rows[row_index + 1 : end] = self._target_rows(name) if expand else []
        self.version += 1

    def set_all_expanded(self, expand: bool) -> None:
        """Show or hide the targets of every property the rows show that has any."""
        names = [row.name for row in self.rows if not row.is_target]
        for name in names:
            details = self.details(name)
            if details is not None and details.has_targets and self.is_expanded(name) != expand:
                self.set_expanded(name, expand)

    def set_time_code(self, time_code: Usd.TimeCode) -> None:
        """Read the properties' values at another time code when next drawn; the rows stay."""
        if time_code != self.time_code:
            self.time_code = time_code
            self.forget_details()

    def forget_details(self) -> None:
        """Read every row's details and metadata again when next asked for, as after a value changed."""
        self._details_by_name.clear()
        self._metadata_by_name.clear()
        self.version += 1

    def _property(self, name: str) -> Usd.Attribute | Usd.Relationship | None:
        """A property of the prim, as its own type: GetProperty gives a plain Usd.Property, which reads neither."""
        if not self._prim.IsValid():
            return None
        attribute = self._prim.GetAttribute(name)
        if attribute:
            return attribute
        relationship = self._prim.GetRelationship(name)
        return relationship if relationship else None

    def _target_rows(self, name: str) -> list[PropertyRow]:
        details = self.details(name)
        return [PropertyRow(name, path) for path in details.target_paths] if details is not None else []

    def _rebuild_rows(self) -> None:
        properties = self._prim.GetProperties() if self._prim.IsValid() else []
        self.property_count = len(properties)
        rows: list[PropertyRow] = []
        for prop in properties:
            if not self._shows_property(prop):
                continue
            name = prop.GetName()
            rows.append(PropertyRow(name))
            if name in self._expanded_names:
                rows.extend(self._target_rows(name))
        self.rows = rows
        self.version += 1


def _missing_paths(stage: Usd.Stage, paths: Iterable[Sdf.Path], are_connections: bool) -> frozenset[Sdf.Path]:
    """Those of a property's targets the stage has nothing at: a connection names a property, a target either."""
    missing: set[Sdf.Path] = set()
    for path in paths:
        found = stage.GetPropertyAtPath(path) if are_connections else stage.GetObjectAtPath(path)
        if not found:
            missing.add(path)
    return frozenset(missing)


def _has_key_at(attribute: Usd.Attribute, value_source: ValueSource, time_code: Usd.TimeCode) -> bool:
    """Whether an animated attribute has a key at a numeric time code: a sample, a clip's sample, or a spline's knot."""
    if time_code.IsDefault() or value_source not in _ANIMATION_SOURCES:
        return False
    time = time_code.GetValue()
    if value_source is ValueSource.SPLINE:
        knots = attribute.GetSpline().GetKnots()  # ty: ignore[unresolved-attribute]  # pxr's stubs lack splines
        return time in knots.keys()
    return bool(attribute.GetTimeSamplesInInterval(Gf.Interval(time, time)))  # value clips' samples are its own


def _read_details(prop: Usd.Attribute | Usd.Relationship, time_code: Usd.TimeCode) -> PropertyDetails:
    stage = prop.GetStage()
    if isinstance(prop, Usd.Relationship):
        target_paths = tuple(prop.GetTargets())
        return PropertyDetails(
            path=prop.GetPath(),
            name=prop.GetName(),
            is_relationship=True,
            type_name="",
            is_uniform=False,
            is_custom=prop.IsCustom(),
            is_authored=prop.IsAuthored(),
            value=None,
            value_source=ValueSource.NONE,
            is_blocked=False,
            has_key_at_time_code=False,
            time_sample_count=0,
            is_time_varying=False,
            target_paths=target_paths,
            missing_target_paths=_missing_paths(stage, target_paths, are_connections=False),
            interpolation="",
        )
    attribute = prop
    value_source = _VALUE_SOURCES_BY_USD_NAME[attribute.GetResolveInfo(time_code).GetSource().name]
    connection_paths = tuple(attribute.GetConnections())
    primvar = UsdGeom.Primvar(attribute)
    return PropertyDetails(
        path=attribute.GetPath(),
        name=attribute.GetName(),
        is_relationship=False,
        type_name=str(attribute.GetTypeName()),
        is_uniform=attribute.GetVariability() == Sdf.VariabilityUniform,
        is_custom=attribute.IsCustom(),
        is_authored=attribute.IsAuthored(),
        value=attribute.Get(time_code),
        value_source=value_source,
        has_key_at_time_code=_has_key_at(attribute, value_source, time_code),
        is_blocked=attribute.HasAuthoredValueOpinion() and not attribute.HasAuthoredValue(),
        time_sample_count=attribute.GetNumTimeSamples(),
        is_time_varying=attribute.ValueMightBeTimeVarying(),
        target_paths=connection_paths,
        missing_target_paths=_missing_paths(stage, connection_paths, are_connections=True),
        interpolation=str(primvar.GetInterpolation()) if UsdGeom.Primvar.IsPrimvar(attribute) else "",
    )


def _read_metadata(prop: Usd.Attribute | Usd.Relationship, time_code: Usd.TimeCode) -> PropertyMetadata:
    time_samples = prop.GetTimeSamples() if isinstance(prop, Usd.Attribute) else []
    is_primvar = isinstance(prop, Usd.Attribute) and UsdGeom.Primvar.IsPrimvar(prop)
    return PropertyMetadata(
        documentation=prop.GetDocumentation(),
        display_group=prop.GetDisplayGroup(),
        opinion_layer_identifiers=tuple(spec.layer.identifier for spec in prop.GetPropertyStack(time_code)),
        first_time_sample=time_samples[0] if time_samples else None,
        last_time_sample=time_samples[-1] if time_samples else None,
        element_size=UsdGeom.Primvar(prop).GetElementSize() if is_primvar else 1,
    )
