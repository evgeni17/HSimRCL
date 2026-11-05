# HSimRCL — SimReady Central for Houdini

[Русская версия](README.ru.md)

Find, download and reference [NVIDIA SimReady Central](https://docs.omniverse.nvidia.com/simready/latest/simready-central.html)
assets in Houdini Solaris. A port of [SimRCL](https://github.com/denwerdan-arch/SimRCL) by Dead_wall (Cinema 4D):
its portable core (catalog search, downloads, local library) is reused; the Houdini side is new.

> Status: **0.1.0 in development** — nodes of the development version can change between builds; do not rely on
> them in production scenes yet.

## What it does

- **SimReady Asset** LOP (`hsimrcl::simready_asset::1.0`): search the catalog, download a package, reference its
  root USD under `/simready/<name>`.
- The asset stays a USD reference: physics, joints, colliders, semantics and UsdPreviewSurface materials are kept
  as authored and render in Karma.
- Adds only a Z-up → Y-up rotation and a unit scale as separate xformOps.
- Downloads go to the same folder as SimRCL for Cinema 4D (`~/Documents/SRC by Deadwall/Assets`), so packages are shared.

## Install

1. Copy or clone this folder, e.g. to `~/tools_houdini/HSimRCL`.
2. Put `HSimRCL.json` into a Houdini `packages` folder and set `HSIMRCL` to that path.
3. Restart Houdini. In `/stage` press Tab → **HSimRCL → SimReady Asset**.

Requirements: Houdini 22 (Python 3.13), internet access to `nvidia-simready-central.hf.space` and `huggingface.co`.

## Licences

Code: Apache-2.0 (see `LICENSE`), except the SimRCL core files under MIT (see `NOTICE`).
Every asset has its own licence, mostly CC BY 4.0 — credit the author and note your changes.

HSimRCL is an independent project, not made or endorsed by NVIDIA or SideFX.
