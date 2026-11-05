# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_library.py @ 1150d3e
"""The local library: which packages are already downloaded. No Cinema 4D imports.

A package folder is `<download dir>/<repo with / as __>/<commit, 12 chars>/<package>/` and holds a
`.complete` marker once the last file arrived (see simready_client.download_package). The same
package in a newer revision lives in another commit folder, so identity is (repo, package) and the
commit only tells whether the local copy is current.
"""
import os
import re

from . import simready_client

REPO_SEPARATOR = "__"
CURRENT, OUTDATED = "current", "outdated"
REGEXP_LIMIT = 850  # the service rejects filter_url_regexp longer than 1000 characters


def _subfolders(path):
    """Names of the folders directly inside path; an unreadable or missing path has none."""
    try:
        return [entry.name for entry in os.scandir(path) if entry.is_dir()]
    except OSError:
        return []


def _complete(package_dir):
    return os.path.isfile(os.path.join(package_dir, simready_client.COMPLETE_MARKER))


def scan(download_dir):
    """[{'repo', 'commit', 'package'}] for every fully downloaded package under download_dir."""
    found = []
    for repo_dir in _subfolders(download_dir):
        repo = repo_dir.replace(REPO_SEPARATOR, "/", 1)
        for commit in _subfolders(os.path.join(download_dir, repo_dir)):
            for package in _subfolders(os.path.join(download_dir, repo_dir, commit)):
                if _complete(os.path.join(download_dir, repo_dir, commit, package)):
                    found.append({"repo": repo, "commit": commit, "package": package})
    return found


def index(entries):
    """{(repo, package): {commits}} so a card can be looked up by what it is, not by its revision."""
    result = {}
    for entry in entries:
        result.setdefault((entry["repo"], entry["package"]), set()).add(entry["commit"])
    return result


def card_key(card):
    """(repo, package) of a card."""
    ref = card["asset"]["ref"]
    return ref["repo"], ref["package"]


def state(card, library):
    """None when the card is not downloaded, CURRENT when this exact revision is, otherwise OUTDATED."""
    commits = library.get(card_key(card))
    if not commits:
        return None
    commit = card["asset"]["ref"]["commit"]
    return CURRENT if any(commit.startswith(local) for local in commits) else OUTDATED


def regexp_chunks(library, limit=REGEXP_LIMIT):
    """URL regular expressions that together match every package in library, each short enough for the service."""
    names = sorted({package for _, package in library})
    chunks, current, size = [], [], 0
    for name in names:
        escaped = re.escape(name)
        if current and size + len(escaped) + 1 > limit:
            chunks.append(current)
            current, size = [], 0
        current.append(escaped)
        size += len(escaped) + 1
    chunks.append(current) if current else None
    return [".*/resolve/[0-9a-f]+/(%s)/.*" % "|".join(chunk) for chunk in chunks]


def keep_downloaded(cards, library):
    """Cards that are in the library, without duplicates (chunks of one search can overlap)."""
    seen, kept = set(), []
    for card in cards:
        if card["key"] in seen or card_key(card) not in library:
            continue
        seen.add(card["key"])
        kept.append(card)
    return kept
