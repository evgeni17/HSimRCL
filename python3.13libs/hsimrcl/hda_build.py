# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Сборка HDA плагина (hsimrcl::simready_asset) из кода.

Запуск в Python Shell Houdini (после deploy.py, см. CONTRIBUTING.md):
    import hsimrcl.hda_build as b; b.build_all(otls="<папка разработки>/otls")
HDA тонкий: логика в модуле hsimrcl.lop, пересборка нужна только при смене интерфейса или справки.
"""
import os

import hou

from . import ROOT, __version__, ASSET_TYPE, HDA_VERSION, FROZEN
from .help_text import HELP_ASSET

OTLS = os.path.join(ROOT, "otls")
BUILD_NODE = "__hsimrcl_build"

# имя пакета, из которого собирается ассет: "hsimrcl" у разработки, "hsimrcl_1_0" у замороженной копии.
# Заглушка и callback'и ссылаются именно на него — замороженный ассет не вызовет изменяемый код.
PKG = __name__.split(".")[0]

COOK_CODE = """# HSimRCL: подключение ассета SimReady (логика в модуле %(pkg)s.lop)
import %(pkg)s.lop as m
m.cook(hou.pwd())
""" % {"pkg": PKG}


def _button(name, label, func, **kw):
    return hou.ButtonParmTemplate(name, label, script_callback="import %s.lop as m; m.%s(kwargs)" % (PKG, func),
                                  script_callback_language=hou.scriptLanguage.Python, **kw)


def _ptg():
    g = hou.ParmTemplateGroup()
    f = hou.FolderParmTemplate("catalog_f", "SimReady Central", folder_type=hou.folderType.Simple)
    f.addParmTemplate(hou.StringParmTemplate("query", "Search", 1, default_value=("",),
                                             help="Words or a description, e.g. 'office chair' or 'robot gripper'."))
    f.addParmTemplate(_button("search", "Search", "search", join_with_next=True))
    f.addParmTemplate(_button("download", "Download", "download", join_with_next=True))
    f.addParmTemplate(_button("reveal", "Reveal Files", "reveal"))
    f.addParmTemplate(hou.ToggleParmTemplate("force", "Download Again", default_value=False,
                                             help="Download every file again even if the package is on disk."))
    f.addParmTemplate(hou.StringParmTemplate("asset", "Asset", 1, default_value=("",)))
    f.addParmTemplate(hou.StringParmTemplate("title", "Title", 1, default_value=("",)))
    f.addParmTemplate(hou.StringParmTemplate("license", "License", 1, default_value=("",),
                                             help="Each asset has its own licence (mostly CC BY 4.0: credit the "
                                                  "author and note your changes)."))
    f.addParmTemplate(hou.StringParmTemplate("asset_json", "Asset Reference", 1, default_value=("",),
                                             is_hidden=True))
    g.append(f)
    f = hou.FolderParmTemplate("usd_f", "USD", folder_type=hou.folderType.Simple)
    f.addParmTemplate(hou.StringParmTemplate("file", "USD File", 1, default_value=("",),
                                             string_type=hou.stringParmType.FileReference, file_type=hou.fileType.Usd))
    f.addParmTemplate(hou.StringParmTemplate("primpath", "Primitive Path", 1, default_value=("",),
                                             help="Empty: /simready/<file name>."))
    f.addParmTemplate(hou.ToggleParmTemplate("yup", "Z-Up to Y-Up", default_value=True,
                                             help="SimReady assets are Z-up; the stage is usually Y-up."))
    f.addParmTemplate(hou.ToggleParmTemplate("units", "Match Stage Units", default_value=True,
                                             help="Scale by the asset's metersPerUnit over the stage's, so sizes stay real."))
    g.append(f)
    return g


def _tool_xml():
    return """<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <tool name="$HDA_DEFAULT_TOOL" label="$HDA_LABEL" icon="$HDA_ICON">
    <toolMenuContext name="viewer"><contextNetType>LOP</contextNetType></toolMenuContext>
    <toolMenuContext name="network"><contextOpType>$HDA_TABLE_AND_NAME</contextOpType></toolMenuContext>
    <toolSubmenu>HSimRCL</toolSubmenu>
    <script scriptType="python"><![CDATA[import loptoolutils
loptoolutils.genericTool(kwargs, '$HDA_NAME')]]></script>
  </tool>
</shelfDocument>
"""


def _build_parent():
    stage = hou.node("/stage")
    old = stage.node(BUILD_NODE)
    if old is not None:
        old.destroy()
    return stage.createNode("subnet", BUILD_NODE)


def build_asset(otls):
    """Subnet LOP: вход -> Python LOP (reference + поворот/масштаб) -> выход."""
    sub = _build_parent()
    for child in sub.children():
        child.destroy()
    py = sub.createNode("pythonscript", "SIMREADY_REFERENCE")
    py.parm("python").set(COOK_CODE)
    py.setInput(0, sub.indirectInputs()[0])
    out = sub.createNode("output", "output0")
    out.setInput(0, py)
    out.setDisplayFlag(True)
    path = os.path.join(otls, "hsimrcl_simready_asset_%s.hda" % HDA_VERSION)
    if os.path.exists(path):
        for d in hou.hda.definitionsInFile(path):
            if d.nodeTypeName() == ASSET_TYPE:
                d.destroy()
    ptg = _ptg()
    sub.setParmTemplateGroup(ptg)
    hda = sub.createDigitalAsset(name=ASSET_TYPE, hda_file_name=path, description="SimReady Asset",
                                 min_num_inputs=0, max_num_inputs=1, ignore_external_references=True)
    d = hda.type().definition()
    d.setParmTemplateGroup(ptg)  # updateFromNode не синхронизирует интерфейс — пишем явно
    d.setIcon("LOP_reference")
    d.setVersion(__version__)
    d.addSection("Tools.shelf", _tool_xml())
    d.addSection("Help", HELP_ASSET)
    d.save(path, hda)
    return path


def build_all(kwargs=None, otls=None, install=True, force=False):
    """Собрать все HDA в otls (по умолчанию $HSIMRCL/otls). Замороженную версию — только с force=True."""
    if FROZEN and not force:
        raise RuntimeError("%s is frozen (assets ::%s): rebuilding it would change scenes that use it"
                           % (PKG, HDA_VERSION))
    otls = otls or OTLS
    os.makedirs(otls, exist_ok=True)
    paths = [build_asset(otls)]
    tmp = hou.node("/stage/" + BUILD_NODE)
    if tmp is not None:
        tmp.destroy()
    for p in paths:
        if install:
            hou.hda.installFile(p)
            hou.hda.reloadFile(p)
    print("[HSimRCL] HDAs built:\n" + "\n".join(paths))
    return paths
