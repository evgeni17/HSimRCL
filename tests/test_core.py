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


class _Parm:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def set(self, value):
        self.store[self.name] = value


class _Node:
    """Нода-заглушка: parm(name).set(...) и evalParm(name)."""

    def __init__(self):
        self.values = {}

    def parm(self, name):
        return _Parm(self.values, name)

    def evalParm(self, name):
        return self.values.get(name, "")


def _card(name, license=None):
    ref = {"repo": "org/repo", "commit": "0123456789abcdef", "package": name, "rel": "simready_usd/%s.usd" % name}
    asset = {"path": "hf://huggingface.co/datasets/org/repo/resolve/0123456789abcdef/%s/simready_usd/%s.usd" % (name, name),
             "name": name + ".usd", "ref": ref}
    return {"asset": asset, "filename": name + ".usd", "title": name.title(), "license": license, "vlm": {}}


def test_choose_switch():
    """Смена ассета: файл, лицензия и имя всегда от нового ассета (раньше файл и лицензия оставались от старого)."""
    lop = _lop()
    client = lop.client
    cached = {"chair"}
    saved = client.is_cached, client.cached_root_usd
    client.is_cached = lambda asset, folder: asset["ref"]["package"] in cached
    client.cached_root_usd = lambda asset, folder: "/lib/%s.usd" % asset["ref"]["package"]
    try:
        node = _Node()
        lop._choose(node, _card("chair", "CC-BY-4.0"), "/lib")
        check("cached: file", node.evalParm("file"), "/lib/chair.usd")
        check("cached: license from card", node.evalParm("license"), "CC-BY-4.0")
        lop._choose(node, _card("door"), "/lib")
        check("not cached: file cleared", node.evalParm("file"), "")
        check("not cached: license cleared", node.evalParm("license"), "")
        check("not cached: asset", node.evalParm("asset"), "door.usd")
    finally:
        client.is_cached, client.cached_root_usd = saved


def test_unsafe_paths():
    """Сегменты пути ассета с ".." или пустые — не ассет (иначе пакет лёг бы вне папки загрузки)."""
    from hsimrcl.core import simready_client as client
    good = "hf://huggingface.co/datasets/org/repo/resolve/0123abcd/chair/simready_usd/chair.usd"
    check("good path", (client.parse_hf_path(good) or {}).get("package"), "chair")
    for bad in ("hf://huggingface.co/datasets/org/repo/resolve/../../chair/x.usd",
                "hf://huggingface.co/datasets/org/repo/resolve/0123abcd/../x.usd",
                "hf://huggingface.co/datasets/../repo/resolve/0123abcd/chair/x.usd",
                "hf://huggingface.co/datasets/org//resolve/0123abcd/chair/x.usd"):
        check("unsafe " + bad.split("/datasets/")[1][:28], client.parse_hf_path(bad), None)


def test_marker_needs_root_usd():
    """Пакет, в манифесте которого нет корневого USD, не помечается скачанным."""
    import tempfile
    from hsimrcl.core import simready_client as client
    asset = {"path": "hf://huggingface.co/datasets/org/repo/resolve/0123abcd/chair/simready_usd/chair.usd",
             "name": "chair.usd", "ref": client.parse_hf_path(
                 "hf://huggingface.co/datasets/org/repo/resolve/0123abcd/chair/simready_usd/chair.usd")}
    saved = client.fetch_manifest, client.select_files, client._download_job
    client.fetch_manifest = lambda path: {}
    client.select_files = lambda manifest: [("textures/a.png", 1)]
    client._download_job = lambda ref, root, rel, size, force=False: None   # ничего не пишет: корневого USD нет
    folder = tempfile.mkdtemp()
    try:
        try:
            client.download_package(asset, folder)
            raised = False
        except OSError:
            raised = True
        check("no root USD raises", raised, True)
        marker = os.path.join(client.package_root(asset, folder), client.COMPLETE_MARKER)
        check("no completion marker", os.path.exists(marker), False)
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        open(marker, "w").close()
        check("marker alone is not cached", client.is_cached(asset, folder), False)
    finally:
        client.fetch_manifest, client.select_files, client._download_job = saved
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_core_imports, test_no_absolute_sibling_imports, test_settings_paths, test_lop_helpers,
               test_choose_switch, test_unsafe_paths, test_marker_needs_root_usd):
        fn()
    print("test_core: %s" % ("OK" if not FAILS else "FAILED " + ", ".join(FAILS)))
    sys.exit(1 if FAILS else 0)
