# Klip

[![ci](https://github.com/aliflazuardi/klip/actions/workflows/ci.yml/badge.svg)](https://github.com/aliflazuardi/klip/actions/workflows/ci.yml)
[![release](https://img.shields.io/github/v/release/aliflazuardi/klip?sort=semver)](https://github.com/aliflazuardi/klip/releases)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Topic → short vertical video.** Give Claude a topic in Indonesian and a voice (male / female);
get back a 1080×1920 MP4 for TikTok, Reels or Shorts with an Indonesian voiceover, word-synced
captions, stock b-roll (or animated icon cards), sound effects, music, a designed cover image
and a ready-to-paste caption with hashtags and sources.

```
topic ──▶ Claude writes spec.json ──▶ you review ──▶ voice (edge-tts) ┐
                                                      assets (b-roll)   ┴▶ compose (HTML/GSAP)
      ──▶ render (HyperFrames) ──▶ post (FFmpeg loudnorm) ──▶ final.mp4 · cover.png · post.txt
```

The **scene spec** (`specs/*.json`, schema in [`schema/spec.schema.json`](schema/spec.schema.json))
is the contract between writing and rendering: the same spec always renders the same video.
You can drive Klip three ways:

| how | for |
|---|---|
| **Claude Code** + the `/klip` skill | the main workflow: Claude researches, writes, you approve, it renders |
| **Claude Desktop** via the MCP server | the same, from a chat window |
| **`klip` CLI** | scripting, batch runs, any OpenAI-compatible LLM, no Claude at all |

No paid API is required: scripts are written on your Claude plan (or a local LLM), the voice is
edge-tts (free), and stock media comes from free sources.

## Features

- 7 scene templates (hook, explain, stat, numbered list, myth/fact, compare, CTA) plus
  illustrated `stage` scenes; TikTok safe-zone layout.
- Word-synced, TikTok-style captions with emphasis words and a pronunciation lexicon.
- Livelier TTS: per-scene delivery presets (rate / pitch / volume).
- Stock b-roll from your own library, Pexels, Pixabay and Openverse, with a Claude **vision
  check** that rates candidates against the narration; fast cuts, never repeated footage.
- Music with ducking, automatic sound effects, -14 LUFS loudness.
- Hook A/B variants, automated QA (`qa.json`), batch mode, and a performance report that joins
  your analytics with what was in each video.
- **Brand packs**: your colours, logo watermark, series pills, end card and cover, kept private.

## Installation

Requirements: [uv](https://docs.astral.sh/uv/), [FFmpeg](https://ffmpeg.org/), Node.js ≥ 22,
git. Developed on macOS (Apple Silicon); Linux works (CI runs on Ubuntu); Windows is untested.

```bash
# macOS
brew install uv ffmpeg
nvm install 22                  # or: brew install node@22 (your default Node can stay older)

git clone https://github.com/aliflazuardi/klip.git && cd klip
uv sync                         # Python 3.12 + deps (uv downloads Python if needed)
(cd renderer && npm ci)         # HyperFrames, GSAP, font, icons; run with Node 22
cp .env.example .env            # optional: stock media API keys, see below
uv run klip doctor              # everything should be ✓
```

To use a tagged release instead of `main`: `git checkout v0.1.0` (see [Releases](https://github.com/aliflazuardi/klip/releases)).

**Optional extras**

| what | why | how |
|---|---|---|
| [Claude Code](https://docs.claude.com/en/docs/claude-code) | `/klip` skill, script writing, vision check | install, then `claude` → `/login` |
| `PEXELS_API_KEY`, `PIXABAY_API_KEY` | more and better stock video | free keys, put them in `.env` |
| `assets/broll/` | your own clips, searched first | [how to name them](assets/broll/README.md) |
| `assets/music/<mood>/` | background music | royalty-free tracks, check each licence |

If `node` on your PATH is older than 22, Klip finds an nvm-installed 22 on its own, or set
`KLIP_NODE=/path/to/node`.

## Quick start

### With Claude Code (recommended)

Open this folder in Claude Code (terminal `claude`, or the Code tab of the Claude desktop app).
The repo ships a project **skill** at [`.claude/skills/klip/SKILL.md`](.claude/skills/klip/SKILL.md)
and an **MCP server** in [`.mcp.json`](.mcp.json) (approve it when asked). Then:

```
/klip "Kenapa langit berwarna biru?" --voice male
```

or just ask: *"buat video tentang kenapa langit biru, suara cowok"*.

Claude researches the facts, writes `specs/<slug>.json`, validates it, **shows you the script
for review**, and after you approve, renders it into `projects/<slug>/`:

| file | what |
|---|---|
| `final.mp4` | the video (H.264/AAC, -14 LUFS), with music if available |
| `final_nomusic.mp4` | same video, voice only (to add a TikTok sound in-app) |
| `cover.png` | designed cover for the TikTok / Instagram grid |
| `post.txt` | caption, hashtags, AI-voice note, sources and credits |
| `qa.json` | automated checks; `klip render` exits 1 if any fail |

### With Claude Desktop (MCP)

```bash
uv run klip mcp-config --install     # adds "klip" to Claude Desktop's config (backs it up first)
```

Restart Claude Desktop and ask the same thing in a chat. Tools: `get_spec_schema`,
`list_voices`, `list_templates`, `list_styles`, `validate_spec`, `render_spec`, `job_status`,
`list_jobs`. `uv run klip mcp-config` without `--install` just prints the entry.

### With the CLI only

```bash
uv run klip render examples/menguap.json --voice male           # render a ready-made spec
uv run klip new "Cara menyimpan cabai biar awet" --voice female  # LLM writes specs/<slug>.json, you review
uv run klip render specs/cara-menyimpan-cabai.json
uv run klip batch examples/batch.yaml                           # many videos in one go
```

`klip new` uses the Claude CLI by default, or any OpenAI-compatible endpoint (Ollama, LM Studio,
OpenRouter…) with `llm.provider: openai` and `LLM_BASE_URL` / `LLM_MODEL` in `.env`.
Add `--stage` for the illustrated [stage look](docs/USAGE.md#the-stage-look-illustrated-explainer) on most scenes.

Other commands: `validate`, `say` (hear a line through the TTS + lexicon), `run <stage>`,
`voices`, `styles`, `report`, `schema`, `doctor`, `--version`. See `uv run klip --help`.

A 45 s video takes about 2–2.5 minutes on an Apple Silicon laptop, mostly the headless Chrome
render. TTS and media are cached in `~/.cache/klip/`, and an unchanged composition skips the render.

## Make it yours

| what | where |
|---|---|
| Every setting (voices, lexicon, timing, b-roll, music, QA, styles, LLM) | [`klip.yaml`](klip.yaml), one commented file |
| Personal overrides that shouldn't be committed | `klip.local.yaml` (gitignored, deep-merged over `klip.yaml`) |
| API keys | `.env` (from [`.env.example`](.env.example)) |
| Your brand: colours, logo, series pills, end card, cover | a [brand pack](docs/BRANDS.md) in `brands/<name>/` |
| Your channel's writing voice for Claude | a skill in your brand pack, linked into `.claude/skills/` |
| Instructions for Claude only on your machine | `CLAUDE.local.md` (gitignored) |

```bash
cp -r brands/example brands/my-brand      # then edit brand.yaml and assets/
uv run klip styles                        # lists default, bold, example, my-brand
```

Your specs (`specs/`), outputs (`projects/`), brand packs, local config, music and b-roll are
all gitignored, so you can pull updates from this repo without conflicts.

## Documentation

- [Usage reference](docs/USAGE.md): templates, spec cheat sheet, hooks and A/B tests, delivery,
  cuts, sound effects, music, stock media, batch, QA, performance report.
- [Brand packs](docs/BRANDS.md): your own style, logo and Claude skill.
- [Contributing](CONTRIBUTING.md): dev setup, tests, conventions, pull requests.
- [Maintaining](docs/MAINTAINING.md): versioning, releases, GitHub settings.
- [Changelog](CHANGELOG.md).

## Notes

- edge-tts uses Microsoft's unofficial online endpoint, which needs internet and can break
  when Microsoft changes it. Keep the pinned version current.
- The voice is synthetic: turn on the platform's AI-generated content label when you post.
- Fact-check the `facts[]` sources yourself before posting health or science content.
- Voices, lexicon and the writing guide are tuned for Indonesian. Other languages need new
  voice ids in `klip.yaml` and a translated writing guide.

## License

Apache-2.0 ([LICENSE](LICENSE)). Bundled at render time: HyperFrames (Apache-2.0), GSAP
(GreenSock standard license, free), Plus Jakarta Sans (OFL), Lucide (ISC). Stock media keeps its
own license (Pixabay Content License, Pexels License, CC0/CC BY via Openverse); see each video's
`post.txt`.
