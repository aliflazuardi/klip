# Klip

Prompt → short vertical video (TikTok / Reels / Shorts) pipeline. Setup and usage: `README.md`.
Contributing: `CONTRIBUTING.md`. Releases: `docs/MAINTAINING.md`.

- To make a video from a topic, follow the `/klip` skill (`.claude/skills/klip/SKILL.md`).
- Python 3.12 + uv: `uv run klip …`, `uv run pytest`.
- Renderer: Node ≥ 22 project in `renderer/` (HyperFrames). `klip` finds Node 22 on its own
  (KLIP_NODE, PATH, or nvm).
- After changing `klip/spec.py`, run `uv run klip schema` (a test checks the schema is current).
- Generated output goes to `projects/` (gitignored). User specs go in `specs/` (gitignored);
  shared examples go in `examples/`.
- **All settings live in `klip.yaml`** (read via `config.get("section.key")`). Add new tunables
  there with a comment, never as hardcoded constants; a test checks every key used exists.
  Personal overrides go in `klip.local.yaml` (gitignored, deep-merged over `klip.yaml`).
- Brands are packs in `brands/<name>/brand.yaml` (only `brands/example/` is tracked). Never put
  a specific channel's brand, logo or wording into `klip.yaml`, templates, tests or examples.
- User-facing changes get a line under `## [Unreleased]` in `CHANGELOG.md`.
- **Commit after every development:** once a change is done and `uv run pytest` passes, commit it
  (only the files that change touched) without waiting to be asked. Don't push unless asked.
