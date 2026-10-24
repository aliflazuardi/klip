# Video styles

The production styles Klip can make, what each needs from you, and which topics each suits.
Claude shows this list at step 2 of the guided flow (`.claude/skills/klip/SKILL.md`, "Guided
flow"); from Claude Desktop the MCP tool `video_styles` returns this file.

Two separate choices make a video's look:

- **Production style** (this page): *how the pictures are made*: stock footage, a collage stage,
  coded motion graphics, a 3D world. Set by the spec's `look` and each scene's `visual.type`.
- **Brand style** (the spec's `"style"`): *whose video it is*: colours, fonts, logo, series pill,
  outro, mascots, voice. `uv run klip styles` lists them (`default`, `bold`, and every brand pack
  in `brands/`). A brand's guide may limit or pre-pick the production style (see "Brands" below).

## At a glance

| # | Style | Looks like | Best for | Needs from you | Mascots | Make time |
|---|---|---|---|---|---|---|
| 1 | **Stock** (b-roll) | Real footage cut every 2–3 s, big captions, template cards for numbers and myths | Everyday life, health, habits: things a camera can film | Nothing (optional: your own clips) | No | ~3 min render |
| 2 | **Stage** (collage explainer) | 90secondslab look: real photos cut out like stickers, logos, charts, headlines and stamps building up on a set | Money, news, numbers, causes and effects, history, Indonesian things stock can't show | Photos the photo brief asks for (products, places, local food); optional | Yes (on every stage scene) | ~5 min (photo search + render) |
| 3 | **Stage + data** (motion components) | Stage with animated diagrams: money flowing, shares splitting, gauges, timelines, slot reels | Budgets, "where does the money go", processes, timelines | Real figures with sources (or a CSV) | Yes | ~5 min |
| 4 | **Motion graphic** (director mode, 2D) | Designed shot by shot: kinetic type, documents with markers, counters, split screens, characters acting | Punchy explainers, comparisons, one striking number, storytelling | Nothing; more review rounds (preview sheets) | Yes (in code scenes, can act) | 20–60 min (write + preview loop) |
| 5 | **Cinematic 3D** | Dark, glowing, film grain; 3D globe, map of Indonesia, terrain, particles, 3D cards and bars | "Big" topics: geography, global trade, history spanning places, big data | Nothing; more review rounds | Optional | 30–90 min |
| 6 | **One world** (camera journey) | One continuous place the camera flies through scene after scene (a road, a map, a timeline), optional cold open on the climax | Journeys, timelines, step-by-step stories with a strong climax | Nothing; most review rounds | Optional | 45–120 min |
| 7 | **Chat** (group chat story) | A family group chat filling up: forwarded chain messages, replies after typing dots, your own reply, a "HOAKS" stamp on the message | Hoaxes, chain messages, scams, myths that spread in WA groups | Nothing (the chat is written by Claude; names are made up) | Yes (stage scene) | ~3 min render |
| 8 | **Quiz** ("tebak dulu", on any style) | A question, 2–4 options popping in, a countdown ring; the answer lights up later in the video | Comparisons people get wrong, "which one is it?", history dates, myths | Nothing (answer backed by facts) | Yes on stage scenes | ~3–5 min (+ preview rounds in code) |
| 9 | **Mixed** | Picks per scene: a stock hook, stage for the explaining, a code scene for the punchline | When one beat needs real footage and another needs a diagram | Depends on the scenes | On stage/code scenes | 5–30 min |

"Make time" is Claude's writing + rendering for a 45 s video, not counting your review.

## 1. Stock (b-roll)

- **Spec:** leave `look` unset (`"mixed"`); scenes use `visual.type: "stock_video"` with `beats`
  (a new clip on the word that names it), template cards (`stat`, `myth_fact`, `compare`) for the
  data beats.
- **Strengths:** fastest; feels like a "real" TikTok; good with relatable daily situations.
- **Weak at:** Indonesian specifics (warung, KRL, local food, institutions), abstract ideas,
  history, anything about a named person or company (stock can't show them).
- **You provide:** nothing. Your own footage goes in `assets/broll/` (matched by name) or a
  scene's `visual: {"type": "local", "path": …}`.
- **Example:** `examples/menguap.json`, `examples/tidur-siang.json`.

## 2. Stage (collage explainer)

- **Spec:** `"look": "stage"`; ≥ 70% of hook/explain/list_item scenes use `visual.type: "stage"`
  (props pop in on their words; sets change with `backdrop`: a photo place, a web page from the
  Wayback Machine, a market board, a phone screen).
- **Strengths:** real things beat stock: a public figure's card (`person`, from Wikipedia), logos,
  live market charts (`chart` with a ticker), real headlines (`news`), old websites. Looks designed
  without coding. Mascots appear here.
- **Weak at:** pure feelings and moods (a stock shot says "tired" better than a collage).
- **You provide** (all optional; the photo brief tells you exactly which):
  - photos of Indonesian products, places, food or app screens (props marked `"own": true`)
  - a news photo or screenshot you want shown as is
  - a cover photo (`cover.png` / `cover-*.jpg` in the photo folder)
  Files go in `specs/photos/<slug>/` under the names the brief gives. Public figures and logos
  come from Wikipedia on their own; you don't need to send them.
- **Example:** `examples/stage.json`, `examples/backdrops.json`.

## 3. Stage + data (motion components)

Stage with one animated diagram filling a page: `kinetic` (big type), `split` (a whole into
shares), `flow` (money to destinations), `meter` (a gauge filling), `cycle`, `timeline`, `funnel`,
`reel` (slot machine landing on the answer). Plus `chart`, `bar`, `unit` (squares) and `stack`.

- **You provide:** the real figures and their sources (Claude researches them; a CSV of your own
  data works for `chart`).
- **Example:** `examples/motion-components.json`.

## 4. Motion graphic (director mode, 2D)

- **Spec:** scenes with `visual.type: "code"`: an HTML file per scene Claude writes, started from a
  starter (`kinetic-type`, `split-compare`, `paper-doc`, `path-timeline`, `road-traffic`,
  `counter-hero`), with a `look_bible` (palette, fonts, texture, motion). Contract and craft:
  [CODE-SCENES.md](CODE-SCENES.md).
- **Strengths:** every shot designed for its line; characters and mascots act (walk, point, jump);
  strongest "this looks expensive" effect.
- **Costs:** the longest to make; Claude previews contact sheets and fixes each scene (2–3 rounds
  normal). You review the sheets too.
- **You provide:** nothing required; a reference video or screenshot of a look you like helps.
- **Example:** `examples/code-scenes.json`, `examples/code-gallery.json`.

## 5. Cinematic 3D

Director mode with Three.js starters (`three-globe`, `three-map-id`, `three-terrain`,
`three-particles`, `three-card`, `three-bars`, `light-beam`) and the `cinematic` look preset
(`"look_bible": {"preset": "cinematic"}`: near-black, one glowing accent, film grain).

- **Strengths:** geography and scale ("from Aceh to Papua", trade routes, a crisis spreading).
- **You provide:** nothing; places and figures come from research.
- **Example:** `examples/code-gallery-3d.json`.

## 6. One world (camera journey)

A `world`: one code layer under a run of code scenes, so the camera travels one continuous place
instead of cutting. With a **cold open**, the hook replays the story's climax, then hard-cuts to
the start. See CODE-SCENES.md "One world" and "Cold open".

- **Example:** `examples/code-world.json`.

## 7. Chat (group chat story)

- **Spec:** stage scenes with `"backdrop": {"kind": "chat", "title": "Keluarga Besar", "info": "23
  anggota"}` and `bubble` elements (`sender`, `text`, `forwarded`, `me`, `date`), each landing on its
  word; a `stamp` with `target` gives the verdict on one bubble. Mix with ordinary stage pages for the
  explanation ("three signs of a chain message"), then back to the chat for the verdict.
- **Strengths:** instantly recognisable in Indonesia; shows *how* a hoax spreads, not just that it's
  wrong; the stamp moment lands hard.
- **Rules:** names are made up, never a real person's name or number; the messenger's look, not its
  logo; quote the hoax as it circulates, with the debunk in `facts`.
- **You provide:** nothing. A screenshot of the real chain message can go in as a `photo` prop if you
  have one (blur names and numbers first).
- **Example:** `examples/chat.json`.

## 8. Quiz ("tebak dulu", on any style)

A scene field, not a set: any `hook`/`explain` scene can carry `"quiz": {options, answer, countdown_at,
reveal_at}`; its `on_screen_text` is the question. The strongest shape follows the curiosity arc: ask in
the hook (options + countdown, no answer), build up, answer in the scene before the cta (same options +
`reveal_at`), and end on `cta_type: "comment"` ("Tadi kamu jawab apa?").

| On… | How it looks | Notes |
|---|---|---|
| Stock / Mixed card scenes | A panel of options over the footage, under the question | The clip plays behind; pick a clip of the subject |
| Stage / Stage + data | Options in the bottom of the props area, the props above | Keep 1 small prop (a label, icon or one cut-out); with mascots the options take the room they need |
| Chat | Not on a chat set (it covers the bubbles) | Ask in the chat ("Tante: ini beneran?"), quiz in the next scene |
| Motion graphic / Cinematic 3D / One world | The code starter `quiz.html` on the look bible's colours | Copy it, mirror the options/answer/cues in its `CFG`; validate checks they match |

- **Example:** `examples/quiz.json` (stage ask, stock reveal); the code starter in `examples/code-gallery.json`.

## 9. Mixed

No `look` (or `"mixed"`); each scene picks its own visual. Typical: a stock hook (a real moment),
stage pages for the explanation, a code scene for the punchline, the brand's outro. Mascots show
only on the stage and code scenes.

## Choosing: a quick guide

| The topic is about… | Recommend | Why |
|---|---|---|
| a daily habit, body, home, food science | Stock, or Mixed with a stage page for the "why" | Filmable; relatable faces |
| money, prices, loans, markets, scams | Stage (+ data) | Real charts, phone notifications, boards |
| news, a public figure, a company, a policy | Stage | Person/logo/news cards from real sources |
| history, a place, an era | Stage (Kilas Masa default); Cinematic 3D for maps and routes | Archive images and paintings; stock has no past |
| one shocking number or a comparison | Motion graphic | A counter or split screen lands harder |
| a process or a journey with a climax | One world, or Stage + `timeline`/`flow` | Continuity carries the story |
| a myth vs fact | Stage (stamps, mascot reactions) or Stock with `myth_fact` cards | |
| a hoax, a chain message, a scam message | Chat | Shows how it spreads; the stamp gives the verdict |
| "which one is it?", a ranking people get wrong, a date to guess | Quiz (on the topic's style) | Viewers commit to a guess and stay for the answer; comments fill with guesses |

When time matters, Stock and Stage render in minutes; director styles need preview rounds.

## Brands

A brand guide (`brands/<name>/skill/SKILL.md`, its "Guided flow" section) says which styles it
uses and which details are fixed. Today:

| Brand | Default style | Allowed | Fixed by the brand |
|---|---|---|---|
| `warga-nalar` | Stage (mascots need it) | Stage, Stage + data, Chat, Quiz, Motion graphic, Mixed; Cinematic 3D and One world when a place or a journey is the answer (rare; brand palette, mascots via the scene kit); Stock (the mascots then don't appear) | Napa (cewek, asks) + Gulung (cowok, explains) duet; series; sign-off "Tetap bernalar, Warga." |
| `kilas-masa` | Stage (dark map set) | Stage, Stage + data, Quiz, Cinematic 3D, One world, Motion graphic, Mixed; Chat rarely (labelled "ilustrasi", no invented quotes); Stock not advised (no footage of the past) | No mascots; voice male unless you ask; series; sign-off "Sampai di masa berikutnya." |
| `default` / `bold` | Mixed | all | nothing |

A new brand pack: add a "Guided flow" section to its skill (see [BRANDS.md](BRANDS.md)).
