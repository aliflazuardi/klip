# Code scenes (director mode)

A code scene is a scene whose picture and motion you write as code: `"visual": {"type": "code",
"code": {"file": "specs/<slug>/<scene-id>.html"}}`. Klip still does the voice, the word-synced
captions, music, sound effects, branding, QA and the post. Code scenes mix freely with template
and stage scenes.

Use them when the video should look designed shot by shot: illustrated stories, characters acting
out a line, kinetic type, data that builds into a picture, 3D. They take longer to write than a
template, so the loop below (preview → look → fix) is part of the job, not optional.

Director mode needs a writer that can create files (Claude Code). `klip new` and the MCP server
write template and stage specs.

## The scene file

One HTML fragment: markup, any `<style>` blocks and exactly one inline `<script>`.

```html
<svg class="farm" viewBox="0 0 1080 1920">
  <rect class="sky" width="1080" height="1920" fill="var(--k-sky)"/>
  <g id="barn">…</g>
</svg>
<div class="title">30 HARI</div>
<style>
  .farm { position: absolute; inset: 0; }
  .title { position: absolute; top: 300px; width: 100%; text-align: center;
           font: 400 200px var(--k-display); color: var(--k-ink); }
</style>
<script>
  k.tl.from("#barn", { y: 300, duration: 0.6, ease: k.look.ease.out }, 0);
  k.tl.from(".title", { scale: 0, duration: 0.4, ease: k.look.ease.pop }, k.at("tiga puluh"));
</script>
```

- The canvas is 1080 × 1920. The scene's `<section>` is positioned and clipped for you, and its
  background is the look's `bg`.
- CSS is scoped to the scene (`@scope (#sc-<id>)`), so plain selectors like `.title` are safe.
- Files the scene uses (PNG, SVG, a photo) go in `"assets": ["specs/<slug>/barn.png"]` and are
  referenced as `@asset/barn.png` in markup, CSS or JS.
- `"captions": false` turns the captions off for the scene (when it shows its own words).
- `"libs": ["three"]` makes Three.js available as `k.lib.THREE`.
- `"include": ["specs/<slug>/lib.js"]` runs shared scripts before the scene's own, inside it (with
  `k`): drawing helpers and motifs several scenes use. Includes are linted like the scene.
- `"texture": "grain"` overrides the look bible's texture for this scene.
- `"sfx": [{"at": "salah", "sfx": "hit"}, {"at": "ingat", "sfx": "riser", "offset_s": -1}]` puts sound
  effects on the scene's own beats (effects in klip.yaml `sfx.dir`: whoosh, pop, ding, riser, hit). The
  cut whoosh and caption cues stay automatic. A riser that should end on the word takes `offset_s: -1`.

## The scene kit `k`

| | |
|---|---|
| `k.tl` | A GSAP timeline that starts with the scene. Times are scene seconds, 0 … `k.dur`. Put every animation on it. |
| `k.dur` | The scene's length in seconds. |
| `k.at("phrase", after = 0)` | When the voice says the phrase (scene seconds), at or after `after`. Validation checks every literal phrase is in the narration. Use it for every beat. |
| `k.words` | `[{text, t, end}]`, the narration's words with scene-relative times. |
| `k.frame(fn)` | `fn(t)` on every frame, for canvas 2D or Three.js. `fn` must draw from `t` alone. |
| `k.rand(seed)` | A seeded random generator: `const r = k.rand(7); r()` → [0, 1). |
| `k.el(tag, attrs, parent)` | Create an element (SVG when the parent is SVG). `text` / `html` attrs set content. |
| `k.$(sel)`, `k.$$(sel)` | Query inside the scene. `k.root` is the scene's `<section>`. |
| `k.look` | The look bible: `palette`, `families`, `texture`, `line`, `ease.{in,out,inOut,pop}`, `tone`. |
| `k.safe` | `{x, y, w, h, captionTop}`: the area clear of the TikTok UI and the captions. |
| `k.text`, `k.emphasis` | The scene's `on_screen_text` and `emphasis`. |
| `k.W`, `k.H`, `k.id` | 1080, 1920, the scene id. |
| `k.mascot("napa", {x, y, h, parent, mirror, bob})` | A brand mascot (the style's mascot cast) as a rig: `.pose("kaget", at, hold)`, `.hide(at)`, `.show(at)`, `.el`, `.w`, `.h`. The scene's speaker mouths its narration, everyone blinks and bobs on their own. Names and poses are checked at validate time. |

CSS variables: `--k-<colour>` for every palette entry (`--k-bg`, `--k-ink`, `--k-accent`, …),
`--k-display`, `--k-body`, `--k-mono`, `--k-font-<key>` for every bundled font, `--k-line`.

### The standard kit

Start every scene from these, so it is legible and on-brand before you add what is unique to it
(defaults in klip.yaml `code.kit`):

| | |
|---|---|
| `const { svg, cam } = k.stage()` | A full-frame SVG behind the scene's HTML (filled with the look's `bg`), with a camera group `cam` to draw into. |
| `k.camera(cam, {to, origin, at, dur})` | A slow push-in (to `code.kit.camera_zoom` by the scene's end). Works on SVG groups and HTML. |
| `k.headline({text, size, top, at, align, scrim})` | The scene's `on_screen_text`, placed below the series pill when it shows, emphasis and ALL-CAPS words in the accent, popping in word by word. Adds a top scrim. |
| `k.cast({scrim, only})` | The style's mascots at the same spots as on stage scenes, over a bottom scrim: `const { napa, gulung } = k.cast()`. |
| `k.scrim("top" \| "bottom", {height, color})` | A band of the look's `bg` so type stays readable over a busy picture. |
| `k.chip(text, x, y, {bg, color, size, rot, at})` | A label chip; pops in at `at`. |
| `k.pop(el, at)`, `k.shake(el, at)` | Pop in with the look's pop ease; a short shake. |
| `k.type(el, at, {cps})` | Typewriter text. |
| `k.count(el, {to, from, at, dur, decimals, prefix, suffix})` | A number counting up, Indonesian format (`1.234,5`). |
| `k.draw(path, at, {dur})` | A stroke drawing on. |

`k.layout` holds what the kit used: `headlineTop`, `cast` spots, `scrim`, and `outro` (when the
style's outro badge slides up over this scene: its time and top, keep that area clear).

**Rendering is a seek, not a playback.** Every frame is the timeline jumped to that time, so:
no `Math.random` (use `k.rand`), no `Date` / `performance.now`, no `requestAnimationFrame`
(use `k.frame`), no `setTimeout`, no CSS `transition` / `@keyframes`, no network, no imports.
`klip validate` rejects them. A script that throws paints a red box in its scene, so you see it in
the preview.

## The look bible

Set it once per video (`"look_bible"` in the spec; a brand pack can give defaults in its style's
`look_bible`). Every scene reads from it, which is what makes ten hand-made scenes look like one
film.

```json
"look_bible": {
  "palette": {"bg": "#E9E2D0", "ink": "#2B2620", "accent": "#C8402F", "sky": "#BFD3C9", "grass": "#7E9A5B"},
  "fonts": {"display": "anton", "body": "jakarta", "caption": null},
  "texture": "paper",
  "line": 6,
  "motion": "snappy",
  "notes": "Flat 2D, no gradients. One farmer (stick body, green cap) in every scene. Camera pushes in slowly."
}
```

- `palette`: named colours. Keep it to 4–7, with **one** accent that carries the story.
- `fonts`: keys from klip.yaml `code.fonts`: `jakarta` (Plus Jakarta Sans), `fraunces` (serif,
  with italics), `fredoka` (round, friendly), `anton` (condensed caps), `mono` (JetBrains Mono).
  `caption` changes the captions' font for the whole video.
- `texture`: `paper`, `watercolor`, `halftone`, `grain`, `hud`, `riso` or `none`, drawn over the
  scene and under the captions. `texture_strength` 0–1.
- `line`: the stroke width for drawn art (`var(--k-line)`). `motion`: `snappy`, `smooth` or
  `bouncy` sets `k.look.ease`.
- `notes`: the art direction in words: style, characters, recurring props, camera. Write it
  before the first scene and follow it in every one.

## The loop

```bash
uv run klip validate specs/<slug>.json          # schema, lint, k.at cues, durations
uv run klip preview specs/<slug>.json           # all code scenes
uv run klip preview specs/<slug>.json -s s3     # one scene after a fix
uv run klip render specs/<slug>.json
```

`klip preview` makes the voice, composes, and captures each code scene at its start,
every `k.at` cue, the middle and the end. The contact sheets land in
`projects/<slug>/preview/<scene>.jpg`. The voice is a free draft (klip.yaml
`voices.preview_engine`, edge by default) unless every take of the final engine is already cached, so
previewing never spends Gemini or ElevenLabs quota; the cues follow whichever voice it used, and
`klip render` records the real voice. Read every sheet and check:

- Does the frame show what the voice says at that moment, on that word?
- Is anything empty, cut off, overlapping the captions or outside `k.safe`?
- Do the scenes share the palette, line weight, type and characters from the look bible?
- Is something moving in every frame (no still holds longer than ~1 s; QA fails frozen video)?

Fix the file and preview that scene again. Two or three rounds per scene is normal.

## Craft: what makes these look designed

Drawn from the reference videos (`.dev/DIRECTOR-PLAN.md`):

1. **A new picture for every line.** Each scene is a place or an object, not a text card. The
   narration says "a farm", the frame is the farm.
2. **Characters act.** A figure walks in, points, jumps, its face changes on the word. Simple
   shapes (a box with legs, a stick figure with a cap) are enough when they move with intent.
3. **Motion lands on words.** Every beat is `k.at(...)`. The reveal happens as the voice says it,
   never on a timer.
4. **The camera moves.** Wrap the world in a group and push in, pan or tilt across the scene
   (`k.tl.to("#world", {scale: 1.08, duration: k.dur, ease: "none"}, 0)`). Layers move at
   different speeds (parallax) so it reads as depth.
5. **One accent, one idea per frame.** The accent colour marks the thing the line is about. Big
   shapes, a clear focal point, lots of quiet space around it.
6. **Type is image.** When a word matters, set it huge in the display font and animate it
   (stagger letters, mask-reveal, counters), and turn off captions for that scene if it repeats them.
7. **Motifs come back.** A prop introduced early (a thermometer, a counter, a jar) returns later,
   changed: that is the story. Reuse its markup across scene files.
8. **Keep the TikTok frame in mind.** The top ~230 px and the bottom ~470 px belong to the app
   and the captions; put faces and key text inside `k.safe`.
9. **Determinism makes iteration cheap.** Seeded randomness and time-driven drawing mean a
   preview still is exactly the rendered frame.

For canvas and Three.js, draw everything from `t` inside `k.frame`. Three.js renders with
SwiftShader in headless Chrome: keep geometry modest and prefer one or two 3D scenes per video.
