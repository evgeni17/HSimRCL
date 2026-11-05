# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Карточка ассета справа: постер или видео (оборот 360° / движение суставов), сведения и кнопки."""
import html

from PySide6 import QtCore, QtGui, QtWidgets

from ..core import simready_catalog as cat
from ..core import simready_library as library
from ..core import simready_media as media

POSTER_H = 280


def _row(name, value):
    text = html.escape(str(value))
    if name == "File":  # \u200b после «_» — места переноса для длинных имён файлов
        text = text.replace("_", "_\u200b")
    return "<tr><td style='color:#999;padding-right:8px'>%s</td><td>%s</td></tr>" % (name, text)


def facts_html(card):
    """Таблица сведений карточки; пустые поля не показываем."""
    extras = card.get("extras") or {}
    rows = [("Provider", card.get("provider")), ("Category", card.get("category")), ("License", card.get("license")),
            ("Size", cat.format_dimensions(card.get("dims"))), ("Mass", cat.format_mass(card.get("mass"))),
            ("Package", cat.format_bytes(card.get("bytes"))), ("Moving parts", card.get("joints") or ""),
            ("Bodies", extras.get("bodies")), ("Polygons", cat.format_count(extras["polygons"]) if extras.get("polygons") else ""),
            ("Author", extras.get("author")), ("Robot", extras.get("robot")),
            ("Physics", ", ".join(extras.get("engines") or [])), ("Profile", card.get("profile")),
            ("File", card.get("filename"))]
    body = "".join(_row(name, value) for name, value in rows if value)
    caption = ((card.get("vlm") or {}).get("caption") or [""])[0]
    tail = "<p style='color:#bbb'>%s</p>" % html.escape(caption) if caption else ""
    return "<table>%s</table>%s" % (body, tail)


def clear_layout(layout):
    """Убрать виджеты из раскладки. Сначала отцепляем от родителя: deleteLater срабатывает только при возврате
    в цикл событий того же уровня, и до этого старые кнопки остаются видимыми поверх новых."""
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class DetailPanel(QtWidgets.QWidget):
    """Сведения об открытом ассете. Сигналы: download, add (кнопки), similar(card), clip(kind)."""

    download = QtCore.Signal()
    add = QtCore.Signal()
    reveal = QtCore.Signal()
    clip = QtCore.Signal(str)
    similar = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.card = None
        self.setMinimumWidth(300)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.setFixedHeight(POSTER_H)
        self.poster = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        self.poster.setStyleSheet("background:#2b2b2b")
        self.video = self._video_widget()
        self.stack.addWidget(self.poster)
        if self.video is not None:
            self.stack.addWidget(self.video)
        self.spin = QtWidgets.QPushButton("360°", checkable=True)
        self.moving = QtWidgets.QPushButton("Moving parts", checkable=True)
        for button, kind in ((self.spin, media.SPIN), (self.moving, media.JOINTS)):
            button.clicked.connect(lambda checked, k=kind: self._clip_clicked(k, checked))
        self.title = QtWidgets.QLabel(wordWrap=True)
        self.title.setStyleSheet("font-size: 14px; font-weight: bold")
        self.facts = QtWidgets.QLabel(wordWrap=True, textFormat=QtCore.Qt.RichText)
        self.facts.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.download_button = QtWidgets.QPushButton("Download")
        self.add_button = QtWidgets.QPushButton("Add to Stage")
        self.add_button.setToolTip("Download if needed and add a SimReady Asset node to the LOP network open in the "
                                   "Network Editor (else /stage). The node is not connected and the display flag "
                                   "is not moved: wire it into your chain.")
        self.reveal_button = QtWidgets.QPushButton("Reveal")
        self.download_button.clicked.connect(self.download)
        self.add_button.clicked.connect(self.add)
        self.reveal_button.clicked.connect(self.reveal)
        self.progress = QtWidgets.QProgressBar(visible=False, textVisible=True)
        self.similar_box = QtWidgets.QVBoxLayout()
        self._layout()
        self.show_card(None)

    def _video_widget(self):
        """Кадры QMediaPlayer -> QVideoSink -> QLabel. QVideoWidget рисует в нативную поверхность, которую
        внутри Houdini не видно ни на снимке панели, ни надёжно на экране; картинка в QLabel — обычный виджет.
        Без QtMultimedia остаётся только постер."""
        try:
            from PySide6 import QtMultimedia
        except ImportError:
            return None
        widget = QtWidgets.QLabel(alignment=QtCore.Qt.AlignCenter)
        widget.setStyleSheet("background:#2b2b2b")
        self.player = QtMultimedia.QMediaPlayer(self)
        self.sink = QtMultimedia.QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._frame)
        self.player.setVideoSink(self.sink)
        self.player.setLoops(QtMultimedia.QMediaPlayer.Infinite)
        return widget

    def _frame(self, frame):
        image = frame.toImage()
        if image.isNull() or self.video is None:
            return
        self.video.setPixmap(QtGui.QPixmap.fromImage(image).scaled(
            self.stack.width(), POSTER_H, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _layout(self):
        clips = QtWidgets.QHBoxLayout()
        clips.addWidget(self.spin)
        clips.addWidget(self.moving)
        clips.addStretch(1)
        buttons = QtWidgets.QHBoxLayout()
        for button in (self.add_button, self.download_button, self.reveal_button):
            buttons.addWidget(button)
        inner = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(inner)
        column.addWidget(self.title)
        column.addLayout(buttons)
        column.addWidget(self.progress)
        column.addWidget(self.facts)
        column.addWidget(QtWidgets.QLabel("<b>Similar</b>"))
        column.addLayout(self.similar_box)
        column.addStretch(1)
        scroll = QtWidgets.QScrollArea(widgetResizable=True)
        scroll.setWidget(inner)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)  # длинные имена файлов переносятся, а не скроллятся
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.stack)
        layout.addLayout(clips)
        layout.addWidget(scroll, 1)

    # ------------------------------------------------------------ показ

    def show_card(self, card, state=None):
        """Открыть карточку (None — пусто). state — состояние локальной копии (library.CURRENT / OUTDATED / None)."""
        self.stop_video()
        self.card = card
        enabled = card is not None
        for widget in (self.download_button, self.add_button, self.spin, self.moving):
            widget.setEnabled(enabled)
        self.spin.setChecked(False)
        self.moving.setChecked(False)
        self.poster.setPixmap(QtGui.QPixmap())
        self.poster.setText("" if enabled else "Pick an asset")
        if not enabled:
            self.title.setText("")
            self.facts.setText("")
            self.set_similar([])
            self.reveal_button.setEnabled(False)
            return
        self.title.setText(card["title"] or card["filename"])
        self.facts.setText(facts_html(card))
        self.set_similar([])  # похожие прошлой карточки не должны оставаться, пока не пришли новые
        self.set_state(state)
        clips = card.get("media") or {}
        self.spin.setVisible(self.video is not None and bool(clips.get(media.SPIN)))
        self.moving.setVisible(self.video is not None and bool(clips.get(media.JOINTS)))

    def set_state(self, state):
        self.download_button.setText({library.CURRENT: "Download Again", library.OUTDATED: "Update"}.get(state, "Download"))
        self.reveal_button.setEnabled(state is not None)

    def set_facts(self, card):
        """Пришли полные сведения (лицензия, масса, автор…) — обновить таблицу, не трогая видео."""
        self.card = card
        self.facts.setText(facts_html(card))

    def set_poster(self, pixmap):
        if pixmap is None or pixmap.isNull():
            return
        self.poster.setPixmap(pixmap.scaled(self.stack.width(), POSTER_H, QtCore.Qt.KeepAspectRatio,
                                            QtCore.Qt.SmoothTransformation))

    def set_similar(self, cards):
        clear_layout(self.similar_box)
        for card in cards:
            button = QtWidgets.QPushButton(card["title"] or card["filename"])
            button.setStyleSheet("text-align:left")
            button.clicked.connect(lambda checked=False, c=card: self.similar.emit(c))
            self.similar_box.addWidget(button)

    # ------------------------------------------------------------ видео

    def _clip_clicked(self, kind, checked):
        other = self.moving if kind == media.SPIN else self.spin
        other.setChecked(False)
        if not checked:
            self.stop_video()
            return
        self.clip.emit(kind)

    def play(self, path):
        if self.video is None or not path:
            return
        self.stack.setCurrentWidget(self.video)
        self.player.setSource(QtCore.QUrl.fromLocalFile(path))
        self.player.play()

    def stop_video(self):
        if self.video is not None:
            self.player.stop()
            self.player.setSource(QtCore.QUrl())
            self.video.clear()
        self.stack.setCurrentWidget(self.poster)

    def set_progress(self, done, total):
        self.progress.setVisible(total > 0 and done < total)
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.progress.setFormat("%d / %d files" % (done, total))
