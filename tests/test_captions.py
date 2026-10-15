"""Tests for worker/pipeline/captions.py - ASS subtitle generation.

Contract under test:
    build_ass(words, clip_start, clip_end, style="hormozi") -> str (ASS format)
    write_ass(path, content) -> writes the file
"""

import os
import re

import pytest

from worker.pipeline.captions import build_ass, write_ass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def ass_timestamp(seconds):
    """Expected ASS timestamp: h:mm:ss.cc (centiseconds)."""
    seconds = max(0.0, seconds)
    whole = int(seconds)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    cs = int(round((seconds - whole) * 100))
    if cs == 100:  # carry, e.g. 10.999 -> 11.00
        s += 1
        cs = 0
        if s == 60:
            m += 1
            s = 0
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def dialogue_lines(ass_text):
    return [ln for ln in ass_text.splitlines() if ln.startswith("Dialogue:")]


def dialogue_text(line):
    # Dialogue: layer,start,end,style,name,marginL,marginR,marginV,effect,text
    return line.split(",", 9)[9]


@pytest.fixture
def caption_words():
    """Word timings with a known anchor: a word starting at exactly 10.42s."""
    return [
        {"word": "Objection,", "start": 10.10, "end": 10.40},
        {"word": "your", "start": 10.42, "end": 10.60},
        {"word": "honor!", "start": 10.62, "end": 10.95},
        {"word": "🔥", "start": 11.00, "end": 11.30},
        {"word": "شکریہ", "start": 11.35, "end": 11.70},
        # outside the clip window - must be filtered out
        {"word": "late", "start": 99.00, "end": 99.40},
    ]


# ---------------------------------------------------------------------------
# build_ass
# ---------------------------------------------------------------------------

def test_ass_contains_header_sections(caption_words):
    out = build_ass(caption_words, clip_start=10.0, clip_end=12.0)
    assert "[Script Info]" in out
    assert "[V4+ Styles]" in out
    assert "[Events]" in out
    assert "Format:" in out


def test_ass_has_dialogue_with_karaoke_tags(caption_words):
    out = build_ass(caption_words, clip_start=10.0, clip_end=12.0)
    lines = dialogue_lines(out)
    assert lines, "no Dialogue lines generated"
    assert any(re.search(r"\{\\k\d+\}", dialogue_text(ln)) for ln in lines), (
        "no karaoke {\\kN} tags found in Dialogue text"
    )


def test_word_timing_converted_to_ass_centiseconds():
    """ASS timestamps are h:mm:ss.cc. A word starting at 10.42s must produce
    an event starting at 0:00:10.42 (absolute clip) or 0:00:00.42 when the
    clip itself starts at 10.0s (relative)."""
    words = [{"word": "go", "start": 10.42, "end": 10.90}]
    absolute = build_ass(words, clip_start=0.0, clip_end=12.0)
    assert ass_timestamp(10.42) == "0:00:10.42"
    assert ",0:00:10.42," in absolute

    relative = build_ass(words, clip_start=10.0, clip_end=12.0)
    assert ass_timestamp(0.42) == "0:00:00.42"
    assert ",0:00:00.42," in relative


def test_karaoke_tags_carry_word_durations_in_centiseconds(caption_words):
    """The word 'your' lasts 0.18s (10.42 -> 10.60) so its karaoke tag must
    be {\\k18} - durations in centiseconds, not seconds or milliseconds."""
    out = build_ass(caption_words, clip_start=10.0, clip_end=12.0)
    assert r"{\k18}your" in out


def test_words_outside_clip_window_are_excluded(caption_words):
    out = build_ass(caption_words, clip_start=10.0, clip_end=12.0)
    assert "late" not in out


def test_max_two_lines_per_event(sample_words):
    """Hormozi-style captions chunk aggressively; no event may exceed 2 lines."""
    out = build_ass(sample_words, clip_start=0.0, clip_end=180.0, style="hormozi")
    lines = dialogue_lines(out)
    assert lines
    for ln in lines:
        text = dialogue_text(ln)
        # strip karaoke override tags before counting visual lines
        visible = re.sub(r"\{[^}]*\}", "", text)
        assert len(visible.split(r"\N")) <= 2, f"event has >2 lines: {text[:80]}"


def test_unicode_text_preserved(caption_words):
    out = build_ass(caption_words, clip_start=10.0, clip_end=12.0)
    assert "🔥" in out
    assert "شکریہ" in out


def test_hormozi_style_is_default_and_applies_its_look(caption_words):
    """style='hormozi' is the default; its look (big white bold text, heavy
    black outline) must be present in the [V4+ Styles] section."""
    default = build_ass(caption_words, clip_start=10.0, clip_end=12.0)
    explicit = build_ass(caption_words, clip_start=10.0, clip_end=12.0, style="hormozi")
    assert default == explicit
    assert "Fontsize, 86" in default or ",86," in default  # big text
    assert "&H00FFFFFF" in default  # white primary colour
    assert ",5," in default or "Outline, 5" in default  # heavy outline


def test_dialogue_events_cover_clip_words_in_order(caption_words):
    out = build_ass(caption_words, clip_start=10.0, clip_end=12.0)
    body = " ".join(dialogue_text(ln) for ln in dialogue_lines(out))
    for token in ("Objection,", "your", "honor!"):
        assert token in body
    assert body.index("Objection,") < body.index("your") < body.index("honor!")


# ---------------------------------------------------------------------------
# write_ass
# ---------------------------------------------------------------------------

def test_write_ass_roundtrip(tmp_path, caption_words):
    content = build_ass(caption_words, clip_start=10.0, clip_end=12.0)
    path = str(tmp_path / "clip.ass")
    assert write_ass(path, content) == path
    assert os.path.exists(path)
    # write_ass saves UTF-8 with BOM (libass-safe); read it back the same way
    with open(path, encoding="utf-8-sig") as fh:
        assert fh.read() == content
    with open(path, "rb") as fh:
        assert fh.read(3) == b"\xef\xbb\xbf", "expected UTF-8 BOM at file start"
