"""Shared pytest fixtures for the Viral Shorts AI test-suite.

IMPORTANT: environment isolation happens at the top of this file, BEFORE any
`backend.*` / `worker.*` / `shared.*` module is imported.  `shared.config`
reads settings at import time via pydantic-settings, so the env vars below
must be in place before the first app import (which happens in the test
modules, i.e. after conftest is loaded).
"""

import contextlib
import math
import os
import sys
from unittest import mock

# ---------------------------------------------------------------------------
# sys.path: make `worker.*`, `backend.*`, `shared.*` importable from the repo
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Test isolation: point every external dependency at throwaway test targets.
# ---------------------------------------------------------------------------
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite:////tmp/test_viral_shorts.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
# shared.config field names (pydantic-settings, case-insensitive):
os.environ["S3_ENDPOINT"] = "http://localhost:9000"
os.environ["S3_BUCKET"] = "test-bucket"
os.environ["S3_ACCESS_KEY"] = "test"
os.environ["S3_SECRET_KEY"] = "test"
os.environ["UPLOAD_TMP_DIR"] = "/tmp/test_uploads"
os.environ["WHISPER_MODEL"] = "tiny"  # fastest model; tests never transcribe anyway

# Fresh sqlite file on every pytest run so tests never see stale rows.
_DB_PATH = "/tmp/test_viral_shorts.db"
if os.path.exists(_DB_PATH):
    os.remove(_DB_PATH)

import pytest  # noqa: E402  (import after env setup is intentional)


# ---------------------------------------------------------------------------
# Sample media fixtures
# ---------------------------------------------------------------------------

# A 3-minute fake courtroom transcript.  Deliberately contains:
#   * questions  -> exercise the "question" scoring component
#   * exclamations / emotional outbursts -> exercise emotion + energy spikes
_COURTROOM_SCRIPT = [
    "The court will now come to order.",
    "Prosecution, you may call your first witness.",
    "The state calls Ms. Alvarez to the stand.",
    "Do you swear to tell the truth, the whole truth, and nothing but the truth?",
    "I do.",
    "Ms. Alvarez, where were you on the night of March 14th?",
    "I was at home, alone, watching television.",
    "Alone? No one can confirm that, can they?",
    "Objection, your honor! Badgering the witness!",
    "Sustained. Rephrase the question, counselor.",
    "Let me ask you again. Who else was in the house that night?",
    "No one. I already told you, no one was there!",
    "Your honor, the witness is clearly hiding something!",
    "Counselor, you will address the court, not the gallery!",
    "I apologize, your honor.",
    "Ms. Alvarez, did you hear anything unusual around midnight?",
    "Yes. I heard glass breaking downstairs.",
    "And what did you do when you heard that sound?",
    "I froze. I was terrified!",
    "Did you call the police?",
    "Not right away. I hid in the closet first.",
    "You hid? For how long?",
    "I don't know! Maybe twenty minutes! I was shaking!",
    "Objection! The witness is speculating!",
    "Overruled. The witness may answer.",
    "Thank you, your honor.",
    "Then what happened? Tell the court exactly what you saw.",
    "I saw a shadow move across the hallway.",
    "A shadow? Could it have been a tree outside the window?",
    "No! It was a person! I know what I saw!",
    "How can you be so sure in the dark?",
    "Because he walked straight toward my bedroom door!",
    "Order in the court! The gallery will remain silent!",
    "I am sorry, I cannot do this anymore!",
    "Ms. Alvarez, please. Take a breath. We need your testimony.",
    "Did the intruder say anything to you?",
    'He whispered, "do not scream."',
    "Those exact words? Do not scream?",
    "Yes. I will never forget that voice!",
    "And then he left through the back door, correct?",
    "Yes. And I finally called nine one one.",
    "No further questions, your honor.",
    "The defense may cross-examine the witness.",
    "Ms. Alvarez, is it true you were behind on your rent that month?",
    "What does that have to do with anything?!",
    "Just answer the question, please.",
    "Fine. Yes, I was behind. So what?",
    "And is it true you filed an insurance claim the very next morning?",
    "Objection! Relevance, your honor!",
    "I will allow it. Answer the question.",
    "Yes, I filed a claim. My window was broken!",
    "How convenient that the window broke the same night, is it not?",
    "Are you calling me a liar?!",
    "I am asking the jury to consider the timeline.",
    "This is outrageous! I was the victim here!",
    "No further questions.",
    "The witness is excused. Court is adjourned until tomorrow morning.",
]

TOTAL_SECONDS = 180.0


@pytest.fixture
def sample_segments():
    """~3 minutes of fake courtroom transcript segments.

    Each segment: {"start": float, "end": float, "text": str}.
    Timings are proportional to word count so the whole script spans 180s.
    """
    total_words = sum(len(line.split()) for line in _COURTROOM_SCRIPT)
    per_word = TOTAL_SECONDS / total_words
    segments = []
    cursor = 0.0
    for line in _COURTROOM_SCRIPT:
        dur = max(len(line.split()) * per_word, 0.4)  # every segment gets some width
        segments.append({"start": cursor, "end": cursor + dur, "text": line})
        cursor += dur
    # Normalise so the transcript ends at exactly TOTAL_SECONDS.
    scale = TOTAL_SECONDS / cursor
    for seg in segments:
        seg["start"] *= scale
        seg["end"] *= scale
    assert segments[-1]["end"] == pytest.approx(TOTAL_SECONDS)
    return segments


@pytest.fixture
def sample_words(sample_segments):
    """Word-level timings derived from sample_segments.

    Each word: {"word": str, "start": float, "end": float}, evenly spread
    across its segment.  Deterministic - no randomness.
    """
    words = []
    for seg in sample_segments:
        tokens = seg["text"].split()
        span = seg["end"] - seg["start"]
        for i, token in enumerate(tokens):
            words.append(
                {
                    "word": token,
                    "start": seg["start"] + span * i / len(tokens),
                    "end": seg["start"] + span * (i + 1) / len(tokens),
                }
            )
    return words


@pytest.fixture
def sample_energy(sample_segments):
    """Fake audio-energy track: [(t_seconds, rms)] every 0.5s over 180s.

    Baseline wobble plus loud spikes wherever the transcript gets emotional
    (segments containing '!'), so energy-aware scoring has signal to find.
    """
    emotional = [(s["start"], s["end"]) for s in sample_segments if "!" in s["text"]]
    points = []
    t = 0.0
    while t <= TOTAL_SECONDS:
        rms = 0.25 + 0.15 * abs(math.sin(t / 7.0)) + 0.10 * abs(math.sin(t / 2.3))
        if any(a <= t <= b for a, b in emotional):
            rms += 0.30
        points.append((round(t, 2), round(min(rms, 1.0), 4)))
        t += 0.5
    return points


# ---------------------------------------------------------------------------
# API test client with external services mocked.
# Only boto3 / celery are ever mocked here - never the app logic under test.
# ---------------------------------------------------------------------------


def _optional_patch(target):
    """Return a mock.patch for *target*, or a no-op if its package is missing."""
    try:
        __import__(target.split(".")[0])
    except ImportError:
        return contextlib.nullcontext()
    return mock.patch(target)


@pytest.fixture
def api_client():
    """FastAPI TestClient with S3 (boto3) and celery send_task mocked out.

    Creates the DB tables first (backend exposes init_db() for exactly this;
    Alembic is used in prod). The sqlite file is wiped at conftest import so
    every pytest run starts from an empty database.
    """
    from fastapi.testclient import TestClient

    from backend.app.db import init_db
    from backend.app.main import app

    init_db()

    patches = [
        _optional_patch("boto3.client"),
        _optional_patch("celery.Celery.send_task"),
    ]
    for p in patches:
        entered = p.__enter__() if hasattr(p, "__enter__") else None
        if entered is not None and hasattr(entered, "return_value"):
            # Presigned-URL style helpers should return something URL-like.
            entered.return_value.generate_presigned_url.return_value = (
                "https://example.com/presigned-test-url"
            )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        for p in patches:
            if hasattr(p, "__exit__"):
                p.__exit__(None, None, None)
