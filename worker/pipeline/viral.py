"""Viral-clip candidate generation, scoring and selection.

Pure functions only -- no ML, no I/O, no randomness -- so this module is
directly unit-testable. Inputs are plain dicts/lists produced by the
transcribe/audio stages:

    segments: [{start: float, end: float, text: str}, ...]
    words:    [{word: str, start: float, end: float}, ...]
    energy:   [(t_seconds: float, rms: float), ...]
"""

from __future__ import annotations

import re
from typing import Iterable

WEIGHTS = {
    "hook": 0.25,
    "curiosity": 0.15,
    "emotion": 0.15,
    "info": 0.15,
    "audio": 0.10,
    "question": 0.10,
    "completion": 0.10,
}

# Words that historically open high-retention shorts (first-5-seconds scan).
HOOK_WORDS = frozenset(
    {
        "stop", "secret", "secrets", "never", "nobody", "mistake", "mistakes",
        "shocking", "insane", "crazy", "free", "truth", "lie", "lies", "hack",
        "hacks", "warning", "dangerous", "proven", "guaranteed", "million",
        "billion", "viral", "banned", "hidden", "finally", "urgent", "breaking",
        "exposed", "revealed", "forbidden",
    }
)

# Phrases signalling an open loop / payoff later in the clip.
OPEN_LOOP_PHRASES = (
    "watch till the end",
    "wait for it",
    "wait until the end",
    "stay tuned",
    "what happens next",
    "you won't believe",
    "here's why",
    "here is why",
    "but first",
    "the truth is",
    "nobody tells you",
    "part 2",
    "part two",
    "in the end",
    "at the end",
    "keep watching",
    "don't skip",
)

CONTRAST_WORDS = frozenset({"but", "however", "although", "though", "yet", "instead", "until"})

# Word -> emotional intensity (0..1).
EMOTION_LEXICON = {
    "love": 1.0, "hate": 1.0, "amazing": 0.9, "terrible": 0.9, "shocking": 0.9,
    "insane": 0.8, "crazy": 0.8, "unbelievable": 0.9, "incredible": 0.9,
    "scary": 0.8, "scared": 0.8, "angry": 0.8, "furious": 0.9, "sad": 0.7,
    "happy": 0.7, "excited": 0.8, "worried": 0.7, "afraid": 0.8, "proud": 0.7,
    "ashamed": 0.8, "jealous": 0.7, "surprised": 0.8, "disgusting": 0.8,
    "beautiful": 0.7, "horrible": 0.9, "stupid": 0.7, "brilliant": 0.8,
    "genius": 0.8, "disaster": 0.9, "miracle": 0.9, "nightmare": 0.9,
    "dream": 0.6, "pain": 0.7, "painful": 0.8, "cry": 0.7, "crying": 0.8,
    "laugh": 0.6, "funny": 0.6, "hilarious": 0.8, "epic": 0.8, "wild": 0.7,
}

WH_WORDS = frozenset({"who", "what", "when", "where", "why", "how", "which", "whom", "whose"})

_SENT_END_RE = re.compile(r"[.!?…]+$")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_CAP_RUN_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------
def _sentences_from_segments(segments: Iterable[dict]) -> list[dict]:
    """Group transcription segments into sentences.

    Sentences always snap to segment boundaries: a candidate never starts or
    ends mid-sentence (mid-segment). A trailing fragment without terminal
    punctuation is kept as its own sentence.
    """
    sentences: list[dict] = []
    buf: list[dict] = []
    start: float | None = None
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if start is None:
            start = float(seg["start"])
        buf.append(seg)
        if _SENT_END_RE.search(text):
            sentences.append(
                {
                    "start": start,
                    "end": float(buf[-1]["end"]),
                    "text": " ".join((s.get("text") or "").strip() for s in buf),
                }
            )
            buf = []
            start = None
    if buf:
        sentences.append(
            {
                "start": start,  # type: ignore[dict-item]
                "end": float(buf[-1]["end"]),
                "text": " ".join((s.get("text") or "").strip() for s in buf),
            }
        )
    return sentences


def generate_candidates(
    segments: list[dict],
    words: list[dict],
    energy: list[tuple[float, float]],
    durations: list[int],
    min_gap: float = 5.0,
) -> list[dict]:
    """Generate clip candidates aligned to sentence boundaries.

    For each target in ``durations`` (seconds), slides over whole sentences and
    emits every contiguous sentence group whose total length is within +/-2s
    of the target. Candidate starts are kept at least ``min_gap`` apart and
    near-duplicates are removed. Each item is ``{start, end, duration}``.
    ``words``/``energy`` are accepted for signature symmetry and ignored here.
    """
    del words, energy  # not needed for boundary-aligned generation
    sentences = _sentences_from_segments(segments)
    targets = sorted({int(d) for d in durations if d and d > 0})
    tol = 2.0

    cands: list[dict] = []
    for target in targets:
        for i in range(len(sentences)):
            start = sentences[i]["start"]
            j = i
            while j < len(sentences) and sentences[j]["end"] - start <= target + tol:
                j += 1
            if j == i:
                continue
            end = sentences[j - 1]["end"]
            if end - start >= target - tol:
                cands.append(
                    {
                        "start": round(start, 3),
                        "end": round(end, 3),
                        "duration": round(end - start, 3),
                    }
                )

    cands.sort(key=lambda c: (c["start"], c["end"]))
    unique: list[dict] = []
    for c in cands:
        if any(
            abs(c["start"] - u["start"]) < 1.0 and abs(c["end"] - u["end"]) < 1.0
            for u in unique
        ):
            continue
        unique.append(c)

    spaced: list[dict] = []
    for c in unique:
        if all(abs(c["start"] - s["start"]) >= min_gap for s in spaced):
            spaced.append(c)
    return spaced


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _words_in(cand: dict, words: list[dict]) -> list[dict]:
    return [
        w
        for w in words
        if w["start"] >= cand["start"] - 1e-6 and w["end"] <= cand["end"] + 1e-6
    ]


def _text_in(cand: dict, segments: list[dict]) -> str:
    parts = [
        s.get("text", "")
        for s in segments
        if s["end"] > cand["start"] and s["start"] < cand["end"]
    ]
    return " ".join(p.strip() for p in parts if p and p.strip())


def score_candidate(
    cand: dict,
    segments: list[dict],
    words: list[dict],
    energy: list[tuple[float, float]],
) -> dict:
    """Score a candidate 0-100 with per-component breakdown.

    Components (each 0..1, weighted by WEIGHTS):
      hook       - hook words / question / numbers in the first 5 seconds
      curiosity  - open-loop phrases and contrast words ("but", "however")
      emotion    - emotional lexicon density
      info       - speech rate near 2.5 wps + capitalised entity-like runs
      audio      - mean RMS in window vs global mean (louder-than-average wins)
      question   - explicit "?" (1.0) or wh-word (0.6)
      completion - ends at sentence end; penalised for trailing silence >1.5s
                   or leading silence >1.0s
    """
    window_words = _words_in(cand, words)
    text = _text_in(cand, segments)
    lowered = text.lower()
    tokens = _WORD_RE.findall(lowered)
    n = len(tokens)
    dur = max(cand["end"] - cand["start"], 1e-6)

    # -- hook: first 5 seconds -------------------------------------------
    first5 = [w for w in window_words if w["start"] < cand["start"] + 5.0]
    first5_text = " ".join(w.get("word", "") for w in first5)
    first5_tokens = _WORD_RE.findall(first5_text.lower())
    hook_hits = sum(1 for t in first5_tokens if t in HOOK_WORDS)
    hook_q = 1.0 if "?" in first5_text else 0.0
    hook_num = 1.0 if re.search(r"\d", first5_text) else 0.0
    hook = min(1.0, hook_hits * 0.25 + hook_q * 0.45 + hook_num * 0.2)

    # -- curiosity: open loops --------------------------------------------
    phrase_hits = sum(1 for p in OPEN_LOOP_PHRASES if p in lowered)
    contrast = sum(1 for t in tokens if t in CONTRAST_WORDS)
    curiosity = min(1.0, phrase_hits * 0.45 + contrast * 0.15)

    # -- emotion ------------------------------------------------------------
    emo = sum(EMOTION_LEXICON.get(t, 0.0) for t in tokens)
    emotion = min(1.0, emo / 3.0)

    # -- info density --------------------------------------------------------
    wps = n / dur
    wps_score = max(0.0, 1.0 - abs(wps - 2.5) / 2.5)
    cap_runs = len(_CAP_RUN_RE.findall(text))
    info = 0.6 * wps_score + 0.4 * min(1.0, cap_runs * 0.25)

    # -- audio energy ----------------------------------------------------------
    win_rms = [r for (t, r) in energy if cand["start"] <= t <= cand["end"]]
    if win_rms and energy:
        gmean = sum(r for _, r in energy) / len(energy)
        ratio = (sum(win_rms) / len(win_rms)) / (gmean + 1e-9)
        audio = min(1.0, ratio / 1.4)
    else:
        audio = 0.5

    # -- question / open loop ----------------------------------------------------
    if "?" in text:
        question = 1.0
    elif any(t in WH_WORDS for t in tokens):
        question = 0.6
    else:
        question = 0.0

    # -- completion --------------------------------------------------------------
    stripped = text.strip()
    completion = 1.0 if _SENT_END_RE.search(stripped) else 0.4
    if window_words:
        trailing = cand["end"] - window_words[-1]["end"]
        leading = window_words[0]["start"] - cand["start"]
        if trailing > 1.5:
            completion *= 0.5
        if leading > 1.0:
            completion *= 0.8

    components = {
        "hook": hook,
        "curiosity": curiosity,
        "emotion": emotion,
        "info": info,
        "audio": audio,
        "question": question,
        "completion": completion,
    }
    total = round(sum(WEIGHTS[k] * components[k] for k in WEIGHTS) * 100, 2)
    return {"total": total, "components": {k: round(v, 3) for k, v in components.items()}}


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def _overlap(a: dict, b: dict) -> float:
    return max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))


def select_top_clips(scored: list[dict], n: int, max_overlap: float = 0.3) -> list[dict]:
    """Greedy top-n selection by score with an overlap constraint.

    Each item of ``scored`` must carry ``start``/``end``/``duration`` and a
    ``score`` dict as returned by :func:`score_candidate`. A candidate is only
    added if its overlap with every already-chosen clip is at most
    ``max_overlap * min(duration_a, duration_b)`` seconds.
    """
    ranked = sorted(scored, key=lambda c: c["score"]["total"], reverse=True)
    chosen: list[dict] = []
    for cand in ranked:
        ok = True
        for sel in chosen:
            limit = max_overlap * min(cand["duration"], sel["duration"])
            if _overlap(cand, sel) > limit:
                ok = False
                break
        if ok:
            chosen.append(cand)
        if len(chosen) >= n:
            break
    return chosen
