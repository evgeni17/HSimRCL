# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Полный цикл скачивания во временную библиотеку (сеть обязательна): hython tests/download_cycle.py

Сценарии: загрузка с нуля, прерывание на середине, сбой сети и повтор, Download Again (force), две
одновременные загрузки одного пакета, импорт результата нодой SimReady Asset. Библиотека пользователя не
трогается: всё пишется во временную папку и удаляется в конце. Код выхода 1 при любой ошибке.
"""
import os
import shutil
import sys
import tempfile
import threading

import hou

import hsimrcl
from hsimrcl import lop
from hsimrcl.core import simready_agent as sr
from hsimrcl.core import simready_client as client
from hsimrcl.net import ensure_tls

ASSET = ("Robotiq_2F_85", "Robotiq_2F_85.usda")  # маленький пакет (~5 МБ) с суставом
FAILS = []


class Stop(Exception):
    """Прерывание загрузки из progress (как отмена в диалоге Houdini)."""


def check(label, ok, detail=""):
    print("%s %s%s" % ("ok " if ok else "BAD", label, "" if ok else ": %s" % (detail,)))
    if not ok:
        FAILS.append(label)


def parts_left(folder):
    return [os.path.join(b, f) for b, _, files in os.walk(folder) for f in files if f.endswith(".part")]


def package_files_ok(asset, folder):
    """Каждый файл манифеста лежит на месте и совпадает по размеру."""
    root = client.package_root(asset, folder)
    bad = []
    for rel, size in client.select_files(client.fetch_manifest(asset["path"])):
        path = client._safe_join(root, rel)
        if path is None or not os.path.isfile(path) or (size is not None and os.path.getsize(path) != size):
            bad.append(rel)
    return bad


def from_scratch(asset, folder):
    path = client.download_package(asset, folder)
    check("scratch: root USD on disk", path and os.path.isfile(path), path)
    check("scratch: marked complete", client.is_cached(asset, folder))
    check("scratch: all files with manifest sizes", not package_files_ok(asset, folder), package_files_ok(asset, folder))
    check("scratch: no temporary files", not parts_left(folder), parts_left(folder))
    return path


def interrupted(asset, folder):
    def progress(done, total):
        if done == 1 and total > 1:
            raise Stop()
    try:
        client.download_package(asset, folder, progress)
        stopped = False
    except Stop:
        stopped = True
    check("interrupt: stopped", stopped)
    check("interrupt: not marked complete", not client.is_cached(asset, folder))
    check("interrupt: no temporary files", not parts_left(folder), parts_left(folder))
    path = client.download_package(asset, folder)
    check("interrupt: retry completes", client.is_cached(asset, folder) and os.path.isfile(path))


def network_failure(asset, folder):
    real = client._resolve_url
    broken = {"done": False}

    def flaky(ref, rel):  # первый файл ведёт на несуществующий адрес — как обрыв сети
        if not broken["done"]:
            broken["done"] = True
            return "https://huggingface.co/hsimrcl-test-missing-file"
        return real(ref, rel)
    client._resolve_url = flaky
    try:
        client.download_package(asset, folder)
        failed = False
    except OSError:
        failed = True
    finally:
        client._resolve_url = real
    check("network failure: error raised", failed)
    check("network failure: not marked complete", not client.is_cached(asset, folder))
    check("network failure: no temporary files", not parts_left(folder), parts_left(folder))
    client.download_package(asset, folder)
    check("network failure: retry completes", client.is_cached(asset, folder) and not package_files_ok(asset, folder))


def download_again(asset, folder):
    path = client.cached_root_usd(asset, folder)
    before = os.path.getmtime(path)
    client.download_package(asset, folder, force=True)
    check("download again: still complete", client.is_cached(asset, folder))
    check("download again: file replaced", os.path.getmtime(path) >= before)
    check("download again: no temporary files", not parts_left(folder), parts_left(folder))


def concurrent(asset, folder):
    errors, paths = [], []

    def work():
        try:
            paths.append(client.download_package(asset, folder))
        except Exception as error:  # оба потока должны завершиться без ошибки
            errors.append(repr(error))
    threads = [threading.Thread(target=work) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    check("concurrent: no errors", not errors, errors)
    check("concurrent: same root USD", len(set(paths)) == 1 and len(paths) == 2, paths)
    check("concurrent: files intact", not package_files_ok(asset, folder), package_files_ok(asset, folder))
    check("concurrent: no temporary files", not parts_left(folder), parts_left(folder))


def imported(card, folder):
    node = hou.node("/stage").createNode(hsimrcl.ASSET_TYPE, "cycle_import")
    lop._choose(node, card, folder)
    node.cook(force=True)
    errors = list(node.errors()) + [e for c in node.children() for e in c.errors()]
    from pxr import Usd, UsdGeom
    prim = node.stage().GetPrimAtPath(lop.target_path(node, node.evalParm("file")))
    box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"]).ComputeWorldBound(prim).ComputeAlignedRange()
    size = [box.GetMax()[i] - box.GetMin()[i] for i in range(3)]
    want = card["dims"]
    check("import: no errors", not errors, errors)
    check("import: size matches the catalog", bool(want) and all(abs(a - b) < 0.01 for a, b in zip(size, [want[0], want[2], want[1]])),
          (size, want))


def main():
    ensure_tls()
    sr.find(ASSET[0], limit=10, mode="Keyword")
    card = next((c for c in sr._STATE["cards"] if c["filename"] == ASSET[1]), None)
    if card is None:
        print("download_cycle: FAILED (%s not in the catalog answer)" % ASSET[1])
        return 1
    base = tempfile.mkdtemp(prefix="hsimrcl_cycle_")
    try:
        for step in (from_scratch, interrupted, network_failure, concurrent):  # у каждого своя пустая библиотека
            step(card["asset"], os.path.join(base, step.__name__))
        download_again(card["asset"], os.path.join(base, "from_scratch"))
        imported(card, os.path.join(base, "from_scratch"))
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("download_cycle: %s" % ("OK" if not FAILS else "FAILED " + ", ".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
