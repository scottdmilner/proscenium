"""F-EDIT-SEQUENCE's refreshes, against the change matrix (change-matrix.md; M7 plan, C7).

Each refresh is checked by support/refresh_checks.py: it displays what a clean binding does, and acts on exactly the
copies its case names, the rest neither replaced nor written. The steps are applied in order to one live stage, a
refresh after each. The cases that change the binding's settings or state, rather than its source, start from the scene
as it starts.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import bpy

from fixtures import edit_sequence
from proscenium_sync.binding_persistence import id_property_records
from proscenium_sync.binding_persistence.manifests import RepresentationRole
from proscenium_sync.results import ResultState
from proscenium_sync.source_access import binding_settings
from support.blend import save_and_reopen
from support.blender_writes import observed_writes
from support.refresh_checks import copy_object, entries_by_source, refresh_acting_on

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    import pytest
    from pxr import Usd

    from proscenium_sync.api.bindings import BindingHandle, Bindings

_GENERATION = re.compile(r"~(\d{6})\.")  # a managed name's generation (DECISIONS.md "Managed object names")


def _sources(copies: Collection[edit_sequence.CopyIdentity]) -> set[str]:
    return {source for source, _ in copies}


def _binding(bindings: Bindings, stage: Usd.Stage) -> BindingHandle:
    handle = bindings.create_binding(bpy.data.scenes["Scene"], name="Shot")
    assert handle.attach(stage).state is not ResultState.FATAL_FAILURE
    assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
    return handle


def test_each_step_acts_on_exactly_its_copies(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # TINC-01, AFF-01, DISC-02, DISC-06, CHG-01 to CHG-03, CHG-07 to CHG-20 on F-EDIT-SEQUENCE.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        for step in scene.steps:
            step.edit(scene.stage)
            before, after, _ = refresh_acting_on(
                bindings,
                handle,
                scene.stage,
                monkeypatch,
                step.name,
                updated=_sources(step.updated),
                rebuilt=_sources(step.rebuilt),
                retired=_sources(step.retired),
                built=_sources(step.built),
            )
            if step.name == "bounds-changed":
                # CHG-08: Odd's object kept, pointed at a new mesh named for Odd in a later generation, the old one
                # retired.
                [old_mesh] = [
                    e.datablock for e in before[edit_sequence.ODD].values() if e.role is RepresentationRole.BOUNDS_MESH
                ]
                obj = copy_object(after[edit_sequence.ODD])
                assert isinstance(obj.data, bpy.types.Mesh) and old_mesh is not None and obj.data != old_mesh
                generation, mesh_generation = (_GENERATION.match(n) for n in (obj.name, obj.data.name))
                assert generation and mesh_generation and mesh_generation.group(1) > generation.group(1)
                assert obj.data.name.endswith(" Odd") and not id_property_records.alive(old_mesh)


def test_a_payload_policy_retires_and_builds_its_contents(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CHG-23, CHG-09, CHG-10: load-none retires Leaf's copy, and load-all builds it again, nothing else written.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        leaf = _sources(scene.payloaded_copies)
        assert handle.set_settings(payload_policy=binding_settings.PayloadPolicy.LOAD_NONE).state is ResultState.SUCCESS
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "load-none", retired=leaf)
        assert handle.set_settings(payload_policy=binding_settings.PayloadPolicy.LOAD_ALL).state is ResultState.SUCCESS
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "load-all", built=leaf)


def test_purposes_build_and_retire_what_they_show(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CHG-24: proxy removed from the viewport's purposes retires Proxy's copy, which the render's don't show, and added
    # again builds it, nothing else written.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        proxy, purposes = _sources(scene.proxy_copies), handle.requested_settings().viewport_purposes
        without = [purpose for purpose in purposes if purpose != "proxy"]
        assert handle.set_settings(viewport_purposes=without).state is ResultState.SUCCESS
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "proxy removed", retired=proxy)
        assert handle.set_settings(viewport_purposes=purposes).state is ResultState.SUCCESS
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "proxy added", built=proxy)


def test_coordinate_conversion_moves_every_copy_in_place(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CHG-25: conversion turned on, the unit scale changed while it is on, and conversion turned off each update
    # every copy's world matrix in place, each object kept.
    target = bpy.data.scenes["Scene"]
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        assert handle.set_settings(coordinate_conversion=False).state is ResultState.SUCCESS
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        every = set(entries_by_source(handle.binding_id))
        assert handle.set_settings(coordinate_conversion=True).state is ResultState.SUCCESS
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "conversion on", updated=every)
        target.unit_settings.scale_length = 0.01
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "unit scale while on", updated=every)
        assert handle.set_settings(coordinate_conversion=False).state is ResultState.SUCCESS
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "conversion off", updated=every)


def test_a_unit_scale_without_conversion_writes_no_resource(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CHG-26: with conversion off, another unit scale changes no copy, so only the records are written.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        assert handle.set_settings(coordinate_conversion=False).state is ResultState.SUCCESS
        assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        bpy.data.scenes["Scene"].unit_settings.scale_length = 0.01
        _, _, observed = refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "unit scale")
        assert "generation" in observed.record_writes  # it records the unit scale


def test_another_representation_version_rebuilds_everything(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CHG-27: the representation version is fixed within a process, and planning plans only this one, so a generation
    # of another reaches a refresh only from a file another process saved; with no plan held for it, the refresh is a
    # full rebuild, every copy's resources replaced and the display a clean binding's (DECISIONS.md "Incremental
    # refresh comparison"). Reopening the file stands in for that process.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        _binding(bindings, scene.stage)
        save_and_reopen(tmp_path / "published.blend")
        [handle] = bindings.in_scene(bpy.data.scenes["Scene"])
        assert handle.attach(scene.stage).state is not ResultState.FATAL_FAILURE
        every = set(entries_by_source(handle.binding_id))
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "reopened", rebuilt=every)


def test_a_reload_updates_only_what_it_reread(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # DISC-01, CHG-28: Far's sublayer rewritten on disk, a refresh writes nothing until the layers are reloaded;
    # after, a refresh updates only Far's copy, in place.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        scene.rewrite_far_on_disk()
        with observed_writes(monkeypatch) as observed:
            assert handle.synchronize(0).state is not ResultState.FATAL_FAILURE
        assert observed.wrote_nothing, observed
        assert handle.reload().state is ResultState.SUCCESS
        refresh_acting_on(bindings, handle, scene.stage, monkeypatch, "reloaded", updated={edit_sequence.FAR})


def test_a_stage_attached_in_place_updates_only_what_differs(
    bindings: Bindings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CHG-29: a stage over the same layers with Far moved in its session layer, attached in place of the live one,
    # then a refresh, updates only Far's copy, in place.
    with edit_sequence.edit_sequence(tmp_path) as scene:
        handle = _binding(bindings, scene.stage)
        attached = scene.open_attached_stage()
        assert handle.attach(attached).state is not ResultState.FATAL_FAILURE
        refresh_acting_on(bindings, handle, attached, monkeypatch, "attached", updated={edit_sequence.FAR})
