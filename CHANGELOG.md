# Changelog

All notable changes to Klip are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (see [docs/MAINTAINING.md](docs/MAINTAINING.md#versioning)).

## [Unreleased]

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

[Unreleased]: https://github.com/aliflazuardi/klip/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aliflazuardi/klip/releases/tag/v0.1.0
