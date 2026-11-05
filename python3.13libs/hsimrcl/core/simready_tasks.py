# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_tasks.py @ 1150d3e
"""Background tasks for the SimReady browser.

Every task runs in a daemon thread and reports through a queue as (kind, token, payload...) tuples.
The module touches no Cinema 4D API, so the dialog can drain the queue on the main thread, where
scene access is allowed.
"""
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from . import simready_catalog
from . import simready_client
from . import simready_library
from . import simready_media
from . import simready_update

NETWORK_ERRORS = (OSError, ValueError, KeyError)
IMAGE_WORKERS = 6
SORT_PAGE_LIMIT = 400  # largest page the service answers quickly without usd_properties
_image_epoch = [0]  # bumped to make queued downloads give up (a list so no global statement is needed)


def _spawn(target, *args):
    """Start target(*args) in a daemon thread so a closed dialog never waits for the network."""
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()
    return thread


def _guarded(events, token, work):
    """Run work(); turn network failures into an 'error' event instead of a silent dead thread."""
    try:
        work()
    except NETWORK_ERRORS as error:
        events.put(("error", token, "%s: %s" % (type(error).__name__, error)))


def catalog_async(events, cache_dir):
    """Load hierarchy, counts, sizes and media indexes, then publish a 'catalog' event."""
    def work():
        events.put(("catalog", 0, simready_catalog.load_catalog(cache_dir)))
    _spawn(_guarded, events, 0, work)


def _cards(hits, catalog):
    """Cards of the hits that are asset entry points."""
    return [c for c in (simready_catalog.card_from_hit(hit, catalog) for hit in hits) if c]


def _featured_cards(catalog):
    """Cards of the leading featured assets in their curated order; they open the default landing page."""
    pattern, count = simready_catalog.featured_filter(catalog.featured)
    hits, _, _ = simready_client.search_page("", "Hybrid", {"filter_url_regexp": pattern}, None, count)
    return simready_catalog.order_featured(_cards(hits, catalog), catalog.featured)


def search_async(events, token, catalog, query, mode, selection, cursor, limit=simready_client.PAGE_SIZE):
    """Fetch one page and publish ('page', token, cards, total, next_cursor, appended)."""
    def work():
        filters = simready_catalog.search_fields(selection, catalog)
        hits, total, next_cursor = simready_client.search_page(query, mode, filters, cursor, limit)
        cards = _cards(hits, catalog)
        landing = not query and not cursor and not simready_catalog.is_filtering(selection)
        if landing:
            featured = _featured_cards(catalog)
            seen = {c["key"] for c in featured}
            cards = featured + [c for c in cards if c["key"] not in seen]
        events.put(("page", token, cards, total, next_cursor, bool(cursor)))
    _spawn(_guarded, events, token, work)


def _all_cards(query, mode, filters, catalog):
    """Cards of every page of one search (the result sets this is used for are small)."""
    cards, cursor = [], None
    while True:
        hits, _, cursor = simready_client.search_page(query, mode, filters, cursor, SORT_PAGE_LIMIT)
        cards += _cards(hits, catalog)
        if cursor is None:
            return cards


def downloaded_async(events, token, catalog, query, mode, selection, library):
    """Search inside the downloaded packages only and publish one complete ('page', ...) event.

    The service cannot know what is on this disk, so the packages are pinned by a URL regular expression
    (in chunks, because its length is limited); every other filter and the text query apply as usual.
    """
    def work():
        base = simready_catalog.search_fields(selection, catalog)
        cards = []
        for pattern in simready_library.regexp_chunks(library):
            cards += _all_cards(query, mode, dict(base, filter_url_regexp=pattern), catalog)
        cards = simready_library.keep_downloaded(cards, library)
        events.put(("page", token, cards, len(cards), None, False))
    _spawn(_guarded, events, token, work)


def details_async(events, token, card, catalog):
    """Fetch the full record (licence, profile, mass, ...) of one listed asset and publish ('details', token, card)."""
    def work():
        ref = card["asset"]["ref"]
        pattern = ".*/resolve/[0-9a-f]+/" + re.escape("%s/%s" % (ref["package"], ref["rel"]))
        hits, _, _ = simready_client.search_page("", "Hybrid", {"filter_url_regexp": pattern}, None, 3, properties=True)
        full = [c for c in (simready_catalog.card_from_hit(hit, catalog) for hit in hits) if c and c["key"] == card["key"]]
        if full:
            events.put(("details", token, full[0]))
    _spawn(_guarded, events, token, work)


def similar_async(events, token, card, catalog):
    """Search assets of the same kind as card and publish ('similar', token, key, [card]); nothing without a query."""
    query = simready_catalog.similar_query(card)
    if not query:
        return

    def work():
        hits, _, _ = simready_client.search_page(query, "Hybrid", {}, None, simready_catalog.SIMILAR_FETCH)
        events.put(("similar", token, card["key"], simready_catalog.pick_similar(card, _cards(hits, catalog))))
    _spawn(_guarded, events, token, work)


def cancel_pending_images():
    """Make every download that has not started yet publish an empty result instead (used before clearing the cache)."""
    _image_epoch[0] += 1


def images_async(events, urls, cache_dir):
    """Download preview images in parallel and publish an 'image' event per finished file."""
    epoch = _image_epoch[0]

    def fetch(url):
        path = simready_media.fetch_image(url, cache_dir) if epoch == _image_epoch[0] else None
        events.put(("image", 0, url, path))

    def work():
        with ThreadPoolExecutor(max_workers=IMAGE_WORKERS) as pool:
            list(pool.map(fetch, urls))
    _spawn(work)


def match_async(events, token, query, keys):
    """Ask the service how well each asset matches query, in batches; publish ('match', token, query, {key: %})
    per batch. Validation is a nicety: when the service refuses or fails, the cards simply show no percentage."""
    def work():
        for start in range(0, len(keys), simready_client.MATCH_BATCH):
            try:
                scores = simready_client.match_scores(query, keys[start:start + simready_client.MATCH_BATCH])
            except NETWORK_ERRORS:
                return
            events.put(("match", token, query, scores))
    _spawn(work)


def video_async(events, url, cache_dir):
    """Download one clip into the preview cache and publish ('video', 0, url, path or None)."""
    def work():
        events.put(("video", 0, url, simready_media.fetch_image(url, cache_dir)))
    _spawn(work)


def previews_async(events, cache_dir, max_bytes, clear=False):
    """Prune (or with clear=True empty) the preview cache off the main thread and publish ('previews', cleared, bytes_left)."""
    def work():
        if clear:
            simready_media.clear_previews(cache_dir)
        else:
            simready_media.prune_previews(cache_dir, max_bytes)
        events.put(("previews", 0, clear, simready_media.preview_usage(cache_dir)[1]))
    _spawn(work)


def update_async(events, local_version, state, now, force=False):
    """Publish ('update', 0, newer release or None, new state, error, force) from simready_update.check."""
    def work():
        events.put(("update", 0) + simready_update.check(local_version, state, now, force) + (force,))
    _spawn(work)


def dependencies_async(events, token, card):
    """Publish ('deps', token, key, [(file, size)]) with the package files other than the root USD."""
    def work():
        files = simready_client.select_files(simready_client.fetch_manifest(card["asset"]["path"]))
        events.put(("deps", token, card["key"], files))
    _spawn(_guarded, events, token, work)


def _fetch_package(events, token, asset, cache_dir, force=False):
    """Return the local root USD of asset, downloading it unless it is already cached (or force is set)."""
    if not force and simready_client.is_cached(asset, cache_dir):
        return simready_client.cached_root_usd(asset, cache_dir)
    progress = lambda done, total: events.put(("progress", token, done, total))
    return simready_client.download_package(asset, cache_dir, progress=progress, force=force)


def install_async(events, token, asset, cache_dir, inspect, force=False, then_import=True):
    """Download asset (again when force is set), then either import it or just report it.

    With then_import the materials are inspected with inspect(path) and an 'installed' event follows; without
    it a 'refreshed' event ends the job and the scene is left alone (Re-Download updates files only).
    inspect is injected (it returns (spec, warning)) so this module stays free of importer code.
    """
    def work():
        path = _fetch_package(events, token, asset, cache_dir, force)
        if not then_import:
            events.put(("refreshed", token, asset["path"], path))
            return
        events.put(("inspecting", token, asset["path"]))
        events.put(("installed", token, asset["path"], path, inspect(path)))
    _spawn(_guarded, events, token, work)
