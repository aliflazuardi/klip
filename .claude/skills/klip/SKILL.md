---
name: klip
description: Turn an Indonesian topic prompt into a finished TikTok video (1080x1920 MP4 with voiceover and word-synced captions) using the Klip pipeline in this repo. Use when the user says /klip, "buat video tentang …", "make a TikTok about …", or asks to render a Klip spec.
argument-hint: '"topik" [--voice male|female] [--duration 30-60]'
---

# Klip: prompt → TikTok video

You are the script writer. You write a **scene spec JSON**, the user reviews it, then the
pipeline renders it. The spec is the contract: re-rendering the same spec gives the same video.

## Flow

1. **Parse the request.** Topic (Indonesian), voice (`male` = Ardi, `female` = Gadis; default
   `female`; "suara cowok" = male, "suara cewek" = female), target duration (default 45 s, max 120),
   and the look: "stage" if the user asks for the stage / illustrated / collage / 90secondslab look
   ("pakai stage", "gaya ilustrasi"), else leave it unset (mixed). If they want a designed,
   motion-graphic video, use code scenes (see "Director mode" below).
2. **Read the contract** if you haven't this session: `schema/spec.schema.json` and the golden
   example `examples/menguap.json`.
3. **Research the facts** for health / science / finance claims and put each one in `facts[]`
   with a real source URL. Don't cite anything you can't point to.
4. **Write the spec** to `specs/<slug>.json` (slug = kebab-case of the topic, ASCII only).
5. **Validate**: `uv run klip validate specs/<slug>.json --voice <voice>`. Fix every error, and
   adjust word count until the estimated duration is within ±15% of the target.
6. **Review gate — stop and show the user** the script: each scene's narration and on-screen
   text, the estimated duration, and the facts with sources. Ask for approval or edits.
   Do not render before the user says yes (skip only if they explicitly said not to review).
   **Stage videos: also send the photo brief.** Run `uv run klip photos specs/<slug>.json`
   (~1–3 min: stock search + vision check, no voice or render) and show the user the props under
   "Perlu foto" and "Bisa lebih bagus" in `projects/<slug>/photo-brief.md`: what each photo
   should show and the file name to save in `specs/photos/<slug>/`. They can drop photos in
   (or say "pakai stock saja"); the render picks the files up automatically.
7. **Render** (about 2–2.5 min for 45 s; run it in the background):
   `uv run klip render specs/<slug>.json --voice <voice>`
   Outputs land in `projects/<slug>/`: `final.mp4`, `cover.png` (designed cover), `post.txt` (with b-roll
   credits), `credits.json`.
8. **Report** the paths, the duration, and the TikTok caption from `post.txt`. Remind the user
   to enable TikTok's AI-generated content label (the voice is synthetic).

**Several topics at once?** Write a YAML file (see `examples/batch.yaml`), run
`uv run klip batch topics.yaml --scripts-only`, show the user the specs, then render with
`uv run klip batch topics.specs.yaml` (in the background; ~3–4 min per video).

If `klip render` fails, run `uv run klip doctor` and fix what it reports. `klip run <stage>`
reruns a single stage (voice | assets | compose | render | post | qa).

**QA:** `klip render` ends with a QA report and exits 1 if a check fails. Fix the cause (e.g.
duration out of range → shorten/lengthen narration or adjust `target_duration_s`) and
re-render; unchanged stages are cached. Tell the user about any check you couldn't fix.

## Director mode: scenes you code (visual.type "code")

When the user wants the video designed shot by shot (an illustrated story, characters acting out
the lines, kinetic type, 3D, "kayak video motion graphic", "bikin kayak video Opus yang viral",
"mode sutradara"), write **code scenes**. Read `docs/CODE-SCENES.md` first: it is the contract
(the scene kit `k`, what is forbidden) and the craft notes. In short:

1. Write the script as usual (narration, facts, `template` per beat), then a **`look_bible`**:
   4–7 named colours with one accent, fonts (`jakarta`, `fraunces`, `fredoka`, `anton`, `mono`),
   a texture, `motion`, and `notes` that fix the art direction (style, the recurring character,
   the motif, the camera). A brand pack's style may already give one.
2. Each code scene gets `"visual": {"type": "code", "code": {"file": "specs/<slug>/<id>.html"}}`;
   start by copying the closest starter from `examples/code-scenes/starters/` (see the doc's table)
   and you write that file: markup + `<style>` + one `<script>` animating on `k.tl`, every beat on
   `k.at("kata")`. Start from the standard kit (`k.stage`, `k.headline`, `k.cast`, `k.camera`, `k.chip`,
   `k.count`…; see the doc) so type, scrims and mascots are placed for you. Give the scene's big beats a
   sound (`code.sfx`: `{at, sfx}`; mascots can act: `rig.walk/enter/exit/jump/point/nod`, within the
   brand's mascot rules; a stamp → hit, a pop-in → pop, a number landing → ding). A new picture per line; characters and props move on the words; the camera
   moves; nothing important outside `k.safe`.
3. `uv run klip validate specs/<slug>.json` (also lints the scene files), then
   `uv run klip preview specs/<slug>.json` and **read every contact sheet** in
   `projects/<slug>/preview/`. Fix and re-preview a scene with `-s <id>` until each still shows
   what the voice says at that moment. Two or three rounds per scene is normal.
   `klip preview` also prints Claude's review of each sheet (score, issues, fixes; `preview/review.json`):
   fix the real ones, then re-preview. Previews use a free draft voice (no Gemini quota) unless the final takes are already cached;
   only `klip render` records the real voice, so preview as often as you like.
4. At the review gate, show the script **and the preview sheets**. Render after approval.

Code scenes mix with template and stage scenes; the cta can stay a template scene (the style's
outro). A brand's rules (voice, sign-off, series, hashtags) still apply.

## What this build can render (Phase 3)

- Templates (pick the one that fits each beat; vary them, since a whole video of `explain` is dull):
  - `hook`: always the first scene. `on_screen_text` 2–5 punchy words.
  - `explain`: the default for narration. `on_screen_text` is a short headline.
  - `list_item`: tips ("Satu, …", "Dua, …"). Use 2–4 **consecutive** list_item scenes; numbering
    and "1/3" are automatic. `on_screen_text` = the tip in ≤ 5 words.
  - `myth_fact`: requires `myth` and `fact` (each ≤ 8 words). Narration states the myth, then
    "Faktanya, …". Set `reveal_at` to that word ("Faktanya,") so the fact card appears on cue.
  - `stat`: requires `stat: {value, suffix?, prefix?, decimals?, label?}`. One striking number,
    e.g. `{"value": 20, "suffix": " menit", "label": "durasi ideal tidur siang"}`. The number
    must appear in the narration and be backed by `facts[]`.
  - `compare`: requires `compare: {left: {label, text?, icon?}, right: {...}}`. Labels ≤ 3 words,
    text ≤ 3 words. `on_screen_text` is an optional title ("Power nap vs tidur lama").
  - `cta`: always the last scene. Set `cta_type` to pick the ask (see the writing guide):
    `follow` | `save` | `comment` | `share`. It adds an action chip (icon + "Follow" / "Simpan" /
    "Komen di bawah" / "Kirim ke teman") under the headline; for `comment`, `on_screen_text` is
    the question and becomes the headline. How the cta looks is the style's `outro.mode`
    (klip.yaml / brand.yaml): `card` (an end card), `overlay` (the previous scene keeps playing
    and a small logo + text + chip badge slides up) or `none`. The cta narration isn't
    captioned (its text is already on screen) unless `outro.captions` is on.
- Look: `"look": "stage"` (set when the user asks for it, or `klip new --stage`) means the
  illustrated explainer look for the whole video: use `visual.type: "stage"` for at least 70%
  (klip.yaml `stage.look_min_share`) of the hook/explain/list_item scenes, keep the scenes of one
  beat on one set so the stage carries across cuts (switch sets with a `backdrop` when the story
  moves to a place, a page, the market or a phone), and keep stock footage for the few moments a real
  shot says it better (often the hook). `stat`, `myth_fact`, `compare` and `cta` scenes keep their
  own cards. `validate` errors if the share is too low. Without `look` (= `"mixed"`), pick per scene.
- Style: leave `"style"` unset (default) unless the user names one or CLAUDE.md / CLAUDE.local.md
  says which to use. `uv run klip styles` lists them (klip.yaml styles and brand packs in
  `brands/<name>/`). A brand pack's series labels come from its `brand.yaml` (`series_pill.labels`).
- Progress bar: the thin bar at the top follows the style (on by default). If the user asks
  for a video without it ("tanpa progress bar", "no progress bar"), set `"progress_bar": false`
  in the spec (or `true` to force it on); otherwise leave it unset.
- Music: leave `music.mood` as "calm" (or another folder name under `assets/music/`); set
  `"mood": null` for no music. If the render says there's no music, mention that the user can
  add tracks to `assets/music/<mood>/`.
- Visuals:
  - `stock_video` (default choice for most scenes) / `stock_photo`: `query` = 2–4 **English**
    words describing a concrete, filmable shot ("woman yawning", "family hugging", "person
    reading book"). Avoid abstract queries ("empathy theory"): stock libraries match
    concrete subjects. **Always add `name`** (a Lucide icon) as a fallback if nothing is found.
  - **Beats (fast cuts):** a clip is never shown twice in a video, so a long scene needs
    several clips. Give every scene longer than ~4 s `beats`: later shots, in narration order,
    each `{at, query}` where `at` is the narration word the cut lands on (the word that names
    what the new clip shows) and `query` is a concrete English stock query for it. Aim for a
    new clip every ~2–3 s (beats closer than 1.4 s are dropped). Example: narration "Rupiah
    melemah, barang impor jadi mahal: kedelai, pakan, sampai BBM" → `query: "rupiah banknotes"`,
    `beats: [{"at": "impor", "query": "container ship port"}, {"at": "kedelai", "query":
    "soybeans closeup"}, {"at": "BBM", "query": "gas station fuel pump"}]`. Pick `at` words where
    the narration changes subject, and vary the subjects: four shots of money read as one long
    shot. A beat with no usable result is skipped (the previous shot runs on), so `validate`
    warns when a scene would rely on one clip for more than ~6 s. Without beats, a scene is cut
    on a timer into as many shots as it has distinct clips. (`queries` is the older, timer-cut
    form; prefer `beats`.) `max_shots: 1` keeps one continuous shot (rarely needed).
  - `stage` (illustrated explainer, 90secondslab style): no stock footage. A persistent
    `background` on which `elements` build up, each popping in on its `at` word and staying.
    Backgrounds: `grid` (dot-grid paper, the default and the calmest), `studio` (a wall over a
    light desk), `spotlight` (a dark desk under a light, for tense or "investigation" beats), the
    older textured `desk`, `paper`, `kraft`, `board`, or an image path.
    **Backdrops: switch the set with the story** (90secondslab never stays on plain paper: an
    apothecary shelf for "rokok dijual di apotek", the red IDX board for an MSCI crash, Kaskus 2010
    for nostalgia, an m-banking screen for KPR instalments, an old map for a card game's history).
    `"backdrop"` replaces `background` on a stage scene: `{"kind": "photo", "query": "old
    apothecary shelves"}` (a place or surface, 2–4 English words; or `who` = a Wikipedia article
    whose lead image is the set: a painting, an old map; or `path`; add `brief` for the photo
    brief, which asks for `<scene>-bg.jpg`), `{"kind": "screenshot", "url": …, "wayback": "2010"}`
    (a page filling the frame), `{"kind": "board", "items": ["BBCA -2,1%", "GOTO +4,8%", …],
    "title": "IDX · 15 Okt 2026"}` (a market/departure board; signed numbers turn green/red; use
    real codes, and numbers only when they are real figures in `facts`, else codes alone), or
    `{"kind": "phone", "title": "autodebet · tgl 5 Jan"}` (an app screen; put `notif` elements on
    it: `outlet` = the app, `text` = the line, `stat` = a big amount, `date` = the corner note;
    they stack down the screen). Optional `dim` (0–0.9), `blur`, `tint` ("#7A0F14" for a red
    crash) and `tone`. On photo/page/board sets the title becomes caps in dark boxes with the
    `emphasis` in an accent box, and the bottom darkens for the captions. Plan 2–4 sets per video,
    one per beat (consecutive scenes on the same backdrop carry it across the cut); `validate` warns
    when 5+ stage scenes share one set. Full example: `examples/backdrops.json`.
    Use stage for scenes about money,
    numbers, causes and effects, or things stock footage shows badly (local food, Indonesian
    institutions). Kinds: `cutout` (`query` = one English object/person, e.g. "soybeans",
    "stressed businessman"; background removed, sticker look), `photo` (photo card), `icon`
    (Lucide `name`), `label` (`text`, 1–4 words), `number` (`text` as shown, ≤ 9 chars, e.g.
    "-11%", "Rp18rb"; `tone` up/down colours it), `bar` (2–4 `bars` `{label, value, text}`),
    `stack` (`name` × `count`, e.g. coins piling up), `highlight` (yellow box around element
    number `target`), `stamp` (`text`, 1–2 words, a rubber-stamp verdict like "BERHASIL" or
    "PALSU"; `tone` up/down colours it). `cutout`/`photo`/`icon`/`logo`/`screenshot` take a short
    `label` tag.
    **Real photos dominate, icons are the exception.** The look is a collage of real things cut
    out with scissors: most object props (≥ 60%, `validate` warns below) are `cutout`/`photo`/
    `person`/`logo`/`screenshot`; keep `icon` for abstract ideas with no photographable object
    ("bisa diatur", "nggak dicek"). Every stage page should have one real photo as its hero.
    For each photo prop also write `brief` (the ideal photo in a few Indonesian words, for the
    photo brief), `name` (a fallback Lucide icon if no photo is found), and `"own": true` when it
    must be exactly right (an Indonesian product, place or app screen) so the user is asked for
    it. Stock search covers Unsplash (with a key), Pexels, Pixabay and Wikimedia Commons (good for
    rupiah, Indonesian places and objects); `query` stays English and short (2–3 words: long
    queries miss the stock tags).
    **Real things beat stock** (90secondslab uses real people, logos, pages and data):
    - `person`: a real person's card: `who` = their Wikipedia article title ("Joko Widodo",
      "Sri Mulyani Indrawati"), `text` = one small line ("2014–2024"), optional `stat` ("+53,95%")
      with `tone`. The photo is the article's lead image, with its licence in the credits. Only
      public figures, in an editorial context; never pair a face with a claim the facts don't
      support. `cutout`/`photo` also take `who` (a cut-out of the real person).
    - `logo`: an organisation's logo on a sign: `who` = its Wikipedia title ("SoftBank Group",
      "Bank Indonesia"). If Wikipedia has no logo the prop is left out (use `path` then).
    - `chart`: a line chart that draws on, from real data: `ticker` (Yahoo Finance: "^JKSE" IHSG,
      "BBCA.JK", "IDR=X" USD/IDR, "BTC-USD") with `start` (and `end`), or `csv` (your file), or
      inline `points` [{x, y}]. `text` = title ("IHSG"); `bands` [{start, end, label}] shade eras
      (terms of office, crises). Line colour follows the trend unless `tone` is set. Cite the data
      source in `facts`.
    - `unit`: `total` squares with `filled` of them highlighted and a legend `text`
      ("1 kotak = 1.000 alat"): for counts and shares people can't picture. Keep total ≤ 200.
    - `news`: a headline card: `outlet`, `date`, `text` (the headline, ≤ 14 words). Only real
      headlines, quoted as published, with the article in `facts`.
    - `screenshot`: a web page in a browser window: `url`, optional `wayback` (YYYY or YYYYMMDD:
      the Wayback Machine copy, for "remember Kaskus in 2010?") and `selector` (capture one part).
    **Motion components** (animated diagrams for the *explaining* beats: numbers, shares, causes,
    processes; they beat a solid background or generic stock). One component usually fills a
    stage page on its own (`"clear": true` before it). Each takes `steps`; a step plays on its own
    `at` word (searched from the element's word on, in order; unset = 0.45 s after the previous)
    and has `text`, optional `value` (sizes it), `show` (the value as shown, "Rp2,5 jt", "30%";
    counts up), `label`, `name` (Lucide icon) and `accent` (the one that matters). Pick by shape:
    - `kinetic`: big type, 1–6 short phrases slamming in (a hook, a punchline). `accent` = marker.
    - `split`: one whole breaking into 2–5 shares (`value`s; `show` defaults to the %): budgets,
      "96% balik, 4% ke bandar", market share. `text` = the whole ("Gaji kamu").
    - `flow`: an amount (`text`, `name`) flowing to 1–4 destinations (`value` = stream width):
      where money/time/goods go.
    - `meter`: a gauge filling to each step's `value` out of `max`, counter showing `show`:
      something accumulating (savings, losses, debt, days). `text` = what's measured.
    - `cycle`: 3–6 steps in a loop with a dot going round: habits, vicious circles, seasons.
    - `timeline`: 2–6 dated events (`label` = date): history, a month's schedule, a story.
    - `funnel`: 2–5 layers narrowing (`value`s): from many to few (applicants → hired, gaji → sisa).
    - `reel`: a slot reel spinning through 3–10 options and landing on the `accent` one (its
      `at` = the word of the answer): "which one is it?" moments.
    Keep step texts to 1–3 words (kinetic phrases ≤ 5). Example: `{"at": "gajimu", "kind": "flow",
    "text": "Rp5 juta", "name": "wallet", "steps": [{"text": "Kebutuhan", "value": 2.5, "show":
    "Rp2,5 jt", "name": "house", "at": "kebutuhan"}, {"text": "Tabungan", "value": 1, "show":
    "Rp1 jt", "name": "piggy-bank", "at": "tabungan", "accent": true}]}`. Full set:
    `examples/motion-components.json`.
    **Mascots** (only when the style's brand pack has a `mascot` cast, e.g. Warga Nalar): they
    stand above the stage captions on every stage scene, mouth the narration of the scene's
    speaker, point at new big props and react to stamps on their own. The spec's `"mascots"`
    picks who appears (`false` = none, `["napa"]` = one; unset = the whole cast; the user may say
    "tanpa maskot" or "cuma Napa"). Each mascot has a voice: a scene narrated in that voice is
    theirs. **Dialogue:** set `"voice": "female"` / `"male"` per scene (or `"mascot": {"speaker":
    "napa"}`, which picks that mascot's voice) so the narration alternates and the mascots take
    turns; consecutive scenes with the same voice are recorded as one natural take. A scene's
    `"mascot"` also takes `poses` [{who, pose, at, hold_s}] (pose =
    a file in the mascot's folder: netral, kepo, kaget, paham, bingung, tunjuk), `hide`. Use poses
    for the beats that matter (a myth landing → `bingung`, the reveal → `paham`); leave the rest
    automatic. They don't show on non-stage scenes. They gesture on their own while speaking
    (leans, nods on emphasised words, listeners nod along, a squash when they land).
    **Cold open (cinematic videos with a `world`):** don't spend the hook on a quiet shot. Put the
    hook in the world's scenes and replay the world's climax under it (docs/CODE-SCENES.md "Cold
    open"), with `k.headline()` and `k.spotlight("<mascot>", {pose: "kaget"})` on top, then hard-cut
    to the story's first shot.
    **Spotlight:** `"mascot": {"focus": true}` (or a name) makes that mascot the star of the
    scene: it slides to the centre, big, under a glow and turning sunburst, gestures more (hops
    on emphasised words) and the others step out. With a picture prop (cutout/photo/chart…) the
    star stands left of centre and the props take the right column; with labels only it stays
    centred and they get a strip above its head. Use it for 1-2 scenes per video: the hook, a
    punchline or a big reaction (pair with a pose like `kaget`); give it 0-2 props.
    Rules: one element per narration subject, every ~1–2 s; `at` words in narration order.
    **Fewer, bigger props read better:** the layout is automatic and composes by count: one
    prop is a big centred hero; a photo/chart + a tag or number becomes hero + tag; three with
    one photo first become hero + two small; 4–6 shrink to a grid. Aim for 1–3 props per stage
    page and `"clear": true` to start the next page rather than piling up 6 small ones (`pos`
    tl…br only to force a place). Works with `hook`, `explain` and `list_item` (the
    on_screen_text becomes a left-aligned title with the `emphasis` words marked). Keep consecutive stage scenes of one beat on
    the same set: it stays on screen and only the props change. Example: narration "Rupiah
    melemah, jadi barang impor mahal: kedelai, pakan ayam, dan BBM" → `{"type": "stage",
    "background": "grid", "elements": [{"at": "Rupiah", "kind": "stack", "name": "coins"},
    {"at": "impor", "kind": "number", "text": "Rp18rb", "tone": "down"}, {"at": "kedelai",
    "kind": "cutout", "query": "soybeans", "label": "Kedelai", "clear": true, "brief": "segenggam
    kedelai kuning", "own": true}, {"at": "pakan", "kind": "cutout", "query": "chicken feed sack",
    "name": "wheat"}, {"at": "BBM", "kind": "cutout", "query": "fuel pump nozzle", "name": "fuel",
    "label": "BBM"}]}`. Stock search is weak for Indonesian food: mark such props `"own": true` (the user
    is asked for the photo) rather than swapping in an icon.
  - `icon`: Lucide `name` (check `renderer/node_modules/lucide-static/icons/<name>.svg`).
    Good for the CTA and for abstract ideas with no good footage.
  - `local`: `path` to the user's own clip. Use it when they mention their own footage.
    `assets/broll/` is also searched automatically by tags.
  - `solid`: gradient background. `ai_image` currently becomes a stock photo (`prompt` is
    used as the query).
- After rendering, check the `assets:` lines in the output and the warnings. If a scene
  fell back to an icon or got an off-topic clip, suggest a better query. For stage scenes,
  look at `projects/<slug>/media/<scene>_el<n>.*` (the cut-outs) the same way, and pass on the
  photo brief line (`Photo brief: …`) if props still want a photo.

## Writing guide

- **Hook first: the first 2 seconds decide everything.** Scene 1 is ≤ 12 words and its
  `on_screen_text` 2–5 punchy words. The first words must already carry the tension; no
  greeting, no "Hai guys", no "Di video ini…". Strong hook types:
  - question that hits a daily experience: "Pernah nggak kamu…?"
  - claim that contradicts a belief: "Minum air dingin bikin gemuk? Salah besar."
  - cost of not knowing: "Kalau kamu nyimpan cabai begini, pantesan cepat busuk."
  - number/list promise: "3 kebiasaan pagi yang diam-diam bikin kamu ngantuk."
- **Open loop:** the hook promises something that is only paid off near the end (the
  answer, "yang ketiga paling penting", the surprising fact). Pay it off in the last content
  scene before the CTA. Never resolve the hook in scene 2.
- **A/B hooks (`hook_variants`):** when asked for hook variants (e.g. `--hooks 3`), add
  alternative first scenes that each use a *different hook type* from the list above, with
  the same payoff so the rest of the video still fits. Each variant: `narration` (≤ 12 words),
  `on_screen_text` (≤ 5 words), optional `emphasis`/`visual`.
- **One idea per video.** 4–6 scenes. Casual Indonesian ("kamu", "nggak", "banget" are fine).
- **Word budget (measured; leave `speech_rate` unset to get the per-voice default):**
  female (Gadis, +15%) ≈ 1.97 words/s, male (Ardi, +8%) ≈ 2.35 words/s. For 45 s: ~85 words
  female, ~100 words male. `klip validate` estimates it.
- **Short sentences**, 1–2 per scene. Each scene's `on_screen_text` is a short headline
  (≤ 6 words), not the narration again.
- `emphasis`: 1–3 key words or phrases per scene, copied exactly as they appear in the
  narration or on-screen text.
- **Delivery** is automatic: hook energetic, stat/myth_fact emphatic, CTA warm, everything else
  neutral. Override a scene with `"delivery"` (`neutral | energetic | emphatic | warm | calm`)
  only when its mood differs, e.g. `calm` for a sad or serious beat, `emphatic` for the payoff.
- `tts_override` only when the TTS mispronounces something (e.g. "Follow" → "Folo"). General
  fixes go in the `lexicon` section of `klip.yaml` (test with `uv run klip say "…"`).
- **Health / finance / safety:** general information only, no individual advice, sources in
  `facts[]`.
- **End with a `cta` scene and pick its `cta_type`.** Comments and saves rank a video higher
  than follows, so prefer them:
  - `comment` when the video has two sides or a choice (compare, myth vs fact, "which do you
    do?"): end on a **two-sided question** anyone can answer in one word, and say it twice: in
    the narration and as `on_screen_text` (≤ 8 words, ends with "?"), e.g. narration "Kamu tim
    kulkas atau tim freezer? Tulis di komentar." + `on_screen_text` "Kamu tim kulkas atau
    freezer?". Not a quiz with one right answer, not "ada pertanyaan?".
  - `save` for tips, steps and lists people will want later ("Simpan biar nggak lupa").
  - `share` when it's useful to someone else ("Kirim ke teman yang suka begadang").
  - `follow` for series or "part 2" teasers ("Follow buat fakta lainnya!").
  One ask per video; the narration must say the same thing the chip shows.
- **Save nudge (automatic):** on list videos (2+ consecutive `list_item`), a "Simpan dulu biar
  nggak lupa" pill pops up when item 2 starts. Don't also say it in the narration. Turn it off
  with `"save_nudge": false` (e.g. when the CTA is already `save`, to avoid asking twice).
- `post.caption`: one sentence plus an emoji. `post.hashtags`: 3–5, including `#edukasi`.
  **Hashtags are always all lowercase** (`#literasikeuangan`, `#ihsg`, never `#LiterasiKeuangan`
  or `#IHSG`), in `post.hashtags`, inside `post.caption` and in any caption variants you write.
  `post.txt` lowercases them anyway (klip.yaml `post.lowercase_hashtags`); `validate` warns.
- **`cover`** (optional; the `cover.png` shown on the profile grid): `title` (3–5 words, the
  lead-in) + `keyword` (1–2 words, the payoff, drawn big in the accent colour), or `lines`
  (2–3 explicit lines, the last is the keyword), plus `subtitle` (one short sentence that adds
  curiosity, not the answer), e.g. `"cover": {"title": "Kenapa Kita Ikut Ikutan", "keyword":
  "Menguap?", "subtitle": "Ternyata bukan karena bosan"}`. Unset → the hook's `on_screen_text`
  (its emphasised ending becomes the keyword) with no subtitle; write one whenever the hook
  text isn't a good title on its own.
  The cover uses the **hero layout** whenever there's a subject: the short title up top, the
  keyword on a tilted accent block, then one big subject (a cut-out photo and/or the brand's
  mascot pulling a face) with an arrow pointing at it and the subtitle as a tag. The subject is
  found on its own (the hook's stage cut-out, another scene's, else the subject lifted from the
  hook's b-roll, else that still as a photo card). Optional extras: `badge` (1-2 words stuck on
  the subject, a tease like `"MITOS?"`, `"1 DETIK"`, `"350 TAHUN"`, never the answer), `mascot`
  (pose: `kaget`, `bingung`, `kepo`… or `"none"`), `who` (which cast member), `image` (your own
  photo, repo-relative; or drop `cover.png`/`cover-*.jpg` in the spec's photo folder) and
  `"layout": "text"` for the old title-only cover. Keep title + keyword to ~3-6 words: the
  cover is read at grid size. Redo just the cover after an edit with `uv run klip cover <spec>`.
