# Contributing

Contributions are welcome under the Apache License 2.0; add your name to `AUTHORS`.
Do not copy GPL code or commit third-party binaries.

The development plan (stages, decisions, rejected options) lives in `docs/PLAN.ru.md`, in Russian.

## Development layout

Houdini never loads the repository. The package `HSimRCL.json` points at the **installed** copy,
`~/tools_houdini/HSimRCL`. Edit the repository, then install:

```bash
python3 deploy.py ~/tools_houdini/HSimRCL      # --dry-run to preview, --clean to drop stale files
```

If the node interface or help changed, rebuild the assets **after** installing (build_all reads the installed code):

1. `python3 deploy.py ~/tools_houdini/HSimRCL`
2. in Houdini: drop `hsimrcl*` from `sys.modules`
3. `import hsimrcl.hda_build as b; b.build_all(otls="<repo>/otls")`
4. `python3 deploy.py ~/tools_houdini/HSimRCL` again, then `hou.hda.reloadFile(...)`

## SimRCL core

`python3.13libs/hsimrcl/core/simready_*.py` are SimRCL files with minimal, header-marked changes
(relative imports, macOS paths). Keep them close to upstream so SimRCL updates can be merged as a diff;
the upstream commit is `SIMRCL_UPSTREAM` in `hsimrcl/__init__.py`.

## Versions

Plugin release `0.N` → assets `::N.0`; the development version is `::1.0` until 0.1 is released.
Node type names are written only through constants in `hsimrcl/__init__.py`.

## Tests

`python3 tests/test_core.py` and `python3 tests/test_repo.py` run without Houdini.
