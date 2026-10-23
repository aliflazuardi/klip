# Changelog

All notable changes to Klip are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (see [docs/MAINTAINING.md](docs/MAINTAINING.md#versioning)).

## [Unreleased]

### Added

- **Kinetic titles and an FX kit.** A stage scene's title now comes in word by word; its keywords
  (emphasis, or ALL-CAPS in a mixed-case title) slam in when the narration says them, with a light
  sweep and a shake (on the hook they pulse, since the hook is up at frame 0). Stamps land with a
  shockwave and sparks. Code scenes get `k.reveal` (letters, words, mask, slam), `k.fx` (sparks,
  shock, shine, shake) and an odometer `k.count({roll: true})` (`stage.motion.title`, `fx`).
- **Motion report in QA.** `qa.json` and the render summary now flag stretches where the picture barely
  moves (dead air) or changes everywhere for too long, per scene (`qa.motion`; informational, never
  fails a render). The stage camera keeps drifting in under the closing outro badge, which the report
  caught as 5+ s of stillness at the end.
- **Props move with weight.** Stage props blur as they fly in and sharpen as they land, wobble once
  after landing (a decaying jelly skew), puff dust when dropped or stamped, and lean back before they
  sweep off (`stage.motion.feel`). Code scenes get the same as `k.land(el, at)`, plus `k.spring()`, a
  deterministic spring ease for any tween.
- **Transition library.** Cuts between scenes now vary: whip (a fast slide with sideways motion
  blur), zoom (a dive through the frame), wipe (a brand-colour circle sweeps across) and flash, each
  with its own sound, never the same twice in a row; the cut out of the hook gets the strongest
  (`style.transitions`). A scene's `"transition"` picks the cut into it. Stage scenes on one set and
  scenes inside a world keep their own continuous moves.
- **Sound on camera moves.** The post stage reads the rendered video and plays a whoosh where a code
  scene's camera starts a big move (most of the picture changing at once), louder for bigger moves,
  clear of scene cuts and of whooshes already cued (`sfx.motion`).
- **Seamless loop.** With `loop` on (style `loop.enabled`, or `"loop": true` in a spec), the last
  half second, after the last word, turns into the video's first frame (an ffmpeg xfade, `zoomin` by
  default), so the platform's auto-replay has no jump. Costs one video re-encode in the post stage.
- **Cold opens for code scenes.** `k.spotlight("napa", {pose})` puts a mascot centre stage in a code
  scene, big, under a glow and a turning sunburst (settings `code.kit.spotlight`). docs/CODE-SCENES.md
  shows how a world replays its climax under the hook so a cinematic video opens on its best shot.
- **Livelier mascots.** Mascots gesture while they speak (a lean on a new sentence or a long word,
  a nod on emphasised words, listeners nod along) and land with a squash. New spotlight:
  `"mascot": {"focus": true}` (or a name) slides that mascot to the centre of the frame, big, under
  a glow and a turning sunburst, while the others step out; picture props move to the right
  column. Settings under `mascot.focus` and `mascot.lively`.
- **Hook covers.** `cover.png` now uses a hero layout whenever the video has a subject: a short
  title up top with the keyword on a tilted accent block, one big subject below (the hook's stage
  cut-out, a subject lifted from the hook's b-roll, or the brand mascot pulling a face), an arrow
  pointing at it, the subtitle as a tag and a sunburst behind. New spec fields `cover.layout`,
  `cover.image`, `cover.mascot`, `cover.who` and `cover.badge`; settings under `cover.hero` in
  `klip.yaml`. `"layout": "text"` keeps the old title-only cover. `klip cover <spec>` redoes just
  the cover.

- Gemini duets in one request: a video that alternates two narrators is recorded as a single
  multi-speaker take (`gemini_tts.dialogue`, on by default with `voices.take: whole`), then cut into
  scenes. One request per video instead of one per narrator turn, and more natural hand-offs.
- **Director mode: code scenes.** `visual.type: "code"` renders a scene from an HTML/CSS/JS file
  written against the scene kit `k` (GSAP timeline, `k.at("word")` cues, `k.frame` for canvas and
  Three.js, seeded random). Validation lints the files (no clock, random, network or rAF; cue words
  must be in the narration). See `docs/CODE-SCENES.md`.
- `look_bible` in the spec (and a style's `look_bible`): palette, fonts, texture (paper,
  watercolor, halftone, grain, hud, riso), line weight and motion shared by every code scene.
  Bundled fonts: Fraunces, Fredoka, Anton and JetBrains Mono, next to Plus Jakarta Sans.
- `klip preview`: stills of each code scene at its start, cue words, middle and end, as contact
  sheets in `projects/<slug>/preview/`.
- `libs: ["three"]` on a code scene loads Three.js (renderer dependency `three`).
- Code scenes: `include` (shared scripts for several scenes) and `k.mascot(name)`, a brand
  mascot rig with poses, lip sync on the scene's narration and blinks.
- Code scenes: a standard kit in `k` (`stage`, `camera`, `headline`, `cast`, `scrim`, `chip`, `pop`,
  `shake`, `type`, `count`, `draw`) that knows the series pill, the mascots' spots and the look, so a
  new scene starts legible and on-brand (settings in klip.yaml `code.kit`).
- Code scenes: light. `k.glow(ctx)` (bloom for a 2D canvas, or a CSS glow on an element),
  `k.bloom(renderer, scene, camera)` (Three.js with bloom) and `k.flare(ctx, x, y)` (lens flare with
  rays and an anamorphic streak); defaults in klip.yaml `code.kit.glow` / `code.kit.flare`.
- `look_bible.preset`: start from a named look in klip.yaml `code.looks`. `"cinematic"` is a dark
  motion-graphics look (warm near-black, hairline strokes, one glowing accent) with the new `film`
  texture (grain + dark vignette) and `cinematic` motion (slow expo eases).
- Starter `light-beam.html`: a beam of light strikes a set of hairline rings on the key word and
  shoots through, with a flare, shockwave, dust and HUD readouts (in the starter gallery).
- Code scenes: `k.trail(ctx, pos, t)` (a tapered streak behind a moving point) and
  `k.motionBlur(ctx, draw)` (sub-frame motion blur for a canvas), settings in klip.yaml
  `code.kit.trail` / `code.kit.motion_blur`; light-beam's exit pulse leaves a trail.
- Spec `world`: one code layer under a run of consecutive code scenes, so a camera can travel through
  one place while the scenes change on top (`k.scenes`, `k.sceneAt(t)`, words of the whole run).
  Starter `examples/code-scenes/worlds/journey.html`, example `examples/code-world.json`.
- Validate warns when a code look's `bg` is darker than video black (it flattens and gradients band).
- `klip ideas`: today's trending searches (Google Trends RSS, `ideas.geo`, with news headlines) and your
  own pasted signals (`--from`) → explainer ideas that fit the channel's brand guide and skip topics
  already made → a `klip batch` file with each idea's angle, hook, trend, facts to check and
  sensitivity as comments. Settings in klip.yaml `ideas`.
- Code scenes follow the music: compose finds the beats of the video's music track (klip/beats.py,
  pure Python, cached; settings in klip.yaml `code.beats`) and passes them as `k.beats`, `k.bpm` and
  `k.period`. `k.pulse(t)` (1 on a beat, decaying) and `k.onBeat(fn)` put motion on them. Spec
  `music.beats: false` turns it off; compose warns when a track's beat is unclear. The light-beam
  starter breathes on the beat and rings out an echo on every bar.
- `klip preview` records with a free draft voice (`voices.preview_engine`, edge) unless the final
  engine's takes are already cached, so previews never spend Gemini or ElevenLabs quota.
- Code scenes: `sfx` cues (`{at, sfx, offset_s}`) put sound effects on a scene's own beats.
- Code scene starters in `examples/code-scenes/starters/` (kinetic type, split comparison, document,
  timeline, road, big counter, and Three.js terrain, particles and globe), all rendered by
  `examples/code-gallery.json`; `k.find` / `k.beat` for scenes that time themselves on any narration;
  `--k-paper-ink` for card text that reads on light and dark looks.
- Code scenes: the mascot rig acts: `walk` (footsteps, bob, lean), `enter` / `exit`, `jump`, `hop`,
  `turn`, `point` at a prop, `nod`, `wiggle`. Feet are found in the pose SVGs automatically (or marked
  `foot-l` / `foot-r`); settings in klip.yaml `code.kit.act`.
- `klip preview` ends with Claude's review of the contact sheets (score per scene, issues with fixes:
  unreadable text, overlaps, safe area, empty frames, off-script, off-style, error boxes), saved to
  `preview/review.json` and carried into `qa.json`. Settings in klip.yaml `code.review`; `--no-review`.
- MCP tool `get_brand_guide(style)`: returns a brand pack's `skill/SKILL.md` and its mascot cast, so
  Claude Desktop sessions follow the brand (voice, series, mascots) without a separately installed skill.
- `list_styles` now lists each brand's mascots (name, voice, side) and whether it has a brand guide.
- MCP tool `preview_spec`: the `klip preview` contact sheets returned as images (plus the stills'
  times and labels), so Claude Desktop can look before it renders. `validate_spec`, `preview_spec`
  and `render_spec` take `scene_files` (code-scene HTML/JS saved to `specs/<slug>/`), which brings
  director mode to Claude Desktop.

### Fixed

- Mascots' eyes no longer slide down their faces when they blink (a CSS transform-box on the eyes
  fought GSAP's own SVG origin; it now scales each eye about its centre).
- `post.txt` no longer repeats hashtags that the caption already contains.
- Code scenes: a mascot pose set at the scene's very start (`pose(name, 0)`) now shows from frame 0.
- Code scenes: the mascot walk no longer breaks `klip render` (HyperFrames' strict lint rejects template
  literals in `querySelector`); `klip validate` now flags that pattern in scene files too.

### Changed

- Cinematic preset: bg lifted to `#16120F` (the old `#0E0C0B` sat below video black) and `film` grain
  is 2 px, so it survives the encode and dithers dark gradients instead of letting them band.
- Faster renders (a 59 s video: about 2 min → 1.5 min). HyperFrames encodes at `render.crf` and post
  copies that video stream into final.mp4 instead of encoding it a second time (post ~33 s → ~14 s;
  `render.reencode: true` restores the re-encode, now at `render.preset: veryfast`). `render.workers:
  cores` runs one Chrome per CPU core but one (7 on an 8-core Mac vs 3 from HyperFrames' `auto`), and
  `render.fast_capture: false` avoids HyperFrames' fast capture, which falls back to one slow worker
  on Klip's drop-shadows and blend modes. A changed `render.crf` or `quality` now re-renders.
- MCP instructions: for a named channel/brand, call `get_brand_guide` before writing; never ask the
  user who the mascots are or which voice they use.
- Warga Nalar skill: mascot summary at the top (Napa = female, asks; Gulung = male, explains; on by
  default), per-scene voice rule for duets, 8–9 scenes allowed for duets, and the invalid
  `bg: "malam"` replaced with `bg: "solid"`.

## [0.4.0] - 2026-10-21

### Added

- A scene's `"mascot"` takes `show` (only these mascots appear, e.g. to introduce one) and `scale`
  (up to 2.2× taller, for a scene about the mascots themselves; the props area makes room).
- Stage backdrops: a stage scene's `"backdrop"` swaps the plain set for a themed one as the story
  moves: `photo` (a place or surface from stock, a Wikipedia image such as an old map, or your
  `<scene>-bg.jpg`), `screenshot` (a web page, also from the Wayback Machine), `board` (a market
  board whose `+`/`-` cells turn green/red) or `phone` (an app screen). Each takes `dim`, `blur`,
  `tint` and `tone`; settings live in `klip.yaml` `stage.backdrop`. Busy sets get boxed caps titles
  (`stage.title.style: box`) and a darker bottom for the captions. Example: `examples/backdrops.json`.
- `notif` stage element: a phone notification card (app, line, big amount, time) that slides down;
  several stack down the screen.
- `validate` suggests switching sets when five or more stage scenes all use one.
- Mascots read on every set: a sticker outline (`mascot.outline`, the cut-out props' language) and a
  contact shadow under the feet (`mascot.ground`) keep a dark character visible on dark or busy sets.
- Mascots point at `notif` cards, and with `mascot.auto.listen` the other mascots lean in (a pose)
  when the speaker first points in a scene, so a duet reacts to each other.

### Fixed

- A neutral stamp on a dark set is drawn light (`stage.stamp.neutral_dark`) instead of vanishing.
- Gemini TTS waits as long as a rate limit asks (the free tier allows 3 requests a minute, and a
  dialogue makes one per narrator turn) instead of failing after short retries.
- The mascots' closing pose waits for a held reaction to finish (Gulung's roll at a "hoaks" stamp
  was cut short), and the mascots rise when the outro badge slides up under them.
- `post.txt` credits every narrator voice of a dialogue video, not just the first.

## [0.3.0] - 2026-10-21

### Added

- Mascots: a brand pack's `mascot.cast` (folders of pose SVGs) stand above the stage captions,
  lip-sync the scene's speaker word by word, blink and sway, point at new props and react to
  stamps; a scene's `"mascot"` picks the speaker and adds poses on words. Example cast in
  `brands/example/mascot/`. A spec picks who appears with `"mascots"` (or `--mascots`).
- Dialogue: a scene can set its own `"voice"`, so a video can alternate female and male narrators.
  Each narrator's turn is recorded as its own take, and a mascot with that `voice` speaks it.
- Motion components for stage scenes: `kinetic`, `split`, `flow`, `meter`, `cycle`, `timeline`,
  `funnel` and `reel`, animated diagrams whose `steps` play on their own narration words, with
  count-up values, accent steps and SFX (`stage.components` in klip.yaml). Example:
  `examples/motion-components.json`.
- Stage props lean on real photos: `klip photos <spec>` (and the MCP tool `photo_brief`) finds
  photos for every stage prop and writes `projects/<slug>/photo-brief.md`, listing the props that
  have no photo, are marked `"own": true` or got a weak stock match, with what to shoot or find
  (`brief`) and the file name to save. Photos dropped in `specs/photos/<slug>/` (`<scene>-<n>…`)
  win over stock on the next render.
- Stock photo sources for stage props: Unsplash (`UNSPLASH_ACCESS_KEY`) and Wikimedia Commons
  (free licences only). Props search every source in any orientation and stop once
  `stage.photos.enough` photos are found; the vision check compares them all.
- A `cutout`/`photo` prop with `name` falls back to that icon when no photo is found (it used to
  be left out), and `klip validate` warns when a stage scene has more icons than real pictures.
- Livelier stage motion (`stage.motion`): props sway gently once they land, cut-outs drop in with
  a squash and photo cards are tossed in, labels wipe in, numbers count up, props sweep off to
  their side, and the camera eases toward each new prop as it pushes in.

- Hashtags are written in lowercase in `post.txt` and the validate preview (`post.lowercase_hashtags`),
  and `klip validate` warns about capitalised hashtags in the spec.

- Natural voices: `voices.engine: elevenlabs` (ELEVENLABS_API_KEY; word timings from the API) and
  `voices.engine: gemini` (GEMINI_API_KEY; Gemini 3.8 Flash TTS with a style prompt in
  `gemini_tts.style`).
- `voices.take: whole` reads the whole script in one TTS call and cuts it into scenes at the
  pauses, so intonation doesn't restart at every scene.
- Forced alignment for engines without word timings (`klip/align.py`, faster-whisper word
  timestamps mapped onto the script; optional: `uv sync --extra align`). Measured against
  edge-tts's own timings: median start error 23 ms after `align.offset_ms`.
- The first word after a pause now starts where the speech resumes even when its timing runs
  late (`voices.snap_late_ms`); with Gemini this took caption sync from up to 215 ms late to a
  mean of +5 ms after pauses.
- `klip ab-voice <spec>` reads one script with several engine/take variants (voice.wav each, or
  full videos with `--render`) to compare by ear.

- Real-world stage elements: `chart` (a line chart that draws on, from a Yahoo Finance `ticker`,
  a `csv` or inline `points`, with shaded `bands`), `unit` (a waffle of squares), `person` (a real
  person's card from Wikipedia via `who`), `logo` (an organisation's logo via Wikidata), `news`
  (a headline card) and `screenshot` (a web page, or its Wayback Machine copy, captured with the
  headless Chrome HyperFrames already installs). `cutout` / `photo` also take `who`.
- Wikimedia source: images come with their licence and author in `credits.json` / `post.txt`;
  non-free photos are never used, non-free logos only with `wikimedia.allow_nonfree_logos`.
- Hero compositions pick the one big prop as the hero, whatever its position in the list.

- Clean stage sets: `grid` (dot-grid paper, now the default), `studio` (a wall over a light desk)
  and `spotlight` (a dark desk under a light). Title, tag and shadow colours follow each set's `tone`.
- Stage `stamp` element: a rubber-stamp verdict ("BERHASIL", "PALSU") that thumps down with a hit.
- Configurable outro (`outro` in klip.yaml styles / brand.yaml): `card` (the end card), `overlay`
  (the previous scene keeps playing under the sign-off while a small logo + text + action chip
  badge slides up) or `none`.
- Caption options: `caption.highlight: underline` (an accent marker sweeps under the active word),
  `caption.shadow`, `caption.hide_gap_ms` (no caption during pauses), and `caption.stage` to
  restyle captions on stage scenes.

### Changed

- The progress bar is off by default (`styles.default.progress_bar.enabled: false`); turn it on
  per video with `"progress_bar": true` or `--progress-bar`.
- Stage layout composes by count and kind (`stage.compositions`): one big hero prop, hero + tag,
  pair, hero + two, grid, scatter. Props are larger.
- Stage titles are left-aligned type with a marker on emphasis words (`stage.title.style: plain`);
  `strip` keeps the old paper strip.
- Captions on stage scenes are phrase pages (up to 6 words), lower, without a stroke, with the
  underline marker, and hidden during pauses.
- The cta narration is no longer captioned by default (`outro.captions`), so the sign-off doesn't
  appear twice.
- Stage props search Unsplash, Pexels, Pixabay and Wikimedia Commons (`stage.photos.providers`);
  Openverse stays for b-roll only (its rate limit stalled prop searches).
- Renderer: gsap 3.15.0. GitHub Actions: astral-sh/setup-uv 7.

### Fixed

- Stage props on one page no longer overlap (a label under an icon, a trophy over a tag): boxes
  are pushed apart, then shrunk if needed (`stage.layout_gap_px`). Stamps may still overlap what
  they judge.
- Uppercase stage labels no longer run off the right edge (their width was underestimated), and
  the stage area keeps `stage.caption_gap_px` clear above the captions. Photo props get a bigger
  box (`stage.photos.grow`).

## [0.2.1] - 2026-10-20

### Fixed

- Stage scenes: props spread over the free area under the title strip (`stage.rows` /
  `stage.columns`) instead of fixed rows, so a two-line title no longer crowds them at the top.

## [0.2.0] - 2026-10-20

### Added

- One switch for the illustrated stage look: spec `"look": "stage"`, `--stage` on `klip new` /
  `klip script`, `stage: true` in batch files, and the MCP / `/klip` skill know it. The writer uses
  stage scenes for most of the video; `klip validate` checks the share (`stage.look_min_share`).
  `klip report` groups by look.

### Changed

- Maximum video length raised from 60 s to 120 s (`qa.max_duration_s`, `target_duration_s` up to 120) for long-form experiments.

### Fixed

- Render no longer crashes in the assets stage ("too many values to unpack") when logging the picked stock clips.
- `compare` scenes: a two-line headline no longer runs under the VS badge and the columns; they now move down to fit the headline.

## [0.1.0] - 2026-10-19

First public release.

### Added
- Scene spec (`schema/spec.schema.json`) as the contract between writing and rendering.
- Pipeline stages: voice (edge-tts, Indonesian male/female), word-synced captions, stock b-roll
  (local library, Pexels, Pixabay, Openverse) with a Claude vision relevance check, HTML/GSAP
  composition, HyperFrames render, loudness-normalised post, designed `cover.png`, `post.txt`.
- Templates: hook, explain, stat, list_item, myth_fact, compare, cta, plus `stage` scenes
  (props building up on a persistent background).
- Per-scene delivery presets (rate/pitch/volume), pronunciation lexicon, sound effects,
  background music with ducking, hook A/B variants.
- Automated QA (`qa.json`), batch mode, performance report (`klip report`).
- `klip new` / `klip script` script writing via the Claude CLI or any OpenAI-compatible API.
- `/klip` Claude Code skill and an MCP server (`klip-mcp`) for Claude Desktop.
- Brand packs: `brands/<name>/brand.yaml` adds a style with logo watermark, series pills,
  end card and cover branding (`brands/example/`). `klip styles` lists them.
- `klip.local.yaml` for personal overrides, deep-merged over `klip.yaml`.
- `klip --version`.

[Unreleased]: https://github.com/aliflazuardi/klip/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/aliflazuardi/klip/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/aliflazuardi/klip/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/aliflazuardi/klip/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/aliflazuardi/klip/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aliflazuardi/klip/releases/tag/v0.1.0
