# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Дымовой тест браузера без окна: QT_QPA_PLATFORM=offscreen hython tests/panel_smoke.py <png> [запрос]

Создаёт BrowserWidget, ждёт каталог и первую выдачу, открывает первую карточку, сохраняет снимок виджета.
"""
import sys
import time

from PySide6 import QtCore, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from hsimrcl.core import simready_media as media  # noqa: E402
from hsimrcl.panel import browser  # noqa: E402


def pump(seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.03)
    return False


def decodable(url):
    pixmap = widget.pixmaps.get(url)
    return pixmap is not None and not pixmap.isNull()


widget = browser.create()
widget.resize(1500, 900)
widget.show()
pump(90, lambda: widget.catalog is not None and widget.loaded and not widget.loading)
print("catalog:", widget.catalog is not None, "cards:", len(widget.loaded), "status:", widget.status_label.text())
search_token = widget.token
if len(sys.argv) > 2:
    widget.search.setText(sys.argv[2])
    widget.new_search()
    search_token = widget.token
    pump(60, lambda: widget.loaded and not widget.loading)
    print("query cards:", len(widget.loaded), "status:", widget.status_label.text())
card = widget.model.cards[0] if widget.model.cards else None
if card is not None:
    widget.view.setCurrentIndex(widget.model.index(0))
    tile, poster = media.media_url(card, media.TILE), media.media_url(card, media.POSTER)
    # сведения — это ответ details_async (detailed=True), а не заголовок, который есть и до запроса
    pump(30, lambda: (widget.detail.card or {}).get("detailed") and decodable(tile) and decodable(poster))
    pump(4, lambda: widget.detail.similar_box.count() > 0)
opened = widget.detail.card or {}
print("detail:", widget.detail.title.text(), "detailed:", bool(opened.get("detailed")),
      "license:", opened.get("license"), "similar:", widget.detail.similar_box.count())
saved = widget.grab().save(sys.argv[1])
print("saved" if saved else "NOT saved", sys.argv[1])
checks = (
    ("catalog not loaded", widget.catalog is None),
    ("search not finished", widget.loading or widget.token != search_token),
    ("no results", card is None),
    ("details not received", not opened.get("detailed") or opened.get("key") != (card or {}).get("key")),
    ("tile of the first result not decodable", card is None or not decodable(tile)),
    ("poster of the opened asset not decodable", card is None or not decodable(poster)),
    ("snapshot not saved", not saved),
)
problems = [text for text, bad in checks if bad]
print("panel_smoke: %s" % ("OK" if not problems else "FAILED " + ", ".join(problems)))
sys.exit(1 if problems else 0)
