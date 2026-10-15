"""Speech transcription with faster-whisper (real inference, GPU when available)."""

from __future__ import annotations

import logging

import torch
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)


def _select_device(explicit: str = "") -> str:
    if explicit:
        return explicit
    return "cuda" if torch.cuda.is_available() else "cpu"


def transcribe_audio(
    audio_path: str,
    model_size: str,
    language: str,
    device: str = "",
) -> dict:
    """Transcribe ``audio_path`` with faster-whisper.

    Returns ``{"language": str, "segments": [...], "words": [...]}`` where
    segments are ``{start, end, text}`` and words are ``{word, start, end}``.
    ``language="auto"`` lets Whisper detect the language (passed as None).
    """
    device = _select_device(device)
    compute_type = "float16" if device == "cuda" else "int8"

    if device == "cuda":
        name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        log.info("transcribe device=cuda gpu='%s' vram=%.1fGB model=%s", name, vram_gb, model_size)
    else:
        log.info("transcribe device=cpu (no CUDA device found) model=%s", model_size)

    lang = None if language == "auto" else language

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        audio_path,
        language=lang,
        word_timestamps=True,
        vad_filter=True,
    )

    segments: list[dict] = []
    words: list[dict] = []
    for seg in segments_iter:
        segments.append(
            {"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()}
        )
        if seg.words:
            for w in seg.words:
                words.append(
                    {"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
                )

    detected = info.language or (lang or "auto")
    log.info(
        "transcription complete: language=%s segments=%d words=%d",
        detected,
        len(segments),
        len(words),
    )
    return {"language": detected, "segments": segments, "words": words}
