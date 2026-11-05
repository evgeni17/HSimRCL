# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Сетка карточек: модель списка и делегат, рисующий превью, название, размеры и значки."""
from PySide6 import QtCore, QtGui, QtWidgets

from ..core import simready_catalog as cat
from ..core import simready_library as library
from ..core import simready_media as media

CARD_ROLE = QtCore.Qt.UserRole + 1
TEXT_H = 40      # подпись под превью: две строки
PAD = 4


class CardModel(QtCore.QAbstractListModel):
    """Карточки текущей выдачи; превью и признак «скачано» берёт у контроллера (их обновляют события)."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner          # BrowserWidget: pixmaps, library
        self.cards = []

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.cards)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        card = self.cards[index.row()]
        if role == CARD_ROLE:
            return card
        if role == QtCore.Qt.DisplayRole:
            return card["title"] or card["filename"]
        if role == QtCore.Qt.ToolTipRole:
            return "%s\n%s\n%s" % (card["title"] or "", card["filename"], card["provider"])
        return None

    def set_cards(self, cards):
        self.beginResetModel()
        self.cards = list(cards)
        self.endResetModel()

    def refresh(self, rows=None):
        """Перерисовать строки (или все), когда пришло превью, процент совпадения или скачался пакет."""
        if not self.cards:
            return
        rows = range(len(self.cards)) if rows is None else rows
        for row in rows:
            index = self.index(row)
            self.dataChanged.emit(index, index, [CARD_ROLE])

    def rows_with_tile(self, url):
        return [i for i, card in enumerate(self.cards) if media.media_url(card, media.TILE) == url]


def _badge(painter, rect, text, color):
    """Скруглённая плашка с текстом в углу превью."""
    metrics = painter.fontMetrics()
    width = metrics.horizontalAdvance(text) + 10
    box = QtCore.QRect(rect.left(), rect.top(), width, metrics.height() + 4)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(box, 4, 4)
    painter.setPen(QtGui.QColor(255, 255, 255))
    painter.drawText(box, QtCore.Qt.AlignCenter, text)
    return box


class TileDelegate(QtWidgets.QStyledItemDelegate):
    """Плитка: превью (вписано в квадрат), значки суставов/совпадения/скачано, две строки текста."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.tile = 170

    def sizeHint(self, option, index):
        return QtCore.QSize(self.tile, self.tile + TEXT_H)

    def paint(self, painter, option, index):
        card = index.data(CARD_ROLE)
        if card is None:
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = option.rect.adjusted(PAD, PAD, -PAD, -PAD)
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover = bool(option.state & QtWidgets.QStyle.State_MouseOver)
        base = QtGui.QColor(58, 58, 58) if not hover else QtGui.QColor(70, 70, 70)
        painter.setPen(QtGui.QPen(option.palette.highlight().color(), 2) if selected else QtCore.Qt.NoPen)
        painter.setBrush(base)
        painter.drawRoundedRect(rect, 6, 6)
        image = QtCore.QRect(rect.left() + PAD, rect.top() + PAD, rect.width() - 2 * PAD, rect.width() - 2 * PAD)
        self._image(painter, image, card)
        self._badges(painter, image, card)
        self._text(painter, QtCore.QRect(rect.left() + 6, image.bottom() + 3, rect.width() - 12, TEXT_H - 6), card)
        painter.restore()

    def _image(self, painter, image, card):
        pixmap = self.owner.pixmaps.get(media.media_url(card, media.TILE))
        if pixmap is None or pixmap.isNull():
            painter.fillRect(image, QtGui.QColor(45, 45, 45))
            return
        scaled = pixmap.scaled(image.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        x = image.left() + (image.width() - scaled.width()) // 2
        y = image.top() + (image.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    def _badges(self, painter, image, card):
        font = painter.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        painter.setFont(font)
        corner = image.adjusted(4, 4, -4, -4)
        if card.get("joints"):
            _badge(painter, corner, "%d joint%s" % (card["joints"], "" if card["joints"] == 1 else "s"),
                   QtGui.QColor(40, 90, 160, 220))
        if card.get("match") is not None:
            text = "%d%%" % card["match"]
            width = painter.fontMetrics().horizontalAdvance(text) + 10
            _badge(painter, QtCore.QRect(corner.right() - width, corner.top(), width, 20), text,
                   QtGui.QColor(30, 130, 90, 220))
        state = library.state(card, self.owner.library)
        if state:
            text = "on disk" if state == library.CURRENT else "update"
            color = QtGui.QColor(60, 140, 60, 230) if state == library.CURRENT else QtGui.QColor(190, 120, 30, 230)
            height = painter.fontMetrics().height() + 4
            _badge(painter, QtCore.QRect(corner.left(), corner.bottom() - height, 0, 0), text, color)

    def _text(self, painter, rect, card):
        metrics = painter.fontMetrics()
        title = card["title"] or card["filename"].rsplit(".", 1)[0]
        painter.setPen(QtGui.QColor(225, 225, 225))
        bold = QtGui.QFont(painter.font())
        bold.setBold(True)
        painter.setFont(bold)
        painter.drawText(rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                         QtGui.QFontMetrics(bold).elidedText(title, QtCore.Qt.ElideRight, rect.width()))
        painter.setFont(QtGui.QFont(painter.font().family(), painter.font().pointSize()))
        painter.setPen(QtGui.QColor(160, 160, 160))
        second = " · ".join(p for p in (cat.format_dimensions(card["dims"]), cat.format_bytes(card["bytes"], 1)) if p)
        painter.drawText(rect.adjusted(0, metrics.height() + 2, 0, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
                         metrics.elidedText(second, QtCore.Qt.ElideRight, rect.width()))
