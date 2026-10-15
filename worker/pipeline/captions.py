"""ASS subtitle generation with word-level karaoke for 1080x1920 shorts.

Produces a valid ASS v4.00+ script: big bold white text with a heavy black
outline ("hormozi" style), bottom-center aligned in the lower third, at most
2 lines per event with <=8 words per line. Unicode-safe: :func:`write_ass`
saves as UTF-8 with BOM (utf-8-sig), which libass handles reliably.
"""

from __future__ import annotations

PLAYRES_W, PLAYRES_H = 1080, 1920

_STYLES = {
    "hormozi": {
        "fontname": "Arial",
        "fontsize": 86,
        "primary": "&H00FFFFFF",    # white
        "secondary": "&H0000FFFF",  # karaoke sweep highlight (yellow)
        "outline_c": "&H00000000",  # black outline
        "back": "&H99000000",       # translucent shadow box
        "outline": 5,
        "shadow": 1,
        "margin_v": 170,            # lower third on 1920px height
    },
}


def _fmt_ts(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _karaoke_line(words: list[dict]) -> str:
    parts = []
    for w in words:
        cs = max(1, int(round((w["end"] - w["start"]) * 100)))
        parts.append("{\\k%d}%s" % (cs, _escape(w["word"].strip())))
    return " ".join(parts)


def build_ass(
    words: list[dict],
    clip_start: float,
    clip_end: float,
    style: str = "hormozi",
) -> str:
    """Build an ASS subtitle string for the clip window.

    ``words`` are absolute-time ``{word, start, end}`` dicts (from
    transcription); only words overlapping ``[clip_start, clip_end]`` are
    used. Words are chunked into events of at most 16 words, rendered as up
    to 2 lines of at most 8 words each, with ``{\\k<cs>}`` karaoke timing.
    """
    if style not in _STYLES:
        raise ValueError(f"unknown caption style: {style!r}")
    st = _STYLES[style]

    win = [w for w in words if w["end"] > clip_start and w["start"] < clip_end]
    win.sort(key=lambda w: w["start"])

    events: list[str] = []
    for i in range(0, len(win), 16):
        chunk = win[i : i + 16]
        line1, line2 = chunk[:8], chunk[8:16]
        text = _karaoke_line(line1)
        if line2:
            text += "\\N" + _karaoke_line(line2)
        start = _fmt_ts(chunk[0]["start"] - clip_start)
        end = _fmt_ts(chunk[-1]["end"] - clip_start)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    header = "\n".join(
        [
            "[Script Info]",
            "Title: Viral Shorts AI Captions",
            "ScriptType: v4.00+",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            f"PlayResX: {PLAYRES_W}",
            f"PlayResY: {PLAYRES_H}",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,{fontname},{fontsize},{primary},{secondary},"
            "{outline_c},{back},-1,0,0,0,100,100,0.5,0,1,{outline},{shadow},"
            "2,40,40,{margin_v},1".format(**st),
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )
    return header + "\n" + "\n".join(events) + "\n"


def write_ass(path: str, content: str) -> str:
    """Write ASS ``content`` to ``path`` as UTF-8 with BOM (libass-safe)."""
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(content)
    return path
