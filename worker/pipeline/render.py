"""Final render: per-segment constant crops + ASS captions -> 1080x1920 MP4.

Honest approach to per-frame camera movement with plain ffmpeg: the clip is
split into short segments (default 2 s); within each segment the crop box is
constant (averaged from the per-frame crop plan), and the segments are
trimmed/cropped/scaled independently, concatenated, then captioned with
libass. ``h264_nvenc`` is preferred when ``codec="auto"`` and the ffmpeg
binary actually exposes the encoder (checked at runtime via
``ffmpeg -encoders``); otherwise libx264 is used.

The per-frame crop plan is passed as a JSON file (``crop_per_frame_file``)::

    {"fps": 30.0, "src_w": 1920, "src_h": 1080, "duration": 32.5,
     "crops": [[x, y, w, h], ...]}   # one entry per frame
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)

CHUNK_SEC = 2.0
OUT_W, OUT_H = 1080, 1920


def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise RuntimeError(
            "ffmpeg binary not found on PATH. It must be installed on the GPU "
            "worker image (Dockerfile.gpu, infra-owned) with libass and (for "
            "GPU encoding) nvenc support, e.g. via the johnvansickle static "
            "build or `apt-get install -y ffmpeg`."
        )
    return path


_nvenc_available: bool | None = None


def _has_nvenc() -> bool:
    """Check at runtime whether this ffmpeg binary exposes h264_nvenc."""
    global _nvenc_available
    if _nvenc_available is None:
        _require_ffmpeg()
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        _nvenc_available = "h264_nvenc" in proc.stdout
        log.info("ffmpeg nvenc available: %s", _nvenc_available)
    return _nvenc_available


def _even(n: float) -> int:
    return max(2, int(round(n)) // 2 * 2)


def _clamp_crop(
    x: float, y: float, w: float, h: float, src_w: int, src_h: int
) -> tuple[int, int, int, int]:
    """Clamp a crop box inside the source and force even dimensions/offsets
    (required for yuv420p)."""
    w = _even(min(w, src_w))
    h = _even(min(h, src_h))
    x = _even(min(max(0.0, x), src_w - w))
    y = _even(min(max(0.0, y), src_h - h))
    return x, y, w, h


def _escape_ass_path(path: str) -> str:
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace(":", "\\:").replace("'", "\\'")
    return f"'{p}'"


def _load_crop_plan(crop_per_frame_file: str):
    with open(crop_per_frame_file, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    return (
        float(plan["fps"]),
        int(plan["src_w"]),
        int(plan["src_h"]),
        float(plan["duration"]),
        plan["crops"],
    )


def build_ffmpeg_cmd(
    src: str,
    dst: str,
    crop_per_frame_file: str,
    ass_path: str,
    codec: str = "auto",
    crf: int = 20,
) -> list[str]:
    """Build the real ffmpeg command rendering the vertical clip."""
    _require_ffmpeg()  # fail fast with a clear error before doing any work
    fps, src_w, src_h, duration, crops = _load_crop_plan(crop_per_frame_file)
    if not crops:
        raise ValueError("crop plan is empty")
    if duration <= 0:
        raise ValueError(f"invalid clip duration: {duration}")

    # -- chunk boundaries (constant crop per chunk) -------------------------
    bounds = [0.0]
    t = CHUNK_SEC
    while t < duration - 1e-6:
        bounds.append(round(t, 3))
        t += CHUNK_SEC
    bounds.append(round(duration, 3))

    chunks: list[tuple[float, float, int, int, int, int]] = []
    for i in range(len(bounds) - 1):
        ts, te = bounds[i], bounds[i + 1]
        f0 = int(ts * fps)
        f1 = max(f0 + 1, min(len(crops), int(round(te * fps))))
        seg = crops[f0:f1]
        ax = sum(c[0] for c in seg) / len(seg)
        ay = sum(c[1] for c in seg) / len(seg)
        aw = sum(c[2] for c in seg) / len(seg)
        ah = sum(c[3] for c in seg) / len(seg)
        x, y, w, h = _clamp_crop(ax, ay, aw, ah, src_w, src_h)
        chunks.append((ts, te, x, y, w, h))

    # -- filter_complex -------------------------------------------------------
    parts: list[str] = []
    for i, (ts, te, x, y, w, h) in enumerate(chunks):
        parts.append(
            f"[0:v]trim=start={ts}:end={te},setpts=PTS-STARTPTS,"
            f"crop={w}:{h}:{x}:{y},scale={OUT_W}:{OUT_H}:flags=lanczos,"
            f"setsar=1[v{i}]"
        )
        parts.append(
            f"[0:a]atrim=start={ts}:end={te},asetpts=PTS-STARTPTS,"
            f"aresample=48000[a{i}]"
        )
    v_ins = "".join(f"[v{i}]" for i in range(len(chunks)))
    a_ins = "".join(f"[a{i}]" for i in range(len(chunks)))
    parts.append(f"{v_ins}{a_ins}concat=n={len(chunks)}:v=1:a=1[vcat][acat]")
    parts.append(f"[vcat]ass={_escape_ass_path(ass_path)}[vout]")
    filter_complex = ";".join(parts)

    # -- encoder selection ------------------------------------------------------
    if codec == "auto":
        enc = "h264_nvenc" if _has_nvenc() else "libx264"
    elif codec in ("h264_nvenc", "libx264"):
        enc = codec
    else:
        raise ValueError(
            f"unsupported codec {codec!r}; expected 'auto', 'h264_nvenc' or 'libx264'"
        )
    if enc == "h264_nvenc":
        vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(crf)]
    else:
        vcodec = ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]

    cmd = (
        ["ffmpeg", "-y", "-i", src, "-filter_complex", filter_complex,
         "-map", "[vout]", "-map", "[acat]"]
        + vcodec
        + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-movflags", "+faststart", "-s", f"{OUT_W}x{OUT_H}", dst]
    )
    log.info(
        "built ffmpeg cmd: encoder=%s chunks=%d duration=%.1fs",
        enc, len(chunks), duration,
    )
    return cmd


def run(cmd: list[str]):
    """Run a command, raising with an stderr tail on nonzero exit."""
    log.info("running ffmpeg (%d args)", len(cmd))
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited with code {proc.returncode}: {proc.stderr[-3000:]}"
        )
    return proc
