# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Главный виджет браузера: поиск, фильтры, сетка, карточка; события фоновых задач ядра разбирает таймер.

Фоновые задачи (simready_tasks) кладут кортежи (kind, token, ...) в очередь; таймер в главном потоке Qt
разбирает её — сцену Houdini и виджеты трогаем только здесь. token отсекает ответы устаревших запросов.
"""
import os
import queue
import re
import tempfile
import time
from collections import OrderedDict

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import simready_catalog as cat
from ..core import simready_client as client
from ..core import simready_library as library
from ..core import simready_media as media
from ..core import simready_settings as prefs
from ..core import simready_tasks as tasks
from ..net import ensure_tls
from .cards import CARD_ROLE, CardModel, TileDelegate
from .detail import DetailPanel, clear_layout
from .sidebar import Sidebar

CACHE_DIR = os.path.join(tempfile.gettempdir(), "simready_cache")          # каталог на сутки — как у SimRCL
PREVIEW_DIR = os.path.join(os.path.expanduser("~"), "Documents", prefs.APP_NAME, "Previews")  # общий с SimRCL
PREVIEW_LIMIT_BYTES = 200 * 1024 * 1024
PIXMAP_LIMIT = 400
SORT_ALL_LIMIT = 1000   # при сортировке не по релевантности догружаем все страницы, если их не больше
TIMER_MS = 80
SCROLL_MARGIN = 400     # px до конца сетки, когда просим следующую страницу
RETRY_SECONDS = 60      # превью, которое не скачалось, снова просим не раньше чем через минуту


class BrowserWidget(QtWidgets.QWidget):
    """Браузер SimReady Central."""

    def __init__(self, parent=None):
        super().__init__(parent)
        ensure_tls()
        self.events = queue.Queue()
        self.catalog = None
        # токены разного вида, чтобы ошибка одной задачи не меняла состояние другой (0 — загрузка каталога)
        self.token = ("search", 0)          # текущий поиск
        self.detail_token = ("detail", 0)   # текущая открытая карточка
        self.loaded, self.total, self.cursor, self.loading = [], 0, None, False
        self.pixmaps = OrderedDict()
        self.requested = set()      # url превью, которые скачиваются сейчас
        self.failed = {}            # url -> время неудачи: повтор не раньше RETRY_SECONDS
        self.wanted = set()         # url, которые отрисовка попросила догрузить
        self.cancelled = set()      # url, отменённые очисткой кэша: их пустой ответ — не неудача
        self.library = {}
        self.jobs = {}              # путь ассета -> {"add": bool}
        self.query, self.mode = "", "Hybrid"
        self._build()
        self.rescan_library()
        self.timer = QtCore.QTimer(self, interval=TIMER_MS, timeout=self.drain)
        self.timer.start()
        self.status("Loading catalog…")
        tasks.catalog_async(self.events, CACHE_DIR)
        tasks.previews_async(self.events, PREVIEW_DIR, PREVIEW_LIMIT_BYTES)

    # ------------------------------------------------------------ интерфейс

    def _build(self):
        self.search = QtWidgets.QLineEdit(placeholderText="Search SimReady Central (words or a description)")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.new_search)
        self.mode_box = QtWidgets.QComboBox()
        for index, mode in enumerate(client.TEXT_MODES):
            self.mode_box.addItem(mode)
            self.mode_box.setItemData(index, client.MODE_DESCRIPTIONS[mode], QtCore.Qt.ToolTipRole)
        self.mode_box.currentTextChanged.connect(lambda _: self.new_search())
        self.sort_box = QtWidgets.QComboBox()
        for key, label in cat.SORT_OPTIONS:
            self.sort_box.addItem(label, key)
        self.sort_box.currentIndexChanged.connect(lambda _: self.resort(fetch_all=True))
        self.desc = QtWidgets.QToolButton(text="↓", checkable=True, toolTip="Descending")
        self.desc.toggled.connect(lambda _: self.resort())
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, minimum=110, maximum=320, value=170)
        self.size_slider.setFixedWidth(110)
        self.size_slider.valueChanged.connect(self.set_tile)
        self.menu_button = QtWidgets.QToolButton(text="⋯", popupMode=QtWidgets.QToolButton.InstantPopup)
        self.menu_button.setMenu(self._menu())
        top = QtWidgets.QHBoxLayout()
        for widget in (self.search, self.mode_box, QtWidgets.QLabel("Sort"), self.sort_box, self.desc,
                       self.size_slider, self.menu_button):
            top.addWidget(widget)
        top.setStretch(0, 1)
        self.chips = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel()
        self.status_label.setStyleSheet("color:#aaa")
        info = QtWidgets.QHBoxLayout()
        info.addWidget(self.status_label)
        info.addLayout(self.chips)
        info.addStretch(1)

        self.sidebar = Sidebar()
        self.sidebar.changed.connect(self.new_search)
        self.model = CardModel(self)
        self.delegate = TileDelegate(self)
        self.view = QtWidgets.QListView()
        self.view.setViewMode(QtWidgets.QListView.IconMode)
        self.view.setResizeMode(QtWidgets.QListView.Adjust)
        self.view.setMovement(QtWidgets.QListView.Static)
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.view.setModel(self.model)
        self.view.setItemDelegate(self.delegate)
        self.view.selectionModel().currentChanged.connect(lambda current, _: self.open_card(current.data(CARD_ROLE)))
        self.view.doubleClicked.connect(lambda index: self.add_to_stage(index.data(CARD_ROLE)))
        self.view.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.set_tile(self.size_slider.value())
        self.detail = DetailPanel()
        self.detail.download.connect(lambda: self.download(self.detail.card, add=False))
        self.detail.add.connect(lambda: self.add_to_stage(self.detail.card))
        self.detail.reveal.connect(self.reveal)
        self.detail.clip.connect(self.play_clip)
        self.detail.similar.connect(self.open_card)

        split = QtWidgets.QSplitter()
        split.addWidget(self.sidebar)
        split.addWidget(self.view)
        split.addWidget(self.detail)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 700, 320])
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addLayout(info)
        layout.addWidget(split, 1)

    def _menu(self):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Download Folder…", self.choose_folder)
        menu.addAction("Open Download Folder", lambda: self._open(self.folder()))
        menu.addAction("Clear Preview Cache", self.clear_previews)
        menu.addSeparator()
        guide = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "data", "licensing.html")
        menu.addAction("Licensing Guide", lambda: self._open(guide))
        menu.addAction("SimRCL by Dead_wall (original for Cinema 4D)",
                       lambda: self._open_url("https://github.com/denwerdan-arch/SimRCL"))
        return menu

    def set_tile(self, size):
        self.delegate.tile = size
        self.view.setGridSize(QtCore.QSize(size + 6, size + 46))
        self.model.layoutChanged.emit()

    def status(self, text):
        self.status_label.setText(text)

    def folder(self):
        return prefs.download_dir(prefs.load())

    # ------------------------------------------------------------ поиск

    def new_search(self):
        """Новый запрос: с первой страницы, со сбросом выдачи."""
        if self.catalog is None:
            return
        self.query, self.mode = self.search.text().strip(), self.mode_box.currentText()
        self.token = ("search", self.token[1] + 1)
        # карточка закрывается: её поздние ответы и ошибки больше не актуальны
        self.detail_token = ("detail", self.detail_token[1] + 1)
        self.loaded, self.total, self.cursor = [], 0, None
        self.model.set_cards([])
        self.detail.show_card(None)
        self._chips()
        self._request(None)

    def _request(self, cursor):
        self.loading = True
        self.status("Searching…" if cursor is None else "Loading more…")
        selection = self.sidebar.selection
        if self.sidebar.only_downloaded:
            tasks.downloaded_async(self.events, self.token, self.catalog, self.query, self.mode, selection, self.library)
        else:
            tasks.search_async(self.events, self.token, self.catalog, self.query, self.mode, selection, cursor)

    def _scrolled(self, value):
        bar = self.view.verticalScrollBar()
        if self.cursor and not self.loading and value > bar.maximum() - SCROLL_MARGIN:
            self._request(self.cursor)

    def _custom_sort(self):
        return self.sort_box.currentData() not in ("relevance", "match")

    def resort(self, fetch_all=False):
        """Пересортировать загруженное; для сортировки по полю догрузить остальные страницы (если их немного)."""
        current = self.detail.card
        cards = cat.sort_cards(self.loaded, self.sort_box.currentData(), self.desc.isChecked())
        self.model.set_cards(cards)
        if current is not None:
            row = next((i for i, c in enumerate(cards) if c["key"] == current["key"]), None)
            if row is not None:
                self.view.selectionModel().blockSignals(True)
                self.view.setCurrentIndex(self.model.index(row))
                self.view.selectionModel().blockSignals(False)
        if fetch_all and self._custom_sort() and self.cursor and self.total <= SORT_ALL_LIMIT and not self.loading:
            self._request(self.cursor)

    def _chips(self):
        """Активные фильтры кнопками «× фильтр»: клик снимает его."""
        clear_layout(self.chips)
        chips = []
        if self.sidebar.only_downloaded:
            chips.append(("Downloaded", "downloaded", None))
        if self.catalog is not None:
            chips += cat.selection_chips(self.sidebar.selection, self.catalog)
        for label, field, key in chips:
            button = QtWidgets.QPushButton("× " + label)
            button.setFlat(True)
            button.clicked.connect(lambda checked=False, f=field, k=key: self.sidebar.remove(f, k))
            self.chips.addWidget(button)
        if len(chips) > 1:
            clear = QtWidgets.QPushButton("Clear all")
            clear.setFlat(True)
            clear.clicked.connect(self.sidebar.clear)
            self.chips.addWidget(clear)

    # ------------------------------------------------------------ карточка

    def open_card(self, card):
        if card is None:
            return
        self.detail_token = ("detail", self.detail_token[1] + 1)
        self.detail.show_card(card, library.state(card, self.library))
        pixmap = self.tile_pixmap(media.media_url(card, media.POSTER))
        if pixmap is not None:
            self.detail.set_poster(pixmap)
        if not card.get("detailed"):
            tasks.details_async(self.events, self.detail_token, card, self.catalog)
        tasks.similar_async(self.events, self.detail_token, card, self.catalog)

    def play_clip(self, kind):
        card = self.detail.card
        url = media.video_url(card, kind) if card else None
        if url:
            path = media.image_path(url, PREVIEW_DIR)
            if os.path.isfile(path):
                self.detail.play(path)
            else:
                self.status("Loading clip…")
                tasks.video_async(self.events, url, PREVIEW_DIR)

    def _images(self, urls):
        """Скачать превью, которых нет на диске и которые не качаются сейчас (недавно неудачные — позже)."""
        now = time.time()
        fresh = [u for u in dict.fromkeys(urls) if u not in self.requested and now - self.failed.get(u, 0) > RETRY_SECONDS]
        self.requested.update(fresh)
        if fresh:
            tasks.images_async(self.events, fresh, PREVIEW_DIR)

    def _store(self, url, pixmap):
        self.pixmaps[url] = pixmap
        self.pixmaps.move_to_end(url)
        while len(self.pixmaps) > PIXMAP_LIMIT:
            self.pixmaps.popitem(last=False)

    def tile_pixmap(self, url):
        """Превью для отрисовки: из памяти, иначе из дискового кэша, иначе просим скачать (вне paint)."""
        pixmap = self.pixmaps.get(url)
        if pixmap is not None:
            self.pixmaps.move_to_end(url)
            return pixmap
        path = media.image_path(url, PREVIEW_DIR)
        if os.path.isfile(path):
            pixmap = QtGui.QPixmap(path)
            if not pixmap.isNull():
                self._store(url, pixmap)
                return pixmap
            _drop_broken(path)  # битый файл: fetch_image отдавал бы его снова и снова
        if url not in self.requested and url not in self.wanted:
            if not self.wanted:  # один отложенный вызов на пачку плиток одной перерисовки
                QtCore.QTimer.singleShot(0, self._request_wanted)
            self.wanted.add(url)
        return None

    def _request_wanted(self):
        urls, self.wanted = list(self.wanted), set()
        self._images(urls)

    # ------------------------------------------------------------ скачивание и сцена

    def rescan_library(self):
        self.library = library.index(library.scan(self.folder()))

    def download(self, card, add=False, force=None):
        """Скачать пакет в фоне; add=True — после скачивания добавить ноду в сцену."""
        if card is None:
            return
        path = card["asset"]["path"]
        if path in self.jobs:
            self.jobs[path]["add"] |= add
            return
        state = library.state(card, self.library)
        force = (state == library.CURRENT and not add) if force is None else force
        if state == library.CURRENT and add and not force:
            self._add_node(card, client.cached_root_usd(card["asset"], self.folder()))
            return
        self.jobs[path] = {"add": add, "card": card}
        self.status("Downloading %s…" % card["filename"])
        tasks.install_async(self.events, path, card["asset"], self.folder(), None, force=force, then_import=False)

    def add_to_stage(self, card):
        self.download(card, add=True)

    def _add_node(self, card, usd_path):
        """Нода SimReady Asset в текущей LOP-сети (или в /stage). Ноду не двигаем — раскладку делает пользователь."""
        import hou
        import hsimrcl
        from .. import lop
        network = _target_network(hou)
        name = re.sub(r"[^A-Za-z0-9_]", "_", card["filename"].rsplit(".", 1)[0])
        node = network.createNode(hsimrcl.ASSET_TYPE, name)
        lop._choose(node, card, self.folder())
        node.parm("file").set(usd_path)
        if card.get("license"):
            node.parm("license").set(card["license"])
        node.setCurrent(True, clear_all_selected=True)
        # нода намеренно не подключается и display не переносится: раскладку и цепочку собирает пользователь
        self.status("Added %s — not connected: wire it into your LOP chain to see it" % node.path())

    def reveal(self):
        card = self.detail.card
        if card is not None and client.is_cached(card["asset"], self.folder()):
            self._open(os.path.dirname(client.cached_root_usd(card["asset"], self.folder())))

    def choose_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Download folder", self.folder())
        if not folder:
            return
        problem = prefs.check_folder(folder)
        if problem:
            QtWidgets.QMessageBox.warning(self, "HSimRCL", problem)
            return
        prefs.save(prefs.with_download_dir(prefs.load(), folder))
        self.rescan_library()
        self.model.refresh()

    def clear_previews(self):
        tasks.cancel_pending_images()
        self.cancelled |= self.requested
        self.pixmaps.clear()
        self.requested.clear()
        self.failed.clear()
        self.wanted.clear()
        tasks.previews_async(self.events, PREVIEW_DIR, PREVIEW_LIMIT_BYTES, clear=True)

    def _open(self, path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def _open_url(self, url):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(url))

    # ------------------------------------------------------------ события фоновых задач

    def drain(self):
        """Разобрать очередь событий (главный поток Qt)."""
        for _ in range(200):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            handler = getattr(self, "_on_" + event[0], None)
            if handler is not None:
                handler(*event[1:])

    def _on_catalog(self, _token, catalog):
        self.catalog = catalog
        self.sidebar.set_catalog(catalog)
        self.new_search()

    def _on_page(self, token, cards, total, next_cursor, appended):
        if token != self.token:
            return
        self.loading = False
        seen = {c["key"] for c in self.loaded} if appended else set()
        fresh = [c for c in cards if c["key"] not in seen]
        self.loaded = (self.loaded if appended else []) + fresh
        self.total, self.cursor = total, next_cursor
        self.resort(fetch_all=True)
        self._images([media.media_url(c, media.TILE) for c in fresh])
        if self.query and self.mode != "Keyword" and fresh:
            tasks.match_async(self.events, self.token, self.query, [c["key"] for c in fresh])
        self.status("%s results%s" % (cat.format_count(total), "" if not self.cursor else " · %d loaded" % len(self.loaded)))

    def _on_image(self, _token, url, path):
        self.requested.discard(url)
        pixmap = QtGui.QPixmap(path) if path else None
        if pixmap is None or pixmap.isNull():
            if path:
                _drop_broken(path)  # скачался нечитаемый файл — убрать, чтобы следующий повтор скачал заново
            if url in self.cancelled:
                self.cancelled.discard(url)
            else:
                self.failed[url] = time.time()
            return
        self.failed.pop(url, None)
        self._store(url, pixmap)
        card = self.detail.card
        if card is not None and url == media.media_url(card, media.POSTER):
            self.detail.set_poster(pixmap)
        self.model.refresh(self.model.rows_with_tile(url))

    def _on_match(self, token, query, scores):
        if token != self.token or query != self.query:
            return
        for card in self.loaded:
            if card["key"] in scores:
                card["match"] = scores[card["key"]]
        if self.sort_box.currentData() == "match":
            self.resort()
        else:
            self.model.refresh()

    def _on_details(self, token, full):
        current = self.detail.card
        if token != self.detail_token or current is None or full["key"] != current["key"]:
            return
        full["match"] = current.get("match")
        for i, card in enumerate(self.loaded):
            if card["key"] == full["key"]:
                self.loaded[i] = full
        self.model.cards = [full if c["key"] == full["key"] else c for c in self.model.cards]
        self.detail.set_facts(full)

    def _on_similar(self, token, key, cards):
        current = self.detail.card
        if token == self.detail_token and current is not None and current["key"] == key:
            self.detail.set_similar(cards)

    def _on_video(self, _token, url, path):
        card = self.detail.card
        if card is None or not path:
            return
        if url in (media.video_url(card, media.SPIN), media.video_url(card, media.JOINTS)):
            self.status("")
            self.detail.play(path)

    def _on_progress(self, asset_path, done, total):
        card = self.detail.card
        if card is not None and card["asset"]["path"] == asset_path:
            self.detail.set_progress(done, total)

    def _on_refreshed(self, asset_path, _same_path, usd_path):
        job = self.jobs.pop(asset_path, {})
        self.rescan_library()
        self.model.refresh()
        card = self.detail.card
        if card is not None and card["asset"]["path"] == asset_path:
            self.detail.set_progress(0, 0)
            self.detail.set_state(library.state(card, self.library))
        self.status("Downloaded %s" % os.path.basename(usd_path))
        if job.get("add"):
            self._add_node(job["card"], usd_path)

    def _on_error(self, token, text):
        """Ошибка фоновой задачи. Устаревшие (прошлый поиск, прошлая карточка) не трогают текущее состояние."""
        if isinstance(token, str):                      # скачивание: token — путь ассета
            self.jobs.pop(token, None)
            card = self.detail.card
            if card is not None and card["asset"]["path"] == token:
                self.detail.set_progress(0, 0)
            self.status("Download failed: " + text[:200])
        elif token == self.token:                       # текущий поиск
            self.loading = False
            self.status("Search failed: " + text[:200])
        elif token == self.detail_token:                # сведения о текущей карточке
            self.status("Could not load details: " + text[:200])
        elif token == 0 and self.catalog is None:       # каталог
            self.status("Could not load the catalog: " + text[:200])

    def _on_previews(self, _token, cleared, bytes_left):
        if cleared:
            self.status("Preview cache cleared")


def _drop_broken(path):
    """Удалить нечитаемое превью из кэша (только файл кэша превью, который мы сами и скачали)."""
    try:
        os.remove(path)
    except OSError:
        pass


def _target_network(hou):
    """LOP-сеть открытого Network Editor; иначе /stage."""
    for pane in hou.ui.paneTabs():
        if pane.type() == hou.paneTabType.NetworkEditor and pane.isCurrentTab():
            network = pane.pwd()
            if network.childTypeCategory() == hou.lopNodeTypeCategory():
                return network
    return hou.node("/stage")


def create():
    """Точка входа Python Panel (onCreateInterface)."""
    return BrowserWidget()
