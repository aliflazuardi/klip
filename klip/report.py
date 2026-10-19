"""Performance loop: join hand-filled analytics (stats.csv) with each video's render outputs and
show which choices go with higher completion and watch time.

stats.csv has one row per posted video per platform, keyed by slug (plus an optional hook
`variant`, A = the main render, B/C = projects/<slug>/variants/<letter>/). Features come from
the project dir: spec.resolved.json, timeline.json, assets.json (shots) and result.json (music
actually used). The analysis is deliberately simple: grouped averages with counts, and groups
smaller than report.min_group flagged as too few to trust.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from klip import config
from klip.paths import PROJECTS_DIR, ROOT

log = logging.getLogger(__name__)

COUNTS = ("views", "likes", "comments", "saves", "shares", "followers_gained")
# Metrics each group is compared on: (key, column header, decimals)
METRICS = [("completion_pct", "completion %", 1), ("avg_watch_s", "avg watch s", 1),
           ("retention_pct", "watch/length %", 0), ("views", "views", 0)]
# Templates every video has; their presence says nothing.
ALWAYS_TEMPLATES = {"hook", "cta"}


@dataclass
class Video:
    """One stats row joined with its project's features."""
    slug: str
    variant: str
    platform: str
    metrics: dict[str, float]
    features: dict[str, str] = field(default_factory=dict)
    templates: set[str] = field(default_factory=set)
    hook: str = ""


# ---- reading stats.csv

def _number(raw: str | None, integer: bool = False) -> float | None:
    """Spreadsheet-friendly: '1,234' / '1.234' (counts), '45%', '12,5' (decimal comma). Blank = None."""
    s = (raw or "").strip().replace("%", "").replace(" ", "")
    if not s:
        return None
    if integer:
        s = s.replace(",", "").replace(".", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"not a number: {raw!r}") from None


def read_stats(path: Path) -> list[dict]:
    """Rows as dicts with parsed numbers. Later rows for the same slug/variant/platform replace
    earlier ones (re-copying updated analytics is just a new row or an edit)."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        if "slug" not in [c.strip().lower() for c in reader.fieldnames or []]:
            raise ValueError(f"{path}: needs a 'slug' column (see stats.example.csv)")
        rows: dict[tuple, dict] = {}
        for n, raw in enumerate(reader, start=2):
            raw = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            slug = raw.get("slug", "")
            if not slug or slug.startswith("#"):
                continue
            try:
                row = {"slug": slug, "variant": (raw.get("variant") or "A").upper(),
                       "platform": (raw.get("platform") or "tiktok").lower(),
                       "posted_date": raw.get("posted_date", ""),
                       "avg_watch_s": _number(raw.get("avg_watch_s")),
                       "completion_pct": _number(raw.get("completion_pct"))}
                row.update({c: _number(raw.get(c), integer=True) for c in COUNTS})
            except ValueError as e:
                raise ValueError(f"{path} line {n}: {e}") from None
            rows[(row["slug"], row["variant"], row["platform"])] = row
    return list(rows.values())


# ---- features from a project dir

def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def hook_type(narration: str) -> str:
    text = narration.lower()
    for name, patterns in (config.get("report.hook_types") or {}).items():
        if any(re.search(p, text) for p in patterns):
            return name
    return "other"


def _bucket(value: float | None, edges: list[float], unit: str) -> str:
    if value is None:
        return "?"
    edges = sorted(edges)
    if value < edges[0]:
        return f"<{edges[0]:g}{unit}"
    for lo, hi in zip(edges, edges[1:]):
        if value < hi:
            return f"{lo:g}–{hi:g}{unit}"
    return f"≥{edges[-1]:g}{unit}"


def _style_default_progress_bar(style: str) -> bool:
    try:
        return bool(config.style(style)["progress_bar"]["enabled"])
    except KeyError:
        return False


def _avg_shot_s(assets: dict | None, timeline: dict | None) -> float | None:
    """Mean on-screen time per shot. Scenes without stock shots (icon/solid cards) count as one shot."""
    if not timeline or not timeline.get("scenes"):
        return None
    shots = (assets or {}).get("scenes", {})
    durs = []
    for sc in timeline["scenes"]:
        planned = (shots.get(sc["id"]) or {}).get("shots") or []
        durs += [s["dur_ms"] for s in planned] if planned else [sc["duration_ms"]]
    return mean(durs) / 1000 if durs else None


def project_dir_for(projects: Path, slug: str, variant: str) -> Path:
    base = projects / slug
    return base if variant == "A" else base / "variants" / variant


def features(pdir: Path) -> tuple[dict[str, str], set[str], str, float | None] | None:
    """(features, templates used, hook narration, duration s) for one rendered video, or None."""
    spec = _load(pdir / "spec.resolved.json")
    if spec is None:
        return None
    timeline = _load(pdir / "timeline.json")
    assets = _load(pdir / "assets.json")
    result = _load(pdir / "result.json") or {}
    scenes = spec.get("scenes") or [{}]
    duration = timeline["total_ms"] / 1000 if timeline and timeline.get("total_ms") else None
    style = spec.get("style") or "default"
    pb = spec.get("progress_bar")
    pb = _style_default_progress_bar(style) if pb is None else pb
    post = result.get("post") or {}
    if "music" in post:      # what the render actually used (a mood folder can be empty)
        music = bool(post["music"])
    else:
        m = spec.get("music") or {}
        music = bool(m.get("track") or m.get("mood", "calm"))
    cta = next((s.get("cta_type") for s in scenes if s.get("template") == "cta"), None)
    hook = scenes[0].get("narration", "")
    feats = {
        "hook type": hook_type(hook),
        "duration": _bucket(duration, config.get("report.duration_bins_s"), " s"),
        "avg shot": _bucket(_avg_shot_s(assets, timeline), config.get("report.shot_bins_s"), " s"),
        "style": style,
        "series": spec.get("series") or "—",
        "cta type": cta or "none",
        "progress bar": "on" if pb else "off",
        "music": "on" if music else "off",
        "scenes": str(len(scenes)),
    }
    return feats, {s.get("template", "?") for s in scenes}, hook, duration


def join(stats: list[dict], projects: Path) -> tuple[list[Video], list[str]]:
    """Videos with features, plus 'slug (variant)' labels of rows with no rendered project."""
    videos, missing = [], []
    for row in stats:
        pdir = project_dir_for(projects, row["slug"], row["variant"])
        got = features(pdir)
        if got is None:
            missing.append(f"{row['slug']}" + (f" ({row['variant']})" if row["variant"] != "A" else ""))
            continue
        feats, templates, hook, duration = got
        metrics = {k: row[k] for k in ("completion_pct", "avg_watch_s", *COUNTS) if row.get(k) is not None}
        if duration and row.get("avg_watch_s") is not None:
            metrics["retention_pct"] = 100 * row["avg_watch_s"] / duration
        feats = {"platform": row["platform"], "hook variant": row["variant"], **feats}
        videos.append(Video(row["slug"], row["variant"], row["platform"], metrics, feats, templates, hook))
    return videos, missing


# ---- grouping

@dataclass
class Group:
    label: str
    n: int
    avg: dict[str, float | None]
    small: bool


def group_by(videos: list[Video], key, min_group: int) -> list[Group]:
    """Groups sorted by average completion (then watch time), best first."""
    buckets: dict[str, list[Video]] = {}
    for v in videos:
        buckets.setdefault(key(v), []).append(v)
    groups = []
    for label, vs in buckets.items():
        avg = {}
        for m, _, _ in METRICS:
            vals = [v.metrics[m] for v in vs if m in v.metrics]
            avg[m] = mean(vals) if vals else None
        groups.append(Group(label, len(vs), avg, len(vs) < min_group))
    return sorted(groups, key=lambda g: (-(g.avg["completion_pct"] or -1), -(g.avg["avg_watch_s"] or -1), g.label))


def feature_keys(videos: list[Video]) -> list[tuple[str, object]]:
    """(name, key function) for every feature; templates become 'has <template>' yes/no."""
    names = list(videos[0].features) if videos else []
    keys = [(n, lambda v, n=n: v.features[n]) for n in names]
    used = sorted(set().union(*(v.templates for v in videos)) - ALWAYS_TEMPLATES) if videos else []
    keys += [(f"has {t}", lambda v, t=t: "yes" if t in v.templates else "no") for t in used]
    return keys


@dataclass
class Report:
    videos: list[Video]
    missing: list[str]
    min_group: int
    tables: list[tuple[str, list[Group]]]
    platform: str

    def takeaways(self) -> list[str]:
        """One line per feature where at least two groups are big enough to compare."""
        lines = []
        for name, groups in self.tables:
            trusted = [g for g in groups if not g.small and g.avg["completion_pct"] is not None]
            if len(trusted) < 2:
                continue
            best, nxt = trusted[0], trusted[1]
            lead = best.avg["completion_pct"] - nxt.avg["completion_pct"]
            watch = ""
            if best.avg["avg_watch_s"] is not None and nxt.avg["avg_watch_s"] is not None:
                watch = f", watch {best.avg['avg_watch_s']:.1f} s vs {nxt.avg['avg_watch_s']:.1f} s"
            lines.append(f"**{name}: {best.label}** leads {nxt.label} by {lead:+.1f} pts completion "
                         f"(n={best.n} vs {nxt.n}{watch})")
        return lines


def build(stats_path: Path, projects: Path = PROJECTS_DIR, platform: str | None = None,
          min_group: int | None = None) -> Report:
    stats = read_stats(stats_path)
    platform = (platform or config.get("report.platform")).lower()
    if platform != "all":
        stats = [r for r in stats if r["platform"] == platform]
    videos, missing = join(stats, projects)
    min_group = int(min_group or config.get("report.min_group"))
    tables = [(name, group_by(videos, key, min_group)) for name, key in feature_keys(videos)]
    # A feature with one value across all videos can't be compared; leave it out.
    tables = [(n, g) for n, g in tables if len(g) > 1]
    return Report(videos, missing, min_group, tables, platform)


# ---- output

def fmt(value: float | None, decimals: int) -> str:
    if value is None:
        return "–"
    return f"{value:,.{decimals}f}"


def to_markdown(r: Report, stats_path: Path) -> str:
    out = ["# Klip performance report", "",
           f"{len(r.videos)} posted videos ({r.platform}) from `{stats_path.name}`. Groups with fewer than {r.min_group} "
           "videos are marked ⚠ (too few to trust). Sorted by completion %. Correlation, not proof: "
           "topic and posting time matter too.", ""]
    if r.missing:
        out += [f"Rows with no rendered project (skipped): {', '.join(r.missing)}", ""]
    out += ["## Takeaways", ""]
    takeaways = r.takeaways()
    out += [f"- {t}" for t in takeaways] if takeaways else \
        [f"Not enough data yet: no feature has two groups of {r.min_group}+ videos. Keep posting and logging.", ""]
    out.append("")
    head = "| group | n | " + " | ".join(h for _, h, _ in METRICS) + " |"
    sep = "|" + "---|" * (len(METRICS) + 2)
    for name, groups in r.tables:
        out += [f"## {name}", "", head, sep]
        for g in groups:
            label = f"{g.label} ⚠" if g.small else g.label
            out.append(f"| {label} | {g.n} | " + " | ".join(fmt(g.avg[m], d) for m, _, d in METRICS) + " |")
        out.append("")
    out += ["## Videos", "", "| slug | var | platform | hook type | duration | completion % | avg watch s | hook |",
            "|---|---|---|---|---|---|---|---|"]
    for v in sorted(r.videos, key=lambda v: -(v.metrics.get("completion_pct") or -1)):
        out.append(f"| {v.slug} | {v.variant} | {v.platform} | {v.features['hook type']} | {v.features['duration']} "
                   f"| {fmt(v.metrics.get('completion_pct'), 1)} | {fmt(v.metrics.get('avg_watch_s'), 1)} "
                   f"| {v.hook.replace('|', '/')} |")
    return "\n".join(out) + "\n"


def stats_path_default() -> Path:
    p = Path(config.get("report.stats_file"))
    return p if p.is_absolute() else ROOT / p


def output_path_default() -> Path:
    p = Path(config.get("report.output"))
    return p if p.is_absolute() else ROOT / p
