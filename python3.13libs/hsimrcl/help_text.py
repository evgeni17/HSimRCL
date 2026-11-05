# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Справка нод: одна страница, сначала английский, ниже тот же раздел по-русски."""

HELP_ASSET = """= SimReady Asset =

#type: node
#context: lop
#internal: hsimrcl::simready_asset
#icon: LOP/reference

\"\"\"Finds, downloads and references an NVIDIA SimReady Central asset into the stage.\"\"\"

The asset is brought in as a USD reference, so its physics (rigid bodies, joints, colliders), semantics and
UsdPreviewSurface materials stay exactly as in the file and render in Karma without conversion. The node adds
only what USD does not do by itself: a rotation from Z-up to the stage's Y-up and a scale to the stage units.

== Usage ==

# Type words in __Search__ and press __Search__; pick an asset in the list.
# Press __Download__. The package goes to the SimRCL download folder (shared with the Cinema 4D version).
# The __USD File__ is filled in and the asset appears under `/simready/<name>`.

== Licences ==

Every asset has its own licence, mostly CC BY 4.0: credit the author and note your changes. The licence is
written into the __License__ field and into the prim's customData (`simready:license`).

@parameters

Search:
    Words or a description of the asset.
Download Again:
    Download every file again even when the package is already on disk.
USD File:
    The root USD file of the package. Any local SimReady file works too.
Primitive Path:
    Where the reference goes. Empty means `/simready/<file name>`.
Z-Up to Y-Up:
    Rotate -90 degrees around X when the asset is Z-up and the stage is Y-up.
Match Stage Units:
    Scale by the asset's metersPerUnit divided by the stage's.

----

= SimReady Asset (по-русски) =

Находит, скачивает и подключает в сцену ассет NVIDIA SimReady Central.

Ассет подключается reference'ом USD: физика (твёрдые тела, суставы, коллизии), семантика и материалы
UsdPreviewSurface остаются как в файле и рендерятся в Karma без перевода. Нода добавляет только то, чего USD
сам не делает: поворот из Z-up в Y-up сцены и масштаб под единицы сцены.

== Как пользоваться ==

# Введите слова в __Search__ и нажмите __Search__, выберите ассет в списке.
# Нажмите __Download__. Пакет ложится в папку загрузок SimRCL (общую с версией для Cinema 4D).
# Поле __USD File__ заполнится, ассет появится в `/simready/<имя>`.

== Лицензии ==

У каждого ассета своя лицензия, чаще всего CC BY 4.0: указать автора и отметить свои изменения. Лицензия
записывается в поле __License__ и в customData прима (`simready:license`).
"""
