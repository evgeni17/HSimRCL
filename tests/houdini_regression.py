# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Регресс в hython: ассеты из чек-листа SimRCL через ноду simready_asset (нужна сеть или скачанные пакеты).

    hython tests/houdini_regression.py [--allow-skip]

Пропуск (нет сети и нет пакета на диске, ассета нет в ответе каталога) считается ошибкой: код выхода 0
должен значить, что все случаи действительно проверены. --allow-skip — для прогона без сети.

Каждый раздел печатает `houdini_regression <раздел>: OK` или `SKIPPED (причина)`.
Размеры сверяются с каталогом (dims, метры, Z-up файла -> X, Z, Y сцены).
"""
import sys

import hou

import hsimrcl
from hsimrcl import lop
from hsimrcl.core import simready_agent as sr
from hsimrcl.core import simready_client as client
from hsimrcl.core import simready_settings as settings

# запрос, режим, имя файла ассета, допуск по размеру (м); ищем по имени файла — порядок выдачи каталога меняется
CASES = {
    "chair": ("sm_chair_office_fabric_manager_a01", "Keyword", "sm_chair_office_fabric_manager_a01_01.usd", 0.02),
    "gripper": ("Robotiq_2F_85", "Keyword", "Robotiq_2F_85.usda", 0.01),
    "door": ("interior_door", "Keyword", "interior_door.usda", 0.03),   # ForgeCAD: части с !resetXformStack!
}


ALLOW_SKIP = "--allow-skip" in sys.argv


def bbox_size(node):
    from pxr import Usd, UsdGeom
    stage = node.stage()
    prim = stage.GetPrimAtPath(lop.target_path(node, node.evalParm("file")))
    box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"]).ComputeWorldBound(prim).ComputeAlignedRange()
    return [box.GetMax()[i] - box.GetMin()[i] for i in range(3)], box.GetMin()[1]


def run_case(name, query, mode, filename, tol):
    sr.find(query, limit=10, mode=mode)
    card = next((c for c in sr._STATE["cards"] if c["filename"] == filename), None)
    if card is None:
        print("houdini_regression %s: SKIPPED (%s not in the catalog answer)" % (name, filename))
        return ALLOW_SKIP
    folder = settings.download_dir(settings.load())
    if not client.is_cached(card["asset"], folder):
        client.download_package(card["asset"], folder)
    node = hou.node("/stage").createNode(hsimrcl.ASSET_TYPE, name)
    lop._choose(node, card, folder)
    size, bottom = bbox_size(node)
    want = card.get("dims")  # x, y, z файла (Z-up) -> в сцене x, z, y
    problems = list(node.errors()) + [e for c in node.children() for e in c.errors()]
    if want:
        expect = [want[0], want[2], want[1]]
        problems += ["size %s != %s" % ([round(v, 3) for v in size], expect)
                     for _ in [0] if any(abs(a - b) > tol for a, b in zip(size, expect))]
    if abs(bottom) > 0.06:
        problems.append("bottom at y=%.3f" % bottom)
    print("houdini_regression %s: %s" % (name, "OK" if not problems else "FAILED " + "; ".join(problems)))
    return not problems


def main():
    ok = True
    for name, case in CASES.items():
        try:
            ok = run_case(name, *case) and ok
        except OSError as error:  # нет сети и нет пакета на диске
            print("houdini_regression %s: SKIPPED (%s)" % (name, error))
            ok = ok and ALLOW_SKIP
    print("houdini_regression: %s" % ("OK" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
