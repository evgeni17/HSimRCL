# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Проверки без Houdini: ядро SimRCL импортируется как пакет, пути настроек, чистые помощники lop."""
import ast
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBS = os.path.join(ROOT, "python3.13libs")
sys.path.insert(0, LIBS)
FAILS = []


def check(label, got, want):
    ok = got == want
    print("%s %s: %r%s" % ("ok " if ok else "BAD", label, got, "" if ok else "  (want %r)" % (want,)))
    if not ok:
        FAILS.append(label)


def test_core_imports():
    """Модули ядра грузятся через hsimrcl.core и не тянут одноимённые модули верхнего уровня."""
    from hsimrcl.core import simready_agent, simready_catalog, simready_library, simready_tasks  # noqa: F401
    check("no top-level simready_client", "simready_client" in sys.modules, False)
    check("catalog uses package client", simready_catalog.simready_client.__name__, "hsimrcl.core.simready_client")


def test_no_absolute_sibling_imports():
    """Ни одного `import simready_x` верхнего уровня в ядре (кроме ленивого C4D-кода agent.add)."""
    core = os.path.join(LIBS, "hsimrcl", "core")
    bad = []
    for name in sorted(os.listdir(core)):
        if name.endswith(".py"):
            for node in ast.walk(ast.parse(open(os.path.join(core, name), encoding="utf-8").read())):
                if isinstance(node, ast.Import) and any(a.name.startswith("simready_") for a in node.names):
                    bad.append(name)
    check("absolute sibling imports", bad, [])


def test_settings_paths():
    from hsimrcl.core import simready_settings as s
    if sys.platform == "darwin":
        check("mac settings dir", s.SETTINGS_PATH.startswith(os.path.expanduser("~/Library/Application Support")), True)
    check("download default", s.DEFAULT_DOWNLOAD_DIR.endswith(os.path.join("SRC by Deadwall", "Assets")), True)


def _lop():
    """hsimrcl.lop без Houdini: подставляем пустой модуль hou."""
    sys.modules.setdefault("hou", types.ModuleType("hou"))
    from hsimrcl import lop
    return lop


def test_lop_helpers():
    lop = _lop()
    check("prim_name plain", lop.prim_name("/a/b/sm_chair_a01.usd"), "sm_chair_a01")
    check("prim_name digits", lop.prim_name("3d-model v2.usda"), "_3d_model_v2")
    check("prim_name empty", lop.prim_name(""), "asset")
    check("z to y", lop.up_rotation("Z", "Y"), -90.0)
    check("y to z", lop.up_rotation("Y", "Z"), 90.0)
    check("same axis", lop.up_rotation("Y", "Y"), 0.0)
    check("units m->m", lop.unit_scale(1.0, 1.0), 1.0)
    check("units cm->m", lop.unit_scale(0.01, 1.0), 0.01)
    check("units missing", lop.unit_scale(0, 1.0), 1.0)


if __name__ == "__main__":
    for fn in (test_core_imports, test_no_absolute_sibling_imports, test_settings_paths, test_lop_helpers):
        fn()
    print("test_core: %s" % ("OK" if not FAILS else "FAILED " + ", ".join(FAILS)))
    sys.exit(1 if FAILS else 0)
