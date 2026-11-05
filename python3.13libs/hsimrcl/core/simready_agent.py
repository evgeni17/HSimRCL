# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_agent.py @ 1150d3e
"""Short-output entry points for AI agents that drive SimRCL through a Cinema 4D MCP bridge (exec_python).

Every call returns one small text block, so an agent spends few tokens per step:

    from hsimrcl.core import simready_agent as sr
    print(sr.find("white lily"))        # numbered one-line results, kept for the calls below
    print(sr.info(1))                   # a few facts about result 1 (one extra request)
    print(sr.fetch(1))                  # download in the background, returns at once
    print(sr.status())                  # poll until the job says ready
    print(sr.add(1, at=(0, 80, 0)))     # import into the active document (main thread only)

Search, download and the facts work without Cinema 4D (the import needs it). Results are numbered from 1
and stay valid until the next find(). Downloads land in the same folder and library as the browser's, so an
asset fetched here is marked as downloaded in the window and the other way round.
"""
import os
import tempfile
import threading

from . import simready_catalog as catalog
from . import simready_client as client
from . import simready_dims as dims
from . import simready_settings as settings

CACHE_DIR = os.path.join(tempfile.gettempdir(), "simready_cache")  # the browser's catalog cache
CAPTION_CHARS = 70
INFO_FACTS = ("license", "mass", "author", "polygons")
_STATE = {"cards": [], "jobs": {}, "catalog": None}
_LOCK = threading.Lock()


# ---------------------------------------------------------------- pure helpers (tested in the sandbox)

def caption(card, limit=CAPTION_CHARS):
    """What the asset is, in a few words: curated title, else the vision model's caption, else the file name."""
    vlm = card.get("vlm") or {}
    text = card.get("title") or (vlm.get("caption") or [""])[0] or os.path.splitext(card.get("filename") or "")[0]
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def size_label(extent):
    """'12 x 11 x 19 cm' below a metre (the catalog has seeds and rice grains), '1.8 x 0.91 x 0.84 m' above."""
    if not extent:
        return ""
    if max(extent) < 1:
        return " x ".join("%g" % round(v * 100, 1) for v in extent) + " cm"
    return " x ".join("%g" % round(v, 2) for v in extent) + " m"


def result_line(index, card, cached=False):
    """'3. Lily (D00305) | 12 x 11 x 19 cm | 57.9 MB | 2 joints | on disk' for a card.

    The file stem follows the name because many assets share a title (every gripper is "Robot gripper").
    """
    stem = os.path.splitext(card.get("filename") or "")[0]
    name = caption(card)
    parts = [name if name == stem else "%s (%s)" % (name, stem), size_label(card.get("dims")),
             catalog.format_bytes(card.get("bytes"), 1)]
    if card.get("joints"):
        parts.append("%d joint%s" % (card["joints"], "" if card["joints"] == 1 else "s"))
    if cached:
        parts.append("on disk")
    return "%d. %s" % (index, " | ".join(p for p in parts if p))


def search_filters(sizes=None, licensed=True):
    """Service filter fields: allowed licences only (default) and optional size limits per axis.

    sizes is {'x': (min_m, max_m), ...}; None on a side means open, as in the size filter of the window.
    """
    fields = {"filter_by_properties_include_any": client.license_filter(client.ALLOWED_LICENSES)} if licensed else {}
    if sizes:
        limits = tuple(tuple(sizes.get(axis, dims.NO_LIMIT)) for axis in dims.AXES)
        fields.update(dims.search_fields(limits))
    return fields


def fact_lines(card, props):
    """'key: value' lines with what an agent needs to decide: licence, mass, author, polygons, path."""
    facts = {"license": props.get(client.LICENSE_PROPERTY), "mass": catalog.format_mass(card.get("mass")),
             "author": (card.get("extras") or {}).get("author"), "polygons": (card.get("extras") or {}).get("polygons")}
    lines = ["%s: %s" % (key, facts[key]) for key in INFO_FACTS if facts.get(key)]
    caption_text = ((card.get("vlm") or {}).get("caption") or [""])[0]
    if caption_text:
        lines.insert(0, "caption: " + caption_text)
    return lines + ["file: " + card["filename"]]


def job_text(name, job):
    """One status line per download job."""
    state, detail = job
    if state == "ready":
        return "%s: ready" % name
    return "%s: %s" % (name, state if not detail else "%s (%s)" % (state, detail))


# ---------------------------------------------------------------- service calls

def _catalog():
    """The catalog datasets (titles, sizes, media), loaded once per session from the day cache."""
    with _LOCK:
        if _STATE["catalog"] is None:
            _STATE["catalog"] = catalog.load_catalog(CACHE_DIR)
        return _STATE["catalog"]


def _download_dir():
    return settings.download_dir(settings.load())


def _card(index):
    cards = _STATE["cards"]
    if not 1 <= index <= len(cards):
        raise IndexError("no result %d: run find() first (it returned %d results)" % (index, len(cards)))
    return cards[index - 1]


def find(query="", limit=8, mode="Hybrid", sizes=None, licensed=True):
    """Search the catalog; returns numbered lines and keeps the results for info / fetch / add.

    mode is Hybrid (words and meaning), Keyword (file names, ids) or Text (meaning only). sizes limits the
    bounding box in metres, e.g. {'z': (None, 0.3)}. licensed keeps the licences the browser allows.
    """
    hits, total, _ = client.search_page(query, mode, search_filters(sizes, licensed), None, limit, False)
    found = [catalog.card_from_hit(hit, _catalog()) for hit in hits]
    _STATE["cards"] = [card for card in found if card]
    folder = _download_dir()
    lines = [result_line(i, card, client.is_cached(card["asset"], folder))
             for i, card in enumerate(_STATE["cards"], start=1)]
    return "\n".join(["%d of %d results" % (len(lines), total)] + lines)


def info(index):
    """A few facts about one result (licence, mass, author, polygons); costs one small request."""
    card = _card(index)
    hits, _, _ = client.search_page(os.path.splitext(card["filename"])[0], "Keyword", {}, None, 5, True)
    hit = next((h for h in hits if h.get("source", {}).get("path") == card["asset"]["path"]), None)
    props = catalog._properties(hit) if hit else {}
    full = catalog.card_from_hit(hit, _catalog()) if hit else card
    return "\n".join([result_line(index, card)] + fact_lines(full or card, props))


def fetch(index, force=False):
    """Download result index in a background thread; returns at once. Poll status() for the end."""
    card = _card(index)
    asset, folder, name = card["asset"], _download_dir(), card["filename"]
    if client.is_cached(asset, folder) and not force:
        _STATE["jobs"][name] = ("ready", client.cached_root_usd(asset, folder))
        return "%s: already on disk" % name

    def progress(done, total):
        _STATE["jobs"][name] = ("downloading", "%d/%d files" % (done, total))

    def work():
        try:
            _STATE["jobs"][name] = ("ready", client.download_package(asset, folder, progress, force))
        except Exception as error:  # reported through status(); a worker thread has nobody else to tell
            _STATE["jobs"][name] = ("failed", str(error)[:200])

    _STATE["jobs"][name] = ("downloading", "starting")
    threading.Thread(target=work, daemon=True).start()
    return "%s: download started" % name


def status():
    """One line per download job of this session."""
    jobs = _STATE["jobs"]
    return "\n".join(job_text(name, job) for name, job in jobs.items()) if jobs else "no downloads"


# ---------------------------------------------------------------- Cinema 4D

def _import_options():
    """The import switches of the window's Settings menu, so an agent import matches a manual one."""
    prefs = settings.load()
    return dict(tidy=settings.tidy_enabled(prefs), rig=settings.rig_enabled(prefs), phong=settings.phong_enabled(prefs),
                split=settings.split_enabled(prefs), layers=settings.layers_enabled(prefs),
                round_corners=settings.round_enabled(prefs))


def _boxes(obj):
    """(low, high) world corners of every object box under obj; boxes, not points, so big meshes stay cheap."""
    while obj:
        if obj.GetRad().GetLength() > 0:
            mg, centre, radius = obj.GetMg(), obj.GetMp(), obj.GetRad()
            corners = [mg * (centre + type(radius)(sx * radius.x, sy * radius.y, sz * radius.z))
                       for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
            yield corners
        yield from _boxes(obj.GetDown())
        obj = obj.GetNext()


def size_text(group, meters_per_unit):
    """' | 12 x 9.7 x 8.1 cm, 1 unit = 1 cm, bottom at y=0' for the imported group; empty without geometry.

    The size is given in cm so it reads the same in every scene; the bottom is in scene units for placing.
    """
    corners = [c for box in _boxes(group.GetDown()) for c in box]
    if not corners:
        return ""
    low = [min(getattr(c, a) for c in corners) for a in "xyz"]
    high = [max(getattr(c, a) for c in corners) for a in "xyz"]
    size_cm = tuple(round((h - l) * meters_per_unit * 100, 1) for l, h in zip(low, high))
    return " | %g x %g x %g cm, 1 unit = %g cm, bottom at y=%g" % (size_cm + (meters_per_unit * 100, round(low[1], 2)))


def add(index, at=None):
    """Import a downloaded result into the active document (call on the main thread, i.e. from exec_python).

    at is an optional (x, y, z) in scene units for the group. Returns the group name and notes. The first
    import of a session can take a minute: it checks (and may install) the private usd-core runtime.
    """
    import c4d  # only here: the rest of the module also runs outside Cinema 4D
    from . import simready_import
    from . import simready_render_target as render_target

    card = _card(index)
    folder = _download_dir()
    if not client.is_cached(card["asset"], folder):
        return "%s is not downloaded: fetch(%d) first" % (card["filename"], index)
    doc = c4d.documents.GetActiveDocument()
    prefs = settings.load()
    choice = render_target.resolve(settings.material_target(prefs, render_target.TARGETS),
                                   settings.prefer_openpbr(prefs), doc)
    path = client.cached_root_usd(card["asset"], folder)
    group, warning, _ = simready_import.import_asset(doc, path, choice=choice, **_import_options())
    if group is None:
        return "could not load " + path
    if at is not None:
        group.SetAbsPos(c4d.Vector(*at))
    c4d.EventAdd()
    doc.ExecutePasses(None, False, False, False, c4d.BUILDFLAGS_NONE)
    unit = simready_import.meters_per_doc_unit(doc)
    return "added %s%s%s" % (group.GetName(), size_text(group, unit), " | " + warning if warning else "")
