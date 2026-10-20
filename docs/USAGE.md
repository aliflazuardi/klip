# Klip usage reference

Everything Klip can do, in detail. Start with the [README](../README.md) for installation and
the quick start.

## Stock media

| source | what | key |
|---|---|---|
| `assets/broll/` | your own clips/photos, matched by file/folder name ([how](../assets/broll/README.md)) | — |
| Pexels | portrait video + photos | `PEXELS_API_KEY` (optional) |
| Pixabay | video + photos | `PIXABAY_API_KEY` ([free](https://pixabay.com/api/docs/)) |
| Openverse | CC0 / CC BY photos | none |

**Vision check:** before anything is downloaded, Claude looks at a numbered contact sheet of
each scene's candidates (videos *and* photos) and rates them 0–3 against the narration. Only
those rated ≥ 2 are used, best first. It's one `claude -p` call per video (~15 s, on your
Claude plan), and it can also rescue a couple of results the tag filter dropped. If the CLI is
missing or not logged in, Klip falls back to tag-based selection. Settings:
`assets.vision_check` in `klip.yaml`; the sheets Claude saw are saved in `projects/<slug>/vision/`.

Each scene tries them in that order. `stock_video` falls back to photos, then to the scene's
icon (`visual.name`), then to a gradient. Landscape footage is center-cropped to 9:16 when
the resolution allows, otherwise it's placed over a blurred copy of itself. API responses
are cached for 24 h and downloads forever in `~/.cache/klip/`, so re-renders make no API
calls. Credits go to `credits.json` and `post.txt`.

If `node` on your PATH is older than 22, Klip still finds the nvm-installed 22 on its own.
To point it somewhere specific, set `KLIP_NODE=/path/to/node`.

## Batch: many videos at once

```bash
uv run klip batch examples/batch.yaml                 # script + render every item
uv run klip batch topics.yaml --scripts-only          # write all specs, review them, then:
uv run klip batch topics.specs.yaml                   # render the reviewed specs
```

```yaml
defaults: {voice: female, duration: 45}
items:
  - "Kenapa kita cegukan?"                          # a topic (defaults apply)
  - {topic: "Kenapa bawang bikin mata perih?", voice: male}
  - {spec: specs/kenapa-langit-biru.json}           # an existing spec
```

Items run one after another; a failure (script, render or QA) is recorded and the batch moves
on. You get a summary table, a JSON report in `projects/_batch/`, and exit code 1 if any item
failed.

## Standalone: topic → video without Claude Code

```bash
uv run klip new "Cara menyimpan cabai biar awet" --voice female   # writes specs/<slug>.json, shows review
uv run klip render specs/cara-menyimpan-cabai.json               # after you've reviewed it
uv run klip new "Kenapa langit biru?" --voice male --no-review   # skip review, render right away
uv run klip new "Kenapa harga tempe naik?" --stage              # illustrated stage look (see below)
uv run klip script "topik" -o specs/x.json                       # spec only
```

The script writer is picked by `llm.provider` in `klip.yaml`:
- **`claude`** (default when installed): the Claude Code CLI (`claude -p`) on your existing
  Claude plan, with web search for sources. Needs `claude` logged in (`/login`).
- **`openai`**: any OpenAI-compatible endpoint (Ollama, LM Studio, OpenRouter…). Set
  `LLM_BASE_URL`, `LLM_MODEL` (and `LLM_API_KEY` if needed) in `.env`.

The model gets the same writing guide as the `/klip` skill. Its answer is validated against
the schema and the linter (durations, icons, template fields), and errors are sent back for
a fix, up to `llm.max_retries` times. The output is always a spec you can read and edit
before rendering.

## The stage look (illustrated explainer)

`stage` scenes build an illustrated collage on a persistent background (desk, paper, kraft,
board): cut-out photos, icons, labels, numbers and bar charts pop in on their narration words
and stay. To make the **whole video** look like that instead of stock footage, flip one switch:

- `"look": "stage"` in the spec,
- `--stage` on `klip new` / `klip script`, `stage: true` in a batch item or its defaults,
- or ask Claude for it (*"pakai stage"*, *"gaya ilustrasi"*); the `/klip` skill and the MCP
  server both know the switch.

The writer then uses `visual.type: "stage"` for most hook/explain/list_item scenes
(`stat`, `myth_fact`, `compare` and `cta` keep their own cards), and `klip validate` errors if
fewer than `stage.look_min_share` (70%) of those scenes are staged. Without it (`"look": "mixed"`,
the default) each scene picks its own visual. Backgrounds and animation are tuned in
`klip.yaml` (`stage`); `klip report` groups results by look.

### Photos on the stage: stock first, then a photo brief for you

Stage props are mostly real photos cut out with scissors. For each `cutout`/`photo`/`person`/`logo`
prop Klip looks, in order, for:

1. **your file** in `specs/photos/<slug>/`, named `<scene>-<n>…` (n = the element's number in the
   scene, from 1), e.g. `specs/photos/judi-online/s1-1-bandar.png`. A transparent PNG is used as
   is; any other photo is cut out automatically;
2. a Wikipedia image (`who`), a screenshot or chart data;
3. stock: Unsplash (`UNSPLASH_ACCESS_KEY`), Pexels, Pixabay and Wikimedia Commons
   (`stage.photos.providers`), in any orientation, with Claude's vision check picking the best
   photo across all of them.

Every asset fetch writes `projects/<slug>/photo-brief.md`: props with no photo, props marked
`"own": true`, and stock photos the vision check found only loosely related, each with what the
photo should show (`brief`), the file name to save and search links. Get it before rendering:

```bash
uv run klip photos specs/<slug>.json      # stock search + vision check + photo brief (no render)
```

Drop the photos you want into the folder and render; the rest stay stock. A photo prop with no
photo at all shows its fallback icon (`name`) if it has one. Stage props also sway gently once
they land, numbers count up, and the camera eases toward each new prop (`stage.motion`).

## Using the CLI directly

```bash
uv run klip validate examples/menguap.json             # review preview + lint (exit 1 on errors)
uv run klip say "Pakai WiFi" --voice female            # hear the TTS (with lexicon) to tune pronunciation
uv run klip render examples/menguap.json --voice male  # full pipeline → projects/<slug>/
uv run klip render specs/x.json -o projects/x-female   # custom output dir
uv run klip run assets examples/menguap.json           # one stage: voice|assets|compose|render|post|qa
uv run klip voices                                     # configured voices
uv run klip schema                                     # re-export JSON Schema
uv run klip doctor                                     # environment check
```

A 45 s video takes about 2–2.5 minutes on an Apple Silicon laptop (mostly the headless Chrome
render; the first run also downloads b-roll). TTS and media are cached, and an unchanged
composition skips the render.

## Templates

| template | use | extra fields |
|---|---|---|
| `hook` | first scene: big question/claim | `on_screen_text` |
| `explain` | narration over b-roll/icon with a headline | `on_screen_text` |
| `list_item` | numbered tip with a "1/3" badge | `on_screen_text`; numbers are automatic for consecutive list items |
| `myth_fact` | ❌ Mitos card, struck through, then ✅ Fakta card | `myth`, `fact`, optional `reveal_at` (narration word) |
| `stat` | big number counting up + label | `stat: {value, prefix, suffix, decimals, label}` |
| `compare` | two columns, A vs B | `compare: {left: {label, text, icon}, right: {…}}` |
| `cta` | outro: follow / save | `on_screen_text` |

`examples/tidur-siang.json` uses all of them.

## Hooks and A/B testing

The first 2 seconds decide whether people keep watching, so the hook gets special treatment:
- its text and first caption page are **on screen at frame 0** (they punch in by scale, they
  don't fade in), the TTS lead-in silence is trimmed so the **first word starts ~60 ms in**,
  and its b-roll opens with a stronger zoom;
- the writing guide enforces strong hook types and an **open loop**: the hook's promise is
  paid off near the end, never in scene 2.

**A/B hooks:** a spec can carry up to 4 `hook_variants` (alternative first scenes).

```bash
uv run klip new "topik" --hooks 3              # Claude writes the main hook + 2 alternatives
uv run klip render specs/x.json --variants     # final.mp4 (A) + variants/B/final.mp4, variants/C/…
```

Post the variants (e.g. on different days) and compare average watch time in TikTok
analytics; `variants.json` lists which hook is in which file. Each variant is a full render
(~2 min); voice and stock media for the unchanged scenes come from cache.

## Delivery (livelier voice)

Each scene is read with a delivery preset that shifts the voice's rate and pitch: the hook
is **energetic** (quicker, brighter), stats and myth/fact reveals **emphatic** (slower,
firmer), the CTA **warm** (relaxed, lower). Everything else is neutral. Measured on Gadis:
energetic +16 Hz median pitch and ~5% faster; warm -7 Hz and ~5% slower. Override a scene
with `"delivery": "calm"` etc., tune the presets in `klip.yaml` (`prosody`), and preview one
with `uv run klip say "teks" --delivery energetic`.

## Fast cuts

Every shot shows its own clip: a source is used once per video (checked by provider id and by
file content) and never looped; a clip shorter than its shot slows down, then holds its last
frame. A scene's `visual.beats` (`[{at, query}]`) cut a new clip in on the narration word `at`,
each from its own query, so the picture changes when the voice changes subject. Without beats,
a scene is cut into ~2.5 s shots on word boundaries (preferably after punctuation), but only
into as many shots as it found distinct clips. Each new shot punches in slightly. `klip validate`
warns about scenes that would hold one clip for more than `cuts.max_shot_s`, and QA's
`fresh_footage` check fails if any source appears twice. `visual.max_shots: 1` keeps a scene
as one shot.

## Sound effects

Effects are placed automatically on visual moments and mixed under the voice: an impact on
the hook's first frame, a whoosh on every scene cut, a riser into the myth→fact reveal, a
ding when a stat lands, and pops for list badges, the VS badge and the CTA icon. The defaults
in `assets/sfx/` are synthesized by `scripts/make_sfx.py` (no licensing issues). Replace any
of them by dropping your own file with the same name. Levels and which moment gets which
effect are in `klip.yaml` (`sfx`); `"sfx": false` in a spec turns them off.

## Music

Put royalty-free tracks in `assets/music/<mood>/` (e.g. `assets/music/calm/`). The spec's
`music.mood` picks one (deterministically, per video). `music.track` sets an exact file, and
`"mood": null` turns music off. Music is set about 16 dB under the voice and ducked further
under speech (net about -22 dB), with a fade-in and fade-out. Levels are in
`klip.yaml` (`music`). Every render with music also writes `final_nomusic.mp4`.

`uv run python scripts/make_test_music.py` generates a synthetic placeholder pad, for testing
only. Replace it with real tracks (e.g. the Pixabay Music or YouTube Audio Library free
tracks; check each license).

## Performance report (what actually works)

After posting, copy each video's numbers from TikTok/Instagram/YouTube analytics into
`stats.csv` (start from `stats.example.csv`; any spreadsheet works, export as CSV). One row per
video per platform, keyed by the project slug:

| column | what |
|---|---|
| `slug` | folder name in `projects/` |
| `variant` | hook variant: blank/`A` = `final.mp4`, `B`/`C` = `variants/<letter>/final.mp4` |
| `platform` | `tiktok` (default), `instagram`, `youtube` |
| `views`, `avg_watch_s`, `completion_pct` | TikTok: "Average watch time" and "Watched full video" |
| `likes`, `comments`, `saves`, `shares`, `followers_gained`, `posted_date`, `notes` | optional |

Blank cells are fine; `1.234`, `1,234`, `21,0` and `18%` all parse. To update numbers, edit the
row or add a new one (the last row for a slug/variant/platform wins).

```bash
uv run klip report
```

It reads each video's `spec.resolved.json`, `timeline.json`, `assets.json` and `result.json`, and
prints grouped averages (completion %, avg watch time, watch time as % of length, views) by
hook type (guessed from the hook text), hook variant, duration, average shot length, style,
series, CTA type, progress bar, music, scene count and which templates were used. Groups
smaller than `report.min_group` (3) are marked ⚠. Only TikTok rows by default
(`--platform instagram|youtube|all`). It also writes `projects/report.md`. Settings: `report` in
`klip.yaml`. Once a pattern holds across 5–10 videos, tell Claude so the writing guide can favour it.

## QA

After every render, `qa.json` checks: 1080×1920 / 30 fps / H.264+AAC; duration within ±15%
of `target_duration_s` and ≤ `qa.max_duration_s` (120 s); no black or frozen video > 1 s; loudness -14 LUFS ±1.5
and true peak ≤ -1 dBTP; voice in every scene; every word has a caption timing and no page
has more than 4 words; credits for every stock asset. Run it alone with `klip run qa <spec>`.
`tests/fixtures/broken-duration.json` is a spec that's meant to fail.

## Spec cheat sheet

```jsonc
{
  "slug": "kenapa-kita-menguap",
  "voice": "female",                 // male = id-ID-ArdiNeural, female = id-ID-GadisNeural
  // "speech_rate": "+8%",          // optional; default per voice (female +15%, male +8%)
  "target_duration_s": 45,
  "scenes": [
    { "id": "s1", "template": "hook", "narration": "Pernah nggak kamu…?",
      "on_screen_text": "Menguap itu MENULAR?", "emphasis": ["menular"],
      "visual": { "type": "stock_video", "query": "woman yawning", "name": "sparkles" } },
    { "id": "s2", "template": "explain", "narration": "…",
      "on_screen_text": "Teori: mendinginkan otak", "visual": { "type": "icon", "name": "brain" } },
    { "id": "s3", "template": "cta", "narration": "Follow buat fakta lainnya!",
      "tts_override": "Folo buat fakta lainnya!" }
  ],
  "post": { "caption": "…", "hashtags": ["#edukasi"] },
  "facts": [{ "claim": "…", "source": "https://…" }]
}
```

Visual types: `stock_video` / `stock_photo` (English `query`; optional `name` = fallback icon),
`local` (`path` to your own file), `icon` ([Lucide](https://lucide.dev/icons) `name`), `solid`.
Pronunciation fixes, colors, fonts, caption position, transitions and b-roll darkening are
all in [`klip.yaml`](../klip.yaml). A spec picks a style with `"style": "bold"` (styles inherit from
`default`).

**Branding.** Every video gets a thin progress bar at the top of the safe zone (with notches at
scene changes); turn it off per spec with `"progress_bar": false`, e.g. to A/B test it, or when
creating/rendering with `--no-progress-bar` (`klip new`, `script`, `render`; `--progress-bar`
forces it on), `progress_bar: false` in a batch item or its defaults, or the MCP `render_spec`
`progress_bar` argument. A style can add a watermark logo/handle, a series pill
(`"series": "why"`, optional `"episode": 12`) and a brand end card on the `cta` scene; the easy
way is a [brand pack](BRANDS.md).
