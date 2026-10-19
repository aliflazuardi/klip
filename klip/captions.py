"""Caption logic: map TTS word timings onto display tokens, mark emphasis, paginate."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from klip.engines.tts.base import Word

_PUNCT_END = re.compile(r"[.!?…]$")
_PUNCT_SOFT = re.compile(r"[,;:—–]$")


def tokenize(text: str) -> list[str]:
    return text.split()


def norm(token: str) -> str:
    """Comparison form: lowercase, letters/digits only ("Menguap?" -> "menguap")."""
    return re.sub(r"[^\w]", "", token.lower())


def align(display: list[str], spoken: list[Word]) -> list[Word]:
    """Give every display token a timing taken from the spoken words.

    Equal runs map 1:1. Replaced runs (lexicon/tts_override) share the spoken span,
    split by character length. Display tokens with no spoken counterpart get a
    zero-length timing at the previous word's end.
    """
    if not display:
        return []
    if not spoken:
        raise ValueError("no spoken word timings to align against")

    out: list[Word | None] = [None] * len(display)
    a = [norm(t) for t in display]
    b = [norm(w.text) for w in spoken]
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                w = spoken[j1 + k]
                out[i1 + k] = Word(display[i1 + k], w.start_ms, w.end_ms)
        elif op == "replace":
            start, end = spoken[j1].start_ms, spoken[j2 - 1].end_ms
            weights = [max(len(a[i]), 1) for i in range(i1, i2)]
            total, t = sum(weights), start
            for i, wgt in zip(range(i1, i2), weights):
                dt = (end - start) * wgt / total
                out[i] = Word(display[i], t, t + dt)
                t += dt
        # "delete" (display-only) handled below; "insert" (spoken-only) is ignored.

    prev_end = spoken[0].start_ms
    result: list[Word] = []
    for tok, w in zip(display, out):
        if w is None:
            w = Word(tok, prev_end, prev_end)
        w.start_ms = max(w.start_ms, prev_end)  # keep monotonic
        w.end_ms = max(w.end_ms, w.start_ms)
        prev_end = w.end_ms
        result.append(w)
    return result


def emphasis_mask(tokens: list[str], phrases: list[str]) -> list[bool]:
    """True for tokens that belong to any emphasis phrase (case/punctuation-insensitive)."""
    mask = [False] * len(tokens)
    normed = [norm(t) for t in tokens]
    for phrase in phrases:
        target = [norm(p) for p in phrase.split() if norm(p)]
        n = len(target)
        if not n:
            continue
        for i in range(len(normed) - n + 1):
            if normed[i : i + n] == target:
                for k in range(i, i + n):
                    mask[k] = True
    return mask


@dataclass
class CaptionWord:
    text: str
    start_ms: float
    end_ms: float
    emphasis: bool = False


@dataclass
class Page:
    scene_id: str
    words: list[CaptionWord] = field(default_factory=list)
    start_ms: float = 0.0
    end_ms: float = 0.0  # display end (may extend past the last word)


def paginate(
    scene_words: list[tuple[str, list[CaptionWord]]],
    max_words: int = 4,
    max_page_ms: float = 1200,
    hold_ms: float = 250,
    scene_ends: dict[str, float] | None = None,
) -> list[Page]:
    """Group words into caption pages of <= max_words, ~<= max_page_ms.

    Pages never cross scene boundaries. Breaks after sentence punctuation, and after
    soft punctuation once a page has 2+ words. A trailing single-word page is merged
    into the previous page when that keeps it within max_words.
    """
    pages: list[Page] = []
    for scene_id, words in scene_words:
        scene_pages: list[Page] = []
        cur: list[CaptionWord] = []

        def flush() -> None:
            if cur:
                scene_pages.append(Page(scene_id, list(cur)))
                cur.clear()

        for w in words:
            if cur and (len(cur) >= max_words or w.end_ms - cur[0].start_ms > max_page_ms):
                flush()
            cur.append(w)
            if _PUNCT_END.search(w.text) or (len(cur) >= 2 and _PUNCT_SOFT.search(w.text)):
                flush()
        flush()

        merged: list[Page] = []
        for p in scene_pages:
            if merged and len(p.words) == 1 and len(merged[-1].words) < max_words \
                    and not _PUNCT_END.search(merged[-1].words[-1].text):
                merged[-1].words.extend(p.words)
            else:
                merged.append(p)

        scene_end = (scene_ends or {}).get(scene_id)
        for i, p in enumerate(merged):
            p.start_ms = p.words[0].start_ms
            if i + 1 < len(merged):
                p.end_ms = merged[i + 1].words[0].start_ms
            else:
                p.end_ms = p.words[-1].end_ms + hold_ms
                if scene_end is not None:
                    p.end_ms = min(p.end_ms, scene_end)
            p.end_ms = max(p.end_ms, p.words[-1].end_ms)
        pages.extend(merged)
    return pages
