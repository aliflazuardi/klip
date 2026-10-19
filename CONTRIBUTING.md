# Contributing to Klip

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Dev setup

Follow [Installation](README.md#installation), then:

```bash
uv run pytest                                   # unit + mocked-TTS pipeline tests (~20 s)
uv run klip render examples/menguap.json        # a real end-to-end render
uv run python scripts/check_sync.py projects/x  # caption ↔ speech sync spot-check
```

Tests don't call the network or the TTS service. The ones that compose or render need FFmpeg
and `renderer/node_modules` and are skipped without them.

## Layout

| path | what |
|---|---|
| `klip/` | Python orchestrator: `spec.py` (schema), `captions.py`, `config.py`, `stages/`, `engines/` (TTS, media, LLM, render) |
| `templates/default/` | Jinja → HyperFrames HTML/GSAP scenes |
| `renderer/` | Node runtime (HyperFrames, GSAP, fonts, icons) |
| `klip.yaml` | every setting, commented |
| `brands/example/` | the sample brand pack |
| `examples/` | golden specs |
| `.claude/skills/klip/` | the Claude Code skill (also the LLM writing guide) |
| `schema/spec.schema.json` | generated from `klip/spec.py` |

## Conventions

- **Settings live in `klip.yaml`**, read with `config.get("section.key")`. New tunables go there
  with a comment, never as hardcoded constants (a test checks every key used exists).
- After changing `klip/spec.py`, run `uv run klip schema` (a test checks the schema is current).
- Keep the core brand-neutral: channel-specific logos, colours or wording belong in a
  [brand pack](docs/BRANDS.md), not in `klip.yaml`, templates, tests or examples.
- Add or update tests for behaviour changes.
- Add a line under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for anything a user would notice.

## Pull requests

1. Fork, then branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. Keep each PR to one change; describe what and why, and how you checked it (attach a frame
   or short clip for visual changes).
3. `uv run pytest` must pass; CI runs it on every PR.
4. Don't commit generated output, your specs, `.env`, brand packs or music; they're gitignored.

By contributing you agree your work is licensed under the [Apache-2.0](LICENSE) license.
