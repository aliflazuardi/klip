"""`klip` command-line interface."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from klip import __version__, config, env, pipeline
from klip.paths import RENDERER_DIR, SCHEMA_PATH
from klip.spec import load_spec, write_schema

app = typer.Typer(help="Klip — prompt → TikTok video pipeline.", no_args_is_help=True, add_completion=False)
console = Console()

VoiceOpt = typer.Option(None, "--voice", "-v", help="male | female (overrides the spec)")
OutOpt = typer.Option(None, "--out", "-o", help="Project dir (default: projects/<slug>)")
ProgressOpt = typer.Option(None, "--progress-bar/--no-progress-bar",
                           help="Show the progress bar at the top (default: the style's setting)")


def _version(value: bool) -> None:
    if value:
        console.print(f"klip {__version__}")
        raise typer.Exit()


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", help="Debug logging"),
          version: bool = typer.Option(False, "--version", callback=_version, is_eager=True,
                                       help="Show the version and exit")) -> None:
    env.load_dotenv()
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(message)s",
                        handlers=[RichHandler(console=Console(stderr=True), show_path=False, show_time=False)])


def _load_or_exit(spec_path: Path, voice: str | None, out: Path | None, progress_bar: bool | None = None):
    if voice and voice not in ("male", "female"):
        raise typer.BadParameter("voice must be 'male' or 'female'")
    try:
        return pipeline.resolve(spec_path, voice, out, progress_bar)
    except ValidationError as e:
        console.print(f"[red]Invalid spec {spec_path}:[/red]\n{e}")
        raise typer.Exit(2)


def print_preview(spec, issues) -> None:
    """The review gate: what the video will say and show, plus anything to fix or verify."""
    t = Table(title=f"{spec.slug} · voice={spec.voice} · style={spec.style}", show_lines=True)
    for col in ("id", "template", "visual", "on-screen", "narration"):
        t.add_column(col, overflow="fold")
    for s in spec.scenes:
        vis = s.visual.type + (f":{s.visual.query or s.visual.name or s.visual.path or ''}" if s.visual.type != "solid" else "")
        if s.visual.type == "stage":
            vis = f"stage:{s.visual.background or 'default'} " + ", ".join(
                e.kind if e.kind != "highlight" else "▭" for e in s.visual.elements)
        on = s.on_screen_text or ""
        if s.template == "myth_fact":
            on = f"❌ {s.myth}\n✅ {s.fact}"
        elif s.template == "stat":
            on = f"{s.stat.prefix}{s.stat.value:g}{s.stat.suffix} · {s.stat.label or on}"
        elif s.template == "compare":
            on = f"{s.compare.left.label} vs {s.compare.right.label}"
        from klip import prosody
        t.add_row(s.id, f"{s.template}\n[dim]{prosody.delivery_name(s)}[/dim]", vis, on, s.narration)
    for i, v in enumerate(spec.hook_variants):
        t.add_row(f"s1·{chr(ord('B') + i)}", "hook variant", "", v.on_screen_text or "", v.narration)
    console.print(t)
    est = pipeline.estimate_duration_s(spec)
    rate = spec.speech_rate or config.default_rate(spec.voice)
    pb = spec.progress_bar if spec.progress_bar is not None else config.style(spec.style)["progress_bar"]["enabled"]
    console.print(f"Words: {spec.word_count} · rate {rate}{'' if spec.speech_rate else ' (voice default)'} · "
                  f"est. duration {est:.1f}s (target {spec.target_duration_s}s) · "
                  f"progress bar {'on' if pb else 'off'}{'' if spec.progress_bar is not None else ' (style default)'}")
    for i in issues:
        color = "red" if i.level == "error" else "yellow"
        console.print(f"[{color}]{'✗' if i.level == 'error' else '!'} {i}[/{color}]")
    if spec.facts:
        console.print("[bold]Facts to verify before posting:[/bold]")
        for f in spec.facts:
            console.print(f"  • {f.claim}\n    {f.source}")
    if spec.post.caption:
        console.print(f"[bold]TikTok caption:[/bold] {spec.post.caption} {' '.join(spec.post.hashtags)}")


@app.command()
def validate(spec_path: Path, voice: Optional[str] = VoiceOpt) -> None:
    """Validate a spec and print the review preview. Exits 1 if it has errors."""
    from klip.lint import errors, lint
    try:
        spec = load_spec(spec_path)
    except ValidationError as e:
        console.print(f"[red]Invalid spec:[/red]\n{e}")
        raise typer.Exit(2)
    if voice:
        spec = spec.model_copy(update={"voice": voice})
    issues = lint(spec)
    print_preview(spec, issues)
    if errors(issues):
        raise typer.Exit(1)


def _write_script(topic: str, voice: str, duration: int, style: str, provider: str | None, out: Path | None,
                  hooks: int = 1, progress_bar: bool | None = None):
    from klip.engines.llm.base import LLMError
    from klip.stages import script
    if voice not in ("male", "female"):
        raise typer.BadParameter("voice must be 'male' or 'female'")
    try:
        with console.status(f"writing script for “{topic}”…"):
            result = script.generate(topic, voice, duration, style, script.get_provider(provider), hooks=hooks)
    except (LLMError, script.ScriptError) as e:
        console.print(f"[red]Script generation failed:[/red] {e}")
        raise typer.Exit(1)
    if progress_bar is not None:
        result.spec = result.spec.model_copy(update={"progress_bar": progress_bar})
    path = script.save(result.spec, out)
    tries = len(result.attempts)
    console.print(f"[green]✓[/green] wrote {path}  ({result.provider}, {tries} attempt{'s' if tries > 1 else ''})")
    print_preview(result.spec, result.issues)
    return path


TopicArg = typer.Argument(..., help="Topic in Indonesian, e.g. \"Kenapa langit biru?\"")
DurationOpt = typer.Option(45, "--duration", "-d", min=10, max=60, help="Target seconds")
StyleOpt = typer.Option("default", "--style", help="Style name from klip.yaml")
ProviderOpt = typer.Option(None, "--provider", help="auto | claude | openai (default: klip.yaml llm.provider)")


HooksOpt = typer.Option(1, "--hooks", min=1, max=5, help="Number of hooks to write (2+ adds hook_variants for A/B tests)")


@app.command()
def script(topic: str = TopicArg, voice: str = typer.Option("female", "--voice", "-v"),
           duration: int = DurationOpt, style: str = StyleOpt, provider: Optional[str] = ProviderOpt,
           out: Optional[Path] = typer.Option(None, "--out", "-o", help="Spec path (default: specs/<slug>.json)"),
           hooks: int = HooksOpt, progress_bar: Optional[bool] = ProgressOpt) -> None:
    """Write a spec for a topic with an LLM (no render)."""
    _write_script(topic, voice, duration, style, provider, out, hooks, progress_bar)


@app.command()
def new(topic: str = TopicArg, voice: str = typer.Option("female", "--voice", "-v"),
        duration: int = DurationOpt, style: str = StyleOpt, provider: Optional[str] = ProviderOpt,
        hooks: int = HooksOpt, progress_bar: Optional[bool] = ProgressOpt,
        no_review: bool = typer.Option(False, "--no-review", help="Render right away, skipping the review gate")) -> None:
    """Topic → spec (→ video with --no-review). Stops for review by default."""
    path = _write_script(topic, voice, duration, style, provider, None, hooks, progress_bar)
    flag = " --variants" if hooks > 1 else ""
    if no_review:
        _render(path, None, None, False, hooks > 1)
    else:
        console.print(f"\n[bold]Review the script above[/bold] (edit {path} if needed), then render:\n"
                      f"  uv run klip render {path}{flag}")


@app.command()
def say(text: str = typer.Argument(..., help="Text to speak, e.g. a tricky word"),
        voice: str = typer.Option("female", "--voice", "-v"), rate: Optional[str] = typer.Option(None, "--rate"),
        delivery: str = typer.Option("neutral", "--delivery", "-d",
                                     help="neutral | energetic | emphatic | warm | calm (klip.yaml prosody)"),
        play: bool = typer.Option(True, "--play/--no-play", help="Play the audio (macOS afplay)")) -> None:
    """Hear how the TTS pronounces something, with the lexicon applied. For tuning klip.yaml lexicon."""
    from klip.lexicon import apply_lexicon
    from klip.paths import PROJECTS_DIR
    from klip.stages.voice import get_engine, synthesize_cached
    from klip import prosody
    from klip.spec import Scene
    spoken = apply_lexicon(text, config.lexicon())
    pro = prosody.for_scene(Scene(id="say", template="explain", narration=text, delivery=delivery),
                            rate or config.default_rate(voice))
    engine = get_engine(config.get("voices.engine", "edge"))
    src, _ = synthesize_cached(engine, spoken, config.voice_id(voice, engine.name), pro.rate, pro.pitch, pro.volume)
    out = PROJECTS_DIR / "_say" / f"say-{voice}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out)
    console.print(f"spoken: “{spoken}”" + ("" if spoken == text else "  [dim](lexicon applied)[/dim]"))
    console.print(f"voice:  {voice}, {delivery} (rate {pro.rate}, pitch {pro.pitch}, volume {pro.volume})")
    console.print(f"audio:  {out}")
    if play and shutil.which("afplay"):
        subprocess.run(["afplay", str(out)])


VariantsOpt = typer.Option(False, "--variants", help="Also render every hook variant (A/B test) into variants/<letter>/")


@app.command()
def render(spec_path: Path, voice: Optional[str] = VoiceOpt, out: Optional[Path] = OutOpt,
           force: bool = typer.Option(False, help="Re-render even if the composition is unchanged"),
           variants: bool = VariantsOpt, progress_bar: Optional[bool] = ProgressOpt) -> None:
    """Render a spec to final.mp4 (voice → assets → compose → render → post → qa)."""
    _render(spec_path, voice, out, force, variants, progress_bar)


def _print_variants(rows: list[dict]) -> None:
    t = Table(title="hook variants (post each, compare watch time)", show_lines=True)
    for col in ("", "hook", "on-screen", "duration", "QA", "file"):
        t.add_column(col, overflow="fold")
    for r in rows:
        qa = "[green]✓[/]" if r.get("qa_passed") else "[red]✗[/]"
        t.add_row(r["variant"], r["hook"], r.get("on_screen") or "",
                  f"{r['duration_s']:.1f}s" if r.get("duration_s") else "", qa, r.get("final") or r.get("error", ""))
    console.print(t)


def _render(spec_path: Path, voice: str | None, out: Path | None, force: bool, variants: bool = False,
            progress_bar: bool | None = None) -> None:
    spec, project_dir = _load_or_exit(spec_path, voice, out, progress_bar)
    with console.status("starting…") as status:
        results = pipeline.run_all(spec, project_dir, force=force,
                                   on_stage=lambda s: status.update(f"[bold]{s}[/bold]…"))
    p = results["post"]
    console.print(f"[green]✓[/green] {p['final']}  ({p['width']}×{p['height']}, {p['fps']} fps, {p['duration_s']}s)")
    if p.get("nomusic"):
        console.print(f"  no-music: {p['nomusic']}  (music: {p['music']})")
    console.print(f"  cover: {project_dir / 'cover.png'}\n  post:  {project_dir / 'post.txt'}")
    warnings = results["compose"]["warnings"] + results["assets"].get("warnings", [])
    if warnings:
        console.print(f"[yellow]{len(warnings)} warning(s):[/yellow] " + "; ".join(warnings))
    _print_qa(results["qa"])
    if variants:
        if not spec.hook_variants:
            console.print("[yellow]--variants: this spec has no hook_variants (write some, or use `klip new --hooks 3`)[/yellow]")
        else:
            with console.status("rendering hook variants…") as status:
                rows = pipeline.run_variants(spec, project_dir, results,
                                             on_stage=lambda s: status.update(f"[bold]{s}[/bold]…"))
            _print_variants(rows)
            if not all(r.get("qa_passed") for r in rows):
                raise typer.Exit(1)
    if not results["qa"]["passed"]:
        raise typer.Exit(1)


def _print_qa(report: dict) -> None:
    console.print(f"[bold]QA {'[green]passed' if report['passed'] else '[red]FAILED'}[/][/bold]")
    for c in report["checks"]:
        console.print(f"  {'[green]✓' if c['ok'] else '[red]✗'}[/] {c['name']}: {c['detail']}")


@app.command("run")
def run_stage(stage: str = typer.Argument(..., help="voice | assets | compose | render | post | qa"),
              spec_path: Path = typer.Argument(...), voice: Optional[str] = VoiceOpt,
              out: Optional[Path] = OutOpt, force: bool = typer.Option(False)) -> None:
    """Run a single stage (for debugging). Earlier stages' outputs must exist."""
    spec, project_dir = _load_or_exit(spec_path, voice, out)
    result = pipeline.run_stage(stage, spec, project_dir, force=force)
    if stage == "qa":
        _print_qa(result)
        raise typer.Exit(0 if result["passed"] else 1)
    console.print_json(json.dumps(result, default=str, ensure_ascii=False))


@app.command()
def batch(path: Path = typer.Argument(..., help="topics.yaml (see examples/batch.yaml)"),
          scripts_only: bool = typer.Option(False, "--scripts-only",
                                            help="Write specs for review, plus <name>.specs.yaml to render them later")) -> None:
    """Make many videos from a YAML list of topics/specs. Continues past failures."""
    from klip import batch as batch_mod
    try:
        results, report = batch_mod.run(
            path, scripts_only,
            on_item=lambda n, total, item, what: console.print(f"[bold][{n}/{total}][/bold] {item.label}: {what}…"))
    except (ValueError, FileNotFoundError) as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)
    t = Table(title=f"batch {path.name}", show_lines=True)
    for col in ("#", "item", "status", "duration", "time", "output / detail"):
        t.add_column(col, overflow="fold")
    colors = {"ok": "green", "scripted": "cyan", "qa_failed": "yellow", "failed": "red"}
    for i, r in enumerate(results, 1):
        t.add_row(str(i), r.label, f"[{colors[r.status]}]{r.status}[/]",
                  f"{r.duration_s:.1f}s" if r.duration_s else "", f"{r.seconds:.0f}s",
                  r.detail or r.final or r.spec_path or "")
    console.print(t)
    ok = sum(r.status in ("ok", "scripted") for r in results)
    console.print(f"{ok}/{len(results)} succeeded · report: {report}")
    if scripts_only:
        console.print(f"Review the specs, then: uv run klip batch {path.with_name(path.stem + '.specs.yaml')}")
    if ok < len(results):
        raise typer.Exit(1)


@app.command()
def mcp() -> None:
    """Run the MCP server on stdio (what Claude Desktop / Claude Code launch)."""
    from klip.mcp_server import main
    main()


DESKTOP_CONFIG = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def desktop_server_entry() -> dict:
    """Absolute paths + PATH, because Claude Desktop starts servers with a minimal environment."""
    import os
    from klip.engines.render.hyperframes import find_node
    from klip.paths import ROOT
    uv = shutil.which("uv") or "uv"
    dirs = [str(Path(p).parent) for p in (uv, shutil.which("ffmpeg"), find_node()) if p and os.path.isabs(p)]
    path = ":".join(dict.fromkeys(dirs + ["/usr/local/bin", "/usr/bin", "/bin"]))
    return {"command": uv, "args": ["--directory", str(ROOT), "run", "klip-mcp"], "env": {"PATH": path}}


@app.command("mcp-config")
def mcp_config(install: bool = typer.Option(False, "--install", help=f"Add it to {DESKTOP_CONFIG} (backs it up first)")) -> None:
    """Print (or install) the Claude Desktop config entry for the Klip MCP server."""
    entry = desktop_server_entry()
    if not install:
        console.print_json(json.dumps({"mcpServers": {"klip": entry}}))
        console.print(f"[dim]Add this to {DESKTOP_CONFIG} (or run with --install), then restart Claude Desktop.[/dim]")
        return
    data = json.loads(DESKTOP_CONFIG.read_text()) if DESKTOP_CONFIG.exists() else {}
    if DESKTOP_CONFIG.exists():
        backup = DESKTOP_CONFIG.with_suffix(".json.bak")
        shutil.copyfile(DESKTOP_CONFIG, backup)
        console.print(f"backup: {backup}")
    data.setdefault("mcpServers", {})["klip"] = entry
    DESKTOP_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_CONFIG.write_text(json.dumps(data, indent=2) + "\n")
    console.print(f"[green]✓[/green] added 'klip' to {DESKTOP_CONFIG}. Restart Claude Desktop.")


@app.command()
def voices() -> None:
    """List configured voices."""
    for engine, mapping in config.get("voices.ids", {}).items():
        mark = " (default)" if engine == config.get("voices.engine") else ""
        console.print(f"[bold]{engine}{mark}[/bold]")
        for k, v in mapping.items():
            console.print(f"  {k:<7} → {v}")


@app.command()
def report(stats: Optional[Path] = typer.Option(None, "--stats", help="Stats CSV (default: report.stats_file)"),
           projects: Optional[Path] = typer.Option(None, "--projects", help="Projects dir (default: projects/)"),
           platform: Optional[str] = typer.Option(None, "--platform", "-p", help="tiktok | instagram | youtube | all (default: report.platform)"),
           out: Optional[Path] = typer.Option(None, "--out", "-o", help="Markdown summary (default: report.output)")) -> None:
    """Which features go with higher completion and watch time (stats.csv × projects/)."""
    from klip import report as rep
    from klip.paths import PROJECTS_DIR
    stats = stats or rep.stats_path_default()
    if not stats.exists():
        console.print(f"[red]No stats file at {stats}.[/red] Copy stats.example.csv to {stats.name} and fill in "
                      "one row per posted video (numbers from TikTok/Instagram/YouTube analytics).")
        raise typer.Exit(1)
    try:
        r = rep.build(stats, projects or PROJECTS_DIR, platform)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)
    if r.missing:
        console.print(f"[yellow]No rendered project for: {', '.join(r.missing)} (skipped)[/yellow]")
    if not r.videos:
        console.print("[yellow]No stats rows matched a project; nothing to report.[/yellow]")
        raise typer.Exit(1)
    console.print(f"[bold]{len(r.videos)} videos ({r.platform})[/bold] · groups with n < {r.min_group} marked ⚠ (too few to trust)")
    for name, groups in r.tables:
        t = Table(title=name, title_justify="left")
        t.add_column("group")
        t.add_column("n", justify="right")
        for _, head, _ in rep.METRICS:
            t.add_column(head, justify="right")
        for g in groups:
            style = "dim" if g.small else None
            t.add_row(f"{g.label} ⚠" if g.small else g.label, str(g.n),
                      *(rep.fmt(g.avg[m], d) for m, _, d in rep.METRICS), style=style)
        console.print(t)
    takeaways = r.takeaways()
    console.print("[bold]Takeaways[/bold]")
    for line in takeaways or [f"not enough data yet (need two groups of {r.min_group}+ videos for a feature)"]:
        console.print("  • " + line.replace("**", ""))
    out = out or rep.output_path_default()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rep.to_markdown(r, stats), encoding="utf-8")
    console.print(f"wrote {out}")


@app.command()
def styles() -> None:
    """List styles a spec can pick with "style" (klip.yaml styles and brand packs)."""
    yaml_styles = set(config.get("styles", {}))
    t = Table("style", "source", "accent", "logo")
    for name in config.styles():
        st = config.style(name)
        source = "klip.yaml" if name in yaml_styles else f"brands/{name}/"
        t.add_row(name, source, st.get("accent_color") or "", "✓" if st["end_card"].get("logo") else "")
    console.print(t)


@app.command()
def schema(out: Path = typer.Option(SCHEMA_PATH, help="Output path")) -> None:
    """Export the spec JSON Schema."""
    console.print(f"wrote {write_schema(out)}")


@app.command()
def doctor() -> None:
    """Check ffmpeg, node, HyperFrames, and edge-tts reachability."""
    from klip.engines.render.hyperframes import HyperFramesRenderer, find_node

    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        console.print(f"{'[green]✓' if passed else '[red]✗'}[/] {name} {detail}")

    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        ver = subprocess.run([tool, "-version"], capture_output=True, text=True).stdout.split("\n")[0] if path else ""
        check(tool, bool(path), ver)
    try:
        node = find_node()
        check("node >= 22", True, subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip() + f" ({node})")
    except Exception as e:
        check("node >= 22", False, str(e))
    check("renderer deps", HyperFramesRenderer().cli.exists(),
          "" if HyperFramesRenderer().cli.exists() else f"run: cd {RENDERER_DIR} && npm install")
    try:
        import asyncio

        import edge_tts
        vs = asyncio.run(edge_tts.list_voices())
        ids = {v["ShortName"] for v in vs}
        want = set(config.get("voices.ids.edge", {}).values())
        check("edge-tts", want <= ids, f"{edge_tts.__version__}; voices {'ok' if want <= ids else 'missing: ' + str(want - ids)}")
    except Exception as e:
        check("edge-tts", False, f"unreachable: {e}")
    from klip.stages.assets import default_providers
    names = [p.name for p in default_providers() if p.enabled()]
    console.print(f"[green]✓[/] media providers: {', '.join(names)}")
    for key in ("PIXABAY_API_KEY", "PEXELS_API_KEY"):
        console.print(f"{'[green]✓' if env.get(key) else '[dim]-'}[/] {key}{'' if env.get(key) else ' (optional, not set)'}")
    raise typer.Exit(0 if ok else 1)


if __name__ == "__main__":
    app()
