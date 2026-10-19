from klip.captions import CaptionWord, align, emphasis_mask, norm, paginate, tokenize
from klip.engines.tts.base import Word
from klip.engines.tts.edge import ticks_to_ms
from klip.lexicon import apply_lexicon


def test_ticks_to_ms():
    assert ticks_to_ms(10_000) == 1.0
    assert ticks_to_ms(9_816_600) == 981.66


def test_norm_strips_punctuation_and_case():
    assert norm("Menguap?") == "menguap"
    assert norm("gara-gara") == "garagara"


def test_lexicon_whole_words_and_symbols():
    lex = {"WiFi": "wai fai", "vs": "versus", "%": "persen", "km/jam": "kilometer per jam"}
    assert apply_lexicon("WiFi vs kabel", lex) == "wai fai versus kabel"
    assert apply_lexicon("Diskon 50%!", lex) == "Diskon 50 persen !"
    assert apply_lexicon("60 km/jam", lex) == "60 kilometer per jam"
    assert apply_lexicon("kvs tetap", lex) == "kvs tetap"  # no partial-word match


def W(text, s, e):
    return Word(text, s, e)


def test_align_equal_tokens_keep_display_text():
    display = tokenize("Halo, apa kabar?")
    spoken = [W("Halo", 0, 300), W("apa", 300, 500), W("kabar", 500, 900)]
    out = align(display, spoken)
    assert [w.text for w in out] == ["Halo,", "apa", "kabar?"]
    assert [(w.start_ms, w.end_ms) for w in out] == [(0, 300), (300, 500), (500, 900)]


def test_align_replaced_run_spans_spoken_time():
    # display "WiFi" spoken as "wai fai"
    display = tokenize("Pakai WiFi rumah")
    spoken = [W("Pakai", 0, 300), W("wai", 300, 450), W("fai", 450, 600), W("rumah", 600, 900)]
    out = align(display, spoken)
    assert [w.text for w in out] == ["Pakai", "WiFi", "rumah"]
    assert out[1].start_ms == 300 and out[1].end_ms == 600


def test_align_display_only_token_gets_zero_length_and_stays_monotonic():
    display = tokenize("satu — dua")
    spoken = [W("satu", 0, 200), W("dua", 300, 500)]
    out = align(display, spoken)
    assert len(out) == 3
    assert out[1].start_ms == out[1].end_ms == 200
    assert all(a.end_ms <= b.start_ms for a, b in zip(out, out[1:]))


def test_emphasis_mask_multiword_and_case():
    toks = tokenize("Teori: mendinginkan Otak, katanya")
    assert emphasis_mask(toks, ["mendinginkan otak"]) == [False, True, True, False]


def cw(text, s, e):
    return CaptionWord(text, s, e)


def test_paginate_max_words_and_scene_boundary():
    words = [cw(f"w{i}", i * 200, i * 200 + 180) for i in range(9)]
    pages = paginate([("a", words[:6]), ("b", words[6:])], max_words=4, max_page_ms=5000)
    assert [len(p.words) for p in pages] == [4, 2, 3]
    assert {p.scene_id for p in pages[:2]} == {"a"} and pages[2].scene_id == "b"
    assert all(len(p.words) <= 4 for p in pages)


def test_paginate_breaks_on_sentence_end_and_time():
    words = [cw("Halo.", 0, 300), cw("Ini", 300, 500), cw("contoh", 500, 900), cw("panjang", 900, 2000)]
    pages = paginate([("a", words)], max_words=4, max_page_ms=1200)
    assert [[w.text for w in p.words] for p in pages] == [["Halo."], ["Ini", "contoh"], ["panjang"]] or \
           [[w.text for w in p.words] for p in pages] == [["Halo."], ["Ini", "contoh", "panjang"]]
    assert pages[0].words[-1].text == "Halo."


def test_paginate_page_end_is_next_start_and_clamped_to_scene():
    words = [cw("a", 0, 100), cw("b.", 100, 200), cw("c", 400, 500), cw("d", 500, 600)]
    pages = paginate([("s", words)], max_words=4, hold_ms=1000, scene_ends={"s": 800})
    assert pages[0].end_ms == 400
    assert pages[-1].end_ms == 800
