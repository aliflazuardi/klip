"""Photo brief: which stage props should get a photo from the user, and the folder they go in.

Stage props (cutout/photo/person/logo) look for the user's own file first: stage.photos.dir/<slug>/
named `<scene>-<n>` or `<scene>-<n>-anything` (n = the element's 1-based number in the scene), e.g.
`specs/photos/judi-online/s1-1-bandar.png`. After the assets fetch, photo-brief.md lists the props
that have no photo, that are marked `own`, or whose stock photo the vision check rated below
stage.photos.brief_below, with the file name to save and where to look.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, quote_plus

from klip import config
from klip.paths import ROOT
from klip.spec import MEDIA, Spec

EXTS = (".png", ".jpg", ".jpeg", ".webp")
KIND_HINT = {
    "cutout": "cutout: objek/orang dipotong dari latarnya (latar polos paling bersih; PNG transparan dipakai apa adanya)",
    "photo": "foto utuh, dibingkai seperti polaroid (boleh landscape)",
    "person": "potret wajah orangnya (kartu tokoh)",
    "logo": "logo resmi, sebaiknya PNG transparan",
}


def _cfg(key: str, default=None):
    return config.get(f"stage.photos.{key}", default)


def photo_dir(spec: Spec) -> Path:
    d = Path(_cfg("dir", "specs/photos"))
    return (d if d.is_absolute() else ROOT / d) / spec.slug


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30] or "foto"


def filename(scene_id: str, i: int, at: str) -> str:
    """Suggested name (without extension) for element i (0-based) of a scene."""
    return f"{scene_id}-{i + 1}-{_slug(at)}"


def find_own(folder: Path, scene_id: str, i: int) -> Path | None:
    """The user's file for element i (0-based): <scene>-<n>.<ext> or <scene>-<n>-<anything>.<ext>."""
    if not folder.is_dir():
        return None
    n = i + 1
    hits = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS and
                  (p.stem.lower() == f"{scene_id}-{n}".lower() or p.stem.lower().startswith(f"{scene_id}-{n}-".lower())))
    return hits[0] if hits else None


def own_photos(spec: Spec) -> dict[str, dict[int, Path]]:
    """{scene id: {element index: file}} for the files in the spec's photo folder."""
    folder = photo_dir(spec)
    out: dict[str, dict[int, Path]] = {}
    for s in spec.scenes:
        if s.visual.type != "stage":
            continue
        for i, e in enumerate(s.visual.elements):
            if e.kind in MEDIA and (f := find_own(folder, s.id, i)):
                out.setdefault(s.id, {})[i] = f
    return out


def _context(narration: str, at: str) -> str:
    first = at.split()[0].lower().strip(".,!?\"'")
    for sent in re.split(r"(?<=[.!?])\s+", narration):
        if first in sent.lower():
            return sent.strip()
    return narration[:140]


def links(query: str) -> dict[str, str]:
    q = query.strip()
    return {"Unsplash": f"https://unsplash.com/s/photos/{quote(q.replace(' ', '-'))}",
            "Pexels": f"https://www.pexels.com/search/{quote(q)}/",
            "Pixabay": f"https://pixabay.com/images/search/{quote(q)}/",
            "Commons": f"https://commons.wikimedia.org/w/index.php?title=Special:MediaSearch&type=image&search={quote_plus(q)}"}


def items(spec: Spec, scenes: dict, vision_ok: bool) -> list[dict]:
    """One row per stage media prop with a status: provided | missing | own | weak | unchecked | ok."""
    below = int(_cfg("brief_below", 3))
    out = []
    for s in spec.scenes:
        if s.visual.type != "stage":
            continue
        rows = {r["el"]: r for r in (scenes.get(s.id) or {}).get("stage", [])}
        for i, e in enumerate(s.visual.elements):
            if e.kind not in MEDIA:
                continue
            r = rows.get(i)
            origin = (r or {}).get("origin")
            score = (r or {}).get("vision_score")
            if origin in ("own", "path"):
                status = "provided"
            elif not r:
                status = "missing"
            elif e.own:
                status = "own"
            elif origin != "stock":
                status = "ok"                       # a Wikipedia image of `who`
            elif (score is not None and score < below) or (vision_ok and score is None) or \
                    (score is None and r.get("vision_rescued")):
                status = "weak"
            elif not vision_ok:
                status = "unchecked"
            else:
                status = "ok"
            cr = (r or {}).get("credit") or {}
            out.append({"scene": s.id, "el": i, "n": i + 1, "at": e.at, "kind": e.kind, "status": status,
                        "want": e.brief or e.query or e.who or "", "query": e.query or e.who or "",
                        "label": e.label, "fallback_icon": e.name if e.kind in ("cutout", "photo") else None,
                        "file": filename(s.id, i, e.at), "context": _context(s.narration, e.at),
                        "vision_score": score, "current": cr.get("page_url") or (r or {}).get("src"),
                        "current_by": f"{cr.get('provider', '')} {cr.get('creator', '')}".strip() or None})
    return out


NEED = ("missing", "own")
BETTER = ("weak", "unchecked")


def markdown(spec: Spec, rows: list[dict], folder: Path) -> str:
    rel = folder.relative_to(ROOT) if folder.is_relative_to(ROOT) else folder
    need = [r for r in rows if r["status"] in NEED]
    better = [r for r in rows if r["status"] in BETTER]
    done = [r for r in rows if r["status"] in ("ok", "provided")]
    lines = [f"# Photo brief: {spec.slug}", "",
             f"Folder: `{rel}/`", "",
             "Simpan foto dengan nama file di bawah (jpg, png atau webp; nama setelah nomor boleh diubah). "
             f"Render ulang (`uv run klip render specs/{spec.slug}.json`) memakainya otomatis. Untuk cutout, "
             "latarnya dihapus otomatis; PNG yang sudah transparan dipakai apa adanya.", "",
             "Pakai foto sendiri atau yang lisensinya bebas dipakai (Unsplash, Pexels, Pixabay, CC0/CC BY), "
             "dan catat kreditnya bila lisensinya minta atribusi.", ""]

    def block(k: int, r: dict) -> list[str]:
        now = {"missing": (f"belum ada foto, sementara ikon `{r['fallback_icon']}`" if r["fallback_icon"]
                           else "belum ada foto, prop ini dilewati"),
               "own": "foto stock sementara" + (f" ({r['current_by']}: {r['current']})" if r["current"] else ""),
               "weak": f"foto stock, cocoknya {r['vision_score'] if r['vision_score'] is not None else '?'}/3"
                       + (f" ({r['current']})" if r["current"] else ""),
               "unchecked": "foto stock, belum dicek vision" + (f" ({r['current']})" if r["current"] else "")}[r["status"]]
        out = [f"### {k}. {r['scene']} · \"{r['at']}\" → `{r['file']}.jpg`", "",
               f"- **Yang dicari:** {r['want']}" + (f" (label: {r['label']})" if r["label"] else ""),
               f"- **Bentuk:** {KIND_HINT[r['kind']]}",
               f"- **Konteks:** \"{r['context']}\"",
               f"- **Sekarang:** {now}"]
        if r["query"]:
            out.append("- **Cari:** " + " · ".join(f"[{n}]({u})" for n, u in links(r["query"]).items()))
        return out + [""]

    k = 0
    if need:
        lines += [f"## Perlu foto ({len(need)})", ""]
        for r in need:
            k += 1
            lines += block(k, r)
    if better:
        lines += [f"## Bisa lebih bagus ({len(better)})", "", "Sudah ada foto stock, tapi kurang pas. Opsional.", ""]
        for r in better:
            k += 1
            lines += block(k, r)
    if done:
        lines += [f"## Sudah oke ({len(done)})", ""]
        lines += [f"- {r['scene']} · \"{r['at']}\": " + ("fotomu" if r["status"] == "provided" else
                  f"{r['current_by'] or 'sumber nyata'}" + (f", cocok {r['vision_score']}/3" if r["vision_score"] is not None else ""))
                  for r in done]
        lines.append("")
    if not rows:
        lines += ["Video ini tidak punya prop foto di stage.", ""]
    return "\n".join(lines)


def write(spec: Spec, scenes: dict, project_dir: Path, vision_ok: bool) -> dict:
    """photo-brief.json + photo-brief.md in the project; creates the photo folder. Returns a summary."""
    rows = items(spec, scenes, vision_ok)
    folder = photo_dir(spec)
    if rows:
        folder.mkdir(parents=True, exist_ok=True)
    (project_dir / "photo-brief.json").write_text(json.dumps({"folder": str(folder), "items": rows},
                                                             indent=2, ensure_ascii=False))
    md = project_dir / "photo-brief.md"
    md.write_text(markdown(spec, rows, folder), encoding="utf-8")
    return {"path": str(md), "folder": str(folder), "props": len(rows),
            "need": sum(r["status"] in NEED for r in rows), "better": sum(r["status"] in BETTER for r in rows),
            "provided": sum(r["status"] == "provided" for r in rows)}
