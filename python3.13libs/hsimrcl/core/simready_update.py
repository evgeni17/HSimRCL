# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_update.py @ 1150d3e
"""Is a newer SimRCL released? Asks GitHub's releases API, at most once a day. No Cinema 4D imports.

The repository is public, so the check needs no account: one anonymous request to the "latest release"
endpoint (GitHub allows 60 an hour per address). The answer is kept in the settings with the time of the
check, so opening the window several times a day costs nothing and a failed check keeps the last answer.
"""
import json
import re
import urllib.request

REPO = "denwerdan-arch/SimRCL"
LATEST_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_PAGE = "https://github.com/%s/releases/latest" % REPO
CHECK_INTERVAL_SECONDS = 24 * 3600
TIMEOUT_SECONDS = 10
NOTES_CHARS = 300
_VERSION = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


def parse_version(text):
    """'v1.2.0' or '1.2' -> (1, 2, 0); None for anything else (a tag such as 'nightly')."""
    match = _VERSION.match((text or "").strip())
    return tuple(int(part or 0) for part in match.groups()) if match else None


def is_newer(remote, local):
    """True when version text remote is later than local; unparsable versions never count as newer."""
    theirs, ours = parse_version(remote), parse_version(local)
    return bool(theirs and ours and theirs > ours)


def release_info(answer):
    """{'version', 'url', 'zip', 'notes'} from a GitHub release JSON; None for drafts, pre-releases or junk."""
    if not isinstance(answer, dict) or answer.get("draft") or answer.get("prerelease"):
        return None
    version = parse_version(answer.get("tag_name"))
    if version is None:
        return None
    zips = [a.get("browser_download_url") for a in answer.get("assets") or [] if str(a.get("name", "")).endswith(".zip")]
    return {"version": ".".join(map(str, version)), "url": answer.get("html_url") or RELEASES_PAGE,
            "zip": zips[0] if zips else None, "notes": (answer.get("body") or "").strip()[:NOTES_CHARS]}


def due(last_check, now, interval=CHECK_INTERVAL_SECONDS):
    """True when the last check is older than interval (or never happened, or lies in the future)."""
    return not isinstance(last_check, (int, float)) or not 0 <= now - last_check < interval


def fetch_latest():
    """The latest release of the repository as release_info; raises OSError / ValueError on failure."""
    request = urllib.request.Request(LATEST_URL, headers={"User-Agent": "SimRCL-update-check",
                                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
        return release_info(json.loads(resp.read()))


def check(local_version, state, now, force=False, fetch=fetch_latest):
    """(newer release or None, new state, error text or None).

    state is what the last call returned ({'last_check': time, 'latest': release_info}); it comes back
    unchanged while a check is not due. A failed request keeps the cached answer and reports the error.
    """
    state = dict(state) if isinstance(state, dict) else {}
    if force or due(state.get("last_check"), now):
        try:
            state = {"last_check": now, "latest": fetch()}
        except (OSError, ValueError) as error:
            return _newer(state.get("latest"), local_version), state, str(error)[:200]
    return _newer(state.get("latest"), local_version), state, None


def _newer(info, local_version):
    return info if info and is_newer(info.get("version"), local_version) else None
