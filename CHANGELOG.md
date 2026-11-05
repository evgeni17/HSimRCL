# Changelog

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
