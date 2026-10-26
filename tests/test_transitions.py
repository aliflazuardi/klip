"""Scene transitions: which cut gets which move."""

from klip import config, transitions
from klip.spec import Spec


def _spec(slug="t", over=None):
    scenes = [{"id": f"s{i}", "template": "hook" if i == 0 else "explain", "narration": f"kalimat nomor {i}",
               **(over or {}).get(i, {})} for i in range(6)]
    return Spec.model_validate({"slug": slug, "scenes": scenes})


def _scenes(n=6, world=(), continues=()):
    return [{"id": f"s{i}", "idx": i, "start": float(i * 3), "dur": 3.0, "hidden": False,
             "on_world": i in world, "stage": {"continues": i in continues} if i in continues else None}
            for i in range(n)]


STYLE = config.style("default")


def test_cuts_vary_and_the_hook_gets_its_own():
    sc = _scenes()
    transitions.plan(_spec(), sc, STYLE)
    kinds = [s["tr_in"]["kind"] for s in sc[1:]]
    assert sc[0]["tr_in"] is None and kinds[0] == STYLE["transitions"]["hook"]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))                  # never twice in a row
    assert set(kinds[1:]) <= set(STYLE["transitions"]["pool"])
    # the outgoing half sits at the end of the previous scene
    assert sc[1]["tr_out"]["at"] == round(6 - STYLE["transitions"]["out_s"], 3) and sc[1]["tr_out"]["sel"] == "#sc-s1"


def test_no_transition_inside_a_world_or_a_continuing_stage_set():
    sc = _scenes(world=(2, 3, 4), continues=(1,))
    transitions.plan(_spec(), sc, STYLE)
    assert sc[1]["tr_in"] is None                     # stage set carries on
    assert sc[3]["tr_in"] is None and sc[4]["tr_in"] is None
    assert sc[2]["tr_in"]["sel"] == "#sc-s2, #sc-world"    # entering the world moves it too
    assert sc[5]["tr_in"] and sc[4]["tr_out"]["sel"] == "#sc-s4, #sc-world"


def test_spec_override_and_same_cuts_for_ab_variants():
    sc = _scenes()
    transitions.plan(_spec(over={3: {"transition": "flash"}, 4: {"transition": "none"}}), sc, STYLE)
    assert sc[3]["tr_in"]["kind"] == "flash" and sc[4]["tr_in"] is None
    a, b = _scenes(), _scenes()
    transitions.plan(_spec(slug="video-a"), a, STYLE)
    transitions.plan(_spec(slug="video-b"), b, STYLE)
    assert [s["tr_in"] for s in a] == [s["tr_in"] for s in b]


def test_title_keywords_slam_when_said():
    from klip.stages.compose import _headline, title_slams
    title = _headline("Ongkirnya PINDAH tempat", ["tempat"])
    words = [{"text": " Jadi", "startMs": 0, "sceneId": "s8"}, {"text": " pindah", "startMs": 2500, "sceneId": "s8"},
             {"text": " tempat.", "startMs": 2900, "sceneId": "s8"}, {"text": " pindah", "startMs": 100, "sceneId": "s1"}]
    title_slams(title, words, "s8")
    by = {h["text"]: h for h in title}
    assert by["PINDAH"]["key"] and by["PINDAH"]["slam"] == 2.5            # ALL-CAPS in a mixed-case title
    assert by["tempat"]["key"] and by["tempat"]["slam"] == 2.9            # emphasis
    assert not by["Ongkirnya"]["key"] and by["Ongkirnya"]["slam"] is None
    caps = _headline("GRATIS ONGKIR", [])
    title_slams(caps, words, "s8")
    assert not any(h["key"] for h in caps)                                 # an all-caps title has no keywords


def test_stage_depth_bokeh_by_tone_and_dof_on_photo_sets():
    from klip import stage
    els = [{"kind": "cutout", "start": 1.2}, {"kind": "highlight", "start": 0.5}]
    dark = stage._depth({"tone": "dark", "elements": els, "backdrop": {"kind": "photo"}}, {"id": "s1"})
    light = stage._depth({"tone": "light", "elements": els, "backdrop": None}, {"id": "s1"})
    d = config.get("stage.depth")
    assert len(dark["fg"]) == d["fg"]["dark"] and len(light["fg"]) == d["fg"]["light"]
    assert dark["dof"] == {"t": 1.2, "px": float(d["dof_px"])} and light["dof"] is None    # the first real prop
    again = stage._depth({"tone": "dark", "elements": els, "backdrop": {"kind": "photo"}}, {"id": "s1"})
    assert again["fg"] == dark["fg"]                                                        # deterministic
