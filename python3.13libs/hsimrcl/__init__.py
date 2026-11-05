# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""HSimRCL — браузер и импорт ассетов NVIDIA SimReady Central в Houdini (Solaris).

Порт SimRCL (Cinema 4D, автор Dead_wall, MIT): переносимое ядро лежит в подпакете core почти без правок,
Houdini-часть — в модулях этого пакета. Пакет подключается через packages/HSimRCL.json ($HSIMRCL — корень плагина).
"""
import os

__version__ = "0.1.0.dev3"

# правило: релиз плагина 0.N -> ассеты ::N.0; до первого выпуска разработка идёт на ::1.0
HDA_VERSION = "1.0"
FROZEN = False
ASSET_TYPE = "hsimrcl::simready_asset::" + HDA_VERSION

# сторонних модулей в vendor/ нет: USD (pxr) берём из Houdini, сеть — urllib из стандартной библиотеки
VENDOR = {}
HOUDINI_TESTED = "22.0.466"
PYTHON_TESTED = "3.13"
# коммит SimRCL, с которого перенесено ядро (core/*.py); при переносе обновлений менять вместе с заголовками файлов
SIMRCL_UPSTREAM = "1150d3e"

# корень плагина: .../HSimRCL (этот файл: .../HSimRCL/python3.13libs/hsimrcl/__init__.py)
ROOT = os.environ.get("HSIMRCL") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
