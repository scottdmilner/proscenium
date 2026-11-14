"""What a property list says about a property: its value and declaration as text, its badge, tooltips, and metadata.

It words what the list has read (`PropertyDetails`, `PropertyMetadata`) and makes no USD queries of its own. A value is
written as a layer would write it, shortened to fit a row: numbers to a few significant digits, and an array to its
length and first elements.
"""

from __future__ import annotations

import enum
import math
from typing import TYPE_CHECKING, Any

from pxr import Gf, Sdf

from .property_list import ValueSource

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .property_list import PropertyDetails, PropertyMetadata, PropertyRow

# What the list's keys do, for the disclosure triangle's tooltip.
KEY_HINTS = "Right: show targets, or step in    Left: hide them, or step out    Shift: every property's"
SIGNIFICANT_DIGITS = 6  # a float's, as a value's text writes it
ARRAY_ELEMENT_LIMIT = 8  # an array's elements a value's text writes before an ellipsis
TEXT_LENGTH_LIMIT = 200  # characters; a row shows fewer, and a tooltip shows each value whole up to this
_GF_VECTOR_TYPES = (
    *(Gf.Vec2d, Gf.Vec2f, Gf.Vec2h, Gf.Vec2i),
    *(Gf.Vec3d, Gf.Vec3f, Gf.Vec3h, Gf.Vec3i),
    *(Gf.Vec4d, Gf.Vec4f, Gf.Vec4h, Gf.Vec4i),
)
_GF_MATRIX_TYPES = (Gf.Matrix2d, Gf.Matrix2f, Gf.Matrix3d, Gf.Matrix3f, Gf.Matrix4d, Gf.Matrix4f)
_GF_QUATERNION_TYPES = (Gf.Quatd, Gf.Quatf, Gf.Quath)


def _number_text(number: float) -> str:
    if isinstance(number, bool):  # a bool is an int, but a layer writes it as a word
        return "true" if number else "false"
    if isinstance(number, int) or not math.isfinite(number):
        return str(number)
    text = f"{number:.{SIGNIFICANT_DIGITS}g}"
    # A float keeps a decimal point, so it reads as one: 1.0, not 1. An exponent already does (1e+06).
    return text if "." in text or "e" in text else f"{text}.0"


def _sequence_text(values: Iterable[Any]) -> str:
    return f"({', '.join(_scalar_text(value) for value in values)})"


def _scalar_text(value: Any) -> str:
    """One value, or one element of an array, as a layer writes it."""
    if isinstance(value, (bool, int, float)):
        return _number_text(value)
    if isinstance(value, str):
        return value
    if isinstance(value, Sdf.AssetPath):
        return f"@{value.path}@"
    if isinstance(value, Sdf.Path):
        return f"<{value}>"
    if isinstance(value, _GF_VECTOR_TYPES):
        return _sequence_text(value)
    if isinstance(value, _GF_QUATERNION_TYPES):
        return _sequence_text((value.GetReal(), *value.GetImaginary()))
    if isinstance(value, _GF_MATRIX_TYPES):
        return _sequence_text(_sequence_text(value.GetRow(row)) for row in range(value.dimension[0]))
    if isinstance(value, dict):
        return f"{{{len(value)} entries}}"
    return str(value)


def _clipped(text: str) -> str:
    single_line = text.replace("\n", " ")
    return single_line if len(single_line) <= TEXT_LENGTH_LIMIT else single_line[: TEXT_LENGTH_LIMIT - 1] + "…"


def value_text(value: Any, type_name: str) -> str:
    """A value as a row shows it: an array's length and first elements, a string quoted, a token bare."""
    if value is None:
        return "None"
    if type_name.endswith("[]"):
        # Indexed, not sliced: a slice of an empty Vt array is None.
        elements = [_scalar_text(value[index]) for index in range(min(len(value), ARRAY_ELEMENT_LIMIT))]
        quoted = [f'"{element}"' for element in elements] if type_name == "string[]" else elements
        more = ", …" if len(value) > ARRAY_ELEMENT_LIMIT else ""
        return _clipped(" ".join([f"[{len(value)}]", *([", ".join(quoted) + more] if quoted else [])]))
    if type_name == "string":
        return _clipped(f'"{value}"')
    return _clipped(_scalar_text(value))


def _targets_text(paths: tuple[Sdf.Path, ...]) -> str:
    if len(paths) == 1:
        return str(paths[0])
    return _clipped(f"[{len(paths)}] {', '.join(str(path) for path in paths[:ARRAY_ELEMENT_LIMIT])}")


def row_value_text(details: PropertyDetails) -> str:
    """A property row's Value cell: its value, or a relationship's targets, or a connected attribute's sources."""
    if details.is_relationship:
        return _targets_text(details.target_paths) if details.has_targets else "No targets"
    if details.value is None and details.has_targets:
        return "→ " + _targets_text(details.target_paths)
    if details.is_blocked:
        return "None (blocked)"
    return value_text(details.value, details.type_name)


def declaration_text(details: PropertyDetails) -> str:
    """A property's declaration as a layer writes it before its name: custom, uniform, and its type, or rel."""
    words = ["custom"] if details.is_custom else []
    if details.is_relationship:
        words.append("rel")
    else:
        words += [*(["uniform"] if details.is_uniform else []), details.type_name]
    return " ".join(words)


def status_text(shown_property_count: int, property_count: int) -> str:
    """A list's status line: how many of its prim's properties show; the summary above it names the prim."""
    shown = (
        f"{shown_property_count:,} of {property_count:,}"
        if shown_property_count < property_count
        else f"{property_count:,}"
    )
    return f"{shown} {'property' if property_count == 1 else 'properties'}"


def row_name(row: PropertyRow, shows_target_path: bool = True) -> str:
    """The text a row's name cell shows: a property's name, or a target's path, or with shows_target_path off its name.

    A target's name is its prim's, with a property's after a dot for a target that's a property (`Surface.outputs:out`).
    """
    path = row.target_path
    if path is None:
        return row.name
    if shows_target_path:
        return str(path)
    return f"{path.GetPrimPath().name}.{path.name}" if path.IsPropertyPath() else path.name


class AnimationMark(enum.Enum):
    """What a row's keyframe icon marks of an animated value, as Blender marks an animated property's field."""

    KEY = "a key at this time code"  # a time sample, clip sample, or spline knot is here: Blender's keyed color
    BETWEEN_KEYS = "between keys at this time code"  # animated, interpolated or held here: Blender's animated color


def animation_mark(details: PropertyDetails) -> AnimationMark | None:
    """Whether a row's keyframe icon marks a key at the time code or a value between keys; None if it isn't animated."""
    if not details.is_animated:
        return None
    return AnimationMark.KEY if details.has_key_at_time_code else AnimationMark.BETWEEN_KEYS


def is_target_missing(details: PropertyDetails, row: PropertyRow) -> bool:
    """Whether a target row names a path the stage has nothing at; its row draws red."""
    return row.target_path is not None and row.target_path in details.missing_target_paths


def _time_samples_text(details: PropertyDetails) -> str:
    count = details.time_sample_count
    varying = "" if details.is_time_varying else ", holding one value"
    return f"{count} time sample{'' if count == 1 else 's'}{varying}"


def _value_source_line(details: PropertyDetails) -> str:
    """Where the value at the time code comes from: a schema's fallback and an authored default are told apart."""
    if details.is_blocked:
        return "Blocked: authored as None, so it has no value"
    source = details.value_source
    mark = animation_mark(details)
    if source is ValueSource.TIME_SAMPLES and mark is not None:
        return f"From {_time_samples_text(details)}; {mark.value}"
    if source is ValueSource.FALLBACK:
        return "Schema fallback"
    if source is ValueSource.DEFAULT:
        return "Authored default value"
    if source is ValueSource.NONE and not details.has_targets:
        return "No value"
    return f"From {source.value}; {mark.value}" if mark is not None else f"From {source.value}"


def _targets_noun(details: PropertyDetails) -> str:
    return "target" if details.is_relationship else "connection"


def row_tooltip(details: PropertyDetails, row: PropertyRow) -> str:
    """A row's tooltip: a property's path, declaration, and where its value comes from; or a target's path."""
    if row.target_path is not None:
        noun = _targets_noun(details).capitalize()
        missing = "\nNothing on the stage at this path" if is_target_missing(details, row) else ""
        return f"{noun} of {details.path}\n{row.target_path}{missing}"
    lines = [str(details.path), declaration_text(details)]
    if not details.is_authored:
        lines.append("Unauthored: no layer has an opinion on it")
    if not details.is_relationship:
        lines.append(f"Value: {row_value_text(details)}")
        lines.append(_value_source_line(details))
    if details.interpolation:
        lines.append(f"Interpolation: {details.interpolation}")
    if details.has_targets:
        count = len(details.target_paths)
        lines.append(f"{count} {_targets_noun(details)}{'' if count == 1 else 's'}")
    if details.missing_target_paths:
        lines.append(f"{len(details.missing_target_paths)} with nothing on the stage at its path")
    return "\n".join(lines)


def jump_tooltip(target_path: Sdf.Path, is_missing: bool) -> str:
    """A target's jump button's tooltip: what a click selects, or why it can't."""
    if is_missing:
        return f"Nothing on the stage at {target_path} to select"
    return f"Select {target_path}"


def disclosure_tooltip(details: PropertyDetails, is_expanded: bool) -> str:
    """The disclosure triangle's tooltip: what a click does to the row, and the keys that do the same."""
    action = "Hide" if is_expanded else "Show"
    return (
        f"{action} the {_targets_noun(details)}s of {details.name}. Shift-click: every property's.\nKeys: {KEY_HINTS}"
    )


def metadata_lines(details: PropertyDetails, metadata: PropertyMetadata, row: PropertyRow) -> list[str]:
    """The metadata panel's summary of a row's property, and of the target its row names."""
    lines = [str(details.path), f"Declared: {declaration_text(details)}"]
    if not details.is_relationship:
        lines.append(f"Value: {row_value_text(details)}")
        lines.append(f"Source: {_value_source_line(details)}")
    if metadata.first_time_sample is not None:
        first, last = _number_text(metadata.first_time_sample), _number_text(metadata.last_time_sample or 0.0)
        lines.append(f"Time samples: {details.time_sample_count}, from {first} to {last}")
    if details.interpolation:
        lines.append(f"Interpolation: {details.interpolation}, element size {metadata.element_size}")
    if details.has_targets:
        lines.append(f"{_targets_noun(details).capitalize()}s: {len(details.target_paths)}")
    if row.target_path is not None:
        missing = " (missing)" if is_target_missing(details, row) else ""
        lines.append(f"Selected {_targets_noun(details)}: {row.target_path}{missing}")
    if metadata.display_group:
        lines.append(f"Display group: {metadata.display_group}")
    layers = metadata.opinion_layer_identifiers
    lines.append(f"Opinions: {len(layers)}" + (f", strongest in {layers[0]}" if layers else ""))
    if metadata.documentation:
        lines.append(_clipped(metadata.documentation))
    return lines
