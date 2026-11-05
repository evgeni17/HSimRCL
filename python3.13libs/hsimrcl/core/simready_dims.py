# SPDX-FileCopyrightText: 2026 Dead_wall
# SPDX-FileCopyrightText: 2026 EOK (Houdini port: package-relative imports)
# SPDX-License-Identifier: MIT
# Upstream: https://github.com/denwerdan-arch/SimRCL simready_lib/simready_dims.py @ 1150d3e
"""Size filter per axis (min / max in metres), with the site's range slider maths. No Cinema 4D imports.

The catalog site draws one row per axis: min field, two-thumb slider, max field. Its slider has 200 steps on a
cubic scale up to 100 m (value = 100 * (step / 200) ** 3), so most of the track covers the sizes most assets
have (a 1 m object sits at step 43). Here the max thumb rests at the right end while there is no maximum, so
an untouched slider reads as "everything" instead of two thumbs stacked at zero.
"""
AXES = ("x", "y", "z")
STEPS = 200
TOP_M = 100.0
NO_LIMIT = (None, None)


def empty():
    """No limit on any axis: ((min, max), ...) per axis, None = open."""
    return (NO_LIMIT,) * len(AXES)


def value_at(step):
    """Metres at a slider step (cubic scale)."""
    step = min(STEPS, max(0, step))
    return TOP_M * (step / STEPS) ** 3


def step_of(value):
    """Slider step of a size in metres (the inverse of value_at)."""
    if value is None or value <= 0:
        return 0
    return STEPS if value >= TOP_M else STEPS * (value / TOP_M) ** (1.0 / 3.0)


def rounded(value):
    """Size as the site shows it: 2 decimals below 1 m, 1 below 10 m, whole metres above."""
    digits = 2 if value < 1 else 1 if value < 10 else 0
    return round(value, digits)


def text(value):
    """Field text of a limit ('' when open)."""
    return "" if value is None else "%g" % rounded(value)


def parse(entry):
    """A typed limit: None for empty or 0 (no limit), else metres; raises ValueError on anything else."""
    cleaned = entry.strip().replace(",", ".").rstrip("m").strip()
    value = float(cleaned) if cleaned else 0.0
    if value < 0:
        raise ValueError(entry)
    return value or None


def clamp(low, high, edited):
    """(low, high) with low <= high; the side just edited ('min' or 'max') gives way, as on the site."""
    if low is None or high is None or low <= high:
        return low, high
    return (high, high) if edited == "min" else (low, low)


def from_steps(low_step, high_step):
    """(min, max) of slider steps; the left end means no minimum, the right end no maximum."""
    low = (rounded(value_at(low_step)) or None) if low_step > 0 else None  # a hair off zero rounds to no limit
    high = (rounded(value_at(high_step)) or None) if high_step < STEPS else None
    return low, high


def thumb_steps(limits):
    """(min step, max step) where the two thumbs are drawn."""
    low, high = limits
    return step_of(low), STEPS if high is None else step_of(high)


def set_axis(dims, axis, limits):
    """dims with axis 0..2 replaced by (min, max)."""
    return tuple(limits if index == axis else current for index, current in enumerate(dims))


def search_fields(dims):
    """Service filters: min_bbox_<axis> / max_bbox_<axis> for the limits that are set."""
    fields = {}
    for axis, (low, high) in zip(AXES, dims):
        if low:
            fields["min_bbox_" + axis] = low
        if high:
            fields["max_bbox_" + axis] = high
    return fields


def chip(axis, limits):
    """Filter chip text such as 'X 0.5-2 m', 'X >= 0.5 m' or 'X <= 2 m'; None when the axis is open."""
    low, high = limits
    name = AXES[axis].upper()
    if low and high:
        return "%s %s–%s m" % (name, text(low), text(high))
    if low:
        return "%s ≥ %s m" % (name, text(low))
    return "%s ≤ %s m" % (name, text(high)) if high else None


def active(dims):
    """True when any axis has a limit."""
    return any(low or high for low, high in dims)


# ---------------------------------------------------------------- row geometry (pixels)

LABEL_W, FIELD_W, GAP = 12, 46, 8


def row_parts(left, right):
    """{'label', 'min', 'track', 'max'}: x ranges of one axis row, the site's 12 / 46 / rest / 46 px grid."""
    label = (left, left + LABEL_W)
    low = (label[1] + GAP, label[1] + GAP + FIELD_W)
    high = (right - FIELD_W, right)
    return {"label": label, "min": low, "track": (low[1] + GAP + 6, high[0] - GAP - 6), "max": high}


def step_at(x, track):
    """Slider step under pixel x of the track (x1, x2)."""
    x1, x2 = track
    return round(STEPS * min(1.0, max(0.0, (x - x1) / float(max(1, x2 - x1)))))


def x_at(step, track):
    """Pixel x of a slider step."""
    x1, x2 = track
    return int(x1 + (x2 - x1) * step / STEPS)


def part_at(x, parts):
    """Which part of the row is under x: 'min', 'max', 'track' or None."""
    for name in ("min", "max"):
        if parts[name][0] <= x <= parts[name][1]:
            return name
    return "track" if parts["track"][0] - 8 <= x <= parts["track"][1] + 8 else None


def nearer_thumb(step, limits):
    """'min' or 'max': the thumb to move for a press at step (the nearer one; a tie goes by side)."""
    low, high = thumb_steps(limits)
    if abs(step - low) == abs(step - high):
        return "max" if step > low else "min"
    return "min" if abs(step - low) < abs(step - high) else "max"


def drag(limits, thumb, step):
    """(min, max) after dragging thumb to step; a thumb never passes the other one."""
    low_step, high_step = thumb_steps(limits)
    if thumb == "min":
        low_step = min(step, high_step)
    else:
        high_step = max(step, low_step)
    return from_steps(low_step, high_step)
