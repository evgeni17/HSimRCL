# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Логика LOP-ассета hsimrcl::simready_asset: поиск, скачивание и подключение ассета SimReady в Solaris.

Нода — Python LOP внутри HDA. Ассет подключается reference'ом (а не импортом геометрии), поэтому физика,
суставы, семантика и материалы UsdPreviewSurface остаются как в исходном файле. Нода добавляет только
то, чего USD сам не делает: поворот Z-up -> Y-up и масштаб под единицы сцены.
"""
import json
import os
import re

import hou

from .core import simready_agent as agent
from .core import simready_catalog as catalog
from .core import simready_client as client
from .core import simready_settings as settings
from .net import ensure_tls

ensure_tls()  # до первого запроса к каталогу: у Python Houdini на macOS нет своих корневых сертификатов

ROOT_PRIM = "/simready"
MAX_RESULTS = 40
_METRICS_CACHE = {}  # (путь, mtime) -> (up_axis, meters_per_unit, default_prim)


# ---------------------------------------------------------------- чистые помощники (тестируются без Houdini)

def prim_name(text):
    """Имя прима из имени файла: только [A-Za-z0-9_], не с цифры."""
    stem = os.path.splitext(os.path.basename(text or ""))[0] or "asset"
    name = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    return name if not name[0].isdigit() else "_" + name


def up_rotation(asset_up, stage_up):
    """Поворот вокруг X в градусах, переводящий ось «вверх» ассета в ось сцены (только Z<->Y)."""
    if asset_up == stage_up:
        return 0.0
    return -90.0 if (asset_up, stage_up) == ("Z", "Y") else 90.0


def unit_scale(asset_mpu, stage_mpu):
    """Множитель, чтобы метр ассета остался метром в сцене."""
    if not asset_mpu or not stage_mpu:
        return 1.0
    return float(asset_mpu) / float(stage_mpu)


# ---------------------------------------------------------------- USD

def asset_metrics(path):
    """(upAxis, metersPerUnit, defaultPrim) файла; открываем без payload'ов и кэшируем по mtime — нода готовится часто."""
    from pxr import Usd, UsdGeom
    key = (path, os.path.getmtime(path))
    if key not in _METRICS_CACHE:
        stage = Usd.Stage.Open(path, Usd.Stage.LoadNone)
        default = stage.GetDefaultPrim()
        _METRICS_CACHE[key] = (str(UsdGeom.GetStageUpAxis(stage)), UsdGeom.GetStageMetersPerUnit(stage),
                               default.GetName() if default else "")
    return _METRICS_CACHE[key]


def target_path(node, file_path):
    """Путь прима: из параметра или /simready/<имя файла>."""
    custom = node.evalParm("primpath").strip()
    return custom or "%s/%s" % (ROOT_PRIM, prim_name(file_path))


def cook(node):
    """Готовка Python LOP: reference на файл ассета + xformOp'ы поворота и масштаба."""
    from pxr import Sdf, UsdGeom
    hda = node.parent()
    path = hda.evalParm("file").strip()
    if not path:
        if hda.evalParm("asset").strip():
            node.addWarning("%s is not downloaded yet: press Download." % hda.evalParm("asset"))
        return
    if not os.path.isfile(path):
        raise hou.NodeError("USD file not found: %s" % path)
    stage = node.editableStage()
    asset_up, asset_mpu, default = asset_metrics(path)
    if not default:
        raise hou.NodeError("The file has no default prim to reference: %s" % path)
    prim = UsdGeom.Xform.Define(stage, Sdf.Path(target_path(hda, path))).GetPrim()
    prim.GetReferences().AddReference(path)
    correction = _place(UsdGeom.Xformable(prim), hda, asset_up, asset_mpu, stage)
    skipped = rebase_resets(stage, prim, correction)
    _tag(prim, hda)
    if skipped:
        node.addWarning("Parts keep a world transform and ignore the up-axis/units correction "
                        "(inside instances or animated): " + ", ".join(skipped[:5]))


def _place(xformable, hda, asset_up, asset_mpu, stage):
    """Поворот и масштаб — отдельными xformOp'ами ПЕРЕД собственными операциями корня ассета.

    Возвращает матрицу T, переводящую мировые координаты файла ассета в мировые координаты сцены
    (local_root = Orig * S * R, значит world_сцены(x) = world_ассета(x) * S * R * W(родителя корня)).
    """
    from pxr import Gf, UsdGeom
    angle = up_rotation(asset_up, str(UsdGeom.GetStageUpAxis(stage))) if hda.evalParm("yup") else 0.0
    scale = unit_scale(asset_mpu, UsdGeom.GetStageMetersPerUnit(stage)) if hda.evalParm("units") else 1.0
    # собственные операции корня из файла: если записать порядок только из наших, они бы пропали
    own = xformable.GetOrderedXformOps()
    reset = xformable.GetResetXformStack()
    ours = []
    if angle:
        ours.append(xformable.AddRotateXOp(opSuffix="simready_up"))
        ours[-1].Set(angle)
    if abs(scale - 1.0) > 1e-9:
        ours.append(xformable.AddScaleOp(opSuffix="simready_units"))
        ours[-1].Set(Gf.Vec3f(scale, scale, scale))
    if ours:
        xformable.SetXformOpOrder(ours + own, reset)
    return _ops_matrix(ours) * UsdGeom.XformCache().GetLocalToWorldTransform(xformable.GetPrim().GetParent())


def _ops_matrix(ops):
    """Матрица списка операций в порядке xformOpOrder: [A, B] -> B * A."""
    from pxr import Gf, Usd
    matrix = Gf.Matrix4d(1.0)
    for op in ops:
        matrix = op.GetOpTransform(Usd.TimeCode.Default()) * matrix
    return matrix


def rebase_resets(stage, root, correction):
    """Части с !resetXformStack! (ForgeCAD пишет так мировую позу тела: xformOp:transform:simulationWorld)
    игнорируют трансформы предков — и наш поворот/масштаб, и перенос ассета пользователем. Переводим их позу
    в локальную относительно родителя: L = M * T * inverse(World_сцены(родителя)); в координатах файла поза
    не меняется. Идём сверху вниз, чтобы родитель был уже исправлен. Возвращает пропущенные пути.
    """
    from pxr import Usd, UsdGeom
    skipped = []
    targets = [p for p in Usd.PrimRange(root, Usd.TraverseInstanceProxies())
               if p != root and p.IsA(UsdGeom.Xformable) and UsdGeom.Xformable(p).GetResetXformStack()]
    for prim in sorted(targets, key=lambda p: p.GetPath().pathElementCount):
        xformable = UsdGeom.Xformable(prim)
        if prim.IsInstanceProxy() or xformable.TransformMightBeTimeVarying():
            skipped.append(str(prim.GetPath()))
            continue
        world_asset = xformable.GetLocalTransformation(Usd.TimeCode.Default())
        parent_world = UsdGeom.XformCache().GetLocalToWorldTransform(prim.GetParent())
        local = world_asset * correction * parent_world.GetInverse()
        xformable.ClearXformOpOrder()
        xformable.AddTransformOp(opSuffix="simready_local").Set(local)
    return skipped


def _tag(prim, hda):
    """Сведения о происхождении и лицензии — в customData прима, чтобы их видел и экспорт, и Scene Graph Details."""
    for key in ("asset", "license"):
        value = hda.evalParm(key).strip()
        if value:
            prim.SetCustomDataByKey("simready:" + key, value)


# ---------------------------------------------------------------- кнопки

def _node(kwargs):
    return kwargs["node"]


def _cards_from(query):
    """Карточки каталога по запросу (только разрешённые лицензии, как в SimRCL)."""
    hits, total, _ = client.search_page(query, "Hybrid", agent.search_filters(None, True), None, MAX_RESULTS, False)
    cards = [catalog.card_from_hit(hit, agent._catalog()) for hit in hits]
    return [card for card in cards if card], total


def search(kwargs):
    """Search: запрос к каталогу, выбор результата из списка, запись ассета в параметры ноды."""
    node = _node(kwargs)
    query = node.evalParm("query").strip()
    with hou.InterruptableOperation("SimReady search", open_interrupt_dialog=True):
        cards, total = _cards_from(query)
    if not cards:
        hou.ui.displayMessage("Nothing found for '%s'." % query, title="HSimRCL")
        return
    folder = settings.download_dir(settings.load())
    lines = [agent.result_line(i, c, client.is_cached(c["asset"], folder)) for i, c in enumerate(cards, 1)]
    picked = hou.ui.selectFromList(lines, exclusive=True, title="SimReady Central: %d of %d" % (len(cards), total),
                                   column_header="Asset", width=900, height=600)
    if picked:
        _choose(node, cards[picked[0]], folder)
        if not node.evalParm("license"):
            _fill_license(node)


def chosen_values(card, folder):
    """Значения параметров ноды для карточки — все про один и тот же ассет.

    Файл — корневой USD, если пакет скачан, иначе пустая строка: оставить прежний файл нельзя, иначе нода
    показывала бы старый объект под новым именем. Лицензия — из карточки или пустая (её дозаполнит Download).
    """
    cached = client.is_cached(card["asset"], folder)
    return {"asset": card["filename"], "asset_json": json.dumps(card["asset"], ensure_ascii=False),
            "title": agent.caption(card), "license": str(card.get("license") or ""),
            "file": client.cached_root_usd(card["asset"], folder) if cached else ""}


def _choose(node, card, folder):
    """Записать выбранную карточку в параметры ноды (см. chosen_values)."""
    for name, value in chosen_values(card, folder).items():
        node.parm(name).set(value)


def download(kwargs):
    """Download: скачать пакет выбранного ассета (с прогрессом и отменой) и подставить корневой USD."""
    node = _node(kwargs)
    raw = node.evalParm("asset_json")
    if not raw:
        hou.ui.displayMessage("Pick an asset with Search first.", title="HSimRCL")
        return
    asset = json.loads(raw)
    folder = settings.download_dir(settings.load())
    with hou.InterruptableOperation("Downloading " + node.evalParm("asset"), open_interrupt_dialog=True) as op:
        def progress(done, total):
            op.updateProgress(float(done) / max(total, 1))
        path = client.download_package(asset, folder, progress, node.evalParm("force"))
    node.parm("file").set(path)
    _fill_license(node)


def _fill_license(node):
    """Лицензия из каталога (один маленький запрос); без сети просто оставляем поле пустым."""
    try:
        stem = os.path.splitext(node.evalParm("asset"))[0]
        hits, _, _ = client.search_page(stem, "Keyword", {}, None, 5, True)
    except Exception:  # сеть недоступна — лицензия не критична для импорта
        return
    want = json.loads(node.evalParm("asset_json") or "{}").get("path")
    hit = next((h for h in hits if h.get("source", {}).get("path") == want), None)
    props = catalog._properties(hit) if hit else {}
    node.parm("license").set(str(props.get(client.LICENSE_PROPERTY) or ""))


def reveal(kwargs):
    """Показать папку пакета в Finder."""
    path = _node(kwargs).evalParm("file")
    if path:
        hou.ui.showInFileBrowser(path)
