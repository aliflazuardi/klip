"""Motion components on the stage: spec rules, step timing, geometry, lint, compose + templates."""

import pytest
from pydantic import ValidationError

from klip import motion
from klip import stage as stage_mod
from klip.lint import lint
from klip.spec import COMPONENTS, StageElement
from klip.stages import compose
from tests.test_stage import _spec, _timeline, needs_renderer, stage, words


def el(kind, *steps, **kw):
    return StageElement(at="a", kind=kind, steps=[dict(s) for s in steps], **kw)


def icon(name):
    return f"<svg data-icon='{name}'></svg>"


# ---- spec

def test_step_rules_per_component():
    el("split", {"text": "A", "value": 1}, {"text": "B", "value": 3})
    with pytest.raises(ValidationError, match="takes 2-5 steps"):
        el("split", {"text": "A", "value": 1})
    with pytest.raises(ValidationError, match="needs a `value`"):
        el("funnel", {"text": "A", "value": 1}, {"text": "B"})
    with pytest.raises(ValidationError, match="requires text"):
        el("flow", {"text": "A", "value": 1})
    with pytest.raises(ValidationError, match="more than `max`"):
        el("meter", {"text": "A", "value": 20}, max=10)
    with pytest.raises(ValidationError, match="exactly one `accent`"):
        el("reel", {"text": "A"}, {"text": "B"}, {"text": "C"})
    with pytest.raises(ValidationError, match="`steps` are for motion components"):
        StageElement(at="a", kind="label", text="x", steps=[{"text": "y"}])


# ---- timing

def test_step_times_follow_words_then_fall_back_to_gaps():
    e = el("cycle", {"text": "A", "at": "gajian"}, {"text": "B"}, {"text": "C", "at": "habis"})
    ws = words(("gajian", 1000), ("lalu", 1500), ("belanja", 2000), ("habis", 3000))
    times = stage_mod.step_times(e, 0.8, 6.0, ws)
    assert times[0] == pytest.approx(1.0 - 0.06) and times[2] == pytest.approx(3.0 - 0.06)
    assert times[1] == pytest.approx(times[0] + 0.45)                  # no `at`: step_gap_s after the previous
    assert stage_mod.step_times(e, 0.8, 2.0, ws)[2] <= 1.8               # never past the end


def test_lint_checks_step_words_in_order():
    narr = "Gaji masuk lalu belanja dan akhirnya habis lagi"
    ok = {"id": "s1", "template": "explain", "narration": narr,
          "visual": stage({"at": "Gaji", "kind": "kinetic", "steps": [{"text": "Gaji", "at": "Gaji"},
                                                                      {"text": "Habis", "at": "habis"}]})}
    assert not [i for i in lint(_spec(ok)) if i.level == "error" and i.where == "s1"]
    bad = {**ok, "visual": stage({"at": "belanja", "kind": "kinetic", "steps": [{"text": "x", "at": "Gaji"}]})}
    assert any("kinetic step at 'Gaji'" in str(i) for i in lint(_spec(bad)) if i.level == "error")


# ---- geometry

def test_split_shares_and_default_values():
    e = el("split", {"text": "A", "value": 96}, {"text": "B", "value": 4, "accent": True})
    c = motion.build(e, 900, 630, [1.0, 1.5], 0.8, 5.0, icon, "#FFC21A")
    a, b = c["steps"]
    assert (a["pct"], b["pct"]) == (96.0, 4.0) and a["show"] == "96%" and b["color"] == "#FFC21A"
    assert a["width"] + b["width"] == pytest.approx(100, abs=0.05)
    assert c["pad"] == 45.0 and c["iw"] == 810.0                           # card padding comes off the inner box


def test_flow_paths_widths_and_meter_levels():
    f = motion.build(el("flow", {"text": "A", "value": 3, "name": "house"}, {"text": "B", "value": 1}, text="Rp4"),
                     900, 945, [1, 2], 0.5, 6, icon, "#000")
    a, b = f["steps"]
    assert a["stroke"] > b["stroke"] and a["path"].startswith("M") and a["len"] > 0 and "house" in a["svg"]
    m = motion.build(el("meter", {"text": "x", "value": 3, "show": "Rp3 juta"}, {"text": "y", "value": 12, "show": "Rp12 juta"},
                        max=12), 900, 810, [1, 2], 0.5, 6, icon, "#000")
    lo, hi = m["steps"]
    assert hi["pct"] == 100 and lo["y"] > hi["y"] and hi["from"] == 0          # Rp3 juta doesn't count; 12 counts from 0
    assert lo["count"] is None and hi["count"]["value"] == 12


def test_cycle_reel_funnel_timeline_geometry():
    cy = motion.build(el("cycle", *({"text": t} for t in "ABCD")), 900, 900, [1, 2, 3, 4], 0.5, 8, icon, "#000")
    assert len(cy["arcs"]) == 4 and cy["steps"][0]["y"] < cy["cy"]           # the first step sits at the top
    reel = motion.build(el("reel", {"text": "A"}, {"text": "B"}, {"text": "C", "accent": True, "at": "a"}),
                        900, 720, [1, 2, 3.5], 0.5, 8, icon, "#000")
    assert reel["strip"][reel["land"]] == "C" and reel["y_to"] == -(reel["land"] - 1) * reel["rh"]
    assert reel["from"] + reel["dur"] == pytest.approx(3.5)                 # lands on the accent step's word
    fn = motion.build(el("funnel", {"text": "A", "value": 100}, {"text": "B", "value": 5}), 900, 855, [1, 2], 0.5, 8, icon, "#000")
    assert fn["steps"][0]["clip"].startswith("polygon(0.00% 0")
    tl = motion.build(el("timeline", {"text": "A", "label": "2014"}, {"text": "B"}), 900, 1125, [1, 2], 0.5, 8, icon, "#000")
    assert tl["steps"][0]["y"] < tl["steps"][1]["y"]


def test_components_are_heroes_with_straight_full_width_boxes():
    e = el("kinetic", {"text": "Gaji masuk"})
    assert stage_mod.box_size(e, "l", None) == (900.0, 675.0) and stage_mod.tilt("s", 0, "kinetic") == 0
    assert set(COMPONENTS) <= set(stage_mod.BIG)


# ---- compose + templates

@needs_renderer
def test_compose_renders_every_component():
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    from klip.paths import TEMPLATES_DIR
    narr = "satu dua tiga empat lima enam tujuh delapan sembilan sepuluh"
    comps = [
        {"kind": "kinetic", "steps": [{"text": "Satu", "accent": True}]},
        {"kind": "split", "steps": [{"text": "A", "value": 1}, {"text": "B", "value": 3}]},
        {"kind": "flow", "text": "Rp4", "name": "wallet", "steps": [{"text": "A", "value": 1, "name": "house"}]},
        {"kind": "meter", "max": 10, "steps": [{"text": "A", "value": 6, "show": "Rp6 juta"}]},
        {"kind": "cycle", "text": "Loop", "steps": [{"text": "A"}, {"text": "B"}, {"text": "C"}]},
        {"kind": "timeline", "steps": [{"text": "A", "label": "2014"}, {"text": "B", "label": "2020"}]},
        {"kind": "funnel", "steps": [{"text": "A", "value": 10}, {"text": "B", "value": 2, "accent": True}]},
        {"kind": "reel", "text": "Pilih", "steps": [{"text": "A"}, {"text": "B", "accent": True}, {"text": "C"}]},
    ]
    w = "satu dua tiga empat lima enam tujuh delapan".split()
    spec = _spec(*({"id": f"s{i}", "template": "explain", "narration": narr,
                    "visual": stage({"at": w[i], **c})} for i, c in enumerate(comps)))
    ws = [x for i in range(8) for x in words(*((t, i * 4000 + 300 * k) for k, t in enumerate(narr.split())), scene=f"s{i}")]
    ctx, warnings = compose.build_context(spec, _timeline(*((f"s{i}", 4000) for i in range(8))), ws, {"scenes": {}})
    assert not warnings
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR / "default"), undefined=StrictUndefined,
                      autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["rgba"] = compose.rgba
    html = env.get_template("index.html.j2").render(**ctx)
    for marker in ("kn-line", "sp-seg", "st-s2-0-d0", "mt-fill", "st-s4-0-orbit", "tl-line", "fn-layer", "rl-strip",
                   "function klipCount", 'klipCount("#st-s3-0-v0"'):
        assert marker in html, marker
    sfx = [m for m, t in ((e["moment"], e["t"]) for e in ctx["sfx"])]
    assert sfx.count("stage_number") >= 2                                    # meter level + reel landing
