#!/usr/bin/env python3
"""Pre-download the faster-whisper transcription model.

Honest note: faster-whisper fetches its model weights from HuggingFace the
first time a WhisperModel is created. This script just triggers that download
ahead of time (e.g. during a Docker build or server setup) so the first real
transcription isn't slow. Nothing is vendored here.

Usage:
    WHISPER_MODEL=large-v3 python scripts/download_models.py
    # or simply: python scripts/download_models.py   (defaults to large-v3)
"""
import os
import sys

MODEL = os.environ.get("WHISPER_MODEL", "large-v3")


def cache_dir():
    try:
        from huggingface_hub import constants

        return constants.HF_HUB_CACHE
    except Exception:
        return os.path.expanduser("~/.cache/huggingface")


def main():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "ERROR: faster-whisper is not installed. "
            "Install it first: pip install faster-whisper",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Downloading faster-whisper model '{MODEL}' from HuggingFace ...")
    print("(This happens once; afterwards the model is reused from the local cache.)")
    # Creating the model triggers the download on first use.
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    del model
    print(f"Model '{MODEL}' is ready.")
    print(f"Cache location: {cache_dir()}")


if __name__ == "__main__":
    main()
