# Maintaining Klip on GitHub

Notes for the maintainer: publishing, versioning, releases, and keeping private work private.

## First publish

1. Create an **empty** repo on GitHub (no README, licence or .gitignore), e.g. `klip`.
   If you pick another name, update the `aliflazuardi/klip` URLs in `README.md`,
   `CHANGELOG.md`, `pyproject.toml` and `klip/http.py`.
2. Check that nothing private is tracked:

   ```bash
   git ls-files | grep -iE "brand|todo|decision|\.dev|specs/|\.env$"   # only brands/example, specs/.gitkeep, docs/BRANDS.md, tests
   git log --oneline                                                   # history you're about to publish
   ```

3. Push and tag the first release:

   ```bash
   git remote add origin git@github.com:aliflazuardi/klip.git
   git push -u origin main
   git push origin v0.1.0          # the release workflow creates the GitHub Release
   ```

4. On GitHub, in **Settings**:
   - *General*: add a description and topics (`tiktok`, `video-generation`, `tts`, `claude`, `mcp`);
     enable Issues; turn on "Automatically delete head branches".
   - *Branches*: add a ruleset for `main`: require a pull request and the `ci / test` check,
     block force pushes.
   - *Actions → General*: "Read and write permissions" is not needed; the release workflow
     asks for `contents: write` itself.
   - *Code security*: enable Dependabot alerts and secret scanning.

## What stays private

Gitignored, so it never leaves your machine: `.env`, `klip.local.yaml`, `CLAUDE.local.md`,
`brands/*` (except `brands/example`), `.claude/skills/*` (except `klip`), `.dev/` (plans,
decisions, to-do), `specs/*`, `projects/`, `stats.csv`, music and b-roll.

Before every push, `git status` should show none of those. If something private was ever
committed, removing it in a new commit is not enough: it is still in history. Rewrite history
before pushing (e.g. [`git filter-repo`](https://github.com/newren/git-filter-repo)
`--path <file> --invert-paths`), and rotate any leaked key.

## Versioning

[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`. The single source of truth is
`version` in `pyproject.toml`; `klip --version` and `klip.__version__` read it.

While on `0.x`, the spec format and config may still change:

| bump | when |
|---|---|
| `0.x.Y` patch | bug fixes, tuning, docs |
| `0.X.0` minor | new features, and any breaking change to the spec, `klip.yaml` keys or CLI (say so under **Changed**/**Removed** with a migration note) |
| `1.0.0` | when the spec format is stable; from then on breaking changes bump MAJOR |

## Making a release

1. Make sure `main` is green and `CHANGELOG.md` has everything under `## [Unreleased]`.
2. Bump the version and move the notes:

   ```bash
   # pyproject.toml: version = "0.2.0"
   uv lock                                         # updates the version in uv.lock
   # CHANGELOG.md: rename "## [Unreleased]" → "## [0.2.0] - YYYY-MM-DD", add a fresh
   #               "## [Unreleased]" above it, and update the compare links at the bottom
   uv run pytest                                   # test_version checks pyproject ↔ CHANGELOG
   git commit -am "Release 0.2.0"
   ```

3. Tag and push:

   ```bash
   git tag -a v0.2.0 -m "Klip 0.2.0"
   git push origin main v0.2.0
   ```

The `release` workflow checks the tag matches `pyproject.toml`, runs the tests, builds the
sdist and wheel, and publishes a GitHub Release with that version's CHANGELOG section as notes.
If it fails, fix on `main`, delete the tag (`git tag -d v0.2.0 && git push origin :v0.2.0`) and
tag again.

## Day-to-day iteration

- Work on short-lived branches and merge through PRs (even solo: CI runs and the history stays
  readable). Squash-merge keeps one commit per change.
- Note user-visible changes under `## [Unreleased]` as you go, so releases are just a rename.
- Release whenever a meaningful set of changes lands; there's no fixed schedule.
- Keep your own experiments (specs, brand, notes) in the gitignored places above, so pulling
  `main` never conflicts with them.
- Review Dependabot PRs; when bumping `edge-tts` (it breaks when Microsoft changes the endpoint),
  render one example end to end before merging.
- Triage issues with labels: `bug`, `enhancement`, `question`, `good first issue`.
