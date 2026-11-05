# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_media.py @ 1150d3e
"""Preview images: where they live on the service and how they are cached locally. No Cinema 4D imports."""
import hashlib
import os
import urllib.parse
from collections import OrderedDict

from . import simready_client

MEDIA_PATH = "/library_media/usdsearch-dev"
TILE, POSTER = "tile", "poster"
SPIN, JOINTS = "spin", "joints"  # MP4 clips: 360 degree turn, moving parts in action
PREVIEW_SUFFIX = ".jpg"
VIDEO_SUFFIX = ".mp4"
CACHE_SUFFIXES = (PREVIEW_SUFFIX, VIDEO_SUFFIX)
PRUNE_TARGET = 0.8  # prune below the limit, not exactly to it, so the next download does not trigger another prune


def media_url(card, kind):
    """URL of the card's tile or poster JPEG; falls back to the service's own render for assets without library media."""
    media = card["media"]
    name = media.get(kind) if media else None
    if name:
        return "%s%s/%s/%s" % (simready_client.SERVICE_URL, MEDIA_PATH, media["id"], name)
    query = urllib.parse.urlencode({"asset_url": card["key"]})
    return "%s/images?%s" % (simready_client.SERVICE_URL, query)


def video_url(card, kind):
    """URL of the card's MP4 clip of kind, or None. A moving-parts clip falls back to the turn, which nearly
    every asset has."""
    media = card["media"] or {}
    name = media.get(kind) or (media.get(SPIN) if kind == JOINTS else None)
    return "%s%s/%s/%s" % (simready_client.SERVICE_URL, MEDIA_PATH, media["id"], name) if name else None


def image_path(url, cache_dir):
    """Cache file of url; the hash keeps names short and safe for Windows, the suffix keeps clips apart."""
    suffix = VIDEO_SUFFIX if url.lower().endswith(VIDEO_SUFFIX) else PREVIEW_SUFFIX
    return os.path.join(cache_dir, hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + suffix)


def fetch_image(url, cache_dir):
    """Download url into the cache and return its path, or None when the service has no such image."""
    target = image_path(url, cache_dir)
    if os.path.isfile(target):
        os.utime(target)  # marks the file as recently used, so pruning keeps what the user looks at
        return target
    try:
        simready_client.download_file(url, target)
    except OSError:
        return None
    return target


def preview_files(cache_dir):
    """Paths of the cached preview images and clips; other files in the folder are never touched."""
    if not os.path.isdir(cache_dir):
        return []
    return [entry.path for entry in os.scandir(cache_dir) if entry.is_file() and entry.name.endswith(CACHE_SUFFIXES)]


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def preview_usage(cache_dir):
    """(file count, total bytes) of the cached previews."""
    files = preview_files(cache_dir)
    return len(files), sum(_size(path) for path in files)


def _remove(path):
    """Delete one file; returns the freed bytes, 0 when it is already gone or locked."""
    size = _size(path)
    try:
        os.remove(path)
    except OSError:
        return 0
    return size


def clear_previews(cache_dir):
    """Delete every cached preview; they are re-downloaded on demand. Returns (files removed, bytes freed)."""
    freed = [_remove(path) for path in preview_files(cache_dir)]
    return sum(1 for size in freed if size), sum(freed)


def prune_previews(cache_dir, max_bytes):
    """Delete the least recently used previews until the cache is below max_bytes. Returns (files removed, bytes freed)."""
    files = sorted(preview_files(cache_dir), key=lambda path: os.path.getmtime(path))
    total = sum(_size(path) for path in files)
    if total <= max_bytes:
        return 0, 0
    removed, freed = 0, 0
    for path in files:
        if total - freed <= max_bytes * PRUNE_TARGET:
            break
        size = _remove(path)
        removed, freed = removed + bool(size), freed + size
    return removed, freed


class BitmapCache:
    """Least-recently-used store of decoded bitmaps, so scrolling through thousands of cards keeps memory flat."""

    def __init__(self, limit, on_evict=None):
        self.limit = limit
        self.on_evict = on_evict
        self.items = OrderedDict()

    def get(self, key):
        """Bitmap stored under key (and mark it as used), or None."""
        bitmap = self.items.get(key)
        if bitmap is not None:
            self.items.move_to_end(key)
        return bitmap

    def put(self, key, bitmap):
        """Store bitmap and drop the least recently used ones beyond the limit."""
        self.items[key] = bitmap
        self.items.move_to_end(key)
        while len(self.items) > self.limit:
            old_key, _ = self.items.popitem(last=False)
            if self.on_evict:
                self.on_evict(old_key)

    def clear(self):
        """Forget every bitmap."""
        self.items.clear()

    def __len__(self):
        return len(self.items)
