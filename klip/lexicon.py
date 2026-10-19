"""Pronunciation lexicon, applied to TTS text only."""

from __future__ import annotations

import re


def apply_lexicon(text: str, lexicon: dict[str, str]) -> str:
    """Replace lexicon keys in `text`.

    Word-like keys ("WiFi", "vs") match whole words only. Symbol keys ("%") match
    anywhere and are spaced out, so "50%" becomes "50 persen".
    """
    # Longest keys first so "km/jam" wins over a hypothetical "km".
    for key in sorted(lexicon, key=len, reverse=True):
        spoken = lexicon[key]
        if re.fullmatch(r"\w+", key):
            text = re.sub(rf"(?<!\w){re.escape(key)}(?!\w)", spoken, text)
        else:
            text = text.replace(key, f" {spoken} ")
    return re.sub(r"[ \t]{2,}", " ", text).strip()
