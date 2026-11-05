# SPDX-FileCopyrightText: 2026 EOK
# SPDX-License-Identifier: Apache-2.0
"""Логика браузера без сети и без окна: QT_QPA_PLATFORM=offscreen hython tests/panel_logic.py

Ошибки устаревших задач, повторная загрузка превью, догрузка с диска после вытеснения, очистка Similar.
Сетевые задачи ядра подменены записью вызовов. Код выхода 1 при любой ошибке.
"""
import os
import sys
import time
import types

from PySide6 import QtGui, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
from hsimrcl.core import simready_media as media  # noqa: E402
from hsimrcl.core import simready_tasks as tasks  # noqa: E402
from hsimrcl.panel import browser  # noqa: E402

FAILS = []
CALLS = []


def check(label, got, want):
    ok = got == want
    print("%s %s: %r%s" % ("ok " if ok else "BAD", label, got, "" if ok else "  (want %r)" % (want,)))
    if not ok:
        FAILS.append(label)


def record(name):
    return lambda *args, **kw: CALLS.append((name, args))


for name in ("catalog_async", "previews_async", "images_async", "details_async", "similar_async", "search_async"):
    setattr(tasks, name, record(name))


def card(key):
    ref = {"repo": "org/repo", "commit": "0123456789ab", "package": key, "rel": key + ".usd"}
    return {"key": "hf://test/" + key, "filename": key + ".usd", "title": key, "media": {}, "detailed": True,
            "asset": {"path": "hf://test/" + key, "name": key + ".usd", "ref": ref}, "dims": None, "bytes": None,
            "joints": 0, "provider": "Test", "vlm": {}, "extras": {}}


def test_stale_errors(w):
    w.token, w.detail_token, w.loading = ("search", 5), ("detail", 3), True
    w.status("Searching…")
    w._on_error(("search", 4), "old failure")
    check("stale search error keeps loading", w.loading, True)
    check("stale search error keeps status", w.status_label.text(), "Searching…")
    w._on_error(("detail", 3), "details failed")
    check("detail error does not stop search", w.loading, True)
    w._on_error(("search", 5), "current failure")
    check("current search error stops loading", w.loading, False)


def test_image_retry(w):
    url = "https://example.invalid/tile_retry.jpg"
    CALLS.clear()
    w._images([url])
    check("first request", len(CALLS), 1)
    w._on_image(0, url, None)
    check("failed url not left in requested", url in w.requested, False)
    CALLS.clear()
    w._images([url])
    check("no retry inside the pause", len(CALLS), 0)
    w.failed[url] = time.time() - browser.RETRY_SECONDS - 1
    w._images([url])
    check("retry after the pause", len(CALLS), 1)


def test_reload_from_disk(w):
    url = "https://example.invalid/tile_disk.jpg"
    path = media.image_path(url, browser.PREVIEW_DIR)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image = QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32)
    image.fill(0x336699)
    image.save(path, "JPG")
    try:
        w.pixmaps.pop(url, None)          # как после вытеснения из памяти
        pixmap = w.tile_pixmap(url)
        check("evicted tile comes back from disk", pixmap is not None and not pixmap.isNull(), True)
    finally:
        os.remove(path)


def test_broken_preview(w):
    """Нечитаемый файл в кэше удаляется, и превью снова запрашивается (раньше вечно отдавался тот же файл)."""
    url = "https://example.invalid/tile_broken.jpg"
    path = media.image_path(url, browser.PREVIEW_DIR)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"not an image")
    w.pixmaps.pop(url, None)
    w.failed.pop(url, None)
    check("broken file gives no pixmap", w.tile_pixmap(url), None)
    check("broken file removed while drawing", os.path.exists(path), False)
    check("broken file asked again", url in w.wanted, True)
    with open(path, "wb") as handle:
        handle.write(b"still not an image")
    w._on_image(0, url, path)
    check("broken download removed", os.path.exists(path), False)
    check("broken download paused", url in w.failed, True)


def test_closed_card_error(w):
    """Новый поиск закрывает карточку: её поздняя ошибка не меняет статус поиска."""
    w.catalog = types.SimpleNamespace(stats={}, nodes={})
    w.open_card(card("closing"))
    old = w.detail_token
    w.new_search()
    w.status("Searching…")
    w._on_error(old, "late details failure")
    check("closed card error ignored", w.status_label.text(), "Searching…")


def test_similar_cleared(w):
    w.catalog = object()
    w.detail.show_card(card("first"))
    w.detail.set_similar([card("a"), card("b")])
    w.open_card(card("second"))
    check("similar cleared on another card", w.detail.similar_box.count(), 0)


if __name__ == "__main__":
    widget = browser.create()
    for fn in (test_stale_errors, test_image_retry, test_reload_from_disk, test_broken_preview,
               test_closed_card_error, test_similar_cleared):
        fn(widget)
    print("panel_logic: %s" % ("OK" if not FAILS else "FAILED " + ", ".join(FAILS)))
    sys.exit(1 if FAILS else 0)
