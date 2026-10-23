"""Scene spec: the contract between script writing and rendering.

The spec file *is* the video: re-rendering the same spec gives the same output.
Run `klip schema` to export the JSON Schema to schema/spec.schema.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TemplateName = Literal["hook", "explain", "list_item", "myth_fact", "stat", "compare", "cta"]
VisualType = Literal["stock_video", "stock_photo", "ai_image", "icon", "solid", "local", "stage", "code"]
StageKind = Literal["cutout", "photo", "icon", "label", "number", "bar", "stack", "highlight", "stamp",
                    "chart", "unit", "person", "news", "logo", "screenshot", "notif",
                    "kinetic", "split", "flow", "meter", "cycle", "timeline", "funnel", "reel"]
# Motion components: animated diagrams whose `steps` play out on their own narration words.
COMPONENTS = ("kinetic", "split", "flow", "meter", "cycle", "timeline", "funnel", "reel")
StagePos = Literal["tl", "tc", "tr", "ml", "mc", "mr", "bl", "bc", "br"]
VoiceName = Literal["male", "female"]
LookName = Literal["mixed", "stage"]
Delivery = Literal["neutral", "energetic", "emphatic", "warm", "calm"]
CtaType = Literal["follow", "save", "comment", "share"]

# Templates and visual types the current build can render. Others are accepted by
# the schema (so specs stay forward-compatible) but fall back with a warning.
IMPLEMENTED_TEMPLATES = {"hook", "explain", "list_item", "myth_fact", "stat", "compare", "cta"}
IMPLEMENTED_VISUALS = {"icon", "solid", "stock_video", "stock_photo", "local", "stage", "code"}
STAGE_TEMPLATES = {"hook", "explain", "list_item"}   # templates whose layout leaves room for a stage


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Beat(_Strict):
    """A new shot inside a stock scene, cut in on a narration word with its own clip."""
    at: str = Field(min_length=1, description="Narration word (or phrase; its first word counts) where this "
                                              "shot starts: the cut lands as the voice says it.")
    query: str = Field(min_length=1, description="English keywords for this shot's stock clip.")


class MotionStep(_Strict):
    """One beat of a motion component (see StageElement.steps)."""
    text: str = Field(min_length=1, description="kinetic: the phrase; split/flow/funnel: the part's name; "
                                                "meter: a short caption for this level; cycle: the step; "
                                                "timeline: the event; reel: an option.")
    at: str | None = Field(None, description="Narration word where this step plays (after the element's own "
                                             "`at`, in order). Unset = shortly after the previous step.")
    value: float | None = Field(None, ge=0, description="split/flow/funnel: the amount (sizes the part); "
                                                        "meter: the fill level (≤ the element's `max`).")
    show: str | None = Field(None, description="The value as shown, e.g. 'Rp96rb', '96%', '1,2 jt'; counts up "
                                               "when it's a number. Unset: split shows the share in %, flow/"
                                               "funnel the plain value.")
    label: str | None = Field(None, description="timeline: the date ('2014', 'Mar 2020'); others: a small line "
                                                "under the step.")
    name: str | None = Field(None, description="Lucide icon for the step (flow/cycle/timeline/funnel nodes).")
    accent: bool = Field(False, description="Highlight this step (kinetic phrase, split/flow part, funnel "
                                            "layer); reel: the option the reel lands on (exactly one).")


class StageBar(_Strict):
    label: str = Field(min_length=1, description="Bar label under the bar, e.g. '2023'.")
    value: float = Field(ge=0, description="Bar height (bars are scaled to the largest).")
    text: str | None = Field(None, description="Value shown on top of the bar, e.g. 'Rp12rb'; unset = no text.")


class ChartPoint(_Strict):
    x: str = Field(min_length=1, description="X value as shown/compared: an ISO date ('2024-10-16') or a label "
                                             "('2019').")
    y: float


class ChartBand(_Strict):
    start: str = Field(min_length=1, description="First x value of the shaded span (same form as the data's x).")
    end: str = Field(min_length=1, description="Last x value of the span.")
    label: str | None = Field(None, description="Short text in the band, e.g. 'SBY'.")


# what each stage element kind needs (one of a tuple is enough)
_STAGE_NEEDS = {"cutout": (("query", "path", "who"),), "photo": (("query", "path", "who"),), "icon": (("name",),),
                "label": (("text",),), "number": (("text",),), "bar": (("bars",),), "stack": (("name",),),
                "highlight": (("target",),), "stamp": (("text",),), "chart": (("points", "csv", "ticker"),),
                "unit": (("total",),), "person": (("who", "path", "query"),), "news": (("text",),),
                "logo": (("who", "path"),), "screenshot": (("url",),), "notif": (("text",),), "kinetic": (("steps",),),
                "split": (("steps",),), "flow": (("steps",), ("text",)), "meter": (("steps",), ("max",)),
                "cycle": (("steps",),), "timeline": (("steps",),), "funnel": (("steps",),), "reel": (("steps",),)}
# steps each component takes (min, max) and whether every step needs a `value`
STEP_RULES = {"kinetic": (1, 6, False), "split": (2, 5, True), "flow": (1, 4, True), "meter": (1, 5, True),
              "cycle": (3, 6, False), "timeline": (2, 6, False), "funnel": (2, 5, True), "reel": (3, 10, False)}
LABELLED = ("cutout", "photo", "icon", "person", "logo", "screenshot")
MEDIA = ("cutout", "photo", "person", "logo")          # an image file: stock, Wikipedia or the user's photo


class StageElement(_Strict):
    """A prop that builds up on a stage scene: it pops in as the voice says `at` and stays."""
    at: str = Field(min_length=1, description="Narration word (or phrase; its first word counts) where this "
                                              "element pops in. Elements are matched in narration order.")
    kind: StageKind = Field(description="cutout = stock photo with its background removed (a sticker); "
                                        "photo = photo card; icon = Lucide icon on a sticker disc; label = paper "
                                        "tag; number = big number; bar = bar chart; stack = a pile of `count` "
                                        "icons; highlight = yellow box around an earlier element; stamp = a "
                                        "rubber stamp that thumps down (a verdict: 'BERHASIL', 'PALSU'); "
                                        "chart = a line chart that draws on (real data: points, csv or ticker); "
                                        "unit = a grid of `total` squares, `filled` of them highlighted; person = a "
                                        "real person's card (Wikipedia photo of `who`, name, a line, a stat); news = "
                                        "a headline card (outlet, date, text); logo = an organisation's logo "
                                        "(`who`) on a sign; screenshot = a web page (`url`) in a browser window; notif = "
                                        "a phone notification card (`outlet` = the app, `text` = the line, "
                                        "`stat` = a big amount, `date` = the corner note). "
                                        "Motion components (animated diagrams; their `steps` play on their own "
                                        "words): kinetic = big kinetic type, one phrase per step; split = a whole "
                                        "that breaks into shares (step values); flow = amounts flowing from a "
                                        "source (`text`, `name`) to 1-4 destinations; meter = a gauge filling to "
                                        "each step's value out of `max`, with a counter; cycle = a loop of 3-6 "
                                        "steps with a dot going round (a vicious circle); timeline = dated events "
                                        "(step `label` = the date); funnel = layers narrowing step by step; "
                                        "reel = a slot reel spinning through options and landing on the "
                                        "`accent` one.")
    query: str | None = Field(None, description="cutout/photo: English keywords for the stock photo, naming one "
                                                "object or person (e.g. 'tempeh block', 'businessman shrugging').")
    path: str | None = Field(None, description="cutout/photo/person/logo: your own image instead of `query` / "
                                               "`who` (a transparent PNG is used as-is).")
    who: str | None = Field(None, description="person/logo/cutout/photo: the Wikipedia article title of a real "
                                              "person or organisation (e.g. 'Joko Widodo', 'SoftBank Group'); its "
                                              "lead image is used, with the licence in the credits.")
    name: str | None = Field(None, description="icon/stack: Lucide icon name, e.g. 'coins'. cutout/photo: an "
                                               "icon shown instead when no photo is found. flow/meter: the source / gauge icon.")
    brief: str | None = Field(None, description="cutout/photo/person/logo: the ideal photo in a few words, in "
                                                "Indonesian, for the photo brief the user may shoot or find ('tangan "
                                                "memegang HP dengan aplikasi slot, malam hari').")
    own: bool = Field(False, description="cutout/photo/person/logo: this prop must be exactly right (a local "
                                         "product, a specific place): always listed in the photo brief; stock "
                                         "is only a placeholder until the user's photo is in the photo folder.")
    text: str | None = Field(None, description="label: the tag text (1-4 words); number: the number as shown, "
                                               "e.g. '-7%' or 'Rp12.000'; stamp: 1-2 words; chart: its title "
                                               "('IHSG'); unit: the legend ('1 kotak = 1.000 alat'); person: one "
                                               "small line ('2014–2024'); news: the headline; flow: the source "
                                               "('Rp100rb'); meter: what's measured ('Uang hilang'); cycle: the "
                                               "centre; split/reel/funnel: an optional title.")
    label: str | None = Field(None, description="cutout/photo/icon/logo/screenshot: a short tag stuck under the "
                                                "element; person: the name (default: from `who`).")
    tone: Literal["up", "down", "neutral"] = Field("neutral", description="number/stamp/person stat/chart line: "
                                                                          "colour (up = green, down = red; a "
                                                                          "neutral chart follows its trend).")
    points: list[ChartPoint] = Field(default_factory=list, max_length=400, description="chart: inline data.")
    csv: str | None = Field(None, description="chart: repo-relative CSV with a header; first column x, second y.")
    ticker: str | None = Field(None, description="chart: a Yahoo Finance symbol, e.g. '^JKSE' (IHSG), 'BBCA.JK', "
                                                 "'IDR=X' (USD/IDR); needs `start`.")
    start: str | None = Field(None, description="chart ticker: first date, YYYY-MM-DD.")
    end: str | None = Field(None, description="chart ticker: last date, YYYY-MM-DD (unset = today).")
    bands: list[ChartBand] = Field(default_factory=list, max_length=6,
                                   description="chart: shaded spans with a label (eras, terms of office).")
    total: int | None = Field(None, ge=2, le=400, description="unit: how many squares.")
    filled: int | None = Field(None, ge=0, le=400, description="unit: how many are highlighted (default all).")
    outlet: str | None = Field(None, description="news: the outlet, e.g. 'Katadata'; notif: the app name "
                                                 "('m-banking', 'Shopee').")
    date: str | None = Field(None, description="news: the date as shown, e.g. 'Jumat, 16 Okt 2026'; notif: the "
                                               "corner note ('bulan ke-12', '09.41').")
    url: str | None = Field(None, description="screenshot: the page to capture (http/https).")
    wayback: str | None = Field(None, description="screenshot: capture the Wayback Machine copy from this date "
                                                  "(YYYY or YYYYMMDD), for pages as they looked back then.")
    selector: str | None = Field(None, description="screenshot: CSS selector of the part to capture (unset = the "
                                                   "top of the page).")
    stat: str | None = Field(None, description="person: a short stat under the name, e.g. '+499,50%'; notif: "
                                               "the big amount ('Rp4,54 jt').")
    bars: list[StageBar] = Field(default_factory=list, max_length=4, description="bar: 2-4 bars, left to right.")
    steps: list[MotionStep] = Field(default_factory=list, max_length=10,
                                    description="Motion components: the beats, in narration order.")
    max: float | None = Field(None, gt=0, description="meter: the full-scale value.")
    count: int | None = Field(None, ge=2, le=8, description="stack: how many icons pile up (default 4).")
    target: int | None = Field(None, ge=1, description="highlight: number (1-based) of the earlier element in "
                                                       "this scene to box.")
    pos: StagePos | None = Field(None, description="Slot on the stage: t/m/b (top/middle/bottom) + l/c/r. "
                                                   "Unset = automatic layout.")
    size: Literal["s", "m", "l"] | None = Field(None, description="Unset = by how many elements share the stage.")
    clear: bool = Field(False, description="Clear the stage (earlier elements leave) before this one enters.")

    @model_validator(mode="after")
    def _kind_fields(self) -> StageElement:
        for opts in _STAGE_NEEDS[self.kind]:
            if not any(getattr(self, f) for f in opts):
                raise ValueError(f"stage element kind={self.kind!r} requires {' or '.join(opts)}")
        if self.steps and self.kind not in COMPONENTS:
            raise ValueError(f"`steps` are for motion components ({', '.join(COMPONENTS)})")
        if self.kind in COMPONENTS:
            lo, hi, valued = STEP_RULES[self.kind]
            if not lo <= len(self.steps) <= hi:
                raise ValueError(f"a {self.kind} takes {lo}-{hi} steps")
            if valued and any(st.value is None for st in self.steps):
                raise ValueError(f"every {self.kind} step needs a `value`")
            if self.kind == "meter" and any(st.value > self.max for st in self.steps):
                raise ValueError("meter step values can't be more than `max`")
            if self.kind == "reel" and sum(st.accent for st in self.steps) != 1:
                raise ValueError("a reel needs exactly one `accent` step (the option it lands on)")
        if self.kind == "bar" and len(self.bars) < 2:
            raise ValueError("a bar element needs 2-4 bars")
        if (self.brief or self.own) and self.kind not in MEDIA:
            raise ValueError(f"`brief` / `own` are for {'/'.join(MEDIA)} elements")
        if self.label and self.kind not in LABELLED:
            raise ValueError(f"`label` is for {'/'.join(LABELLED)} elements (use kind=label for a lone tag)")
        if self.ticker and not self.start:
            raise ValueError("a chart `ticker` needs `start` (YYYY-MM-DD)")
        if self.kind == "chart" and sum(map(bool, (self.points, self.csv, self.ticker))) > 1:
            raise ValueError("a chart takes one of points, csv or ticker")
        if self.kind == "chart" and self.points and len(self.points) < 2:
            raise ValueError("a chart needs at least 2 points")
        if self.kind == "unit" and self.filled is not None and self.filled > self.total:
            raise ValueError("unit `filled` can't be more than `total`")
        if self.url and not self.url.startswith(("http://", "https://")):
            raise ValueError("screenshot `url` must start with http:// or https://")
        return self


BackdropKind = Literal["photo", "screenshot", "board", "phone"]


class Backdrop(_Strict):
    """A themed set behind a stage scene's props, instead of a plain built-in `background`: a real
    place (photo), a web page, a market board or a phone screen."""
    kind: BackdropKind = Field(description="photo = a full-screen photo of a place or surface (stock `query`, "
                                           "Wikipedia `who` for a painting/map, or your `path`), darkened so props "
                                           "read on it; screenshot = a web page (`url`, optional `wayback`) filling "
                                           "the frame; board = a dense market/departure board of `items` "
                                           "('BBCA -2,1%'), tinted; phone = a phone app screen with a `title` "
                                           "header (pair it with notif elements).")
    query: str | None = Field(None, description="photo: English keywords for a place or surface, 2-4 words "
                                                "('old apothecary shelves', 'vintage world map', 'trading floor').")
    who: str | None = Field(None, description="photo: a Wikipedia article whose lead image is the set (a painting, "
                                              "an old map, a building).")
    path: str | None = Field(None, description="photo: your own image (repo-relative).")
    brief: str | None = Field(None, description="photo: the ideal backdrop in a few Indonesian words, for the "
                                                "photo brief.")
    url: str | None = Field(None, description="screenshot: the page (http/https).")
    wayback: str | None = Field(None, description="screenshot: the Wayback Machine copy from this date (YYYY or "
                                                  "YYYYMMDD).")
    items: list[str] = Field(default_factory=list, max_length=40,
                             description="board: 4-40 short cells ('BBCA -2,1%', 'GOTO +4,8%', 'CGK 09.40'); a "
                                         "'-' / '+' number colours the cell red / green. Repeated to fill.")
    title: str | None = Field(None, description="phone: the small header line ('autodebet · tgl 5 Jan'); "
                                                "board: an optional header ('IDX · 15 Okt 2026').")
    dim: float | None = Field(None, ge=0, le=0.9, description="How much the set is darkened (0-0.9); unset = "
                                                              "klip.yaml stage.backdrop.<kind>.dim.")
    blur: float | None = Field(None, ge=0, le=30, description="photo/screenshot: blur in px; unset = the kind's default.")
    tint: str | None = Field(None, description="A colour wash over the set, e.g. '#7A0F14' (a red market crash); "
                                               "unset = none.")
    tone: Literal["light", "dark"] | None = Field(None, description="Whether the set reads as light or dark "
                                                                    "(title and tag colours); unset = the kind's default.")

    @model_validator(mode="after")
    def _kind_fields(self) -> Backdrop:
        need = {"photo": ("query", "who", "path"), "screenshot": ("url",), "board": ("items",), "phone": ()}[self.kind]
        if need and not any(getattr(self, f) for f in need):
            raise ValueError(f"backdrop kind={self.kind!r} requires {' or '.join(need)}")
        if self.kind == "board" and len(self.items) < 4:
            raise ValueError("a board backdrop needs at least 4 items")
        if self.url and not self.url.startswith(("http://", "https://")):
            raise ValueError("backdrop `url` must start with http:// or https://")
        if self.tint and not re.fullmatch(r"#[0-9a-fA-F]{6}", self.tint):
            raise ValueError("backdrop `tint` must be a #RRGGBB colour")
        return self


CodeLib = Literal["three"]
Texture = Literal["none", "paper", "watercolor", "halftone", "grain", "hud", "riso", "film"]


class CodeSfx(_Strict):
    """A sound effect on a code scene's beat."""
    at: str = Field(min_length=1, description="Narration word (or phrase) the effect lands on, as in k.at().")
    sfx: str = Field(min_length=1, description="Effect name: a file in klip.yaml sfx.dir (whoosh, pop, ding, riser, "
                                               "hit).")
    offset_s: float = Field(0.0, ge=-3, le=3, description="Shift from the word (s); a riser that should END on "
                                                          "the word takes about -1.")


class CodeScene(_Strict):
    """A scene whose look and motion are code Claude writes (see docs/CODE-SCENES.md): markup, <style>
    and one <script> that animates on the scene kit `k` (a GSAP timeline at the scene's start, the
    narration's word times, the look bible)."""
    file: str = Field(pattern=r"\.html$", description="Repo-relative scene file, e.g. 'specs/<slug>/s1.html'.")
    assets: list[str] = Field(default_factory=list, max_length=20,
                              description="Repo-relative files the scene uses (images, SVGs); reference them as "
                                          "'@asset/<file name>' in markup, CSS or JS.")
    include: list[str] = Field(default_factory=list, max_length=8,
                               description="Repo-relative .js files run before the scene's script, inside it "
                                           "(with `k`): helpers and motifs shared by several scenes.")
    libs: list[CodeLib] = Field(default_factory=list, description="Extra libraries: 'three' = Three.js as "
                                                                  "k.lib.THREE.")
    captions: bool = Field(True, description="false = no captions on this scene (it shows its own words, e.g. "
                                             "kinetic type).")
    texture: Texture | None = Field(None, description="This scene's texture instead of the look bible's.")
    sfx: list[CodeSfx] = Field(default_factory=list, max_length=12,
                               description="Sound effects on this scene's own beats (the stamp, the bar filling, "
                                           "the pop), on top of the automatic cut whoosh.")


class World(_Strict):
    """One code layer under a run of consecutive code scenes (see docs/CODE-SCENES.md, "One world"): a single
    picture the camera travels through while the scenes change on top, instead of a cut per scene. Its
    `k` spans the run: k.words / k.at cover every scene's narration, k.scenes says when each one plays."""
    file: str = Field(pattern=r"\.html$", description="Repo-relative world file, e.g. 'specs/<slug>/world.html'.")
    scenes: list[str] = Field(default_factory=list, description="Ids of the consecutive code scenes it runs under; "
                                                                "empty = every code scene (they must be consecutive).")
    assets: list[str] = Field(default_factory=list, max_length=20, description="As in a code scene.")
    include: list[str] = Field(default_factory=list, max_length=8, description="As in a code scene.")
    libs: list[CodeLib] = Field(default_factory=list, description="As in a code scene.")


class Visual(_Strict):
    type: VisualType = "solid"
    query: str | None = Field(None, description="English keywords for stock search (the scene's first shot).")
    beats: list[Beat] = Field(default_factory=list, max_length=5,
                              description="Later shots of this scene, in narration order, each cut in on a word "
                                          "with its own clip. Preferred over `queries`.")
    queries: list[str] = Field(default_factory=list, max_length=3,
                               description="Legacy: extra English queries for later shots, cut on a timer. "
                                           "Use `beats` instead.")
    max_shots: int | None = Field(None, ge=1, le=6, description="Cap the cuts in this scene; 1 = a single shot.")
    name: str | None = Field(None, description="Lucide icon name, e.g. 'brain'.")
    bg: Literal["solid", "gradient"] = "gradient"
    path: str | None = Field(None, description="Local clip/photo path (type=local).")
    prompt: str | None = Field(None, description="Image prompt (type=ai_image).")
    background: str | None = Field(None, description="type=stage: 'grid' (dot-grid paper), 'studio' (wall over a "
                                                     "light desk), 'spotlight' (dark desk under a light), or the "
                                                     "older 'desk', 'paper', 'kraft', 'board' (see klip.yaml "
                                                     "stage.backgrounds), or a repo-relative image path. "
                                                     "Unset = stage.default_background.")
    backdrop: Backdrop | None = Field(None, description="type=stage: a themed set instead of `background` (a real "
                                                        "place, a web page, a market board, a phone screen). Vary "
                                                        "sets across the video as the story moves.")
    elements: list[StageElement] = Field(default_factory=list, max_length=12,
                                         description="type=stage: props that build up on the background, each "
                                                     "popping in on its narration word, in narration order.")
    code: CodeScene | None = Field(None, description="type=code: the scene file and its options.")

    @model_validator(mode="after")
    def _required_fields(self) -> Visual:
        need = {"icon": "name", "stock_video": "query", "stock_photo": "query",
                "local": "path", "ai_image": "prompt", "code": "code"}.get(self.type)
        if need and not getattr(self, need):
            raise ValueError(f"visual.type={self.type!r} requires visual.{need}")
        if self.beats and self.queries:
            raise ValueError("use either visual.beats or visual.queries, not both")
        if self.beats and self.type not in ("stock_video", "stock_photo"):
            raise ValueError("visual.beats is only for stock_video / stock_photo scenes")
        if self.type == "stage":
            if not self.elements:
                raise ValueError("visual.type='stage' requires visual.elements")
            self._check_stage()
            if self.backdrop and self.background:
                raise ValueError("use either visual.background or visual.backdrop, not both")
        elif self.elements or self.background or self.backdrop:
            raise ValueError("visual.elements / visual.background / visual.backdrop are only for visual.type='stage'")
        if self.code and self.type != "code":
            raise ValueError("visual.code is only for visual.type='code'")
        return self

    def _check_stage(self) -> None:
        page_start, on_stage = 0, 0
        for i, e in enumerate(self.elements):
            if e.clear:
                page_start, on_stage = i, 0
            if e.kind == "highlight":
                t = e.target - 1
                if not page_start <= t < i:
                    raise ValueError(f"elements[{i}] highlight target {e.target} must be an earlier element "
                                     f"still on the stage (after the last clear)")
                if self.elements[t].kind == "highlight":
                    raise ValueError(f"elements[{i}] highlight target {e.target} is itself a highlight")
                continue
            on_stage += 1
            if on_stage > 6:
                raise ValueError(f"elements[{i}]: at most 6 elements on the stage at once; set clear: true "
                                 f"on one to start a fresh stage")


class LookFonts(_Strict):
    """Font keys from klip.yaml code.fonts (e.g. 'jakarta', 'fraunces', 'fredoka', 'anton', 'mono')."""
    display: str | None = Field(None, description="Headlines and big type.")
    body: str | None = Field(None, description="Labels and small text.")
    mono: str | None = Field(None, description="Numbers, HUD readouts, code.")
    caption: str | None = Field(None, description="The word-synced captions (all scenes).")


class LookBible(_Strict):
    """Art direction shared by every code scene so the video reads as one film. Unset fields come from
    the style's look_bible (brand pack), then klip.yaml code.look."""
    preset: str | None = Field(None, description="A named look to start from (klip.yaml code.looks, e.g. "
                                                 "'cinematic': dark, hairline, glowing accent, film grain). "
                                                 "The fields below override it.")
    palette: dict[str, str] = Field(default_factory=dict, description="Named colours ('bg', 'ink', 'accent', "
                                                                      "'paper', 'sky', …) → CSS vars --k-<name> "
                                                                      "and k.look.palette. 'bg' fills the scene.")
    fonts: LookFonts = Field(default_factory=LookFonts)
    texture: Texture | None = Field(None, description="Overlay on every code scene: paper (fibres + vignette), "
                                                      "watercolor (wash blotches), halftone (dot screen), grain "
                                                      "(film grain), hud (scanlines + corner marks), riso (misprint "
                                                      "grain), film (grain + dark vignette, for dark looks), none.")
    texture_strength: float | None = Field(None, ge=0, le=1, description="0-1; unset = the texture's default.")
    line: float | None = Field(None, ge=0.5, le=24, description="Stroke width (px) for drawn art: k.look.line.")
    motion: Literal["snappy", "smooth", "bouncy", "cinematic"] | None = Field(None, description="Default eases in "
                                                                                          "k.look.ease.")
    notes: str | None = Field(None, description="Art direction in prose for whoever writes the scenes (style, "
                                                "characters, camera, motifs). Not rendered.")

    @model_validator(mode="after")
    def _colours(self) -> LookBible:
        for k, v in self.palette.items():
            if not re.fullmatch(r"[a-z][a-z0-9-]*", k):
                raise ValueError(f"look_bible.palette key {k!r}: use lowercase letters, digits and '-'")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                raise ValueError(f"look_bible.palette.{k} must be a #RRGGBB colour")
        return self


class Stat(_Strict):
    value: float = Field(description="Number the counter animates to, e.g. 34 or 1.5.")
    prefix: str = Field("", description="Shown before the number, e.g. 'Rp'.")
    suffix: str = Field("", description="Shown after the number, e.g. '%' or ' menit'.")
    decimals: int = Field(0, ge=0, le=2)
    label: str | None = Field(None, description="Line under the number; defaults to on_screen_text.")


class Side(_Strict):
    label: str = Field(description="Column title, e.g. 'Power nap'.")
    text: str | None = Field(None, description="One short line under the title.")
    icon: str | None = Field(None, description="Lucide icon name.")


class Compare(_Strict):
    left: Side
    right: Side


class MascotPose(_Strict):
    """A mascot changes pose (expression) on a narration word."""
    who: str = Field(min_length=1, description="Mascot name from the style's mascot cast, e.g. 'napa'.")
    pose: str = Field(min_length=1, description="Pose file name in that mascot's folder, e.g. 'kaget', 'paham', "
                                                "'kepo', 'bingung', 'tunjuk'.")
    at: str | None = Field(None, description="Narration word where the pose starts; unset = the scene's start.")
    hold_s: float | None = Field(None, gt=0, le=20, description="Back to the neutral pose after this long; unset "
                                                               "= until the next pose or the scene's end.")


class SceneMascot(_Strict):
    """The style's mascots (a brand pack's cast) in this scene."""
    speaker: str | None = Field(None, description="Who speaks this scene's narration (mouth moves with the words); "
                                                  "unset = the style's default for the template; 'none' = nobody.")
    poses: list[MascotPose] = Field(default_factory=list, max_length=12,
                                    description="Pose changes in narration order (on top of automatic reactions).")
    hide: bool = Field(False, description="No mascots in this scene.")
    show: list[str] | None = Field(None, description="Only these mascots appear in this scene (e.g. ['napa'] "
                                                     "to introduce one); unset = all of the video's mascots.")
    scale: float = Field(1.0, ge=0.5, le=2.2, description="Mascot size in this scene (2 = twice as tall, for "
                                                          "a scene about the mascots themselves); the props "
                                                          "area shrinks to make room.")


class Scene(_Strict):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    template: TemplateName
    narration: str = Field(min_length=1, description="Spoken text; also what captions display.")
    tts_override: str | None = Field(None, description="Optional spoken version, e.g. 'wai fai' for 'WiFi'.")
    on_screen_text: str | None = None
    visual: Visual = Field(default_factory=Visual)
    emphasis: list[str] = Field(default_factory=list, description="Words/phrases to color with the emphasis color.")
    voice: VoiceName | None = Field(None, description="This scene's narrator when it differs from the video's "
                                                      "`voice` (a dialogue: alternate male and female). Unset = "
                                                      "the voice of the scene's mascot speaker if one is set, "
                                                      "else the video's voice.")
    delivery: Delivery | None = Field(None, description="Voice style for this scene (rate/pitch preset in "
                                                        "klip.yaml prosody); unset = by template.")
    # Template-specific data
    list_index: int | None = Field(None, ge=1, description="list_item: number shown; auto-numbered if unset.")
    list_total: int | None = Field(None, ge=1, description="list_item: total shown ('1/3'); auto if unset.")
    myth: str | None = Field(None, description="myth_fact: the myth (short).")
    fact: str | None = Field(None, description="myth_fact: the fact (short).")
    reveal_at: str | None = Field(None, description="myth_fact: narration word at which the fact card appears "
                                                    "(default: ~45% into the scene).")
    stat: Stat | None = None
    compare: Compare | None = None
    mascot: SceneMascot | None = Field(None, description="Mascots (only when the style has a mascot cast): who "
                                                         "speaks and pose changes.")
    cta_type: CtaType | None = Field(None, description="cta: what the outro asks for; shows an action chip "
                                                       "(icon + label). 'comment' = on_screen_text is a "
                                                       "two-sided question shown as the headline.")

    @model_validator(mode="after")
    def _template_data(self) -> Scene:
        need = {"myth_fact": ("myth", "fact"), "stat": ("stat",), "compare": ("compare",)}.get(self.template, ())
        missing = [f for f in need if getattr(self, f) is None]
        if missing:
            raise ValueError(f"template {self.template!r} requires: {', '.join(missing)}")
        if self.cta_type and self.template != "cta":
            raise ValueError("cta_type is only for the 'cta' template")
        return self


class HookVariant(_Strict):
    """An alternative first scene for A/B testing; unset fields keep the main hook's."""
    narration: str = Field(min_length=1)
    on_screen_text: str | None = None
    tts_override: str | None = None
    visual: Visual | None = None
    emphasis: list[str] = Field(default_factory=list)


class Music(_Strict):
    mood: str | None = Field("calm", description="Picks a track from assets/music/<mood>/; null = no music.")
    track: str | None = Field(None, description="Explicit track path (overrides mood).")
    beats: bool = Field(True, description="Code scenes follow the track's beats (k.beats, k.pulse). Turn off for "
                                          "a track without a steady beat (ambient, orchestral swells).")


class Post(_Strict):
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)


class Cover(_Strict):
    lines: list[str] = Field(default_factory=list, max_length=3,
                             description="Title as 2-3 explicit lines; the last line is the keyword "
                                         "(bigger, accent colour). Use this or title + keyword.")
    title: str | None = Field(None, description="Title lead-in (3-5 words, wraps to max 2 lines), "
                                                "e.g. 'Kenapa Kita Ikut Ikutan'.")
    keyword: str | None = Field(None, description="The payoff word(s) shown big as the last line, e.g. 'Menguap?'.")
    subtitle: str | None = Field(None, description="One short sentence under the title, e.g. "
                                                   "'Ternyata bukan karena bosan'.")
    layout: Literal["hero", "text"] | None = Field(
        None, description="hero = short title on top, a big subject (cut-out photo and/or mascot) below; "
                          "text = title only. Unset: hero whenever there is a subject.")
    image: str | None = Field(None, description="Hero photo path (relative to the repo), cut out as a "
                                                "sticker. Unset: <photos dir>/<slug>/cover.*, the hook's stage "
                                                "cut-out, another scene's, else the subject lifted from the "
                                                "hook's b-roll.")
    mascot: str | None = Field(None, description="Mascot pose on the cover (e.g. 'kaget', 'bingung'), or "
                                                 "'none'. Unset: klip.yaml cover.hero.mascot_pose.")
    who: str | None = Field(None, description="Which cast member is on the cover. Unset: the hook's speaker.")
    badge: str | None = Field(None, max_length=18,
                              description="1-2 word sticker on the hero, e.g. 'MITOS?', '1 DETIK', "
                                          "'350 TAHUN'. Teases, never answers.")

    @model_validator(mode="after")
    def _one_title_form(self) -> Cover:
        if self.lines and (self.title or self.keyword):
            raise ValueError("cover: give either `lines` or `title`/`keyword`, not both")
        if len(self.lines) == 1:
            raise ValueError("cover.lines needs 2-3 lines (the last one is the keyword); "
                             "for one line use `keyword`")
        return self


class Fact(_Strict):
    claim: str
    source: str


class Spec(_Strict):
    version: Literal[1] = 1
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    language: str = "id-ID"
    voice: VoiceName = "female"
    speech_rate: str | None = Field(None, pattern=r"^[+-]\d{1,3}%$",
                                    description="e.g. '+8%'. Unset = per-voice default in klip.yaml.")
    target_duration_s: int = Field(45, ge=10, le=120)
    style: str = "default"
    series: str | None = Field(None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
                               description="Series key, e.g. 'kenapa'; shown as a pill (label from the style's "
                                           "series_pill.labels, else the key in capitals).")
    episode: int | None = Field(None, ge=1, description="Episode number shown on the series pill ('#12').")
    look: LookName = Field("mixed", description="'stage' = illustrated explainer look: most hook/explain/"
                                                 "list_item scenes use visual.type 'stage' (share in klip.yaml "
                                                 "stage.look_min_share). 'mixed' = pick per scene.")
    look_bible: LookBible | None = Field(None, description="Art direction for code scenes (palette, fonts, "
                                                           "texture, motion); unset = the style's.")
    world: World | None = Field(None, description="One code layer the camera travels through under a run of "
                                                  "consecutive code scenes (their own bg turns transparent).")
    mascots: bool | list[str] | None = Field(None, description="Which of the style's mascots appear: unset/true = "
                                                               "the whole cast, false = none, or a list of names "
                                                               "(e.g. ['napa']).")
    progress_bar: bool | None = Field(None, description="Thin progress bar at the top; unset = the style's setting. "
                                                        "Set false/true to A/B test it.")
    save_nudge: bool | None = Field(None, description="'Simpan dulu' pill when the 2nd list_item starts; "
                                                      "unset = the style's save_nudge.enabled.")
    music: Music = Field(default_factory=Music)
    scenes: list[Scene] = Field(min_length=1, max_length=12)
    post: Post = Field(default_factory=Post)
    cover: Cover | None = Field(None, description="Designed cover.png (profile grid thumbnail); unset = built "
                                                  "from the hook's on_screen_text (emphasised end = keyword).")
    facts: list[Fact] = Field(default_factory=list)
    sfx: bool = Field(True, description="Sound effects on cuts, reveals, badges (see klip.yaml sfx).")
    hook_variants: list[HookVariant] = Field(
        default_factory=list, max_length=4,
        description="Alternative hooks (scene 1) for A/B testing; `klip render --variants` renders each.")

    @model_validator(mode="after")
    def _unique_scene_ids(self) -> Spec:
        ids = [s.id for s in self.scenes]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate scene ids: {sorted(dupes)}")
        return self

    @model_validator(mode="after")
    def _variants_need_hook(self) -> Spec:
        if self.hook_variants and self.scenes[0].template != "hook":
            raise ValueError("hook_variants requires the first scene to use the 'hook' template")
        return self

    def with_hook_variant(self, i: int) -> Spec:
        """This spec with scene 1 replaced by hook_variants[i] (variants themselves dropped)."""
        v = self.hook_variants[i]
        hook = self.scenes[0].model_copy(update={
            "narration": v.narration, "tts_override": v.tts_override,
            "on_screen_text": v.on_screen_text if v.on_screen_text is not None else self.scenes[0].on_screen_text,
            "visual": v.visual or self.scenes[0].visual, "emphasis": v.emphasis})
        return self.model_copy(update={"scenes": [hook, *self.scenes[1:]], "hook_variants": []})

    @property
    def word_count(self) -> int:
        return sum(len(s.narration.split()) for s in self.scenes)


def load_spec(path: str | Path) -> Spec:
    return Spec.model_validate_json(Path(path).read_text(encoding="utf-8"))


def export_schema() -> dict:
    schema = Spec.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Klip scene spec"
    return schema


def write_schema(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(export_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
