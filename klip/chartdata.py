"""Data series for stage `chart` elements: inline points, a CSV file, or a Yahoo Finance ticker.

The resolved series is written into the project (assets.fetch.json), so a re-render draws the same
line even after the market moves; a ticker is fetched again only when the assets stage reruns.
"""

from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from klip import config, http
from klip.paths import ROOT
from klip.spec import StageElement

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval={iv}"
BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"


class DataError(RuntimeError):
    pass


def _ts(d: str) -> int:
    return int(datetime.strptime(d[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def downsample(points: list[tuple[str, float]], n: int) -> list[tuple[str, float]]:
    """At most n points, evenly spaced, always keeping the first and last."""
    if len(points) <= n:
        return points
    step = (len(points) - 1) / (n - 1)
    return [points[round(i * step)] for i in range(n)]


def from_csv(path: str) -> list[tuple[str, float]]:
    p = Path(path).expanduser()
    p = p if p.is_absolute() else ROOT / p
    if not p.is_file():
        raise DataError(f"chart csv not found: {path}")
    with p.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    out = []
    for r in rows[1:]:
        if len(r) >= 2 and r[1].strip():
            try:
                out.append((r[0].strip(), float(r[1].replace(",", ""))))
            except ValueError:
                raise DataError(f"{path}: {r[1]!r} is not a number") from None
    return out


def from_ticker(sym: str, start: str, end: str | None) -> list[tuple[str, float]]:
    """Daily/weekly/monthly closes (by span) from Yahoo Finance's chart endpoint."""
    p1 = _ts(start)
    p2 = _ts(end) + 86400 if end else int(time.time()) // 86400 * 86400 + 86400   # whole days: cacheable
    days = (p2 - p1) / 86400
    iv = "1d" if days <= 200 else "1wk" if days <= 5 * 366 else "1mo"
    url = YAHOO.format(sym=quote(sym, safe=""), p1=p1, p2=p2, iv=iv)
    try:
        d = http.get_json(url, headers={"User-Agent": BROWSER_UA}, cache_key=f"yahoo:{sym}:{p1}:{p2}:{iv}")
    except http.HTTPError as e:
        raise DataError(f"ticker {sym}: {e}") from None
    res = ((d.get("chart") or {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise DataError(f"ticker {sym}: no data between {start} and {end or 'today'}")
    closes = res["indicators"]["quote"][0].get("close") or []
    off = int((res.get("meta") or {}).get("gmtoffset") or 0)        # dates in the exchange's time zone
    return [(datetime.fromtimestamp(t + off, timezone.utc).date().isoformat(), float(c))
            for t, c in zip(res["timestamp"], closes) if c is not None]


def series(e: StageElement) -> dict:
    """{"points": [[x, y], ...], "credit": {...} | None} for a chart element."""
    if e.points:
        pts, credit = [(p.x, p.y) for p in e.points], None
    elif e.csv:
        pts, credit = from_csv(e.csv), None
    else:
        pts = from_ticker(e.ticker, e.start, e.end)
        credit = {"provider": "yahoo", "id": e.ticker, "kind": "data", "duration_s": 0.0, "creator": "Yahoo Finance",
                  "creator_url": "", "page_url": f"https://finance.yahoo.com/quote/{quote(e.ticker, safe='')}",
                  "license": "data", "license_url": "", "title": f"{e.ticker} {pts[0][0] if pts else ''}–"
                                                                  f"{pts[-1][0] if pts else ''}", "nonfree": False}
    if len(pts) < 2:
        raise DataError("a chart needs at least 2 data points")
    return {"points": [[x, y] for x, y in downsample(pts, int(config.get("stage.chart.max_points", 160)))],
            "credit": credit}
