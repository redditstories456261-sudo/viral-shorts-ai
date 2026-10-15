"""Title / hook / description generation.

Two real strategies, selected by ``LLM_PROVIDER``:
  * "none"   - local template logic: picks the best hook sentence from the
               transcript (first question, else highest-emotion sentence),
               builds a title from the transcript's top keywords, and a
               description from the hook + transcript excerpt + hashtags.
               Nothing is invented beyond what the transcript says.
  * "openai" - real httpx POST to ``{base_url}/chat/completions`` (OpenAI
               chat-completions schema) with a system prompt that constrains
               the model to facts present in the transcript. Falls back to
               the template logic if the call fails.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter

import httpx

log = logging.getLogger(__name__)

STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
        "been", "being", "to", "of", "in", "on", "for", "with", "as", "at",
        "by", "from", "that", "this", "it", "its", "you", "your", "we", "our",
        "they", "their", "he", "she", "his", "her", "i", "me", "my", "not",
        "no", "yes", "so", "if", "then", "than", "too", "very", "just",
        "like", "get", "got", "going", "know", "think", "really", "much",
        "more", "all", "one", "two", "also", "because", "what", "when",
        "where", "who", "how", "why", "which", "will", "would", "can",
        "could", "should", "do", "does", "did", "have", "has", "had",
    }
)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text.strip()) if s.strip()]


def _best_hook_sentence(text: str) -> str:
    """Best hook sentence: first question, else highest-emotion sentence."""
    from worker.pipeline.viral import EMOTION_LEXICON

    sents = _sentences(text)
    if not sents:
        return ""
    for s in sents:
        if "?" in s:
            return s[:140]
    word_re = re.compile(r"[A-Za-z']+")

    def emo(s: str) -> float:
        return sum(EMOTION_LEXICON.get(w.lower(), 0.0) for w in word_re.findall(s))

    return max(sents, key=emo)[:140]


def _keywords(text: str, n: int = 6) -> list[str]:
    toks = re.findall(r"[A-Za-z][A-Za-z0-9']*", text.lower())
    caps = Counter(re.findall(r"\b[A-Z][a-z]{2,}\b", text))
    freq = Counter(t for t in toks if t not in STOPWORDS and len(t) > 3)
    scored: Counter = Counter()
    for t, c in freq.items():
        scored[t] += c
    for t, c in caps.items():  # proper nouns count double
        scored[t.lower()] += c * 2
    return [w for w, _ in scored.most_common(n)]


def _template_title_hook(transcript_text: str) -> dict:
    """Honest template logic: everything returned is derived from the transcript."""
    text = (transcript_text or "").strip()
    hook = _best_hook_sentence(text)
    kws = _keywords(text)
    title = " ".join(w.capitalize() for w in kws[:5])[:70].strip() or "Viral Short"
    if len(title) > 60:
        title = title[:57].rstrip() + "..."

    if text and len(text) > 220:
        description = hook + "\n\n" + text[:220].rstrip() + "..."
    elif text:
        description = text[:280]
    else:
        description = hook
    hashtags = " ".join("#" + re.sub(r"\W", "", w) for w in kws[:3] if w.isalpha())
    if hashtags:
        description = (description + "\n\n" + hashtags).strip()
    return {"title": title, "hook": hook, "description": description}


def _via_openai(transcript_text: str, base_url: str, api_key: str, model: str) -> dict:
    """Real OpenAI-compatible chat-completions call for title/hook/description."""
    url = base_url.rstrip("/") + "/chat/completions"
    system = (
        "You write YouTube Shorts titles. Use ONLY facts stated in the transcript "
        "below. Do not invent names, numbers, places, or claims that are not "
        "present in the transcript. Reply with JSON only, exactly: "
        '{"title": "<=60 chars>", "hook": "<=140 chars, the single most gripping '
        'line from the transcript>", "description": "<=300 chars summary plus 3 '
        'hashtags>"}.'
    )
    payload = {
        "model": model,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": (transcript_text or "")[:6000]},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:  # never logged
        headers["Authorization"] = "Bearer " + api_key
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return {
            "title": str(parsed.get("title", ""))[:70] or "Viral Short",
            "hook": str(parsed.get("hook", ""))[:160],
            "description": str(parsed.get("description", ""))[:400],
        }
    except Exception as exc:
        log.warning(
            "LLM title generation failed (%s); using transcript template fallback",
            type(exc).__name__,
        )
        return _template_title_hook(transcript_text)


def generate_title_hook(
    transcript_text: str,
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
) -> dict:
    """Return ``{title, hook, description}`` for a clip's transcript text."""
    provider = (provider or "none").lower()
    if provider == "openai" and base_url and model:
        return _via_openai(transcript_text, base_url, api_key, model)
    if provider not in ("none", "openai"):
        log.warning("unknown LLM provider %r; using transcript template logic", provider)
    return _template_title_hook(transcript_text)
