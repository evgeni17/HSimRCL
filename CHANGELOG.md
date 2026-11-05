# Changelog

## 0.1.0-dev.1

- Repository layout by the plugin rules (development / installed copy, `deploy.py`, `VERSIONS.json`).
- Portable core of SimRCL (commit `1150d3e`, MIT) moved to `hsimrcl.core`: package-relative imports,
  settings in `~/Library/Application Support/SRC by Deadwall` on macOS.
- `hsimrcl::simready_asset::1.0` LOP: Search / Download / Reveal Files, USD reference under `/simready/<name>`,
  Z-up → Y-up rotation and unit scale as xformOps, licence in the prim's customData.
- Shelf `HSimRCL`, help page EN + RU.
