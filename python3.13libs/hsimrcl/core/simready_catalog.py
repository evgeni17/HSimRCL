# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_catalog.py @ 1150d3e
"""Catalog data of SimReady Central that the browser needs besides search hits.

Covers the category tree with counts, facet options, package sizes, preview media, card titles and
the translation of the user's selection into search request fields. Pure Python without Cinema 4D
imports, so it runs in worker threads and can be tested outside Cinema 4D.
"""
import json
import os
import re
import time
from collections import Counter, namedtuple

from . import simready_client
from . import simready_dims

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
META_DIRNAME = "meta"
META_MAX_AGE_SECONDS = 24 * 3600
KIBI = 1024

CATEGORY_PROPERTY = "central:category"
PROFILE_PROPERTY = "simready_metadata_validation__profile"
MASS_PROPERTY = "simready_metadata_mass"
DATE_PROPERTY = "simready_metadata_usd_date_generated"  # the only date left once the service dropped modified_timestamp
RIGID_PROPERTY = "simready_metadata_rigid_body_count"
DIMENSION_AXES = ("x", "y", "z")

# Mass bands of the original UI; each band is a list of numeric constraints that are ANDed.
MASS_BANDS = (
    ("Under 1 kg", (("<", 1),)),
    ("1\u201310 kg", ((">=", 1), ("<", 10))),
    ("10\u2013100 kg", ((">=", 10), ("<", 100))),
    ("100 kg and over", ((">=", 100),)),
)
RIGID_BANDS = (("Single body", (("=", 1),)), ("Multi-body", ((">=", 2),)))

# Acronyms keep their case in titles taken from the VLM object type.
ACRONYMS = frozenset("ac atv cnc co2 cv dc dpf hvac iv lcd led obd2 oled pc pos ppe sds tv ups usb uv".split())
_VERSIONISH = re.compile(r"^(?:v\d{1,2}|\d{1,2}[dv])$")
_VLM_SUFFIX = "_vlm_generated"

Option = namedtuple("Option", "key label count")
Catalog = namedtuple("Catalog", "tree nodes hierarchy sizes media stats featured titles makers", defaults=({},))
# groups: the landing page groups the maker belongs to ("oem", "isv", "dsx"; one maker can be in two)
Provider = namedtuple("Provider", "key name groups count url")
PROVIDER_PREFIX = "oem:"  # the service files every company under central:category = oem:<repository owner>
GROUP_OEM, GROUP_ISV, GROUP_DSX, GROUP_OTHER = "oem", "isv", "dsx", "other"
# the landing page's order; "other" holds makers makers.json does not list yet
GROUP_LABELS = ((GROUP_OEM, "OEMs"), (GROUP_ISV, "ISVs"), (GROUP_DSX, "DSX"), (GROUP_OTHER, "Other"))
GROUP_TAGS = {GROUP_OEM: "OEM", GROUP_ISV: "ISV", GROUP_DSX: "DSX", GROUP_OTHER: ""}


class Node:
    """One category in the hierarchy tree; count includes everything below it."""

    __slots__ = ("key", "label", "count", "children", "values")

    def __init__(self, key, label):
        self.key, self.label, self.count = key, label, 0
        self.children, self.values = [], []


# ---------------------------------------------------------------- formatting

def format_count(number):
    """3599 -> '3 599', the grouping of the original UI."""
    return "{:,}".format(number).replace(",", " ")


def format_bytes(size, digits=2):
    """Binary-based size text: 47384571 -> '45.19 MB', 1.8e9 -> '1.68 GB'."""
    if size is None:
        return ""
    for unit, factor in (("GB", KIBI ** 3), ("MB", KIBI ** 2), ("KB", KIBI)):
        if size >= factor:
            return "%.*f %s" % (digits, size / factor, unit)
    return "%d B" % size


def format_dimensions(dims):
    """(0.62115, 0.296, 2.2644) -> '0.62 \u00d7 0.3 \u00d7 2.26 m'; empty text when unknown."""
    if not dims:
        return ""
    return " \u00d7 ".join("%g" % round(value, 2) for value in dims) + " m"


def format_mass(kilograms):
    """26.949758 -> '26.9 kg', 0.3203 -> '0.32 kg'; empty when unknown."""
    return "" if kilograms is None else "%s kg" % ("%.3g" % kilograms)


def format_modified(timestamp):
    """'2026-10-15T22:19:52.055621' or '2026-10-15 22:19:52' -> '15.10.2026, 22:19:52'."""
    match = re.match(r"(\d{4})-(\d\d)-(\d\d)[T ](\d\d:\d\d:\d\d)", timestamp or "")
    return "%s.%s.%s, %s" % (match.group(3), match.group(2), match.group(1), match.group(4)) if match else ""


# ---------------------------------------------------------------- metadata cache

def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    os.replace(path + ".part", path)


def _is_fresh(path):
    return os.path.isfile(path) and time.time() - os.path.getmtime(path) < META_MAX_AGE_SECONDS


def load_meta(cache_dir, name, service_path, reduce):
    """Reduced JSON dataset from the service, cached on disk for a day.

    The raw files are large (the media index is 16 MB), so only the reduced form is stored. A stale
    copy is better than no catalog when the service is unreachable.
    """
    path = os.path.join(cache_dir, META_DIRNAME, name + ".json")
    if _is_fresh(path):
        return _read_json(path)
    try:
        data = reduce(simready_client.get_json(service_path))
    except OSError:
        if os.path.isfile(path):
            return _read_json(path)
        raise
    _write_json(path, data)
    return data


# ---------------------------------------------------------------- reducers

def reduce_hierarchy(raw):
    """{category value: {'label', 'path': [[key, label], ...]}} without the bulky bookkeeping."""
    return {value: {"label": entry["label"], "path": [[s["qcode"], s["label"]] for s in entry["path"]]}
            for value, entry in raw["qcodes"].items()}


def reduce_sizes(raw):
    """Package size in bytes per asset (keyed by the blob URL)."""
    return raw["sizes"]


def _files(entry, block):
    return (entry.get(block) or {}).get("files") or {}


def _media_entry(entry):
    """Library id, joint count, the JPEG stills and the MP4 clips (360 turn, moving parts) of one asset."""
    still = _files(entry, "still")
    return {"id": entry["id"], "moving": entry.get("moving", 0), "tile": still.get("tile"), "poster": still.get("poster"),
            "spin": _files(entry, "spin").get("card"), "joints": _files(entry, "rtxclip").get("textured")}


def reduce_media(raw):
    """Preview media per asset: library id, joint count, JPEG tile and poster, MP4 clips (Cinema 4D cannot read WebP)."""
    return {key: _media_entry(entry) for key, entry in raw["assets"].items()}


def reduce_stats(raw):
    """Value counts of the properties that drive the sidebar filters."""
    wanted = {CATEGORY_PROPERTY, PROFILE_PROPERTY, simready_client.LICENSE_PROPERTY, MASS_PROPERTY, RIGID_PROPERTY}
    out = {key: {} for key in wanted}
    for pair in raw["kv_pairs"]:
        if pair["key"] in wanted:
            out[pair["key"]][str(pair["value"])] = pair["asset_count"]
    return out


def maker_groups(maker):
    """Groups of one makers.json entry: its "group" list (since 2026-11-02), else the older kind / segment fields."""
    group = maker.get("group")
    if group:
        return [group] if isinstance(group, str) else list(group)
    legacy = [GROUP_ISV if maker.get("kind") == GROUP_ISV else GROUP_OEM]
    return legacy + ([GROUP_DSX] if maker.get("segment") == GROUP_DSX else [])


def reduce_makers(raw):
    """{category value 'oem:<owner>': {'name', 'groups', 'url'}} of the companies the landing page lists."""
    return {maker["code"]: {"name": maker["name"], "groups": maker_groups(maker), "url": maker.get("url") or ""}
            for maker in raw.get("makers", []) if maker.get("code") and maker.get("name")}


def reduce_featured(raw):
    """Blob URLs of the landing assets, in display order."""
    return [asset["key"] for asset in raw["assets"]]


def load_titles():
    """Curated display names shipped with the plugin, keyed by 'repo/path-in-repo'."""
    return _read_json(os.path.join(DATA_DIR, "titles.json"))


# ---------------------------------------------------------------- category tree

def _child(parent, key, label):
    for node in parent.children:
        if node.key == key:
            return node
    node = Node(key, label)
    parent.children.append(node)
    return node


def _insert(root, value, entry, count):
    node = root
    for key, label in entry["path"]:
        node = _child(node, key, label)
        node.count += count
    node.values.append(value)


def _sort_tree(node):
    node.children.sort(key=lambda child: (-child.count, child.label.lower()))
    for child in node.children:
        _sort_tree(child)


def build_tree(hierarchy, category_counts):
    """Tree of categories that contain assets; counts roll up to every ancestor."""
    root = Node("", "All")
    for value, entry in hierarchy.items():
        count = category_counts.get(value, 0)
        if count:
            _insert(root, value, entry, count)
            root.count += count
    _sort_tree(root)
    return root


def index_nodes(root):
    """{node key: Node} for every node below root."""
    found = {}
    stack = list(root.children)
    while stack:
        node = stack.pop()
        found[node.key] = node
        stack.extend(node.children)
    return found


def subtree_values(node):
    """Category property values of every asset category at or below node."""
    values = list(node.values)
    for child in node.children:
        values.extend(subtree_values(child))
    return values


def visible_rows(root, expanded, depth, hidden=()):
    """Flat list of (node, level, expandable, is_open) for the sidebar; levels deeper than depth stay hidden.

    hidden holds keys of top-level branches that the sidebar shows elsewhere (the providers).
    """
    rows = []

    def walk(node, level):
        for child in node.children:
            if level == 1 and child.key in hidden:
                continue
            expandable = bool(child.children) and level < depth
            is_open = expandable and child.key in expanded
            rows.append((child, level, expandable, is_open))
            if is_open:
                walk(child, level + 1)

    walk(root, 1)
    return rows


# ---------------------------------------------------------------- providers

def provider_branch_keys(tree):
    """Keys of the top-level branches that only hold companies (every category value is 'oem:...')."""
    return {node.key for node in tree.children
            if subtree_values(node) and all(value.startswith(PROVIDER_PREFIX) for value in subtree_values(node))}


def _provider_nodes(tree):
    branches = provider_branch_keys(tree)
    return [leaf for node in tree.children if node.key in branches for leaf in _leaves(node)]


def _leaves(node):
    return [leaf for child in node.children for leaf in (_leaves(child) or [child])]


def provider_list(catalog):
    """Providers of the catalog, most assets first; the kind and group come from makers.json when the service has it."""
    found = []
    for node in _provider_nodes(catalog.tree):
        code = next((value for value in node.values if value.startswith(PROVIDER_PREFIX)), node.key)
        maker = catalog.makers.get(code, {})
        groups = tuple(maker.get("groups") or (GROUP_OTHER,))
        found.append(Provider(node.key, maker.get("name") or node.label, groups, node.count, maker.get("url", "")))
    return sorted(found, key=lambda p: p.name.lower())  # alphabetical inside each group, as on the landing page


def provider_kinds(providers):
    """('all',) plus the groups that have makers, in the landing page's order (the switch above the list)."""
    return ("all",) + tuple(group for group, _ in GROUP_LABELS if any(group in p.groups for p in providers))


def provider_groups(providers, kind="all"):
    """[(heading, count, [Provider])] in the landing page order; a maker in two groups is listed in both.

    The switch narrows to one group, which then shows without a heading (as does a list with only one group).
    """
    shown = [group for group, _ in GROUP_LABELS if kind in ("all", group)]
    labels = dict(GROUP_LABELS)
    groups = [(labels[group], [p for p in providers if group in p.groups]) for group in shown]
    groups = [(label, sum(p.count for p in members), members) for label, members in groups if members]
    return groups if len(groups) > 1 else [("", count, members) for _, count, members in groups]


def provider_tag(provider):
    """Short group tag of a provider row, e.g. 'ISV' or 'OEM / DSX'."""
    return " / ".join(GROUP_TAGS[group] for group in provider.groups if GROUP_TAGS.get(group))


def provider_name(catalog, owner):
    """Display name of the company behind a repository owner ('NVIDIA' for the library NVIDIA publishes itself)."""
    code = PROVIDER_PREFIX + owner
    name = catalog.makers.get(code, {}).get("name") or (catalog.nodes[code].label if code in catalog.nodes else "")
    return name or ("NVIDIA" if owner.lower() == "nvidia" else owner)


# ---------------------------------------------------------------- facets

def profile_options(stats):
    """Profiles of the SimReady validation, most common first."""
    counts = stats.get(PROFILE_PROPERTY, {})
    return [Option(name, name, count) for name, count in sorted(counts.items(), key=lambda kv: -kv[1])]


def _license_key(spelling):
    return spelling.lower().replace(" ", "-")


def license_groups(stats):
    """Licence options with every spelling merged: {key: (label, count, [raw spellings])}."""
    groups = {}
    for spelling, count in stats.get(simready_client.LICENSE_PROPERTY, {}).items():
        groups.setdefault(_license_key(spelling), []).append((spelling, count))
    return {key: _license_group(items) for key, items in groups.items()}


def _license_group(items):
    spellings = [spelling for spelling, _ in items]
    label = max(items, key=lambda item: item[1])[0]
    return (label.replace(" ", "-") if len(items) > 1 else label), sum(c for _, c in items), spellings


def license_options(stats):
    """Licence options, most common first."""
    groups = license_groups(stats)
    ordered = sorted(groups.items(), key=lambda kv: -kv[1][1])
    return [Option(key, label, count) for key, (label, count, _) in ordered]


def _in_band(value, band):
    ops = {"<": value.__lt__, "<=": value.__le__, ">": value.__gt__, ">=": value.__ge__, "=": value.__eq__}
    return all(ops[op](limit) for op, limit in band)


def _band_options(counts, bands):
    totals = Counter()
    for raw, count in counts.items():
        for index, (_, band) in enumerate(bands):
            totals[index] += count if _in_band(float(raw), band) else 0
    return [Option(str(index), label, totals[index]) for index, (label, _) in enumerate(bands)]


def mass_options(stats):
    """Mass bands with the number of assets in each."""
    return _band_options(stats.get(MASS_PROPERTY, {}), MASS_BANDS)


def rigid_options(stats):
    """Single/multi body options with counts."""
    return _band_options(stats.get(RIGID_PROPERTY, {}), RIGID_BANDS)


# ---------------------------------------------------------------- selection -> search fields

def empty_selection():
    """Nothing filtered."""
    return {"nodes": (), "profiles": (), "licenses": (), "rigid": None, "mass": None, "dims": simready_dims.empty()}


def toggle_member(selection, field, value, extend=True):
    """Add or remove value from a multi-select field; without extend the field becomes just that value."""
    current = selection[field]
    if value in current:
        members = tuple(v for v in current if v != value)
    else:
        members = tuple(current) + (value,) if extend else (value,)
    return dict(selection, **{field: members})


def toggle_choice(selection, field, value):
    """Single-select field: choosing the active value clears it."""
    return dict(selection, **{field: None if selection[field] == value else value})


def set_dimension(selection, axis, limits):
    """Set the (min, max) size in metres along axis 0..2; (None, None) clears it."""
    return dict(selection, dims=simready_dims.set_axis(selection["dims"], axis, limits))


def clear_dimensions(selection):
    """Remove every size limit."""
    return dict(selection, dims=simready_dims.empty())


def _node_chip(node):
    """Chip text of a category; companies say so, because their names alone do not read as a filter."""
    return ("Provider: " if node.key.startswith(PROVIDER_PREFIX) else "") + node.label


def selection_chips(selection, catalog):
    """[(label, field, key)] for every active filter, in the order the sidebar shows them."""
    stats, chips = catalog.stats, []
    chips += [(_node_chip(catalog.nodes[key]), "nodes", key) for key in selection["nodes"] if key in catalog.nodes]
    chips += [(name, "profiles", name) for name in selection["profiles"]]
    groups = license_groups(stats)
    chips += [(groups[key][0], "licenses", key) for key in selection["licenses"] if key in groups]
    if selection["rigid"] is not None:
        chips.append((RIGID_BANDS[int(selection["rigid"])][0], "rigid", selection["rigid"]))
    if selection["mass"] is not None:
        chips.append((MASS_BANDS[int(selection["mass"])][0], "mass", selection["mass"]))
    chips += [(simready_dims.chip(axis, limits), "dims", axis) for axis, limits in enumerate(selection["dims"])
              if simready_dims.chip(axis, limits)]
    return chips


def is_filtering(selection):
    """True when any filter is active."""
    return selection != empty_selection()


def _equals(prop, value):
    return "%s=%s" % (prop, value)


def _numeric(prop, band):
    return ",".join("%s%s%g" % (prop, op, limit) for op, limit in band)


def _exclusions(prop, all_values, chosen):
    """Express 'one of chosen' as 'none of the others': the service ORs only one include list."""
    return [_equals(prop, value) for value in all_values if value not in chosen]


def _category_fields(values):
    if not values:
        return {}
    if len(values) == 1:
        return {"filter_by_properties": _equals(CATEGORY_PROPERTY, values[0])}
    return {"filter_by_properties_include_any": ",".join(_equals(CATEGORY_PROPERTY, v) for v in values)}


def _exclude_fields(selection, catalog):
    stats, excludes = catalog.stats, []
    if selection["profiles"]:
        excludes += _exclusions(PROFILE_PROPERTY, stats.get(PROFILE_PROPERTY, {}), selection["profiles"])
    if selection["licenses"]:
        groups = license_groups(stats)
        chosen = {s for key in selection["licenses"] for s in groups[key][2]}
        excludes += _exclusions(simready_client.LICENSE_PROPERTY, stats.get(simready_client.LICENSE_PROPERTY, {}), chosen)
    return {"exclude_filter_by_properties": ",".join(excludes)} if excludes else {}


def _numeric_fields(selection):
    parts = []
    if selection["rigid"] is not None:
        parts.append(_numeric(RIGID_PROPERTY, RIGID_BANDS[int(selection["rigid"])][1]))
    if selection["mass"] is not None:
        parts.append(_numeric(MASS_PROPERTY, MASS_BANDS[int(selection["mass"])][1]))
    return {"filter_by_properties_numeric": ",".join(parts)} if parts else {}


def _dimension_fields(selection):
    return simready_dims.search_fields(selection["dims"])


def search_fields(selection, catalog):
    """Request fields that apply selection; merge them into a search body."""
    values = [v for key in selection["nodes"] for v in subtree_values(catalog.nodes[key])]
    fields = {}
    for part in (_category_fields(values), _exclude_fields(selection, catalog),
                 _numeric_fields(selection), _dimension_fields(selection)):
        fields.update(part)
    return fields


# ---------------------------------------------------------------- cards

def _properties(hit):
    return {p.get("name"): p.get("value") for p in hit.get("source", {}).get("usd_properties", [])}


def _repo_key(base_key):
    """'repo/path' part of a blob URL, the key of the curated titles."""
    match = re.match(r"^https://huggingface\.co/datasets/([^/]+/[^/]+)/blob/[^/]+/(.+)$", base_key or "")
    return "%s/%s" % match.groups() if match else None


def _vlm_object_type(source):
    for name, entries in source.items():
        if not name.endswith(_VLM_SUFFIX) or not isinstance(entries, list):
            continue
        for entry in entries:
            if entry.get("name") == "object_type" and entry.get("value_text"):
                return str(entry["value_text"][0]).strip().lower()
    return ""


VLM_TEXT_FIELDS = (("colors", "Colors"), ("materials", "Materials"), ("environment", "Setting"), ("style", "Style"),
                   ("scale", "Scale"), ("state", "State"), ("physical_attributes", "Features"), ("visible_text", "Text on it"))
TAG_LIMIT = 14
_VARIANT_RE = re.compile(r"^simready_metadata_Variants__Physics__(\w+?)__variantSetName$")


def _vlm_fields(source):
    """{name: [text, ...]} of the vision-model description (caption, tags, colours, ...) when the service sends it."""
    found = {}
    for name, entries in source.items():
        if not name.endswith(_VLM_SUFFIX) or not isinstance(entries, list):
            continue
        for entry in entries:
            values = [str(v).strip() for v in entry.get("value_text") or [] if str(v).strip()]
            if values and entry.get("name") not in found:
                found[entry["name"]] = values
    return found


def _extras(props):
    """Facts that exist only in the full record: polygons, author, robot type, physics variants, rigid bodies."""
    polygons = _number(props.get("__polygon_count"))
    bodies = _number(props.get(RIGID_PROPERTY))
    return {"polygons": int(polygons) if polygons else None, "author": props.get("simready_metadata_author"),
            "robot": props.get("isaac:robotType"), "bodies": int(bodies) if bodies else None,
            "engines": [m.group(1) for m in map(_VARIANT_RE.match, sorted(props)) if m]}


def _capitalise(text):
    """Sentence-case a VLM object type but keep acronyms (UPS, TV, V8) upper case."""
    text = re.sub(r"[A-Za-z0-9]+", lambda m: m.group(0).upper()
                  if m.group(0).lower() in ACRONYMS or _VERSIONISH.match(m.group(0).lower()) else m.group(0), text)
    return text[:1].upper() + text[1:]


def card_title(hit, titles):
    """Display name: curated title, else the VLM object type, else None (the file name is shown alone)."""
    source = hit.get("source", {})
    curated = titles.get(_repo_key(source.get("base_key")) or "")
    if curated:
        return curated
    guess = _vlm_object_type(source)
    return _capitalise(guess) if guess and guess != "unknown" else None


def _dimensions(source):
    dims = source.get("usd_dimensions") or {}
    values = [dims.get("scaled_bbox_dimension_" + a, dims.get("bbox_dimension_" + a)) for a in DIMENSION_AXES]
    return tuple(values) if all(v is not None for v in values) else None


def _number(value):
    """Float of a property value that may arrive as text; None when missing or not numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _category_label(props, hierarchy):
    entry = hierarchy.get(props.get(CATEGORY_PROPERTY, ""))
    return entry["path"][-1][1] if entry else props.get("simready_metadata_category")


def card_from_hit(hit, catalog):
    """Everything a card and the detail panel show, or None when the hit is not an asset entry point."""
    asset = simready_client.hit_to_asset(hit)
    if asset is None:
        return None
    source, props = hit["source"], _properties(hit)
    key = source.get("base_key")
    media = catalog.media.get(key) or {}
    return {
        "asset": asset, "key": key, "filename": asset["name"], "title": card_title(hit, catalog.titles),
        "bytes": catalog.sizes.get(key), "license": props.get(simready_client.LICENSE_PROPERTY),
        "profile": props.get(PROFILE_PROPERTY), "asset_type": props.get("simready_metadata_asset_type"),
        "category": _category_label(props, catalog.hierarchy), "qcode": props.get("simready_metadata_qcode"),
        "detailed": bool(props), "dims": _dimensions(source), "mass": _number(props.get(MASS_PROPERTY)), "modified": source.get("modified_timestamp") or props.get(DATE_PROPERTY),
        "joints": media.get("moving", 0), "media": media, "source_name": asset["ref"]["repo"].split("/")[-1],
        "provider": provider_name(catalog, asset["ref"]["repo"].split("/")[0]),
        "vlm": _vlm_fields(source), "extras": _extras(props),
    }


SIMILAR_LIMIT = 3
SIMILAR_FETCH = 12  # a few more than shown: variants of the same package and the asset itself are dropped
_CODE_WORD = re.compile(r"^(sm|[a-z]?\d+[a-z]?\d*)$")


def _stem_words(filename):
    """'sm_kitchenware_pan_a01_01.usd' -> 'kitchenware pan': the readable words of a file name."""
    words = re.split(r"[\W_]+", os.path.splitext(filename or "")[0].lower())
    return " ".join(w for w in words if w and not _CODE_WORD.match(w))


def similar_query(card):
    """Search text that finds assets of the same kind: the vision model's object type, else the title or file name."""
    kind = ((card.get("vlm") or {}).get("object_type") or [""])[0].strip().lower()
    if kind and kind != "unknown":
        return kind
    return (card.get("title") or _stem_words(card.get("filename"))).strip().lower()


def search_name(card):
    """Text the 'More' button searches for: the displayed name of the asset, else the words of its file name."""
    return (card.get("title") or _stem_words(card.get("filename"))).strip()


def _package_id(card):
    ref = card["asset"]["ref"]
    return ref["repo"], ref["package"]


def pick_similar(card, candidates, limit=SIMILAR_LIMIT):
    """Up to limit other assets for the 'Similar' strip: one per package, never the asset's own package.

    Candidates of exactly the same object type come first (a pan gives pans before woks); within each
    group the service's relevance order is kept.
    """
    seen, others = {_package_id(card)}, []
    for candidate in candidates:
        package = _package_id(candidate)
        if package not in seen:
            seen.add(package)
            others.append(candidate)
    kind = similar_query(card)
    return sorted(others, key=lambda other: similar_query(other) != kind)[:limit]


def _without_revision(key):
    """Blob URL with the commit removed: the featured list is matched regardless of the dataset revision."""
    return re.sub(r"/blob/[0-9a-f]{7,40}/", "/blob/", key or "")


SORT_OPTIONS = (
    ("relevance", "Relevance"), ("name", "Name"), ("filename", "File name"), ("filename_length", "File name length"),
    ("size", "File size"), ("volume", "Dimensions (volume)"), ("largest", "Largest dimension"),
    ("joints", "Moving parts"), ("modified", "Date"), ("match", "Match %"),
)


def available_sort_options(cards):
    """SORT_OPTIONS the loaded cards can actually be ordered by.

    The service stopped sending the file date in lists (November 2026), so a date sort would silently do nothing;
    a key is offered only when at least half of the cards carry a value for it. Relevance is always offered.
    """
    def covered(key):
        return key == "relevance" or 2 * sum(1 for card in cards if _sort_value(card, key) is not None) >= len(cards)
    return tuple(option for option in SORT_OPTIONS if covered(option[0]))


def _volume(dims):
    return dims[0] * dims[1] * dims[2] if dims else None


def _sort_value(card, key):
    """Comparable value of card for key, or None when the asset has no such data (those sort last)."""
    stem = card["filename"].rsplit(".", 1)[0]
    values = {
        "name": (card["title"] or card["filename"]).lower(), "filename": card["filename"].lower(),
        "filename_length": len(stem), "size": card["bytes"], "volume": _volume(card["dims"]),
        "largest": max(card["dims"]) if card["dims"] else None,
        "joints": card["joints"], "modified": card["modified"], "match": card.get("match"),
    }
    return values[key]


def sort_cards(cards, key, descending=False):
    """Cards ordered by key; relevance keeps the service order. Assets without the value always come last."""
    if key == "relevance":
        return list(cards)
    keyed = [(card, _sort_value(card, key)) for card in cards]
    present = sorted((pair for pair in keyed if pair[1] is not None), key=lambda pair: pair[1], reverse=descending)
    return [card for card, _ in present] + [card for card, value in keyed if value is None]


def order_featured(cards, featured):
    """Cards whose key is in featured first (in that order), the rest after them in retrieval order."""
    rank = {_without_revision(key): index for index, key in enumerate(featured)}
    return sorted(cards, key=lambda card: rank.get(_without_revision(card["key"]), len(rank)))


def featured_filter(featured, max_length=900):
    """(regexp, count) that matches the first featured assets by file name.

    The index rejects patterns longer than 1000 characters, so only as many leading entries as fit are used.
    """
    names, length = [], 4
    for key in featured:
        name = re.escape(key.rsplit("/", 1)[-1])
        if length + len(name) + 1 > max_length:
            break
        names.append(name)
        length += len(name) + 1
    return ".*/(" + "|".join(names) + ")", len(names)


# ---------------------------------------------------------------- loading

def _optional_meta(cache_dir, name, service_path, reduce):
    """load_meta for data that only improves the display: {} when the service has no such file."""
    try:
        return load_meta(cache_dir, name, service_path, reduce)
    except (OSError, ValueError, KeyError):
        return {}


def load_catalog(cache_dir):
    """Download (or read from the day cache) every dataset and assemble the Catalog; blocking."""
    hierarchy = load_meta(cache_dir, "hierarchy", "/wikidata_hierarchy.json", reduce_hierarchy)
    stats = load_meta(cache_dir, "stats", "/search/stats/usd_properties", reduce_stats)
    tree = build_tree(hierarchy, stats.get(CATEGORY_PROPERTY, {}))
    return Catalog(
        makers=_optional_meta(cache_dir, "makers_v2", "/makers.json", reduce_makers), tree=tree, nodes=index_nodes(tree), hierarchy=hierarchy, stats=stats,
        sizes=load_meta(cache_dir, "sizes", "/package_sizes.json", reduce_sizes),
        media=load_meta(cache_dir, "media_v2", "/library_media/usdsearch-dev/manifest.json", reduce_media),
        featured=load_meta(cache_dir, "featured", "/featured.json", reduce_featured), titles=load_titles(),
    )
