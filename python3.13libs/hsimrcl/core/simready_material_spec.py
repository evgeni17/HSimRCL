# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_material_spec.py @ 1150d3e
"""Backend-independent view of an inspected UsdPreviewSurface material. No Cinema 4D imports.

simready_inspect describes a material with USD names (diffuseColor, emissiveColor, ...). Every renderer
backend works from the same flat description: one entry per slot, either a constant or a texture.
"""
BASE_COLOR, METALLIC, ROUGHNESS, NORMAL, EMISSION, OPACITY = (
    "base_color", "metallic", "roughness", "normal", "emission", "opacity")
USD_SLOTS = {"diffuseColor": BASE_COLOR, "metallic": METALLIC, "roughness": ROUGHNESS,
             "normal": NORMAL, "emissiveColor": EMISSION, "opacity": OPACITY}
OPAQUE_FROM = 0.999  # a constant opacity of 1 is the default of every shader, so it is not written
UDIM_TOKEN = "<UDIM>"
EMISSION_STRENGTH_CAP = 10.0


def is_black(value):
    """True for a colour or scalar whose components are all zero."""
    parts = value if isinstance(value, list) else [value]
    return all(part == 0 for part in parts)


def keep(slot, entry):
    """Whether a slot is worth writing: constant emission must glow, constant opacity must be see-through."""
    if "texture" in entry:
        return True
    if slot == EMISSION:
        return not is_black(entry["value"])
    if slot == OPACITY:
        return entry["value"] < OPAQUE_FROM
    return True


def normalized_emission(entry):
    """Split an authored emission into a colour with peak 1 and a strength.

    SimReady stores emission in physical units (values such as 40 or 3000), which would blow every renderer's
    glow out of range; the colour keeps the hue and the strength is capped to a value that still reads as a glow.
    """
    if "texture" in entry:
        return dict(entry, strength=1.0)
    rgb = as_rgb(entry["value"])
    peak = max(rgb)
    return {"value": [part / peak for part in rgb], "strength": min(peak, EMISSION_STRENGTH_CAP)}


def slots(spec):
    """{slot: {'texture': {...}} or {'value': ...}} for the inputs of one material description."""
    found = {USD_SLOTS[name]: entry for name, entry in spec.items() if name in USD_SLOTS}
    kept = {slot: entry for slot, entry in found.items() if keep(slot, entry)}
    return {slot: normalized_emission(entry) if slot == EMISSION else entry for slot, entry in kept.items()}


def emission_strength(slots_map):
    """The strength of the emission slot (1 when absent)."""
    return slots_map.get(EMISSION, {}).get("strength", 1.0)


def has_udim(texture):
    """True when the texture path is a tile template (<UDIM>)."""
    return UDIM_TOKEN in (texture.get("file") or "")


def uv_scale(texture):
    """(s, t) tiling of a texture; (1, 1) when it has no UV transform."""
    transform = texture.get("uv") or {}
    scale = transform.get("scale") or [1.0, 1.0]
    return float(scale[0]), float(scale[1])


def material_uv_scale(spec):
    """(s, t) tiling of a whole material: the value most of its textures use (a material is tiled as one), or
    None when it has no textures. Ties go to the base colour's scale, the one the eye judges the size by."""
    textures = {name: entry["texture"] for name, entry in spec.items() if isinstance(entry, dict) and entry.get("texture")}
    if not textures:
        return None
    scales = [uv_scale(texture) for texture in textures.values()]
    counted = sorted(set(scales), key=lambda scale: (-scales.count(scale), scale != uv_scale(textures.get("diffuseColor", {}))))
    return counted[0]


def uv_offset(texture):
    """(s, t) offset of a texture; (0, 0) when it has no UV transform."""
    transform = texture.get("uv") or {}
    offset = transform.get("translation") or [0.0, 0.0]
    return float(offset[0]), float(offset[1])


def as_rgb(value):
    """First three components of a colour value as floats; a scalar becomes a grey."""
    parts = value if isinstance(value, list) else [value] * 3
    return [float(part) for part in parts[:3]]


def channel_index(texture):
    """0, 1 or 2 for the r, g or b channel a scalar slot reads; None for a colour texture."""
    return {"r": 0, "g": 1, "b": 2}.get(texture.get("channel"))
