"""Real face detection and speaker tracking with MediaPipe.

Uses ``mediapipe.solutions.face_detection`` (short-range model) for broad
compatibility. Coordinates are normalized (0..1) relative to frame size.
Callers fall back to a center crop when no persistent face is found.
"""

from __future__ import annotations

import logging
import math

import mediapipe as mp

log = logging.getLogger(__name__)

_detector = None


def _get_detector(min_confidence: float = 0.5):
    global _detector
    if _detector is None:
        _detector = mp.solutions.face_detection.FaceDetection(
            model_selection=0, min_detection_confidence=min_confidence
        )
    return _detector


def detect_faces_bgr(frame) -> list[dict]:
    """Detect faces in a BGR (OpenCV) frame.

    Returns ``[{x, y, w, h, confidence}]`` with normalized coordinates.
    Empty list when no face is detected.
    """
    import cv2  # local import: keeps this module importable without cv2

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = _get_detector().process(rgb)
    faces: list[dict] = []
    if result.detections:
        for det in result.detections:
            bb = det.location_data.relative_bounding_box
            conf = float(det.score[0]) if det.score else 0.0
            faces.append(
                {
                    "x": max(0.0, float(bb.xmin)),
                    "y": max(0.0, float(bb.ymin)),
                    "w": float(bb.width),
                    "h": float(bb.height),
                    "confidence": conf,
                }
            )
    return faces


def _face_score(det: dict) -> float:
    """Largest * most-central face wins: area weighted by centrality."""
    cx = det["x"] + det["w"] / 2.0
    cy = det["y"] + det["h"] / 2.0
    centrality = 1.0 - min(1.0, math.hypot(cx - 0.5, cy - 0.5) * 1.2)
    return det["w"] * det["h"] * (0.5 + 0.5 * centrality)


def _as_cxcywh(det: dict) -> tuple[float, float, float, float]:
    return (
        det["x"] + det["w"] / 2.0,
        det["y"] + det["h"] / 2.0,
        det["w"],
        det["h"],
    )


def smooth_tracks(
    detections_by_frame: dict[int, list[dict]], alpha: float = 0.35
) -> dict[int, tuple[float, float, float, float]]:
    """EMA-smooth the primary (largest, most central) face across frames.

    Input maps frame index -> detections from :func:`detect_faces_bgr`.
    Output maps frame index -> smoothed ``(cx, cy, w, h)`` in normalized
    coords. Frames without detections are skipped (last state carries over).
    """
    track: dict[int, tuple[float, float, float, float]] = {}
    state: tuple[float, float, float, float] | None = None
    for f in sorted(detections_by_frame):
        dets = detections_by_frame[f]
        if not dets:
            continue
        cur = _as_cxcywh(max(dets, key=_face_score))
        if state is None:
            state = cur
        else:
            state = tuple(c * alpha + s * (1.0 - alpha) for c, s in zip(cur, state))
        track[f] = state
    return track


def pick_speaker_track(
    detections_by_frame: dict[int, list[dict]], min_presence: float = 0.3
) -> dict[int, tuple[float, float, float, float]]:
    """Choose the speaker track: largest, most central, persistent face.

    Persistence is measured as the fraction of sampled frames (over the span
    from first to last sampled frame) in which a face was detected. Returns
    the EMA-smoothed track, or ``{}`` when no face persists -- the caller
    must then fall back to a center crop.
    """
    if not detections_by_frame:
        return {}
    frames = sorted(detections_by_frame)
    primaries: dict[int, list[dict]] = {}
    for f in frames:
        dets = detections_by_frame[f]
        if dets:
            primaries[f] = [max(dets, key=_face_score)]
    if not primaries:
        return {}
    span = max(1, frames[-1] - frames[0] + 1)
    presence = len(primaries) / span
    if presence < min_presence:
        log.info(
            "face presence %.2f below threshold %.2f; using center-crop fallback",
            presence,
            min_presence,
        )
        return {}
    log.info("speaker track selected: presence=%.2f over %d sampled frames", presence, len(primaries))
    return smooth_tracks(primaries)
