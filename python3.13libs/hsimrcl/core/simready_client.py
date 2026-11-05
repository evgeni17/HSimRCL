# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports; HSimRCL: safe path segments,
#   completion marker only with the root USD on disk — marked "HSimRCL:" below)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_client.py @ 1150d3e
"""HTTP client for SimReady Central: search the index and download asset packages.

Standard library only and free of Cinema 4D imports, so it is safe to run in a worker thread.
"""
import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

SERVICE_URL = "https://nvidia-simready-central.hf.space"
HF_URL = "https://huggingface.co"
USER_AGENT = "c4d-simready-importer/0.4"
LICENSE_PROPERTY = "simready_metadata_asset_license"
# Contributors spell the same licence differently, so every spelling must be listed.
# Edit this tuple to change the policy; the importer never judges legal terms for you.
ALLOWED_LICENSES = ("CC-BY 4.0", "CC-BY-4.0", "cc-by-4.0", "Apache-2.0", "BSD-3-Clause")
DOWNLOAD_WORKERS = 4
THUMBNAIL_WORKERS = 6
COMPLETE_MARKER = ".complete"
TIMEOUT_SECONDS = 30
CHUNK_BYTES = 1 << 20

# source_assets duplicates Textures/ (and ships MDL files Cinema 4D ignores), which doubles the download.
SKIP_SEGMENTS = frozenset({"source_assets", ".thumbs"})
# Folders that hold parts of an asset and never its entry point.
PART_SEGMENTS = frozenset({"payloads", "Textures", "source_assets", ".thumbs"})
USD_EXTENSIONS = (".usd", ".usda", ".usdc", ".usdz")
_HF_PREFIX = "hf://huggingface.co/datasets/"


def _request(url, payload=None):
    """Build a request; a JSON payload turns it into a POST."""
    headers = {"User-Agent": USER_AGENT}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=data, headers=headers)


def _get_json(url, payload=None):
    """Fetch url and decode the JSON answer."""
    with urllib.request.urlopen(_request(url, payload), timeout=TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read())


def get_json(path):
    """GET a service endpoint given its path ('/package_sizes.json') and decode the JSON answer."""
    return _get_json(SERVICE_URL + path)


def parse_hf_path(path):
    """Split an hf:// asset path into dataset, commit, package folder and file path inside the package.

    Returns None when the path does not look like a pinned Hugging Face dataset file.
    """
    if not path.startswith(_HF_PREFIX) or "/resolve/" not in path:
        return None
    repo, rest = path[len(_HF_PREFIX):].split("/resolve/", 1)
    parts = rest.split("/")
    if len(parts) < 3:
        return None
    # HSimRCL: репозиторий, коммит и пакет становятся папками загрузки — ".." или пустой сегмент вывел бы
    # пакет за её пределы (путь приходит от стороннего сервиса)
    if not all(_safe_segment(segment) for segment in repo.split("/") + parts[:2]):
        return None
    return {"repo": repo, "commit": parts[0], "package": parts[1], "rel": "/".join(parts[2:])}


def _safe_segment(segment):
    """HSimRCL: имя папки без перехода по дереву и без разделителей Windows."""
    return segment not in ("", ".", "..") and "\\" not in segment and ":" not in segment


def _is_entry_point(rel):
    """True for the root USD of a package, false for payloads, textures and other parts."""
    in_part_folder = PART_SEGMENTS & set(rel.split("/")[:-1])
    return rel.lower().endswith(USD_EXTENSIONS) and not in_part_folder


def hit_to_asset(hit):
    """Convert a search hit to a compact asset dict, or None if the hit is not an asset entry point."""
    source = hit.get("source", {})
    ref = parse_hf_path(source.get("path", ""))
    if ref is None or not _is_entry_point(ref["rel"]):
        return None
    props = {p.get("name"): p.get("value") for p in source.get("usd_properties", [])}
    return {
        "name": source.get("name") or os.path.basename(ref["rel"]),
        "path": source["path"],
        "ref": ref,
        "size": source.get("size"),
        "license": props.get(LICENSE_PROPERTY),
    }


def license_filter(licenses):
    """Server-side OR filter; the service takes one comma-separated string and rejects lists."""
    return ",".join("%s=%s" % (LICENSE_PROPERTY, name) for name in licenses)


def search(query, licenses=ALLOWED_LICENSES, limit=60):
    """Search the index by text and return asset dicts.

    licenses limits results to those licence spellings; pass None to see everything.
    """
    body = {
        "hybrid_text_query": query,
        "vector_queries": [{"field_name": "siglip2-embedding.embedding", "query_type": "text", "query": query}],
        "file_extension_include": "usd*",
        "limit": limit,
        "return_usd_properties": True,
    }
    if licenses:
        body["filter_by_properties_include_any"] = license_filter(licenses)
    hits = _get_json(SERVICE_URL + "/search_hybrid", body).get("hits", [])
    return [asset for asset in map(hit_to_asset, hits) if asset]


PAGE_SIZE = 48  # about two screens; the rest is fetched when the user scrolls near the end
TEXT_MODES = ("Hybrid", "Keyword", "Text")
MODE_DESCRIPTIONS = {
    "Hybrid": "Words and meaning together - the best default",
    "Keyword": "Words in names, tags and properties - for file names and IDs",
    "Text": "Meaning of a description, judged from the picture - ranks the whole catalog",
}
MATCH_BATCH = 24  # assets per validation request; 24 answer in about 1.5 s
_VECTOR_FIELD = "siglip2-embedding.embedding"


def _query_fields(query, mode):
    """Text-search fields of a request body for the Hybrid / Keyword / Text modes of the original UI."""
    if not query:
        return {}
    vector = [{"field_name": _VECTOR_FIELD, "query_type": "text", "query": query}]
    if mode == "Keyword":
        return {"hybrid_text_query": query}
    if mode == "Text":
        return {"vector_queries": vector}
    return {"hybrid_text_query": query, "vector_queries": vector}


def search_body(query, mode, filters, limit=PAGE_SIZE, cursor=None, properties=False):
    """Request body for one page of results; filters are the fields from simready_catalog.search_fields.

    properties adds the USD properties (licence, profile, mass, ...). They make a page 10-20 times larger
    (some libraries carry tens of kilobytes per asset), so lists are fetched without them.
    """
    body = {
        "limit": limit, "file_extension_include": "usd*", "return_usd_properties": properties,
        "return_usd_dimensions": True, "return_vision_generated_metadata": True, "return_tags": False,
        "validate_results": False,
    }
    body.update(_query_fields(query, mode))
    body.update(filters)
    if cursor:
        body["cursor"] = cursor
    return body


def search_page(query="", mode="Hybrid", filters=None, cursor=None, limit=PAGE_SIZE, properties=False):
    """One page of raw hits as (hits, total, next_cursor); next_cursor is None on the last page."""
    answer = _get_json(SERVICE_URL + "/search_hybrid", search_body(query, mode, filters or {}, limit, cursor, properties))
    return answer.get("hits", []), answer.get("total", 0), answer.get("next_cursor") if answer.get("has_more") else None


def match_scores(query, asset_urls):
    """{asset url: percent 0..100}: how well each asset's preview matches query, judged by the service's vision
    model (the percentages of the catalog site). The answer streams one JSON line per asset; assets the
    service could not judge are left out."""
    items = [{"id": str(index), "asset_url": url} for index, url in enumerate(asset_urls)]
    scores = {}
    with urllib.request.urlopen(_request(SERVICE_URL + "/vlm_validate/batch_stream", {"query_text": query, "items": items}),
                                timeout=TIMEOUT_SECONDS) as resp:
        for line in resp:
            entry = json.loads(line) if line.strip() else {}
            verdict = entry.get("verdict") or {}
            if "id" in entry and "similarity_score" in verdict:
                scores[asset_urls[int(entry["id"])]] = int(round(min(100.0, max(0.0, verdict["similarity_score"]))))
    return scores


def fetch_manifest(asset_path):
    """Return [(path inside package, size in bytes)] for every file of the asset's package."""
    ref = parse_hf_path(asset_path)
    if ref is None:
        raise ValueError("Unsupported asset path: " + asset_path)
    query = urllib.parse.urlencode({"asset_url": asset_path, "manifest_only": "true"})
    manifest = _get_json("%s/download/asset?%s" % (SERVICE_URL, query))
    marker = "/blob/%s/%s/" % (ref["commit"], ref["package"])
    return [
        (urllib.parse.unquote(f["url"].split(marker, 1)[1]), f["size"])
        for f in manifest.get("files", [])
        if marker in f["url"]
    ]


def select_files(manifest):
    """Drop files Cinema 4D does not need (duplicated sources, thumbnails)."""
    return [(rel, size) for rel, size in manifest if not SKIP_SEGMENTS & set(rel.split("/")[:-1])]


def _safe_join(root, rel):
    """Join rel under root, or return None if it would escape root (the manifest comes from a third party)."""
    target = os.path.normpath(os.path.join(root, *rel.split("/")))
    return target if os.path.abspath(target).startswith(os.path.abspath(root) + os.sep) else None


def _resolve_url(ref, rel):
    """Direct download URL of a file in a pinned dataset revision."""
    return "%s/datasets/%s/resolve/%s/%s/%s" % (
        HF_URL, ref["repo"], ref["commit"], ref["package"], urllib.parse.quote(rel))


def _download_file(url, target, expected_size, force=False):
    """Download url to target through a .part file, so an interrupted run never leaves a half-written file.

    A file of the expected size is kept unless force is set (a forced download replaces it file by file,
    atomically, so a scene that uses the package never sees a half-written texture)."""
    if not force and expected_size is not None and os.path.isfile(target) and os.path.getsize(target) == expected_size:
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + ".part"
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT_SECONDS) as resp, open(part, "wb") as out:
        for chunk in iter(lambda: resp.read(CHUNK_BYTES), b""):
            out.write(chunk)
    if expected_size is not None and os.path.getsize(part) != expected_size:
        os.remove(part)
        raise IOError("Size mismatch for " + url)
    os.replace(part, target)


def download_file(url, target):
    """Download url to target without a size check; used for preview images whose size is not known upfront."""
    _download_file(url, target, None)


def thumbnail_urls(asset):
    """Candidate thumbnail URLs for asset, best first; packages ship them under .thumbs next to the root USD."""
    ref = asset["ref"]
    folder, name = os.path.split(ref["rel"])
    stem = os.path.splitext(name)[0]
    candidates = (".thumbs/256x256/%s_light.png" % name, ".thumbs/%s_thumbnail.png" % stem)
    return [_resolve_url(ref, "/".join(filter(None, [folder, tail]))) for tail in candidates]


def _thumbnail_path(asset, thumb_dir):
    """Cache file of the thumbnail; the commit hash keeps entries valid across dataset updates."""
    ref = asset["ref"]
    key = "%s__%s__%s.png" % (ref["repo"].replace("/", "__"), ref["commit"][:12], ref["package"])
    return os.path.join(thumb_dir, key)


def download_thumbnail(asset, thumb_dir):
    """Fetch the thumbnail into thumb_dir and return its path, or None when the package has none."""
    target = _thumbnail_path(asset, thumb_dir)
    if os.path.isfile(target):
        return target
    os.makedirs(thumb_dir, exist_ok=True)
    for url in thumbnail_urls(asset):
        try:
            _download_file(url, target, None)
            return target
        except OSError:
            continue
    return None


def download_thumbnails(assets, thumb_dir, on_ready):
    """Fetch thumbnails in parallel; on_ready(asset, path) is called from the calling thread per finished one."""
    with ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS) as pool:
        jobs = {pool.submit(download_thumbnail, asset, thumb_dir): asset for asset in assets}
        for job in as_completed(jobs):
            path = job.result()
            if path:
                on_ready(jobs[job], path)


def _download_job(ref, root, rel, size, force=False):
    """Download one manifest entry; skipped silently when the manifest path would escape root."""
    target = _safe_join(root, rel)
    if target is not None:
        _download_file(_resolve_url(ref, rel), target, size, force)


def package_root(asset, cache_dir):
    """Local folder that holds (or will hold) the package of asset."""
    ref = asset["ref"]
    return os.path.join(cache_dir, ref["repo"].replace("/", "__"), ref["commit"][:12], ref["package"])


def is_cached(asset, cache_dir):
    """True when the whole package was downloaded earlier (the marker is written only after the last file)."""
    root_usd = cached_root_usd(asset, cache_dir)  # HSimRCL: маркер без корневого USD не считается скачанным пакетом
    return os.path.isfile(os.path.join(package_root(asset, cache_dir), COMPLETE_MARKER)) and bool(root_usd) \
        and os.path.isfile(root_usd)


def cached_root_usd(asset, cache_dir):
    """Local path of the root USD of a cached package."""
    return _safe_join(package_root(asset, cache_dir), asset["ref"]["rel"])


def download_package(asset, cache_dir, progress=None, force=False):
    """Download the files of an asset package into cache_dir and return the local path of its root USD.

    force fetches every file again. The completion marker is removed first, so an interrupted forced
    download is not mistaken for a finished package.

    Files load in parallel because one HTTP stream is far slower than the link. progress, if given,
    is called as progress(done_files, total_files) from the calling thread after each finished file.
    """
    files = select_files(fetch_manifest(asset["path"]))
    root = package_root(asset, cache_dir)
    marker = os.path.join(root, COMPLETE_MARKER)
    if force and os.path.isfile(marker):
        os.remove(marker)
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        jobs = [pool.submit(_download_job, asset["ref"], root, rel, size, force) for rel, size in files]
        for done, job in enumerate(as_completed(jobs), start=1):
            job.result()  # re-raises the first download error
            if progress:
                progress(done, len(files))
    root_usd = _safe_join(root, asset["ref"]["rel"])
    if not root_usd or not os.path.isfile(root_usd):  # HSimRCL: манифест без корневого USD — пакет не готов
        raise OSError("the package has no root USD file: %s" % asset["ref"]["rel"])
    open(marker, "w").close()
    return root_usd
