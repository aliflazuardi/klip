"""klip report: stats.csv parsing, feature extraction from project dirs, grouping and the CLI."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from klip import report
from klip.cli import app

FIX = Path(__file__).parent / "fixtures" / "report"
STATS, VIDEOS = FIX / "stats.csv", FIX / "videos"


def test_number_parsing_is_spreadsheet_friendly():
    assert report._number("1,234", integer=True) == 1234
    assert report._number("1.234", integer=True) == 1234     # Indonesian thousands separator
    assert report._number("21,0") == 21.0                     # decimal comma
    assert report._number("18%") == 18
    assert report._number("") is None
    with pytest.raises(ValueError):
        report._number("lots")


def test_read_stats_defaults_and_dedupe(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("Slug;Views;completion_pct\nfoo;100;10\n# comment;1;1\nfoo;150;12\nbar;;\n")
    rows = report.read_stats(p)
    assert [(r["slug"], r["views"], r["completion_pct"]) for r in rows] == [("foo", 150, 12), ("bar", None, None)]
    assert rows[0]["variant"] == "A" and rows[0]["platform"] == "tiktok"


def test_read_stats_reports_line_of_bad_number(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("slug,views\nfoo,100\nbar,banyak\n")
    with pytest.raises(ValueError, match="line 3"):
        report.read_stats(p)


@pytest.mark.parametrize("hook,kind", [
    ("Minum air dingin bikin gemuk? Salah besar.", "contradiction"),
    ("Tidur siang bikin malas? Belum tentu!", "contradiction"),
    ("3 kebiasaan pagi yang diam-diam bikin kamu ngantuk.", "number"),
    ("Ada dua momen otakmu kesetrum saat lagu favorit diputar.", "number"),
    ("Kalau kamu nyimpan cabai begini, pantesan cepat busuk.", "cost"),
    ("Hik! Pernah cegukan? Ternyata begini penyebabnya.", "question"),
    ("Langit itu biru.", "other"),
])
def test_hook_type(hook, kind):
    assert report.hook_type(hook) == kind


def test_features_from_project_dir():
    feats, templates, hook, duration = report.features(VIDEOS / "pagi-ngantuk")
    assert feats["hook type"] == "number" and feats["cta type"] == "save"
    assert feats["progress bar"] == "off" and feats["music"] == "on" and feats["duration"] == "≥45 s"
    assert feats["series"] == "kenapa" and feats["style"] == "example"
    assert "list_item" in templates and duration == 50
    # music comes from what the render used (result.json), not the spec's mood
    assert report.features(VIDEOS / "cabai-busuk")[0]["music"] == "off"
    # progress_bar unset in the spec = the style's default
    assert report.features(VIDEOS / "langit-biru")[0]["progress bar"] == "off"
    assert report.features(VIDEOS / "nope") is None


def test_variant_rows_read_variant_dir():
    b = report.features(report.project_dir_for(VIDEOS, "merinding", "B"))
    assert b[0]["hook type"] == "contradiction"


def test_avg_shot_counts_cards_as_one_shot():
    tl = {"scenes": [{"id": "a", "duration_ms": 4000}, {"id": "b", "duration_ms": 3000}]}
    assets = {"scenes": {"a": {"shots": [{"dur_ms": 2000}, {"dur_ms": 2000}]}}}
    assert report._avg_shot_s(assets, tl) == pytest.approx(7 / 3)


def test_build_groups_and_takeaways():
    r = report.build(STATS, VIDEOS, platform="tiktok", min_group=3)
    assert len(r.videos) == 9 and r.missing == ["belum-dirender"]
    tables = dict(r.tables)
    assert "platform" not in tables                 # one platform: nothing to compare
    hooks = {g.label: g for g in tables["hook type"]}
    assert hooks["contradiction"].n == 4 and not hooks["contradiction"].small
    assert hooks["number"].small
    assert hooks["contradiction"].avg["completion_pct"] == pytest.approx((31 + 29.5 + 34 + 27) / 4)
    assert tables["hook type"][0].label == "contradiction"          # best first
    assert any(t.startswith("**hook type: contradiction**") for t in r.takeaways())
    assert {g.label for g in tables["has myth_fact"]} == {"yes", "no"}


def test_all_platforms_skips_missing_metrics():
    r = report.build(STATS, VIDEOS, platform="all", min_group=3)
    plat = {g.label: g for g in dict(r.tables)["platform"]}
    assert plat["instagram"].n == 1 and plat["instagram"].avg["completion_pct"] is None
    assert plat["instagram"].avg["avg_watch_s"] == pytest.approx(10.2)


def test_markdown_flags_small_groups():
    md = report.to_markdown(report.build(STATS, VIDEOS, min_group=3), STATS)
    assert "## hook type" in md and "number ⚠" in md and "contradiction ⚠" not in md
    assert "belum-dirender" in md


def test_cli_report(tmp_path):
    out = tmp_path / "report.md"
    res = CliRunner().invoke(app, ["report", "--stats", str(STATS), "--projects", str(VIDEOS), "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "Takeaways" in res.output and out.read_text().startswith("# Klip performance report")


def test_cli_report_without_stats_file(tmp_path):
    res = CliRunner().invoke(app, ["report", "--stats", str(tmp_path / "missing.csv")])
    assert res.exit_code == 1 and "stats.example.csv" in res.output
