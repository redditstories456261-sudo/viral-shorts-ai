"""Audio extraction and energy analysis.

Uses the system ``ffmpeg`` binary (via subprocess) and the stdlib ``wave``
module + numpy only -- no librosa dependency.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import wave

import numpy as np

log = logging.getLogger(__name__)


def _require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise RuntimeError(
            "ffmpeg binary not found on PATH. It must be installed on the GPU "
            "worker image (Dockerfile.gpu, infra-owned), e.g. "
            "`apt-get install -y ffmpeg`."
        )
    return path


def extract_audio(video_path: str, out_wav: str) -> str:
    """Extract audio from ``video_path`` to 16 kHz mono WAV via ffmpeg."""
    _require_ffmpeg()
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        out_wav,
    ]
    log.info("extracting audio: %s -> %s", video_path, out_wav)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {proc.stderr[-2000:]}")
    return out_wav


def audio_energy(wav_path: str, frame_sec: float = 0.5) -> list[tuple[float, float]]:
    """Compute per-frame RMS energy of a WAV file.

    Returns a list of ``(t_seconds, rms)`` tuples, one per ``frame_sec`` window.
    Pure numpy over stdlib-decoded PCM -- no librosa.
    """
    with wave.open(wav_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sampwidth)
    if dtype is None:
        raise ValueError(f"unsupported WAV sample width: {sampwidth} bytes")
    audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    audio /= float(2 ** (8 * sampwidth - 1))
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    frame_len = max(1, int(frame_sec * framerate))
    out: list[tuple[float, float]] = []
    for start in range(0, len(audio), frame_len):
        chunk = audio[start : start + frame_len]
        if chunk.size == 0:
            break
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        out.append((round(start / framerate, 3), rms))
    return out
