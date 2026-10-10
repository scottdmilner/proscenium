# M1b research reports (2026-10-09)

Four investigations made before the [M1b plan](../M01b-evaluation-gate.md), whose "Research basis" section digests them. They read OpenUSD v26.03 (bundled with Blender 5.2), OpenUSD `dev` at `5bc38c9`, the Blender 5.2.2 sources and pinned `lib-*` repositories, and the shipped binaries.

**These are source-reading reports, not test results.** Each claim carries a label: a source location, a URL, *measured* (a command was run), or *inferred*. Only the measured claims were checked by running anything; the rest are inputs for M1b's phases to verify. Where a later feasibility record or decision disagrees, the record wins.

| Report | Covers |
|---|---|
| [01-hydra-core.md](01-hydra-core.md) | Hydra 2 core: scene indices, data sources, schemas, observers and dirty locators, sampled data and contributing sample times, threading, plugins, Hydra 1 emulation, error handling |
| [02-usdimaging-chain.md](02-usdimaging-chain.md) | `UsdImagingCreateSceneIndices` chain, prim adapters, Hdsi filters, native and point instancing and the reverse mapping, materials, skinning, time-varying detection, gaps |
| [03-render-delegates.md](03-render-delegates.md) | HdStorm, HdEmbree, and HdPrman as reference consumers; reusable helpers; patterns for a non-render consumer |
| [04-native-build-boundary.md](04-native-build-boundary.md) | Building against Blender's USD on macOS, Windows, and Linux; one-USD checks; stage exchange; zero-copy transfer; errors; distribution; prior art |

The zero-copy measurement in report 04 is reproducible with the `buffer_transfer` feasibility probe (`tools/feasibility/probe_buffer_transfer.py`).

Source paths in the reports are relative to the checkout named in each report's label section. File paths cited from a local checkout are not in this repository.
