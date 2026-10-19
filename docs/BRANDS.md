# Brand packs

A brand pack turns a folder into a Klip **style**: colours, a logo watermark, series pills,
an end card on the last (`cta`) scene, and the logo on `cover.png`. Klip ships one,
[`brands/example/`](../brands/example/); yours stay private.

```
brands/<name>/
├── brand.yaml        # required: `style:` overrides on top of styles.default in klip.yaml
├── assets/           # logo, wordmark, watermark (SVG or PNG); paths relative to the folder
├── skill/SKILL.md    # optional: a Claude skill with your channel's voice and rules
└── docs/             # optional: your brand book, anything else
```

## Make your own

```bash
cp -r brands/example brands/my-brand
# edit brands/my-brand/brand.yaml (name, colours, labels) and replace the files in assets/
uv run klip styles                     # my-brand is listed
```

Then use it: `"style": "my-brand"` in a spec, `uv run klip new "…" --style my-brand`, or tell
Claude *"pakai style my-brand"*.

`brand.yaml`'s `style:` block is deep-merged over `styles.default` in [`klip.yaml`](../klip.yaml),
so list only what you change. Every key there works (caption size, palette, cover layout, CTA
labels…). The ones that make it a brand:

| key | what |
|---|---|
| `text_color`, `accent_color`, `emphasis_color`, `stroke_color`, `shade_color` | colours |
| `palette` | gradient backgrounds for scenes without footage |
| `watermark.file` / `watermark.text` | small logo / `@handle` at the top right |
| `series_pill.labels` | spec `"series": "<key>"` → on-screen label (e.g. `why: "WHY?"`) |
| `end_card.logo`, `wordmark`, `tagline`, `disc_color` | the `cta` scene as an end card; also the cover footer |

## Keep it private

Everything under `brands/` except `brands/example/` is **gitignored**, so your logo and brand
rules never reach the public repo. To version your brand, make its folder its own (private)
git repo:

```bash
cd brands/my-brand && git init && git add . && git commit -m "My brand pack"
```

Override the folder with `brands.dir` in `klip.local.yaml` if you keep brand packs elsewhere.

## Optional: a Claude skill for your brand

Write your channel's voice, series formats and fact-checking rules in
`brands/my-brand/skill/SKILL.md` (with `name:` and `description:` frontmatter, see
[`.claude/skills/klip/SKILL.md`](../.claude/skills/klip/SKILL.md) for the format), then link it
where Claude Code finds skills:

```bash
ln -s ../../brands/my-brand/skill .claude/skills/my-brand
```

`.claude/skills/*` other than `klip` is gitignored too. Tell Claude to use it for every video in
`CLAUDE.local.md` (gitignored, loaded next to `CLAUDE.md`):

```markdown
For any my-brand video, also follow .claude/skills/my-brand/SKILL.md and use "style": "my-brand".
```
