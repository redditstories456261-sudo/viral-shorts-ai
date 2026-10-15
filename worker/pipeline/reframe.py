"""Crop planning for 1080x1920 vertical reframing.

``plan_crop`` turns a (possibly sparse) speaker track into a per-frame list of
source-pixel crop boxes. Sparse tracks are linearly interpolated to every
frame; when the track is empty the crop is a static centered box (the
caller's fallback).

Modes:
    "single" - one 9:16 box per frame following the smoothed face center,
               with headroom (face top ~25% down from the top of the frame).
    "two"    - two stacked panels tiling the tracked 9:16 region; panel 0
               contains the speaker, panel 1 the scene band below.
    "three"  - three stacked panels; panel 0 contains the speaker.
               The caller composites the panels into 1080x1920.
"""

from __future__ import annotations

OUT_W, OUT_H = 1080, 1920
TARGET_ASPECT = 9.0 / 16.0
HEADROOM_TOP = 0.25  # face top sits ~25% down from the top of the crop
MIN_CROP_W = 240


def _base_crop_box(src_w: int, src_h: int) -> tuple[int, int]:
    """Largest 9:16 box that fits the source, with a minimum-size guard."""
    crop_w = int(src_h * TARGET_ASPECT)
    crop_h = src_h
    if crop_w > src_w:
        crop_w = src_w
        crop_h = int(src_w / TARGET_ASPECT)
    crop_w = max(MIN_CROP_W, crop_w)
    crop_h = int(crop_w / TARGET_ASPECT)
    if crop_h > src_h:
        crop_h = src_h
        crop_w = int(crop_h * TARGET_ASPECT)
    return min(crop_w, src_w), min(crop_h, src_h)


def _interpolate_track(
    track: dict[int, tuple[float, float, float, float]], total_frames: int
) -> list[tuple[float, float, float, float] | None]:
    """Expand a sparse ``{frame_idx: (cx,cy,w,h)}`` track to every frame."""
    keys = sorted(track)
    if not keys:
        return [None] * total_frames
    out: list[tuple[float, float, float, float] | None] = []
    for f in range(total_frames):
        if f <= keys[0]:
            out.append(track[keys[0]])
        elif f >= keys[-1]:
            out.append(track[keys[-1]])
        else:
            for i in range(len(keys) - 1):
                a, b = keys[i], keys[i + 1]
                if a <= f <= b:
                    t = (f - a) / (b - a)
                    va, vb = track[a], track[b]
                    out.append(tuple(x + (y - x) * t for x, y in zip(va, vb)))
                    break
    return out


def _clamp_box(
    x: float, y: float, w: int, h: int, src_w: int, src_h: int
) -> tuple[int, int, int, int]:
    x = min(max(0.0, x), float(src_w - w))
    y = min(max(0.0, y), float(src_h - h))
    return int(round(x)), int(round(y)), int(w), int(h)


def plan_crop(
    track: dict[int, tuple[float, float, float, float]],
    src_w: int,
    src_h: int,
    fps: float,
    total_frames: int,
    mode: str = "single",
) -> list:
    """Plan per-frame crop boxes for ``total_frames`` frames.

    ``track`` maps frame index -> smoothed ``(cx, cy, w, h)`` in normalized
    coords (see ``faces.pick_speaker_track``); may be sparse or empty.
    ``fps`` is accepted for API symmetry with the sampler and validated.
    """
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    if total_frames <= 0:
        raise ValueError(f"total_frames must be positive, got {total_frames}")

    crop_w, crop_h = _base_crop_box(src_w, src_h)
    interp = _interpolate_track(track or {}, total_frames)

    frames: list[tuple[int, int, int, int]] = []
    for entry in interp:
        if entry is None:
            # No face data: static, centered, slight upward bias.
            x = (src_w - crop_w) / 2.0
            y = max(0.0, (src_h - crop_h) / 2.0 - 0.08 * crop_h)
        else:
            cx, cy, _w, h = entry
            fx = cx * src_w
            fy = cy * src_h
            face_top = fy - (h * src_h) / 2.0
            x = fx - crop_w / 2.0
            y = face_top - HEADROOM_TOP * crop_h
        frames.append(_clamp_box(x, y, crop_w, crop_h, src_w, src_h))

    if mode == "single":
        return frames
    if mode not in ("two", "three"):
        raise ValueError(f"unknown reframe mode: {mode!r}")

    k = 2 if mode == "two" else 3
    panels: list[list[tuple[int, int, int, int]]] = []
    for (x, y, w, h) in frames:
        ph = h // k
        rects = []
        for i in range(k):
            last_h = h - (k - 1) * ph if i == k - 1 else ph
            rects.append((x, y + i * ph, w, last_h))
        panels.append(rects)
    return panels
