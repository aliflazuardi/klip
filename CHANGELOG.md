# Changelog

All notable changes to Klip are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (see [docs/MAINTAINING.md](docs/MAINTAINING.md#versioning)).

## [Unreleased]

### Added

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

- Stage layout composes by count and kind (`stage.compositions`): one big hero prop, hero + tag,
  pair, hero + two, grid, scatter. Props are larger.
- Stage titles are left-aligned type with a marker on emphasis words (`stage.title.style: plain`);
  `strip` keeps the old paper strip.
- Captions on stage scenes are phrase pages (up to 6 words), lower, without a stroke, with the
  underline marker, and hidden during pauses.
- The cta narration is no longer captioned by default (`outro.captions`), so the sign-off doesn't
  appear twice.

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

[Unreleased]: https://github.com/aliflazuardi/klip/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/aliflazuardi/klip/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/aliflazuardi/klip/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aliflazuardi/klip/releases/tag/v0.1.0
