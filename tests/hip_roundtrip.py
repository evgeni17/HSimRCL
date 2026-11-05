# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Сохранение и повторное открытие сцены, экспорт USD — двумя отдельными процессами hython.

    hython tests/hip_roundtrip.py build <scene.hip> <snapshot.json>
    hython tests/hip_roundtrip.py check <scene.hip> <snapshot.json>

build: ноды SimReady Asset для скачанных тестовых ассетов (кресло, Robotiq, дверь из библиотеки пользователя,
только чтение), снимок состояния (путь прима, размеры, суставы, материалы, xformOp'ы корня), сохранение HIP и
экспорт сцены в USD рядом с ним. check: открыть HIP в новом процессе, сравнить со снимком, сравнить размеры
в экспортированном USD. Код выхода 1 при расхождении.
"""
import json
import os
import sys

import hou

import hsimrcl
from hsimrcl import lop
from hsimrcl.core import simready_agent as sr
from hsimrcl.core import simready_client as client
from hsimrcl.core import simready_settings as settings
from hsimrcl.net import ensure_tls

ASSETS = (("chair", "sm_chair_office_fabric_manager_a01", "sm_chair_office_fabric_manager_a01_01.usd"),
          ("gripper", "Robotiq_2F_85", "Robotiq_2F_85.usda"),
          ("door", "interior_door", "interior_door.usda"))
TOLERANCE = 1e-4


def describe(stage, path):
    """Снимок одного ассета на сцене: размеры, число суставов и материалов, операции корня."""
    from pxr import Usd, UsdGeom, UsdPhysics
    prim = stage.GetPrimAtPath(path)
    if not prim:
        return None
    box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"]).ComputeWorldBound(prim).ComputeAlignedRange()
    prims = list(Usd.PrimRange(prim, Usd.TraverseInstanceProxies()))
    return {"size": [box.GetMax()[i] - box.GetMin()[i] for i in range(3)],
            "min": list(box.GetMin()),
            "joints": sum(1 for p in prims if p.IsA(UsdPhysics.Joint)),
            "materials": sum(1 for p in prims if p.GetTypeName() == "Material"),
            "ops": [str(op) for op in (UsdGeom.Xformable(prim).GetXformOpOrderAttr().Get() or [])]}


def build(hip, snapshot):
    ensure_tls()
    folder = settings.download_dir(settings.load())
    merge = hou.node("/stage").createNode("merge", "all_assets")
    state = {}
    for index, (name, query, filename) in enumerate(ASSETS):
        sr.find(query, limit=10, mode="Keyword")
        card = next((c for c in sr._STATE["cards"] if c["filename"] == filename), None)
        if card is None or not client.is_cached(card["asset"], folder):
            print("hip_roundtrip: FAILED (%s is not downloaded; run houdini_regression.py first)" % filename)
            return 1
        node = hou.node("/stage").createNode(hsimrcl.ASSET_TYPE, name)
        lop._choose(node, card, folder)
        merge.setInput(index, node)
        state[name] = {"node": node.path(), "prim": lop.target_path(node, node.evalParm("file")),
                       "file": node.evalParm("file"), "license": node.evalParm("license")}
    merge.setDisplayFlag(True)
    stage = merge.stage()
    for name, entry in state.items():
        entry.update(describe(stage, entry["prim"]))
    usd = os.path.splitext(hip)[0] + "_export.usdc"  # usdc: плоская сцена с геометрией компактнее
    stage.Export(usd)  # сцена целиком в один слой (flatten), как экспорт USD ROP
    hou.hipFile.save(hip)
    with open(snapshot, "w", encoding="utf-8") as handle:
        json.dump({"usd": usd, "assets": state}, handle, indent=1)
    print("hip_roundtrip build: saved %s, %s" % (hip, usd))
    return 0


def close(a, b):
    return all(abs(x - y) <= TOLERANCE for x, y in zip(a, b))


def check(hip, snapshot):
    from pxr import Usd
    data = json.load(open(snapshot, encoding="utf-8"))
    hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    stage = hou.node("/stage/all_assets").stage()
    exported = Usd.Stage.Open(data["usd"])
    problems = []
    for name, want in data["assets"].items():
        node = hou.node(want["node"])
        if node is None or node.type().name() != hsimrcl.ASSET_TYPE:
            problems.append("%s: node or type changed" % name)
            continue
        if node.evalParm("file") != want["file"] or node.evalParm("license") != want["license"]:
            problems.append("%s: parameters changed" % name)
        for label, got in (("reopened", describe(stage, want["prim"])), ("exported USD", describe(exported, want["prim"]))):
            if got is None:
                problems.append("%s: no prim in %s" % (name, label))
                continue
            for key in ("joints", "materials", "ops"):
                if got[key] != want[key]:
                    problems.append("%s %s: %s %s != %s" % (name, label, key, got[key], want[key]))
            if not close(got["size"], want["size"]) or not close(got["min"], want["min"]):
                problems.append("%s %s: bounds moved" % (name, label))
    for problem in problems:
        print("BAD " + problem)
    print("hip_roundtrip check: %s" % ("OK" if not problems else "FAILED"))
    return 1 if problems else 0


if __name__ == "__main__":
    mode, hip_path, snapshot_path = sys.argv[1:4]
    sys.exit(build(hip_path, snapshot_path) if mode == "build" else check(hip_path, snapshot_path))
