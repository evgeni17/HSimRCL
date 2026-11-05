# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Дымовой тест браузера без окна: QT_QPA_PLATFORM=offscreen hython tests/panel_smoke.py <png> [запрос]

Создаёт BrowserWidget, ждёт каталог и первую выдачу, открывает первую карточку, сохраняет снимок виджета.
"""
import sys
import time

from PySide6 import QtCore, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from hsimrcl.panel import browser  # noqa: E402


def pump(seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.03)
    return False


widget = browser.create()
widget.resize(1500, 900)
widget.show()
pump(90, lambda: widget.catalog is not None and widget.loaded)
print("catalog:", widget.catalog is not None, "cards:", len(widget.loaded), "status:", widget.status_label.text())
if len(sys.argv) > 2:
    widget.search.setText(sys.argv[2])
    widget.new_search()
    pump(60, lambda: widget.loaded and not widget.loading)
    print("query cards:", len(widget.loaded), "status:", widget.status_label.text())
if widget.loaded:
    widget.view.setCurrentIndex(widget.model.index(0))
pump(15, lambda: len(widget.pixmaps) >= min(12, len(widget.loaded)))
pump(6)
print("pixmaps:", len(widget.pixmaps), "detail:", widget.detail.title.text())
print("similar:", widget.detail.similar_box.count(), "facts len:", len(widget.detail.facts.text()))
widget.grab().save(sys.argv[1])
print("saved", sys.argv[1])
problems = [text for text, bad in (("catalog not loaded", widget.catalog is None), ("no results", not widget.loaded),
                                    ("no previews", not widget.pixmaps), ("no details", not widget.detail.title.text()))
            if bad]
print("panel_smoke: %s" % ("OK" if not problems else "FAILED " + ", ".join(problems)))
sys.exit(1 if problems else 0)
