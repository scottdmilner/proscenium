# `proscenium.api`

What callers use to reach bindings ([Synchronization API](../../../docs/spec/source-access.md#synchronization-api)). Tier 5: it may import every unit below it, and only `proscenium.addon` imports it ([import rules](../README.md#import-rules)).

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: `bindings`. |
| `bindings.py` | `BindingHandle`, the immutable value of a binding's identifier that callers hold, and `Bindings`, the process's bindings, of which `BINDINGS` is the one instance. Also `BindingNotFoundError`, and `RequestedSettings` and `Result`, the types callers pass and receive, re-exported so callers outside `proscenium` import only this module. |

## `bindings.py`

- **The handle** holds only the binding's identifier, never a datablock or cached state, so undo, redo, and file loads can't leave it stale. Its methods (`attach`, `release`, `synchronize`, `cache`, `set_settings`, `reload`, `retry_cleanup`, `possibly_out_of_date`, `requested_settings`, `live_stage`) delegate to the methods of `BINDINGS` keyed by that identifier, which tests call on a fresh `Bindings`.
- **Operations that span bindings** are `Bindings`' own: creating an unattached binding (`create_binding(scene, ...)`), listing a scene's bindings (`in_scene`), and reporting copied bindings (`copied`). Callers open source stages and resolve file paths.
- **Results and refusals:** an operation returns a `Result` (`proscenium.binding.results`) whose diagnostics say why it failed: an unavailable source, a configuration that can't be read, or a binding with copies and no canonical candidate. A query raises instead, and methods needing records raise `BindingNotFoundError` for a binding that doesn't exist, one whose destination or target scene was removed included. `release()` is an idempotent runtime operation that remains valid after undo or removal.
- **Runtime stages:** each binding's source and evaluation stages are in `Bindings.stages`, a `BindingStageTracker` (`proscenium.binding.runtime.stage_tracking`), created unattached on first use and compared with the bindings before any use once the bindings' state was rebuilt. `addon.py` drops them all when a file is loaded (`drop_all_stages`).

`synchronize(time_code=None)` finds the binding and refuses one that isn't usable, and `proscenium.synchronization` runs the transaction at the time code given, the USD default time code included, or else at the target scene's current frame's, its subframe included, since time code t is frame t. The result names the time code attempted; a refusal here, before the attempt, names only one given.

`cache(time_codes)` finds the binding the same way, and `proscenium.synchronization` caches the published generation at each time code it hasn't cached. One time code is a collection of one, and the result names those not cached before. It publishes no generation, records no last attempt, and pushes no undo step. The default time code isn't one to cache: passing it raises `ValueError`, caching nothing.

A synchronization, a cache call, and a cleanup retry each run alone: while one runs, `synchronize`, `cache`, `retry_cleanup`, `attach`, `release`, and `reload` on any binding raise `ReentrantCallError` before changing anything, whether a Blender handler, a USD notice, or another thread calls them; `set_settings` may be called, and the running attempt keeps the settings it started with ([Source Consistency](../../../docs/spec/source-access.md#source-consistency)). `Bindings.running` is the flag.

A synchronization that publishes and a cleanup retry that commits each push one undo step, with global undo on outside background mode; nothing else does. An operator that calls the API declares no `UNDO`, so it adds no second step. `possibly_out_of_date()` is false only while the destination shows the generation this session last published for the binding, with any time codes cached in it since, and its source is at that generation's revision, so it's true after an undo or redo restores another generation ([Undo and Runtime State](../../../docs/spec/lifecycle.md#undo-and-runtime-state)).

## Caller workflow

With the extension enabled in Blender, the caller opens a stage and attaches it through the returned handle:

```python
import bpy
from pxr import Usd

from proscenium.api.bindings import BINDINGS

stage = Usd.Stage.Open("/absolute/path/to/shot.usda")
handle = BINDINGS.create_binding(bpy.context.scene, name="Shot")
attachment = handle.attach(stage)
if attachment.is_success:
    result = handle.synchronize()  # at the scene's current frame
    print(result)
```

Each handle attaches and releases independently. A different stored root-layer identifier produces a fatal `source confirmation required` diagnostic and leaves the binding unchanged; the caller can explicitly choose `handle.attach(stage, confirm=True)`. Callers resolve file paths before opening, including Blender-relative paths through `bpy.path.abspath`. The default destination name is `USD Display`.

After reopening a `.blend`, find existing handles with `BINDINGS.in_scene(scene)` or reconstruct a `BindingHandle` from its persistent identifier, then call `handle.attach(stage)` for each binding to restore. Until attached, bindings retain their saved display and report the source unavailable. `handle.live_stage()` exposes the supplied stage immediately.

To give bindings separate source opinions over shared layers, create an anonymous root for each stage and sublayer the shared source:

```python
from pxr import Sdf

overlay = Sdf.Layer.CreateAnonymous()
overlay.subLayerPaths.append(stage.GetRootLayer().identifier)
independent_stage = Usd.Stage.Open(overlay)
other = BINDINGS.create_binding(bpy.context.scene)
other.attach(independent_stage)
```

Release each binding's attachment when finished, including after undo removes the binding:

```python
handle.release()
other.release()
del stage, independent_stage
```

The binding holds a strong stage reference until release, replacement, or file load. Releasing clears its source and evaluation stages; the caller's own references keep the source alive until they are dropped too.

## Measuring source access

Time the caller's stage opening, the binding's first evaluation-stage acquisition, and subsequent acquisitions separately. The first acquisition composes a second stage over the source's loaded root and session layers; later acquisitions reuse it while those layers match. Record the payload policy, host, fixture, and cache conditions with each result. A retained evaluation stage also retains its composed layers, so include both held stages when measuring memory.

The direct source-access boundary can be measured independently of Blender's records and diagnostics:

```python
from time import perf_counter

from pxr import Usd

from proscenium.binding.source_access import stages

started = perf_counter()
stage = Usd.Stage.Open("/absolute/path/to/shot.usda")
opened = perf_counter()
binding_stages = stages.BindingStages()
binding_stages.attach(stage)
attached = perf_counter()
evaluation = binding_stages.acquire_evaluation_stage(stages.PayloadPolicy.LOAD_ALL)
acquired = perf_counter()
reused = binding_stages.acquire_evaluation_stage(stages.PayloadPolicy.LOAD_ALL)
finished = perf_counter()
assert reused == evaluation
print(
    {
        "caller stage open": opened - started,
        "first evaluation acquisition": acquired - attached,
        "reused evaluation acquisition": finished - acquired,
    }
)
binding_stages.release()
```

M4's feasibility bridge times its own source opening and bridge construction. It evaluates its supplied stage directly; measurements of the product's source access use `BindingStages` as above to include its evaluation-stage construction.
