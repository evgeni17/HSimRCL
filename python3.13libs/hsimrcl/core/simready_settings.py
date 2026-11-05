# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports, macOS settings paths)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_settings.py @ 1150d3e
"""User settings kept in a small JSON file. No Cinema 4D imports.

The file lives in a fixed per-user location, never inside the download folder: the folder is what the user moves.
"""
import json
import os
import shutil
import sys
import uuid

APP_NAME = "SRC by Deadwall"  # legacy name of the data folders, kept so existing downloads and settings are found
DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Documents", APP_NAME, "Assets")
# HSimRCL: на macOS нет APPDATA — настройки в ~/Library/Application Support, а не в корне домашней папки
_MAC_SUPPORT = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
_CONFIG_BASE = os.environ.get("APPDATA") or (_MAC_SUPPORT if sys.platform == "darwin" else os.path.expanduser("~"))
_LOCAL_BASE = os.environ.get("LOCALAPPDATA") or _CONFIG_BASE
SETTINGS_PATH = os.path.join(_CONFIG_BASE, APP_NAME, "settings.json")
# The private USD runtime (usd-core) lives outside Temp: Windows' temp clean-up deleted its .py files while the
# locked .pyd stayed, which left a "pxr" folder that imports but has no Usd.Stage.
RUNTIME_DIR = os.path.join(_LOCAL_BASE, APP_NAME, "usd_runtime")
DOWNLOAD_KEY = "download_dir"
TIDY_KEY = "tidy_hierarchy"
TARGET_KEY = "material_target"
OPENPBR_KEY = "prefer_openpbr"
AUTO_TARGET = "auto"
RIG_KEY = "rig_controls"
VIDEO_KEY = "video_preview"
PHONG_KEY = "area_weighted_phong"
SPLIT_KEY = "split_multi_material"
LAYERS_KEY = "asset_layers"
ROUND_KEY = "round_corners"
UPDATES_KEY = "check_updates"
UPDATE_STATE_KEY = "update_state"  # {last_check, latest}: the last answer of simready_update.check


def load(path=SETTINGS_PATH):
    """Settings dict; a missing or damaged file means defaults (the damaged file is overwritten on the next save)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(settings, path=SETTINGS_PATH):
    """Write settings through a temporary file so a crash never leaves half a JSON document. Returns an error text or ''."""
    temporary = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
        os.replace(temporary, path)
    except OSError as error:
        return str(error)
    return ""


def download_dir(settings):
    """The folder for downloaded packages: the custom one when set, otherwise the default."""
    custom = settings.get(DOWNLOAD_KEY)
    return custom if isinstance(custom, str) and custom else DEFAULT_DOWNLOAD_DIR


def tidy_enabled(settings):
    """Whether imports remove the USD importer's clutter; on unless the user switched it off."""
    return settings.get(TIDY_KEY, True) is not False


def with_tidy(settings, enabled):
    """Copy of settings with the tidy-on-import switch set."""
    return dict(settings, **{TIDY_KEY: bool(enabled)})


def rig_enabled(settings):
    """Whether moving parts get animation controls on import; on unless the user switched it off."""
    return settings.get(RIG_KEY, True) is not False


def with_rig(settings, enabled):
    """Copy of settings with the rig-controls switch set."""
    return dict(settings, **{RIG_KEY: bool(enabled)})


def phong_enabled(settings):
    """Whether imported meshes get Area Weighted Phong normals; on unless switched off."""
    return settings.get(PHONG_KEY, True) is not False


def split_enabled(settings):
    """Whether a one-mesh model with separate parts per material is split into one object per material; on by default."""
    return settings.get(SPLIT_KEY, True) is not False


def layers_enabled(settings):
    """Whether every imported asset and its materials go on a layer of their own; on by default."""
    return settings.get(LAYERS_KEY, True) is not False


def round_enabled(settings):
    """Whether imports get render-time round corners controls (off on the model until switched on); on by default."""
    return settings.get(ROUND_KEY, True) is not False


def updates_enabled(settings):
    """Whether the window asks GitHub for a newer release when it opens (once a day); on by default."""
    return settings.get(UPDATES_KEY, True) is not False


def update_state(settings):
    """The cached answer of the last update check, {} when there was none."""
    state = settings.get(UPDATE_STATE_KEY)
    return state if isinstance(state, dict) else {}


def with_flag(settings, key, enabled):
    """Copy of settings with the boolean switch key set."""
    return dict(settings, **{key: bool(enabled)})


def video_enabled(settings):
    """Whether hovering a card plays its clip; off unless switched on (clips download on hover and cost time)."""
    return settings.get(VIDEO_KEY, False) is True


def with_video(settings, enabled):
    """Copy of settings with the video-preview switch set."""
    return dict(settings, **{VIDEO_KEY: bool(enabled)})


def material_target(settings, allowed=()):
    """The renderer the materials are built for: a stored value from allowed, otherwise 'auto' (the document's renderer)."""
    stored = settings.get(TARGET_KEY)
    return stored if stored in allowed else AUTO_TARGET


def with_material_target(settings, target):
    """Copy of settings with the material renderer set; 'auto' removes the override."""
    updated = {key: value for key, value in settings.items() if key != TARGET_KEY}
    if target and target != AUTO_TARGET:
        updated[TARGET_KEY] = target
    return updated


def prefer_openpbr(settings):
    """Whether OpenPBR shaders are used where the renderer has them; on unless the user switched it off."""
    return settings.get(OPENPBR_KEY, True) is not False


def with_openpbr(settings, enabled):
    """Copy of settings with the OpenPBR preference set."""
    return dict(settings, **{OPENPBR_KEY: bool(enabled)})


def is_default(settings):
    """True while no custom download folder is set."""
    return download_dir(settings) == DEFAULT_DOWNLOAD_DIR


def check_folder(path):
    """Empty string when path can hold downloads, otherwise a short reason. Creates the folder when it is missing."""
    if not path or not os.path.isabs(path):
        return "Choose a full folder path"
    probe = os.path.join(path, ".src_write_test_" + uuid.uuid4().hex[:8])
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "wb"):
            pass
        os.remove(probe)
    except OSError as error:
        return "Cannot write to this folder (%s)" % (error.strerror or error)
    return ""


def free_bytes(path):
    """Free space of the drive that holds path (or its nearest existing parent); None when unknown."""
    probe = path
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            return None
        probe = parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def with_download_dir(settings, path):
    """Copy of settings with the download folder set; an empty path (or the default one) removes the override."""
    updated = {key: value for key, value in settings.items() if key != DOWNLOAD_KEY}
    if path and os.path.normcase(os.path.normpath(path)) != os.path.normcase(os.path.normpath(DEFAULT_DOWNLOAD_DIR)):
        updated[DOWNLOAD_KEY] = os.path.normpath(path)
    return updated
