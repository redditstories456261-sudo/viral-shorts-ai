"""Tests for worker/pipeline/viral.py - candidate generation, scoring, selection.

Contract under test:
    WEIGHTS: dict of the scoring components
    generate_candidates(segments, words, energy, durations, min_gap)
        -> [{"start", "end", "duration"}]
    score_candidate(cand, segments, words, energy)
        -> {"total", "components"}
    select_top_clips(scored, n, max_overlap=0.3)
"""

import pytest

from worker.pipeline.viral import (
    WEIGHTS,
    generate_candidates,
    score_candidate,
    select_top_clips,
)

DURATIONS = [30, 45, 60]
MIN_GAP = 5.0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bounds(entry):
    """Extract (start, end, duration) whether *entry* is a bare candidate or a
    scored entry.  Supports both shapes so the test stays honest about what the
    contract guarantees (start/end/duration present) without over-fitting to
    one particular wrapper layout."""
    cand = entry.get("candidate") if isinstance(entry.get("candidate"), dict) else entry
    return cand["start"], cand["end"], cand["duration"]


def _overlap_fraction(a_start, a_end, b_start, b_end):
    """Intersection over the shorter clip - the natural 'how much do these
    two clips cover each other' measure used by the max_overlap constraint."""
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    shorter = min(a_end - a_start, b_end - b_start)
    return inter / shorter if shorter > 0 else 0.0


def _scored(candidates, segments, words, energy):
    """Score candidate dicts -> scored entries for select_top_clips.

    Each entry carries start/end/duration plus the "score" dict returned by
    score_candidate, exactly as select_top_clips documents.
    """
    out = []
    for cand in candidates:
        out.append({**cand, "score": score_candidate(cand, segments, words, energy)})
    return out


# ---------------------------------------------------------------------------
# WEIGHTS contract
# ---------------------------------------------------------------------------

def test_weights_has_seven_components():
    assert isinstance(WEIGHTS, dict)
    assert len(WEIGHTS) == 7
    for name, weight in WEIGHTS.items():
        assert isinstance(name, str) and name
        assert isinstance(weight, (int, float)), f"weight {name!r} is not numeric"


# ---------------------------------------------------------------------------
# generate_candidates
# ---------------------------------------------------------------------------

def test_candidates_snap_to_segment_boundaries(sample_segments, sample_words, sample_energy):
    """No candidate may start or end in the middle of a spoken segment -
    cuts must land on sentence boundaries."""
    candidates = generate_candidates(
        sample_segments, sample_words, sample_energy, DURATIONS, MIN_GAP
    )
    assert candidates, "expected at least one candidate from 3 minutes of speech"
    # The implementation rounds boundaries to 3 decimals, so allow 1ms slack.
    for cand in candidates:
        assert any(
            abs(cand["start"] - seg["start"]) < 1e-3 for seg in sample_segments
        ), f"candidate start {cand['start']} is mid-segment"
        assert any(
            abs(cand["end"] - seg["end"]) < 1e-3 for seg in sample_segments
        ), f"candidate end {cand['end']} is mid-segment"


def test_candidate_durations_come_from_requested_set(
    sample_segments, sample_words, sample_energy
):
    """Candidate windows target the requested durations. The implementation
    allows +/-2s of slack so cuts can land on sentence boundaries."""
    candidates = generate_candidates(
        sample_segments, sample_words, sample_energy, DURATIONS, MIN_GAP
    )
    assert candidates
    for cand in candidates:
        assert any(
            abs(cand["duration"] - d) <= 2.0 + 1e-6 for d in DURATIONS
        ), f"candidate duration {cand['duration']} not within 2s of {DURATIONS}"
        # start/end/duration are independently rounded to 3 decimals: allow 2ms
        assert abs((cand["end"] - cand["start"]) - cand["duration"]) <= 2e-3


def test_candidates_respect_min_gap(sample_segments, sample_words, sample_energy):
    """Candidates generated from the same neighbourhood must be at least
    min_gap apart in start time (no near-duplicate windows)."""
    candidates = generate_candidates(
        sample_segments, sample_words, sample_energy, [30], MIN_GAP
    )
    starts = sorted(c["start"] for c in candidates)
    for a, b in zip(starts, starts[1:]):
        assert b - a >= MIN_GAP - 1e-9, f"candidates {a} and {b} closer than min_gap"


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------

def test_score_candidate_total_in_range_with_all_components(
    sample_segments, sample_words, sample_energy
):
    candidates = generate_candidates(
        sample_segments, sample_words, sample_energy, [30], MIN_GAP
    )
    result = score_candidate(candidates[0], sample_segments, sample_words, sample_energy)
    assert 0.0 <= result["total"] <= 100.0
    assert isinstance(result["components"], dict)
    assert len(result["components"]) == 7
    assert set(result["components"]) == set(WEIGHTS)
    for name, value in result["components"].items():
        assert isinstance(value, (int, float)), f"component {name!r} not numeric"
        assert 0.0 <= value <= 100.0, f"component {name!r}={value} outside 0-100"


def _question_key(components):
    for key in components:
        if "question" in key.lower():
            return key
    raise AssertionError(f"no question component found in {sorted(components)}")


def test_question_segment_scores_higher_on_question_component(
    sample_segments, sample_words, sample_energy
):
    """A clip built around a question must outscore an otherwise identical
    clip built around a plain statement, on the question component."""
    seg_q = next(s for s in sample_segments if "?" in s["text"])
    seg_n = next(
        s
        for s in sample_segments
        if "?" not in s["text"] and "!" not in s["text"]
    )
    cand_q = {"start": seg_q["start"], "end": seg_q["end"],
              "duration": seg_q["end"] - seg_q["start"]}
    cand_n = {"start": seg_n["start"], "end": seg_n["end"],
              "duration": seg_n["end"] - seg_n["start"]}
    score_q = score_candidate(cand_q, sample_segments, sample_words, sample_energy)
    score_n = score_candidate(cand_n, sample_segments, sample_words, sample_energy)
    qkey = _question_key(score_q["components"])
    assert (
        score_q["components"][qkey] > score_n["components"][qkey]
    ), "question segment did not outscore statement segment on question component"


def test_different_content_scores_differently(sample_segments, sample_words, sample_energy):
    """Sanity: scoring is content-sensitive, not a constant."""
    candidates = generate_candidates(
        sample_segments, sample_words, sample_energy, [30], MIN_GAP
    )
    totals = {
        score_candidate(c, sample_segments, sample_words, sample_energy)["total"]
        for c in candidates[:10]
    }
    assert len(totals) > 1, "first 10 candidates all scored identically"


# ---------------------------------------------------------------------------
# select_top_clips
# ---------------------------------------------------------------------------

def test_select_top_clips_returns_n_with_overlap_constraint(
    sample_segments, sample_words, sample_energy
):
    candidates = generate_candidates(
        sample_segments, sample_words, sample_energy, [30], MIN_GAP
    )
    scored = _scored(candidates, sample_segments, sample_words, sample_energy)
    top = select_top_clips(scored, 4, max_overlap=0.3)
    assert len(top) == 4
    bounds = [_bounds(e) for e in top]
    for i in range(len(bounds)):
        for j in range(i + 1, len(bounds)):
            frac = _overlap_fraction(*bounds[i][:2], *bounds[j][:2])
            assert frac <= 0.3 + 1e-9, (
                f"clips {bounds[i]} and {bounds[j]} overlap by {frac:.2f} > 0.3"
            )


def test_select_top_clips_prefers_higher_scores(
    sample_segments, sample_words, sample_energy
):
    """With overlapping candidates, the higher-scoring one must survive."""
    candidates = generate_candidates(
        sample_segments, sample_words, sample_energy, [30], MIN_GAP
    )
    scored = _scored(candidates[:6], sample_segments, sample_words, sample_energy)
    scored = sorted(scored, key=lambda e: e["score"]["total"], reverse=True)
    best, worst = scored[0], scored[-1]
    # Force a heavy overlap: move the worst clip to (almost) the best clip's window.
    b_start, b_end, b_dur = _bounds(best)
    w_start, w_end, w_dur = _bounds(worst)
    shift = b_start - w_start
    worst["start"] = w_start + shift
    worst["end"] = w_end + shift
    worst["duration"] = w_dur
    top = select_top_clips(scored, 1, max_overlap=0.3)
    assert len(top) == 1
    assert _bounds(top[0]) == pytest.approx((b_start, b_end, b_dur))


def test_select_top_clips_prunes_exact_duplicates(
    sample_segments, sample_words, sample_energy
):
    """Two identical candidate windows must not both appear in the output."""
    candidates = generate_candidates(
        sample_segments, sample_words, sample_energy, [30], MIN_GAP
    )
    scored = _scored(candidates[:4], sample_segments, sample_words, sample_energy)
    dup = dict(scored[0])
    dup["score"] = dict(scored[0]["score"])
    dup["score"]["total"] = scored[0]["score"]["total"] - 1.0  # same window, worse
    scored.append(dup)
    top = select_top_clips(scored, 3, max_overlap=0.3)
    windows = [(_bounds(e)[0], _bounds(e)[1]) for e in top]
    assert len(windows) == len(set(windows)), "duplicate window survived pruning"
