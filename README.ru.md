# HSimRCL — SimReady Central для Houdini

[English version](README.md)

Поиск, скачивание и подключение ассетов [NVIDIA SimReady Central](https://docs.omniverse.nvidia.com/simready/latest/simready-central.html)
в Houdini Solaris. Порт [SimRCL](https://github.com/denwerdan-arch/SimRCL) автора Dead_wall (Cinema 4D):
его переносимое ядро (поиск в каталоге, скачивание, локальная библиотека) используется как есть, Houdini-часть — новая.

## Благодарность

Огромное спасибо **Dead_wall** — автору [SimRCL](https://github.com/denwerdan-arch/SimRCL), браузера SimReady Central
для Cinema 4D. HSimRCL построен на его работе: поиск в каталоге, скачивание и локальная библиотека — его код, а его
заметки для переноса (`AGENTS.md`) сделали версию для Houdini возможной.

- Оригинальный плагин для Cinema 4D: https://github.com/denwerdan-arch/SimRCL
- Видео о том, как работает SimRCL: https://www.youtube.com/watch?v=xmf307dYwqM

> Состояние: **0.1.0 в разработке** — ноды разрабатываемой версии могут меняться от сборки к сборке, в рабочих
> сценах на них пока полагаться нельзя.

## Что делает

- Панель **SimReady Browser** (полка *HSimRCL → SimReady Browser* или меню вкладок любой панели): поиск с процентом
  совпадения, фильтры по категории, производителю, лицензии, профилю, массе, числу тел и размерам, превью с видео
  оборота 360° и движения частей, Download и **Add to Stage** (или двойной клик по плитке).
- LOP **SimReady Asset** (`hsimrcl::simready_asset::1.0`): поиск в каталоге, скачивание пакета, reference на его
  корневой USD в `/simready/<имя>`.
- Ассет остаётся reference'ом USD: физика, суставы, коллизии, семантика и материалы UsdPreviewSurface — как в
  файле, рендерятся в Karma.
- Добавляются только поворот Z-up → Y-up и масштаб под единицы сцены, отдельными xformOp'ами.
- Загрузки идут в ту же папку, что у SimRCL для Cinema 4D (`~/Documents/SRC by Deadwall/Assets`), пакеты общие.

## Установка

1. Скопировать или склонировать папку, например в `~/tools_houdini/HSimRCL`.
2. Положить `HSimRCL.json` в папку `packages` Houdini и указать в `HSIMRCL` этот путь.
3. Перезапустить Houdini. В `/stage` — Tab → **HSimRCL → SimReady Asset**.

Требования: Houdini 22 (Python 3.13), доступ в интернет к `nvidia-simready-central.hf.space` и `huggingface.co`.

## Лицензии

Код: Apache-2.0 (см. `LICENSE`), кроме файлов ядра SimRCL под MIT (см. `NOTICE`).
У каждого ассета своя лицензия, чаще всего CC BY 4.0 — указать автора и отметить свои изменения.

HSimRCL — независимый проект, не сделан и не одобрен NVIDIA или SideFX.
