"""Turns raw Phase E runs into per-stage statistics: wall and CPU time, cores busy, and memory over a baseline."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

MB = 1e6
# Stages that make up initial synchronization, from opening the file to the first depsgraph evaluation.
SYNC = {
    "importer": ["import", "evaluate"],
    "prototype": ["stage open", "bridge construction", "capture", "planning", "transfer", "construction", "evaluate"],
}
# Blender construction plus the first evaluation; for the importer only its whole operator is separable.
HYDRA = ["bridge construction", "capture", "planning", "transfer"]
# M4 Phase C: an update after its edit, from the incremental capture to the depsgraph evaluation.
UPDATE = ["capture", "planning", "diff", "prepare", "publish", "retire", "evaluate"]
# While both generations' data exist: from preparation until retirement has removed the old.
COEXIST = ("prepare", "retire")


def _primary(samples: list[dict[str, Any]]) -> str:
    """The memory counter reported: the physical footprint on macOS, resident memory elsewhere."""
    return "footprint" if samples and "footprint" in samples[0] else "resident"


def _window(samples: list[dict[str, Any]], begin: float, end: float, key: str) -> list[float]:
    return [s[key] for s in samples if begin <= s["t"] <= end]


def _after(samples: list[dict[str, Any]], t: float, key: str) -> float | None:
    return next((s[key] for s in samples if s["t"] >= t), None)


def analyze(run: dict[str, Any]) -> dict[str, Any]:
    """One run's stages and rest windows, memory relative to its baseline window."""
    samples, markers = run["samples"], run["markers"]
    key = _primary(samples)
    peak_key = "peak footprint" if key == "footprint" else "peak resident"
    by_name = {m["name"]: m for m in markers}
    base_window = _window(samples, by_name["settle:baseline"]["t"], by_name["settled:baseline"]["t"], key)
    baseline = statistics.median(base_window) if base_window else _after(samples, by_name["settle:baseline"]["t"], key)
    if baseline is None:
        raise ValueError("no samples in the baseline window")
    stages: dict[str, dict[str, Any]] = {}
    for marker in markers:
        if not marker["name"].startswith("begin:"):
            continue
        name = marker["name"].removeprefix("begin:")
        begin, end = marker, by_name[f"end:{name}"]
        wall = end["t"] - begin["t"]
        cpu = end["cpu"] - begin["cpu"]
        window = _window(samples, begin["t"], end["t"], key)
        after = _after(samples, end["t"], key)
        threads = _window(samples, begin["t"], end["t"], "threads")
        # The process's own lifetime peak is exact for this stage when the stage raised it.
        raised = end.get(peak_key, 0) > begin.get(peak_key, 0)
        stages[name] = {
            "wall s": wall,
            "cpu s": cpu,
            "cores": cpu / wall if wall > 0 else None,
            "peak MB": (max(window) - baseline) / MB if window else None,
            "exact peak MB": (end[peak_key] - baseline) / MB if raised else None,
            "end MB": (after - baseline) / MB if after is not None else None,
            "max threads": max(threads) if threads else None,
        }
    # Live heap (malloc'd, not freed) from the child's markers, where the platform provides it.
    base_heap = by_name["settled:baseline"].get("heap")

    def heap(marker: dict[str, Any]) -> float | None:
        value = marker.get("heap")
        return None if value is None or base_heap is None else (value - base_heap) / MB

    for name, stage in stages.items():
        stage["end heap MB"] = heap(by_name[f"end:{name}"])
    rest_heap = {
        m["name"].removeprefix("settled:"): heap(m)
        for m in markers
        if m["name"].startswith("settled:") and m["name"] != "settled:baseline"
    }
    rest: dict[str, float] = {}
    for marker in markers:
        if marker["name"].startswith("settle:") and marker["name"] != "settle:baseline":
            name = marker["name"].removeprefix("settle:")
            window = _window(samples, marker["t"], by_name[f"settled:{name}"]["t"], key)
            if window:
                rest[name] = (statistics.median(window) - baseline) / MB
    side = "importer" if run["mode"].startswith("importer") else "prototype"
    sync = [stages[name] for name in SYNC[side] if name in stages]
    totals = {
        "sync wall s": sum(s["wall s"] for s in sync),
        "sync cpu s": sum(s["cpu s"] for s in sync),
        "sync peak MB": max((s["peak MB"] for s in sync if s["peak MB"] is not None), default=None),
    }
    if side == "prototype":
        totals["hydra wall s"] = sum(stages[name]["wall s"] for name in HYDRA)
        totals["blender wall s"] = stages["construction"]["wall s"] + stages["evaluate"]["wall s"]
    else:
        totals["blender wall s"] = None
    if "update:prepare" in stages:
        totals["update wall s"] = sum(stages[f"update:{name}"]["wall s"] for name in UPDATE)
        # The extra memory both generations hold, over the level just before preparation.
        begin, end = by_name[f"begin:update:{COEXIST[0]}"]["t"], by_name[f"end:update:{COEXIST[1]}"]["t"]
        before = [s[key] for s in samples if s["t"] <= begin]
        window = _window(samples, begin, end, key)
        totals["coexist MB"] = (max(window) - before[-1]) / MB if window and before else None
    return {
        "counter": key,
        "baseline MB": baseline / MB,
        "stages": stages,
        "rest MB": rest,
        "rest heap MB": rest_heap,
        "totals": totals,
    }


def _stats(values: list[float | None]) -> dict[str, float | None] | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return {"median": statistics.median(present), "min": min(present), "max": max(present), "first": values[0]}


def _aggregate(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    """Medians, ranges, and the first run of each metric over the repeats."""

    def collect(path: tuple[str, ...]) -> dict[str, float | None] | None:
        values = []
        for analysis in analyses:
            node: Any = analysis
            for part in path:
                node = node.get(part) if isinstance(node, dict) else None
            values.append(node)
        return _stats(values)

    first = analyses[0]
    return {
        "counter": first["counter"],
        "runs": len(analyses),
        "baseline MB": collect(("baseline MB",)),
        "stages": {
            stage: {metric: collect(("stages", stage, metric)) for metric in first["stages"][stage]}
            for stage in first["stages"]
        },
        "rest MB": {name: collect(("rest MB", name)) for name in first["rest MB"]},
        "rest heap MB": {name: collect(("rest heap MB", name)) for name in first["rest heap MB"]},
        "totals": {name: collect(("totals", name)) for name in first["totals"]},
    }


def summarize(runs_dir: Path, scenes: dict[str, dict[str, Any]], environment: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    results: dict[tuple[str, str], dict[str, Any]] = {}
    failures: list[str] = []
    for path in sorted(runs_dir.glob("*.json")):
        run = json.loads(path.read_text())
        if run["scene"] not in scenes:
            continue
        if run["returncode"] != 0 or not run["result"]:
            failures.append(path.stem)
            continue
        grouped[(run["scene"], run["mode"])].append(run)
    summary: dict[str, Any] = {"environment": environment, "failures": failures, "scenes": {}}
    for (scene, mode), runs in sorted(grouped.items()):
        runs.sort(key=lambda r: r["repeat"])
        results[(scene, mode)] = runs[0]["result"]
        entry = summary["scenes"].setdefault(scene, {"scene": scenes[scene], "modes": {}})
        entry["modes"][mode] = {
            **_aggregate([analyze(run) for run in runs]),
            "result": runs[0]["result"],
            "log warnings": runs[0]["warnings"],
            "log errors": runs[0]["errors"],
        }
        if mode == "interaction":
            entry["modes"][mode]["interaction"] = _interaction([run["result"]["plan"]["interaction"] for run in runs])
    return summary


# M4's provisional interaction budgets: each function, with the Blender updates it triggers (M04 plan, item 4).
INTERACTION_BUDGETS = {"single": 0.050, "assembly": 0.250}


def _interaction(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Each operation's per-run medians, as a median and range over the runs, and the first run's sizes."""
    first = runs[0]["timings"]
    timings = {
        name: (_stats([run["timings"][name]["median"] for run in runs]) or {}) | {"repeats": first[name]["repeats"]}
        for name in first
    }
    return {"runs": len(runs), "timings": timings, "sizes": runs[0]["sizes"]}


def _fmt(stat: dict[str, float | None] | None, digits: int = 3) -> str:
    if not stat:
        return "—"
    median, low, high = (float(stat[key] or 0.0) for key in ("median", "min", "max"))
    if high - low < 10**-digits:
        return f"{median:.{digits}f}"
    return f"{median:.{digits}f} ({low:.{digits}f}–{high:.{digits}f})"


def _budgets(entry: dict[str, Any]) -> list[str]:
    """M4's provisional budgets against one scene's runs, where it has them (M04 plan, settled item 4)."""
    modes = entry["modes"]

    def median(mode: str, total: str) -> float | None:
        stat = modes.get(mode, {}).get("totals", {}).get(total)
        return None if not stat else stat["median"]

    sync = median("update:initial", "sync wall s") or median("prototype", "sync wall s")
    peak = median("update:initial", "sync peak MB") or median("prototype", "sync peak MB")
    importer, importer_peak = median("importer-matched", "sync wall s"), median("importer-matched", "sync peak MB")
    rows = []
    if sync and importer and peak and importer_peak:
        rows.append(f"| Initial synchronization | at most 1.5× the importer's time | {sync / importer:.2f}× |")
        rows.append(
            f"| Initial synchronization | at most 2× the importer's peak memory | {peak / importer_peak:.2f}× |"
        )
    unchanged = median("update:unchanged", "update wall s")
    if sync and unchanged:
        rows.append(f"| Unchanged refresh | no slower than initial synchronization | {unchanged / sync:.2f}× |")
    for scenario in ("transform", "shared-geometry", "material"):
        update = median(f"update:{scenario}", "update wall s")
        if sync and update:
            rows.append(f"| {scenario} update | at least 10× faster than a full rebuild | {sync / update:.1f}× |")
    if not rows:
        return []
    return ["", "| Budget | Provisional | Measured (medians) |", "|---|---|---|", *rows]


def _updates(entry: dict[str, Any]) -> list[str]:
    updates = {mode: data for mode, data in entry["modes"].items() if mode.startswith("update:")}
    lines = []
    if any("update wall s" in data["totals"] for data in updates.values()):
        lines += [
            "",
            "| Scenario | Update s | " + " | ".join(f"{name} s" for name in UPDATE) + " | Coexist MB | Changes |",
            "|---|---|" + "---|" * len(UPDATE) + "---|---|",
        ]
        for mode, data in updates.items():
            if "update wall s" not in data["totals"]:
                continue
            stages = " | ".join(_fmt(data["stages"][f"update:{name}"]["wall s"]) for name in UPDATE)
            facts = data["result"]["plan"]["update"]
            changes = {**facts["diff"], **facts["written"]}
            lines.append(
                f"| {mode.removeprefix('update:')} | {_fmt(data['totals']['update wall s'])} | {stages} | "
                f"{_fmt(data['totals']['coexist MB'], 1)} | `{json.dumps(changes)}` |"
            )
    initial = updates.get("update:initial")
    if initial:
        size = initial["result"]["plan"]["blend bytes"] / MB
        lines += [
            "",
            f".blend size after synchronization (uncompressed): {size:.1f} MB; saving took "
            f"{_fmt(initial['stages']['save']['wall s'])} s.",
        ]
    return lines


def _interaction_lines(entry: dict[str, Any]) -> list[str]:
    data = entry["modes"].get("interaction", {}).get("interaction")
    if not data:
        return []
    lines = [
        "",
        f"Interaction ({data['runs']} runs; each run's median of its repeats, as a median and range over the runs):",
        "",
        "| Operation | Repeats per run | ms | Budget ms |",
        "|---|---|---|---|",
    ]
    for name, stat in data["timings"].items():
        budget = INTERACTION_BUDGETS.get(name.split(":")[0])
        scaled = {key: value * 1000 for key, value in stat.items() if key in ("median", "min", "max")}
        lines.append(
            f"| {name} | {stat['repeats']} | {_fmt(scaled, 3)} | {'—' if budget is None else f'{budget * 1000:.0f}'} |"
        )
    lines += ["", f"Sizes: `{json.dumps(data['sizes'])}`"]
    return lines


def markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Measurements (M1b Phase E, M4 Phase C)",
        "",
        "Medians over the runs, with ranges. Memory is relative to each run's "
        "baseline window (the empty factory-startup process). The live heap is what malloc has handed out and not "
        "taken back; the gap between it and the footprint or resident memory is the allocator keeping freed pages.",
        "",
    ]
    env = summary["environment"]
    lines += [f"- {key}: {value}" for key, value in env.items() if key != "power"]
    if "power" in env:
        lines.append(f"- power: {env['power'].splitlines()[0] if env['power'] else '?'}")
    if summary["failures"]:
        lines.append(f"- **failed runs:** {', '.join(summary['failures'])}")
    for scene, entry in summary["scenes"].items():
        lines += ["", f"## {scene}", ""]
        if entry["scene"].get("parameters"):
            lines += [f"Parameters: `{json.dumps(entry['scene']['parameters'])}`", ""]
        lines += [
            "| Mode | Stage | Wall s | CPU s | Cores | Peak MB | Exact peak MB | End MB | End heap MB | Threads |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for mode, data in entry["modes"].items():
            for stage, metrics in data["stages"].items():
                lines.append(
                    f"| {mode} | {stage} | {_fmt(metrics['wall s'])} | {_fmt(metrics['cpu s'])} | "
                    f"{_fmt(metrics['cores'], 2)} | {_fmt(metrics['peak MB'], 1)} | "
                    f"{_fmt(metrics['exact peak MB'], 1)} | {_fmt(metrics['end MB'], 1)} | "
                    f"{_fmt(metrics['end heap MB'], 1)} | "
                    f"{_fmt(metrics['max threads'], 0)} |"
                )
        lines += [
            "",
            "| Mode | Sync wall s | Sync CPU s | Sync peak MB | Hydra stages s | Blender s | Baseline MB | "
            "At rest MB | At rest, live heap MB |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for mode, data in entry["modes"].items():
            totals = data["totals"]
            rest = "; ".join(f"{name} {_fmt(value, 1)}" for name, value in data["rest MB"].items())
            heap = "; ".join(f"{name} {_fmt(value, 1)}" for name, value in data["rest heap MB"].items())
            lines.append(
                f"| {mode} | {_fmt(totals['sync wall s'])} | {_fmt(totals['sync cpu s'])} | "
                f"{_fmt(totals['sync peak MB'], 1)} | {_fmt(totals.get('hydra wall s'))} | "
                f"{_fmt(totals.get('blender wall s'))} | {_fmt(data['baseline MB'], 1)} | {rest} | {heap} |"
            )
        lines += _budgets(entry) + _updates(entry) + _interaction_lines(entry)
        lines += ["", "| Mode | Built (first run) |", "|---|---|"]
        for mode, data in entry["modes"].items():
            built = dict(data["result"]["blender"])
            if "plan" in data["result"]:
                built["plan"] = {k: v for k, v in data["result"]["plan"].items() if k not in ("update", "interaction")}
            lines.append(f"| {mode} | `{json.dumps(built)}` |")
    return "\n".join(lines) + "\n"
