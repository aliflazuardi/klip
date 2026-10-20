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
   ("pakai stage", "gaya ilustrasi"), else leave it unset (mixed).
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
  (klip.yaml `stage.look_min_share`) of the hook/explain/list_item scenes, keep them on one
  background so the stage carries across cuts, and keep stock footage for the few moments a real
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
    older textured `desk`, `paper`, `kraft`, `board`, or an image path. Use it for scenes about money,
    numbers, causes and effects, or things stock footage shows badly (local food, Indonesian
    institutions). Kinds: `cutout` (`query` = one English object/person, e.g. "soybeans",
    "stressed businessman"; background removed, sticker look), `photo` (photo card), `icon`
    (Lucide `name`), `label` (`text`, 1–4 words), `number` (`text` as shown, ≤ 9 chars, e.g.
    "-11%", "Rp18rb"; `tone` up/down colours it), `bar` (2–4 `bars` `{label, value, text}`),
    `stack` (`name` × `count`, e.g. coins piling up), `highlight` (yellow box around element
    number `target`), `stamp` (`text`, 1–2 words, a rubber-stamp verdict like "BERHASIL" or
    "PALSU"; `tone` up/down colours it). `cutout`/`photo`/`icon`/`logo`/`screenshot` take a short
    `label` tag.
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
    Rules: one element per narration subject, every ~1–2 s; `at` words in narration order.
    **Fewer, bigger props read better:** the layout is automatic and composes by count: one
    prop is a big centred hero; a photo/chart + a tag or number becomes hero + tag; three with
    one photo first become hero + two small; 4–6 shrink to a grid. Aim for 1–3 props per stage
    page and `"clear": true` to start the next page rather than piling up 6 small ones (`pos`
    tl…br only to force a place). Works with `hook`, `explain` and `list_item` (the
    on_screen_text becomes a left-aligned title with the `emphasis` words marked). Keep consecutive stage scenes on the same
    background: it stays on screen and only the props change. Example: narration "Rupiah
    melemah, jadi barang impor mahal: kedelai, pakan ayam, dan BBM" → `{"type": "stage",
    "background": "grid", "elements": [{"at": "Rupiah", "kind": "stack", "name": "coins"},
    {"at": "impor", "kind": "number", "text": "Rp18rb", "tone": "down"}, {"at": "kedelai",
    "kind": "cutout", "query": "soybeans", "label": "Kedelai", "clear": true}, {"at": "pakan",
    "kind": "cutout", "query": "chicken"}, {"at": "BBM", "kind": "icon", "name": "fuel", "label":
    "BBM"}]}`. Stock search is weak for Indonesian food: prefer an icon, or `path` to the
    user's own photo, when a prop must be exactly right.
  - `icon`: Lucide `name` (check `renderer/node_modules/lucide-static/icons/<name>.svg`).
    Good for the CTA and for abstract ideas with no good footage.
  - `local`: `path` to the user's own clip. Use it when they mention their own footage.
    `assets/broll/` is also searched automatically by tags.
  - `solid`: gradient background. `ai_image` currently becomes a stock photo (`prompt` is
    used as the query).
- After rendering, check the `assets:` lines in the output and the warnings. If a scene
  fell back to an icon or got an off-topic clip, suggest a better query. For stage scenes,
  look at `projects/<slug>/media/<scene>_el<n>.*` (the cut-outs) the same way.

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
