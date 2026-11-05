# Changelog

## 0.1.0-dev.4

Fixes from the re-check report of 0.1.0-dev.3:

- **Concurrent downloads of one package** (two panels, two Houdini sessions) no longer break each other: every
  writer has its own temporary file (core, marked "HSimRCL:"); an interrupted or failed file leaves no `.part`.
  The old shared `<file>.part` failed in 5 of 5 runs of the new concurrency test.
- Browser: an unreadable preview in the disk cache is deleted and downloaded again (after the retry pause)
  instead of being served forever.
- Browser: a new search invalidates the closed asset card, so its late error no longer replaces the search status.
- Add to Stage says in the status line, tooltip, panel help and README that the node is not connected and the
  display flag is not moved.
- Tests: `panel_smoke.py` now requires the finished current search, the received details (not just the title),
  decodable tile and poster of the opened asset and a saved snapshot; `houdini_regression.py` fails when the
  catalog has no reference size. New `download_cycle.py` (temporary library: from scratch, interruption, network
  failure and retry, Download Again, two concurrent downloads, import) and `hip_roundtrip.py` (save and reopen the
  HIP in a second process, flattened USD export; compares sizes, positions, joints, materials, root xformOps and
  node parameters, with a negative self-check done by hand).

## 0.1.0-dev.3

Fixes from the external test report of 0.1.0-dev.2:

- **Asset choice is consistent.** Picking another asset sets file, name, package reference and licence together:
  the USD file is cleared until the new package is downloaded (the node warns "press Download") instead of
  showing the previous object under the new name; the licence comes from the card or is cleared.
- Browser: an error of an outdated search or of the asset details no longer stops the current search or
  overwrites its status (search and detail jobs carry different tokens).
- Browser: previews come back after being dropped from memory (read from the disk cache while drawing) and
  after a failed download (retried after a minute); clearing the cache does not mark pending previews as failed.
- Browser: the Similar list is cleared when another asset is opened.
- Core (SimRCL files, marked "HSimRCL:"): asset paths with `..` or empty segments are rejected; a package is
  marked complete only when its root USD is on disk, and a marker alone does not count as downloaded.
- Tests: `houdini_regression.py` fails on skipped cases unless `--allow-skip`; `panel_smoke.py` exits with 1
  when the catalog, results, previews or details do not load; new `panel_logic.py` (offline browser logic);
  `test_core.py` covers asset switching, unsafe paths and the completion marker.

## 0.1.0-dev.2

- **SimReady Browser** — a Python Panel (pane tab or floating window; shelf tool *SimReady Browser*), the Houdini
  counterpart of the SimRCL window: search (Hybrid / Keyword / Text) with the catalog's match percentages,
  filters (categories, providers, licence, profile, mass, bodies, size per axis) with removable chips, sorting,
  a grid of previews with a size slider and endless scrolling, asset details with the 360° and moving-parts
  clips, similar assets, Download / Add to Stage / Reveal. Double-click a tile to add it to the stage.
- Add to Stage creates a SimReady Asset node in the LOP network open in the Network Editor (else `/stage`),
  downloading the package first when needed; the node is not moved.
- Previews and the download folder are shared with SimRCL (`~/Documents/SRC by Deadwall`).
- Clips are drawn through `QVideoSink` into a plain label: `QVideoWidget` paints a native surface that does not
  show in Houdini pane captures.
- Banner `docs/hsimrcl_banner.png` at the top of both READMEs (checked by `test_repo.py`).
- README EN/RU: «About SimReady» — Omniverse / Isaac Sim context and links.
- `tests/panel_smoke.py` (hython, offscreen): catalog, search, previews, details, similar.

## 0.1.0-dev.1

- Repository layout by the plugin rules (development / installed copy, `deploy.py`, `VERSIONS.json`).
- Portable core of SimRCL (commit `1150d3e`, MIT) moved to `hsimrcl.core`: package-relative imports,
  settings in `~/Library/Application Support/SRC by Deadwall` on macOS.
- `hsimrcl::simready_asset::1.0` LOP: Search / Download / Reveal Files, USD reference under `/simready/<name>`,
  Z-up → Y-up rotation and unit scale as xformOps, licence in the prim's customData.
- Shelf `HSimRCL`, help page EN + RU.
- README EN/RU: credits to Dead_wall with links to SimRCL and its video overview.
- HTTPS inside Houdini on macOS: its Python has no root certificates; `hsimrcl.net` installs a certifi
  context only when the default one has none (verification stays on).
- Up-axis/units correction is prepended to the asset root's own xformOps instead of replacing them.
- Parts with `!resetXformStack!` (ForgeCAD writes body poses as `xformOp:transform:simulationWorld`) are
  rebased to local transforms, so they follow the correction and later moves (interior door).
- `tests/houdini_regression.py` (hython): office chair, Robotiq 2F-85, interior door — sizes match the catalog.
