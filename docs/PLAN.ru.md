# HSimRCL — план работ

## Зачем

Ассеты NVIDIA SimReady Central (OpenUSD, >2000 шт., физика, суставы, семантика) нужны прямо в Houdini.
Есть готовый браузер для Cinema 4D — SimRCL (Dead_wall, MIT) — с переносимым ядром и описанием порта
(`AGENTS.md` в его репозитории). Переносим ядро, Houdini-часть пишем заново.

## Принятые решения

- **Имя**: HSimRCL; пакет `hsimrcl`, ассеты `hsimrcl::*::N.0`.
- **Свой репозиторий** (`evgeni17/HSimRCL`, Apache-2.0), а не форк SimRCL: раскладка по правилам плагинов;
  файлы ядра SimRCL — под MIT с уведомлением (`NOTICE`, `third_party/SimRCL-LICENSE.txt`).
- **Ядро почти без правок**: только относительные импорты (иначе замороженные копии делили бы модули в
  `sys.modules`) и пути настроек на macOS. Так обновления SimRCL переносятся diff'ом; коммит —
  `SIMRCL_UPSTREAM`.
- **Контекст — Solaris (LOP)**, рендер — Karma. Ассет подключается reference'ом: физика, суставы, семантика,
  UsdPreviewSurface и `UsdTransform2d` сохраняются, отдельный бэкенд материалов не нужен.
- **Нода — Python LOP внутри HDA**, HDA собирается из кода (`hda_build.py`).
- **Папка загрузок общая с SimRCL** (`~/Documents/SRC by Deadwall/Assets`).
- **Без vendor**: USD берём из Houdini (`pxr`), сеть — `urllib`.

## Отвергнутые варианты

- Отдельный процесс с `usd-core` для разбора USD (как в C4D) — в Houdini есть `pxr`, разбираем в процессе.
- Перенос шагов SimRCL «починка xformOps», «материалы на instanceable», «UV-тайлинг» — это обходы импортёра C4D;
  в Solaris не нужны (проверить на тестовых ассетах, этап 1).
- Импорт в SOP/OBJ на первом этапе — пользователь выбрал Solaris; SOP — позже, если понадобится.

## Этапы

### 0.1.0
1. [x] Каркас репозитория, перенос ядра, `deploy.py`.
2. [ ] LOP `simready_asset`: Search / Download / reference, Z-up→Y-up, единицы. Проверка в Houdini на ассетах
   из чек-листа SimRCL: офисное кресло `sm_chair_office_fabric_manager_a01` (суставы, UV-тайлинг), стол,
   робот (Comau / Robotiq), дверь; рендер Karma.
3. [ ] Коллизии: скрыть в вьюпорте/рендере (purpose guide или отключение), если они видны.
4. [ ] Тесты: `test_core.py`, `test_repo.py`, `houdini_regression.py`; `freeze.py` (по образцу HIFC) до выпуска.
5. [ ] Выпуск 0.1.0 (заморозка `::1.0`, тег, релиз).

### Дальше
- Qt-панель браузера (Python Panel): сетка карточек, превью, фильтры (ядро `simready_tasks` уже есть).
- Управление суставами: параметры на HDA с лимитами из `UsdPhysics` (revolute — градусы, prismatic — длина).
- `simready_update` сейчас смотрит релизы SimRCL — переключить на `evgeni17/HSimRCL` или выключить.
- Импорт в SOP при необходимости.
