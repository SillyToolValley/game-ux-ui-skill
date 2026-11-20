#!/usr/bin/env python3
"""Anchor-first game UI workflow.

One shipped game screen is the *anchor*: the quality bar and the structural model for one
screen of your game. These commands keep that loop cheap and honest:

- ``anchor add``  register one hero anchor (and at most two narrow supports) per screen
- ``anchor show`` print what is registered
- ``shot``        screenshot your build at the size it ships at
- ``compare``     put anchor and candidate side by side with squint/value/overlay tools
- ``audit``       deterministic floor checks on an HTML build (text size, contrast, safe area)

``anchor`` and ``compare`` need nothing beyond the standard library. ``shot``, ``audit`` and
palette extraction use the optional Playwright extra.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
from html import escape
from pathlib import Path
from typing import Any

MAX_SUPPORTS = 2
ROUND_SOFT_CAP = 3
CAPTURE_KINDS = ("own-capture", "press-kit", "store-page", "trailer-frame", "other")
BROWSER_ENV = "UI_REF_BROWSER_PATH"

# Floors, not targets. Text heights are CSS px at a 1080-line canvas and scale with viewport
# height, except "handheld" and "mobile", which are absolute. Sources are listed in the skill's
# references/platform-numbers.md together with their verification status.
PLATFORMS: dict[str, dict[str, Any]] = {
    "tv": {
        "label": "Console / TV (10-foot)",
        "viewport": (1920, 1080), "min_text": 26, "warn_text": 28, "scale_text": True,
        "safe": 0.05, "min_target": 0, "needs_focus": True,
    },
    "desktop": {
        "label": "PC (desk distance)",
        "viewport": (1920, 1080), "min_text": 18, "warn_text": 20, "scale_text": True,
        "safe": 0.0, "min_target": 0, "needs_focus": False,
    },
    "handheld": {
        "label": "Handheld PC (1280x800, 30 cm)",
        "viewport": (1280, 800), "min_text": 9, "warn_text": 12, "scale_text": False,
        "safe": 0.0, "min_target": 0, "needs_focus": True,
    },
    "mobile": {
        "label": "Phone (touch)",
        "viewport": (390, 844), "min_text": 11, "warn_text": 14, "scale_text": False,
        "safe": 0.04, "min_target": 44, "needs_focus": False,
    },
}


def _cli() -> Any:
    import ui_ref_cli
    return ui_ref_cli


# --------------------------------------------------------------------------------------
# Workspace helpers
# --------------------------------------------------------------------------------------

def anchor_root(args: argparse.Namespace) -> tuple[Path, Path]:
    cli = _cli()
    root = cli.project_root_from_args(args)
    cfg = cli.load_config(root, args)
    workspace = str(cfg.get("anchor_workspace") or "ui_anchor")
    return root, cli.resolve_under_root(root, workspace)


def screen_dir(base: Path, screen: str) -> Path:
    slug = _cli().safe_slug(screen, "")
    if not slug or slug in {".", ".."}:
        raise SystemExit(f"Invalid screen id: {screen!r}")
    return base / slug


def load_anchor(folder: Path) -> dict[str, Any]:
    path = folder / "anchor.json"
    if not path.exists():
        raise SystemExit(
            f"No anchor registered for screen {folder.name!r}. "
            f"Run: ui-ref anchor add <image> --screen {folder.name} --game \"<game>\""
        )
    data = _cli().load_json(path)
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid anchor file: {path}")
    return data


def parse_viewport(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*", value or "")
    if not match:
        raise SystemExit(f"Viewport must look like 1920x1080, got {value!r}")
    return int(match.group(1)), int(match.group(2))


def next_round(folder: Path) -> tuple[int, Path]:
    rounds = folder / "rounds"
    # A round exists once its record is written; a bare folder holding a fresh screenshot does not count.
    existing = [int(p.name) for p in rounds.iterdir() if p.name.isdigit() and (p / "round.json").exists()] if rounds.exists() else []
    number = max(existing, default=0) + 1
    return number, rounds / f"{number:02d}"


# --------------------------------------------------------------------------------------
# Browser (optional)
# --------------------------------------------------------------------------------------

class BrowserUnavailable(RuntimeError):
    pass


def _with_page(viewport: tuple[int, int], work: Any, scale: float = 1.0) -> Any:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        raise BrowserUnavailable(
            f"Playwright is not installed ({exc}). Install the optional extra: "
            "pip install 'game-ux-ui-skill[browser]' && playwright install chromium"
        ) from exc
    with sync_playwright() as pw:
        options: dict[str, Any] = {"headless": True}
        explicit = os.environ.get(BROWSER_ENV)
        if explicit:
            options["executable_path"] = explicit
        try:
            browser = pw.chromium.launch(**options)
        except Exception as exc:
            raise BrowserUnavailable(
                f"Chromium could not be launched ({str(exc).splitlines()[0]}). Run "
                f"`playwright install chromium`, or point {BROWSER_ENV} at a Chromium binary."
            ) from exc
        try:
            context = browser.new_context(
                viewport={"width": viewport[0], "height": viewport[1]}, device_scale_factor=scale
            )
            return work(context.new_page())
        finally:
            browser.close()


def target_url(root: Path, target: str) -> str:
    if re.match(r"^https?://", target, flags=re.I):
        return target
    path = Path(target)
    path = path if path.is_absolute() else (root / path)
    if not path.is_file():
        raise SystemExit(f"Target not found: {target} (expected an HTML file or an http(s) URL)")
    return path.resolve().as_uri()


_PALETTE_JS = r"""
async (dataUrl) => {
  const img = new Image();
  img.src = dataUrl;
  await img.decode();
  const scale = Math.min(1, 200 / Math.max(img.naturalWidth, img.naturalHeight));
  const w = Math.max(1, Math.round(img.naturalWidth * scale));
  const h = Math.max(1, Math.round(img.naturalHeight * scale));
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h).data;
  const buckets = new Map();
  let lum = 0, dark = 0, light = 0, n = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 128) continue;
    const r = data[i], g = data[i + 1], b = data[i + 2];
    const key = (r >> 4 << 8) | (g >> 4 << 4) | (b >> 4);
    let e = buckets.get(key);
    if (!e) { e = [0, 0, 0, 0]; buckets.set(key, e); }
    e[0] += r; e[1] += g; e[2] += b; e[3] += 1;
    const l = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    lum += l; n += 1;
    if (l < 0.2) dark += 1; else if (l > 0.8) light += 1;
  }
  if (!n) return null;
  const hex = (r, g, b) => '#' + [r, g, b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const sat = (r, g, b) => { const mx = Math.max(r, g, b), mn = Math.min(r, g, b); return mx === 0 ? 0 : (mx - mn) / mx; };
  let cols = [...buckets.values()].map(e => ({ r: e[0] / e[3], g: e[1] / e[3], b: e[2] / e[3], count: e[3] }));
  cols.sort((a, b) => b.count - a.count);
  const merged = [];
  for (const c of cols) {
    const near = merged.find(m => Math.abs(m.r - c.r) + Math.abs(m.g - c.g) + Math.abs(m.b - c.b) < 48);
    if (near) {
      const t = near.count + c.count;
      near.r = (near.r * near.count + c.r * c.count) / t;
      near.g = (near.g * near.count + c.g * c.count) / t;
      near.b = (near.b * near.count + c.b * c.count) / t;
      near.count = t;
    } else merged.push({ ...c });
  }
  merged.sort((a, b) => b.count - a.count);
  const out = c => ({ hex: hex(c.r, c.g, c.b), share: +(100 * c.count / n).toFixed(1) });
  const dominant = merged.filter(c => c.count / n >= 0.0005).slice(0, 8).map(out);
  const accents = merged
    .filter(c => c.count / n >= 0.002 && sat(c.r, c.g, c.b) >= 0.55 && Math.max(c.r, c.g, c.b) >= 110)
    .sort((a, b) => sat(b.r, b.g, b.b) * Math.sqrt(b.count) - sat(a.r, a.g, a.b) * Math.sqrt(a.count))
    .slice(0, 5).map(out);
  return {
    dominant, accents,
    mean_luminance: +(lum / n).toFixed(3),
    dark_share: +(100 * dark / n).toFixed(1),
    light_share: +(100 * light / n).toFixed(1),
  };
}
"""


def extract_palette(image: Path) -> dict[str, Any] | None:
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
    data_url = f"data:{mime.get(image.suffix.lower(), 'image/png')};base64," + base64.b64encode(image.read_bytes()).decode("ascii")

    def work(page: Any) -> Any:
        page.set_content("<!doctype html><title>palette</title>")
        return page.evaluate(_PALETTE_JS, data_url)

    return _with_page((400, 300), work)


# --------------------------------------------------------------------------------------
# anchor add / show
# --------------------------------------------------------------------------------------

def anatomy_template(screen: str, game: str, hero_name: str, dims: tuple[int, int] | None, palette: dict[str, Any] | None) -> str:
    size = f"{dims[0]}x{dims[1]}" if dims else "unknown — measure it"
    if palette:
        dominant = ", ".join(f"`{c['hex']}` {c['share']}%" for c in palette.get("dominant", []))
        accents = ", ".join(f"`{c['hex']}` {c['share']}%" for c in palette.get("accents", [])) or "none detected"
        measured_palette = (
            f"- Extracted dominant colours: {dominant}\n"
            f"- Extracted saturated accents: {accents}\n"
            f"- Mean luminance {palette.get('mean_luminance')}; dark pixels {palette.get('dark_share')}%, "
            f"light pixels {palette.get('light_share')}%\n"
        )
    else:
        measured_palette = "- Palette was not extracted (browser extra missing). Sample the hex values yourself.\n"
    return f"""# Anchor anatomy — {screen}

Anchor: **{game or 'TODO: game title'}** · `{hero_name}` · {size}

Fill this in by looking at the anchor image. Write numbers and named mechanisms, not adjectives.
Delete every TODO before you build.

## 1. Why this anchor

TODO: one or two sentences. Which job does this screen do better than its peers, and why does
that job match ours?

## 2. Measured

- Canvas: {size}. Observed outer margin: TODO px / % of width.
- Blocking — each region as a share of the screen (ASCII map, anchor proportions):

```
TODO
```

- UI coverage: TODO % of the frame is UI. Kept-clear zone: TODO.
- Type: largest TODO px · body TODO px · smallest TODO px (at native size). Weights, case,
  tracking, numeral style: TODO. Number of distinct sizes: TODO.
{measured_palette}- Colour roles (assign the extracted colours): background TODO · surface TODO · primary text
  TODO · accent TODO · danger TODO · reward/rarity TODO. Accent share of the frame: TODO %.
- Shape and material: corner radius TODO · stroke weight TODO · fill style TODO (flat, gradient,
  texture, bevel) · icon construction TODO · frame/ornament vocabulary TODO.
- Motion (only if you watched footage; otherwise write "not observed"): TODO.

## 3. Why it works

Three to five mechanisms. Each names a visible feature and the player problem it solves.

1. TODO
2. TODO
3. TODO

## 4. Translation — keep, change, drop

Keep structure and mechanisms. Change everything that carries the anchor's identity.

| Aspect | Anchor does | We do | K/C/D | Why |
| --- | --- | --- | --- | --- |
| Layout proportions | TODO | TODO | Keep | TODO |
| Information hierarchy | TODO | TODO | Keep | TODO |
| Density and spacing rhythm | TODO | TODO | Keep | TODO |
| Palette | TODO | TODO | Change | Ours comes from our fiction |
| Typeface | TODO | TODO | Change | TODO |
| Material and ornament | TODO | TODO | Change | TODO |
| Iconography | TODO | TODO | Change | Original art only |
| Content and labels | TODO | TODO | Change | Our real game data |
| TODO anchor-specific feature | TODO | — | Drop | TODO |

## 5. Our plan

- Colours (4–6, hex + role): TODO
- Type roles (display / body / numerals): TODO
- Layout (ASCII, our proportions):

```
TODO
```

- Where our game's fiction shows up (materials, vernacular, world objects): TODO
- The one place we spend boldness: TODO
- Generic check: would this plan fit any similar game unchanged? If yes, revise before building.
"""


def critique_template(screen: str, number: int, game: str) -> str:
    return f"""# Round {number:02d} critique — {screen}

Open `compare.html`. Judge the candidate against the anchor ({game or 'anchor'}) at the size it
ships at. Record what you see, then fix the top three and run another round.

| # | Lens | Anchor | Candidate | Verdict | Fix |
| --- | --- | --- | --- | --- | --- |
| 1 | Squint: big shapes and blocking | | | | |
| 2 | Values: what reads first, second, third | | | | |
| 3 | Density: coverage, spacing rhythm, clear zone | | | | |
| 4 | Type: size steps, weight contrast, numerals | | | | |
| 5 | Colour: roles, accent budget | | | | |
| 6 | Material: shape language, edges, texture | | | | |
| 7 | Readability at shipping size and distance | | | | |
| 8 | Game-UI tells (see references/game-ui-tells.md) | | | | |
| 9 | Originality: our fiction, our assets, not a clone | n/a | | | |

Verdict is one of: `matches bar`, `below bar`, `not assessed`.

## Top three fixes for the next round

1.
2.
3.

## Outcome

One of: **ship** · **another round** · **wrong anchor or wrong plan** (go back to ANATOMY.md
instead of polishing).
"""


def command_anchor_add(args: argparse.Namespace) -> int:
    cli = _cli()
    root, base = anchor_root(args)
    folder = screen_dir(base, args.screen)
    source = Path(args.image)
    source = source if source.is_absolute() else (root / source)
    if not source.is_file():
        raise SystemExit(f"Image not found: {args.image}")
    suffix = source.suffix.lower()
    if suffix not in cli.IMAGE_EXTS:
        raise SystemExit(f"Unsupported image type {suffix!r}; use one of {', '.join(sorted(cli.IMAGE_EXTS))}")

    meta_path = folder / "anchor.json"
    meta: dict[str, Any] = cli.load_json(meta_path) if meta_path.exists() else {"format": 1, "screen": folder.name, "supports": []}
    supports: list[dict[str, Any]] = list(meta.get("supports") or [])

    if args.role == "hero":
        if meta.get("hero") and not args.force:
            raise SystemExit(
                f"Screen {folder.name!r} already has a hero anchor ({meta['hero'].get('game') or meta['hero'].get('file')}). "
                "One screen gets one hero: a second one averages two designs into a generic one. "
                "Use --role support --borrow \"<one specific thing>\" for a narrow addition, or --force to replace the hero."
            )
        filename = f"hero{suffix}"
    else:
        if not meta.get("hero"):
            raise SystemExit("Register the hero anchor first; a support only fills a named gap in the hero.")
        if not (args.borrow or "").strip():
            raise SystemExit("--role support needs --borrow \"<the one specific thing taken from this image>\".")
        if len(supports) >= MAX_SUPPORTS:
            raise SystemExit(
                f"Screen {folder.name!r} already has {MAX_SUPPORTS} supports. More references blur the anchor; "
                "remove one from anchor.json first."
            )
        used = {s.get("file") for s in supports}
        index = next(i for i in range(1, MAX_SUPPORTS + 2) if not any(str(u).startswith(f"support-{i}.") for u in used))
        filename = f"support-{index}{suffix}"

    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / filename
    if args.role == "hero":
        for stale in folder.glob("hero.*"):
            if stale != destination:
                stale.unlink()
    cli.write_bytes(destination, source.read_bytes())
    dims = cli.image_dimensions(destination)

    palette = None
    palette_note = ""
    if not args.no_palette:
        try:
            palette = extract_palette(destination)
        except BrowserUnavailable as exc:
            palette_note = f"Palette not extracted: {exc}"
        except Exception as exc:  # palette is a convenience; never block registration on it
            palette_note = f"Palette not extracted: {type(exc).__name__}: {exc}"

    record: dict[str, Any] = {
        "file": filename,
        "game": args.game or "",
        "source_url": args.source_url or "",
        "capture": args.capture,
        "note": args.note or "",
        "sha256": cli.file_sha256(destination),
        "width": dims[0] if dims else None,
        "height": dims[1] if dims else None,
        "added_at": cli.now_iso(),
        "palette": palette,
    }
    if args.role == "hero":
        meta["hero"] = record
    else:
        record["borrow"] = args.borrow.strip()
        supports.append(record)
    meta["supports"] = supports
    cli.write_json(meta_path, meta)

    anatomy = folder / "ANATOMY.md"
    if args.role == "hero" and (not anatomy.exists() or args.force):
        if anatomy.exists():
            shutil.copyfile(anatomy, folder / "ANATOMY.previous.md")
        cli.write_text(anatomy, anatomy_template(folder.name, args.game or "", filename, dims, palette))

    print(f"Registered {args.role} anchor for {folder.name}: {cli.rel_to_root(root, destination)}")
    if dims:
        print(f"Size: {dims[0]}x{dims[1]}")
    if palette:
        print("Dominant: " + ", ".join(f"{c['hex']} {c['share']}%" for c in palette["dominant"]))
        if palette["accents"]:
            print("Accents:  " + ", ".join(f"{c['hex']} {c['share']}%" for c in palette["accents"]))
    elif palette_note:
        print(palette_note)
    if not args.source_url:
        print("Note: no --source-url recorded. Add where this capture came from before sharing the work.")
    if args.role == "hero":
        print(f"Next: fill in {cli.rel_to_root(root, anatomy)} from the image, then build.")
    return 0


def command_anchor_show(args: argparse.Namespace) -> int:
    cli = _cli()
    root, base = anchor_root(args)
    folders = [screen_dir(base, args.screen)] if args.screen else sorted(p for p in base.iterdir() if (p / "anchor.json").exists()) if base.exists() else []
    if not folders:
        print("No anchors registered. Run: ui-ref anchor add <image> --screen <id> --game \"<game>\"")
        return 0
    for folder in folders:
        meta = load_anchor(folder)
        hero = meta.get("hero") or {}
        rounds = sorted(p.name for p in (folder / "rounds").iterdir() if (p / "round.json").exists()) if (folder / "rounds").exists() else []
        anatomy = folder / "ANATOMY.md"
        todo = anatomy.read_text(encoding="utf-8").count("TODO") if anatomy.exists() else None
        print(f"{folder.name}")
        print(f"  hero:    {hero.get('game') or '(no game title)'} — {cli.rel_to_root(root, folder / str(hero.get('file')))}"
              f" [{hero.get('width')}x{hero.get('height')}, {hero.get('capture')}]")
        for support in meta.get("supports") or []:
            print(f"  support: {support.get('game') or support.get('file')} — borrow: {support.get('borrow')}")
        if todo is None:
            print("  anatomy: missing")
        else:
            print(f"  anatomy: {'complete' if todo == 0 else f'{todo} TODO left'}")
        print(f"  rounds:  {len(rounds)}")
    return 0


# --------------------------------------------------------------------------------------
# shot / compare
# --------------------------------------------------------------------------------------

def take_screenshot(url: str, out: Path, viewport: tuple[int, int], wait_ms: int, selector: str | None, scale: float) -> None:
    def work(page: Any) -> None:
        page.goto(url, wait_until="load", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        try:
            page.evaluate("document.fonts && document.fonts.ready")
        except Exception:
            pass
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)
        out.parent.mkdir(parents=True, exist_ok=True)
        if selector:
            page.locator(selector).first.screenshot(path=str(out))
        else:
            page.screenshot(path=str(out), full_page=False)

    _with_page(viewport, work, scale)


_COMPARE_CSS = """
:root{color-scheme:dark;--bg:#111318;--panel:#1b1e26;--line:#2c313c;--text:#e8eaf0;--dim:#9aa1b0;--accent:#ffb454}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center}
h1{font-size:15px;margin:0 8px 0 0;font-weight:600}
.group{display:flex;gap:6px;align-items:center}
button,label.t{background:#252a35;color:var(--text);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:inherit;cursor:pointer;user-select:none}
button[aria-pressed=true],label.t:has(input:checked){border-color:var(--accent);color:var(--accent)}
label.t input{position:absolute;opacity:0;pointer-events:none}
main{padding:16px}
.stage{display:grid;gap:12px;grid-template-columns:1fr 1fr}
.stage.stack{grid-template-columns:1fr}
figure{margin:0;min-width:0}
figcaption{color:var(--dim);font-size:12px;margin-bottom:6px;display:flex;justify-content:space-between;gap:8px}
.frame{position:relative;background:#000;border:1px solid var(--line);overflow:hidden}
.frame img{display:block;width:100%;height:auto}
.is-overlay .stage{grid-template-columns:1fr}
.is-overlay figure.a{display:none}
.is-overlay figure.b .under{display:block}
.under{display:none;position:absolute;inset:0;width:100%;height:100%;object-fit:fill}
.is-overlay figure.b .top{position:relative;opacity:var(--mix,.5)}
body.is-squint .frame img{filter:blur(var(--blur,10px))}
body.is-values .frame img{filter:grayscale(1) contrast(1.1)}
body.is-squint.is-values .frame img{filter:grayscale(1) blur(var(--blur,10px))}
.guides{position:absolute;inset:0;pointer-events:none;display:none}
body.is-guides .guides{display:block}
.guides i{position:absolute;border:1px dashed rgba(255,180,84,.9)}
.guides .safe{inset:5%}.guides .action{inset:3.5%;border-color:rgba(120,200,255,.7)}
.guides .v1,.guides .v2{top:0;bottom:0;border-width:0 0 0 1px;border-color:rgba(255,255,255,.35)}
.guides .h1,.guides .h2{left:0;right:0;border-width:1px 0 0 0;border-color:rgba(255,255,255,.35)}
.guides .v1{left:33.333%}.guides .v2{left:66.666%}.guides .h1{top:33.333%}.guides .h2{top:66.666%}
.guides .c{left:35%;right:35%;top:35%;bottom:35%;border-color:rgba(255,90,90,.7)}
.meta{color:var(--dim);font-size:12px;margin-top:14px;max-width:110ch}
.meta code{color:var(--text)}
.pal{display:inline-flex;gap:2px;vertical-align:middle;margin-left:6px}.pal b{width:14px;height:14px;border:1px solid #0008;display:inline-block}
input[type=range]{accent-color:var(--accent)}
@media(max-width:900px){.stage{grid-template-columns:1fr}}
"""

_COMPARE_JS = """
const b=document.body,$=s=>document.querySelector(s);
function mode(m){b.classList.toggle('is-overlay',m==='overlay');document.querySelector('.stage').classList.toggle('stack',m==='stack');
document.querySelectorAll('[data-mode]').forEach(x=>x.setAttribute('aria-pressed',x.dataset.mode===m));}
document.querySelectorAll('[data-mode]').forEach(x=>x.addEventListener('click',()=>mode(x.dataset.mode)));
document.querySelectorAll('[data-toggle]').forEach(x=>x.addEventListener('change',()=>b.classList.toggle('is-'+x.dataset.toggle,x.checked)));
$('#mix').addEventListener('input',e=>b.style.setProperty('--mix',e.target.value/100));
$('#blur').addEventListener('input',e=>b.style.setProperty('--blur',e.target.value+'px'));
let flick=null;$('#flicker').addEventListener('click',e=>{if(flick){clearInterval(flick);flick=null;e.target.setAttribute('aria-pressed','false');b.style.setProperty('--mix',$('#mix').value/100);return;}
mode('overlay');let on=false;e.target.setAttribute('aria-pressed','true');flick=setInterval(()=>{on=!on;b.style.setProperty('--mix',on?1:0);},700);});
"""


def _swatches(palette: dict[str, Any] | None) -> str:
    if not palette:
        return ""
    cells = "".join(f'<b style="background:{escape(str(c.get("hex", "#000")))}" title="{escape(str(c.get("hex")))} {escape(str(c.get("share")))}%"></b>'
                    for c in (palette.get("dominant") or [])[:8])
    return f'<span class="pal">{cells}</span>'


def compare_html(title: str, anchor_src: str, candidate_src: str, anchor_label: str, candidate_label: str,
                 anchor_palette: dict[str, Any] | None, candidate_palette: dict[str, Any] | None, footer: str) -> str:
    guides = '<div class="guides"><i class="safe"></i><i class="action"></i><i class="v1"></i><i class="v2"></i><i class="h1"></i><i class="h2"></i><i class="c"></i></div>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data: file:; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>{_COMPARE_CSS}</style></head>
<body>
<header>
  <h1>{escape(title)}</h1>
  <div class="group"><button data-mode="side" aria-pressed="true">Side by side</button><button data-mode="stack" aria-pressed="false">Stacked</button><button data-mode="overlay" aria-pressed="false">Overlay</button><button id="flicker" aria-pressed="false">Flicker</button></div>
  <div class="group"><label>Mix <input id="mix" type="range" min="0" max="100" value="50"></label></div>
  <div class="group"><label class="t"><input type="checkbox" data-toggle="squint">Squint</label><label>Blur <input id="blur" type="range" min="2" max="30" value="10"></label></div>
  <div class="group"><label class="t"><input type="checkbox" data-toggle="values">Values</label><label class="t"><input type="checkbox" data-toggle="guides">Guides</label></div>
</header>
<main>
  <div class="stage">
    <figure class="a"><figcaption><span>Anchor — {escape(anchor_label)}{_swatches(anchor_palette)}</span></figcaption>
      <div class="frame"><img src="{escape(anchor_src, quote=True)}" alt="Anchor">{guides}</div></figure>
    <figure class="b"><figcaption><span>Candidate — {escape(candidate_label)}{_swatches(candidate_palette)}</span></figcaption>
      <div class="frame"><img class="under" src="{escape(anchor_src, quote=True)}" alt=""><img class="top" src="{escape(candidate_src, quote=True)}" alt="Candidate">{guides}</div></figure>
  </div>
  <p class="meta"><b>Squint</b> blurs both: compare the big shapes and where the eye lands. <b>Values</b> removes colour: the reading order must survive.
  <b>Guides</b> draws the 90% title-safe box (amber), 93% action-safe box (blue), thirds, and the centre 30% that a gameplay HUD keeps clear (red).
  <b>Overlay/Flicker</b> stretches the anchor under the candidate to compare proportions, not to trace it.</p>
  <p class="meta">{footer}</p>
</main>
<script>{_COMPARE_JS}</script>
</body></html>
"""


def _safe_palette(image: Path) -> dict[str, Any] | None:
    try:
        return extract_palette(image)
    except Exception:
        return None


def start_round(root: Path, folder: Path, candidate: Path, note: str = "") -> tuple[int, Path]:
    cli = _cli()
    meta = load_anchor(folder)
    hero = meta.get("hero") or {}
    hero_path = folder / str(hero.get("file"))
    if not hero_path.is_file():
        raise SystemExit(f"Hero image is missing: {hero_path}")
    number, round_dir = next_round(folder)
    round_dir.mkdir(parents=True, exist_ok=True)
    suffix = candidate.suffix.lower() or ".png"
    stored = round_dir / f"candidate{suffix}"
    if candidate.resolve() != stored.resolve():
        cli.write_bytes(stored, candidate.read_bytes())
    dims = cli.image_dimensions(stored)
    palette = _safe_palette(stored)
    hero_dims = (hero.get("width"), hero.get("height"))
    notes = []
    if dims and all(hero_dims) and abs(dims[0] / dims[1] - hero_dims[0] / hero_dims[1]) > 0.02:
        notes.append(f"Aspect ratios differ (anchor {hero_dims[0]}x{hero_dims[1]}, candidate {dims[0]}x{dims[1]}); overlay will distort.")
    footer = (f"Round {number:02d} · anchor sha256 <code>{escape(str(hero.get('sha256', ''))[:12])}</code> · "
              f"candidate sha256 <code>{cli.file_sha256(stored)[:12]}</code>. " + escape(" ".join(notes)))
    html = compare_html(
        f"{folder.name} — round {number:02d}", f"../../{hero.get('file')}", stored.name,
        f"{hero.get('game') or hero.get('file')} ({hero_dims[0]}x{hero_dims[1]})",
        f"round {number:02d}" + (f" ({dims[0]}x{dims[1]})" if dims else ""),
        hero.get("palette"), palette, footer,
    )
    cli.write_text(round_dir / "compare.html", html)
    critique = round_dir / "critique.md"
    if not critique.exists():
        cli.write_text(critique, critique_template(folder.name, number, str(hero.get("game") or "")))
    cli.write_json(round_dir / "round.json", {
        "round": number, "created_at": cli.now_iso(), "candidate": stored.name,
        "candidate_sha256": cli.file_sha256(stored), "width": dims[0] if dims else None,
        "height": dims[1] if dims else None, "palette": palette, "note": note,
    })
    print(f"Round {number:02d} for {folder.name}: {cli.rel_to_root(root, round_dir / 'compare.html')}")
    print(f"Critique: {cli.rel_to_root(root, critique)}")
    for line in notes:
        print(f"Note: {line}")
    if palette and hero.get("palette"):
        print("Anchor dominant:    " + ", ".join(c["hex"] for c in hero["palette"]["dominant"][:6]))
        print("Candidate dominant: " + ", ".join(c["hex"] for c in palette["dominant"][:6]))
    if number > ROUND_SOFT_CAP:
        print(f"Round {number} exceeds the usual cap of {ROUND_SOFT_CAP}. If it is still below the bar, the anchor or "
              "the plan is wrong: revisit ANATOMY.md rather than polishing.")
    return number, round_dir


def command_shot(args: argparse.Namespace) -> int:
    cli = _cli()
    root = cli.project_root_from_args(args)
    url = target_url(root, args.target)
    if not args.screen and not args.out:
        raise SystemExit("Give --screen <id> (starts a compare round) or --out <file.png>.")
    folder = None
    viewport = parse_viewport(args.viewport) if args.viewport else None
    if args.screen:
        _, base = anchor_root(args)
        folder = screen_dir(base, args.screen)
        hero = load_anchor(folder).get("hero") or {}
        if viewport is None and hero.get("width") and hero.get("height"):
            width, height = int(hero["width"]), int(hero["height"])
            if width > 2560:  # keep CSS pixels sane for 4K anchors
                width, height = width // 2, height // 2
            viewport = (width, height)
    viewport = viewport or (1920, 1080)
    out = cli.resolve_under_root(root, args.out) if args.out else None
    if folder is not None and out is None:
        _, round_dir = next_round(folder)
        out = round_dir / "candidate.png"
    assert out is not None
    try:
        take_screenshot(url, out, viewport, args.wait, args.selector, args.scale)
    except BrowserUnavailable as exc:
        raise SystemExit(str(exc))
    print(f"Screenshot {viewport[0]}x{viewport[1]}: {cli.rel_to_root(root, out)}")
    if folder is not None:
        start_round(root, folder, out, note=f"shot {args.target}")
    return 0


def command_compare(args: argparse.Namespace) -> int:
    cli = _cli()
    root = cli.project_root_from_args(args)
    candidate = Path(args.candidate)
    candidate = candidate if candidate.is_absolute() else (root / candidate)
    if not candidate.is_file():
        raise SystemExit(f"Candidate image not found: {args.candidate}")
    if args.screen:
        _, base = anchor_root(args)
        start_round(root, screen_dir(base, args.screen), candidate)
        return 0
    if not args.against or not args.out:
        raise SystemExit("Give --screen <id>, or both --against <anchor image> and --out <file.html>.")
    against = Path(args.against)
    against = against if against.is_absolute() else (root / against)
    if not against.is_file():
        raise SystemExit(f"Anchor image not found: {args.against}")
    out = cli.resolve_under_root(root, args.out)
    rel = lambda p: os.path.relpath(str(p.resolve()), str(out.parent.resolve())).replace("\\", "/")
    cli.write_text(out, compare_html(f"{against.stem} vs {candidate.stem}", rel(against), rel(candidate),
                                     against.name, candidate.name, _safe_palette(against), _safe_palette(candidate), ""))
    print(f"Comparison sheet: {cli.rel_to_root(root, out)}")
    return 0


# --------------------------------------------------------------------------------------
# audit — deterministic floor checks on an HTML build
# --------------------------------------------------------------------------------------

_CHECK_JS = r"""
(cfg) => {
  const W = window.innerWidth, H = window.innerHeight;
  const safeX = W * cfg.safe, safeY = H * cfg.safe;
  const parse = (s) => { const m = (s || '').match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  const describe = (el) => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id;
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2); if (cls.length) s += '.' + cls.join('.'); return s; };
  const visible = (el) => { const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return false;
    if (r.bottom <= 0 || r.right <= 0 || r.top >= H || r.left >= W) return false;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) { const cs = getComputedStyle(n);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.05) return false; } return true; };
  const background = (el) => { const layers = []; let image = false;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) { const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') image = true;
      if (n.tagName === 'IMG' || n.tagName === 'CANVAS' || n.tagName === 'VIDEO') image = true;
      const c = parse(cs.backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 0.999) break; } }
    if (image) return null;
    let base = { r: 255, g: 255, b: 255, a: 1 }; for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base); return base; };
  const out = { texts: 0, small: [], near: [], contrast: [], contrastUnknown: 0, unsafe: [], clipped: [], targets: [],
                interactive: 0, focused: null, pageOverflow: document.documentElement.scrollWidth > W + 1,
                viewport: [W, H], sizes: {} };
  const interactiveSel = 'a[href],button,input,select,textarea,[role=button],[role=tab],[role=menuitem],[role=link],[tabindex]:not([tabindex="-1"])';
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue.replace(/\s+/g, ' ').trim(); if (!text) continue;
    const el = node.parentElement; if (!el || seen.has(el)) continue;
    if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE'].includes(el.tagName)) continue;
    if (!visible(el)) continue; seen.add(el);
    const cs = getComputedStyle(el); const size = parseFloat(cs.fontSize); const rect = el.getBoundingClientRect();
    out.texts += 1; const key = Math.round(size); out.sizes[key] = (out.sizes[key] || 0) + 1;
    const item = { el: describe(el), text: text.slice(0, 48), size: +size.toFixed(1) };
    if (size < cfg.minText - 0.01) out.small.push(item); else if (size < cfg.warnText - 0.01) out.near.push(item);
    const fg = parse(cs.color); const bg = background(el);
    if (!fg || !bg) out.contrastUnknown += 1; else {
      const f = over(fg, bg); const l1 = lum(f), l2 = lum(bg); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const weight = parseInt(cs.fontWeight, 10) || 400; const large = size >= cfg.largeText || (size >= cfg.largeText * 0.78 && weight >= 700);
      const need = large ? 3 : 4.5; if (ratio < need - 0.01) out.contrast.push({ ...item, ratio: +ratio.toFixed(2), need }); }
    if (cfg.safe > 0 && (rect.left < safeX - 0.5 || rect.top < safeY - 0.5 || rect.right > W - safeX + 0.5 || rect.bottom > H - safeY + 0.5))
      out.unsafe.push({ ...item, box: [Math.round(rect.left), Math.round(rect.top), Math.round(rect.right), Math.round(rect.bottom)] });
    const clipX = el.scrollWidth > el.clientWidth + 1 && ['hidden', 'clip'].includes(cs.overflowX);
    const clipY = el.scrollHeight > el.clientHeight + 1 && ['hidden', 'clip'].includes(cs.overflowY);
    if (clipX || clipY) out.clipped.push(item);
  }
  for (const el of document.querySelectorAll(interactiveSel)) {
    if (!visible(el)) continue; out.interactive += 1; const r = el.getBoundingClientRect();
    if (cfg.minTarget > 0 && Math.min(r.width, r.height) < cfg.minTarget - 0.5)
      out.targets.push({ el: describe(el), text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 32), size: [Math.round(r.width), Math.round(r.height)] });
    if (cfg.safe > 0 && !seen.has(el) && (r.left < safeX - 0.5 || r.top < safeY - 0.5 || r.right > W - safeX + 0.5 || r.bottom > H - safeY + 0.5))
      out.unsafe.push({ el: describe(el), text: '(control)', size: 0, box: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)] });
  }
  const active = document.activeElement; out.focused = active && active !== document.body && active !== document.documentElement ? describe(active) : null;
  return out;
}
"""


def run_check(url: str, platform: str, viewport: tuple[int, int], wait_ms: int, overrides: dict[str, Any]) -> dict[str, Any]:
    preset = PLATFORMS[platform]
    factor = viewport[1] / 1080 if preset["scale_text"] else 1.0
    cfg = {
        "minText": overrides.get("min_text") or round(preset["min_text"] * factor, 2),
        "warnText": round(preset["warn_text"] * factor, 2),
        "largeText": round(24 * factor, 2) if preset["scale_text"] else 24,
        "safe": preset["safe"] if overrides.get("safe") is None else overrides["safe"],
        "minTarget": preset["min_target"] if overrides.get("min_target") is None else overrides["min_target"],
    }
    cfg["warnText"] = max(cfg["warnText"], cfg["minText"])

    def work(page: Any) -> Any:
        page.goto(url, wait_until="load", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)
        return page.evaluate(_CHECK_JS, cfg)

    raw = _with_page(viewport, work)
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def add(bucket: list[dict[str, Any]], rule: str, message: str, items: list[Any]) -> None:
        if items:
            bucket.append({"rule": rule, "message": message, "count": len(items), "items": items[:12]})

    add(failures, "text-size", f"Text below the {cfg['minText']}px floor for {preset['label']}", raw["small"])
    add(warnings, "text-size-near", f"Text below the recommended {cfg['warnText']}px", raw["near"])
    add(failures, "contrast", "Text contrast below 4.5:1 (3:1 for large text)", raw["contrast"])
    add(failures, "safe-area", f"Text or controls outside the {round((1 - 2 * cfg['safe']) * 100)}% safe area", raw["unsafe"])
    add(failures, "clipped-text", "Text is clipped by its container", raw["clipped"])
    add(failures, "target-size", f"Touch targets under {cfg['minTarget']}px", raw["targets"])
    if raw["pageOverflow"]:
        failures.append({"rule": "page-overflow", "message": "Page is wider than the viewport", "count": 1, "items": []})
    if preset["needs_focus"] and raw["interactive"] and not raw["focused"]:
        failures.append({"rule": "initial-focus", "count": 1, "items": [],
                         "message": "Nothing is focused when the screen opens; a gamepad player has no starting point"})
    if len(raw["sizes"]) > 6:
        warnings.append({"rule": "type-scale", "count": len(raw["sizes"]), "items": [],
                         "message": f"{len(raw['sizes'])} distinct text sizes; shipped game screens rarely use more than 4-6"})
    not_assessed = []
    if raw["contrastUnknown"]:
        not_assessed.append(f"contrast of {raw['contrastUnknown']} text element(s) over images or gradients — check by eye in the screenshot")
    not_assessed.append("motion, focus order, state coverage, localisation expansion, and anything drawn inside a canvas")
    return {
        "target": url, "platform": platform, "platform_label": preset["label"], "viewport": list(viewport),
        "thresholds": cfg, "text_elements": raw["texts"], "interactive_elements": raw["interactive"],
        "text_sizes": raw["sizes"], "initial_focus": raw["focused"],
        "failures": failures, "warnings": warnings, "not_assessed": not_assessed,
    }


def command_audit(args: argparse.Namespace) -> int:
    cli = _cli()
    root = cli.project_root_from_args(args)
    url = target_url(root, args.target)
    preset = PLATFORMS[args.platform]
    viewport = parse_viewport(args.viewport) if args.viewport else preset["viewport"]
    if args.safe_area is not None and not 0 <= args.safe_area < 0.5:
        raise SystemExit("--safe-area is a fraction of each edge, for example 0.05")
    overrides = {"min_text": args.min_text, "safe": args.safe_area, "min_target": args.min_target}
    try:
        report = run_check(url, args.platform, viewport, args.wait, overrides)
    except BrowserUnavailable as exc:
        raise SystemExit(str(exc))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Floor check — {report['platform_label']} at {viewport[0]}x{viewport[1]}")
        sizes = ", ".join(f"{k}px×{v}" for k, v in sorted(report["text_sizes"].items(), key=lambda kv: -int(kv[0])))
        print(f"{report['text_elements']} text elements, {report['interactive_elements']} controls. Sizes: {sizes or 'none'}")
        for label, bucket in (("FAIL", report["failures"]), ("WARN", report["warnings"])):
            for finding in bucket:
                print(f"{label} {finding['rule']}: {finding['message']} ({finding['count']})")
                for item in finding["items"][:6]:
                    detail = ", ".join(f"{k}={v}" for k, v in item.items() if k not in {"el", "text"})
                    print(f"     {item.get('el')} \"{item.get('text')}\" {detail}")
        if not report["failures"] and not report["warnings"]:
            print("PASS: no floor violations found.")
        print("NOT ASSESSED: " + "; ".join(report["not_assessed"]))
        print("A pass means the floor holds. It says nothing about whether the screen is good; use `ui-ref compare` for that.")
    return 1 if report["failures"] else 0


# --------------------------------------------------------------------------------------
# Parser registration
# --------------------------------------------------------------------------------------

def register_anchor_commands(sub: Any) -> None:
    anchor = sub.add_parser("anchor", help="Register and inspect the one shipped-game screen each of your screens is anchored on.")
    anchor_sub = anchor.add_subparsers(dest="anchor_command", required=True)

    add = anchor_sub.add_parser("add", help="Register a hero anchor (or a narrow support) for a screen.")
    add.add_argument("image", help="Local screenshot of a shipped game's screen.")
    add.add_argument("--screen", required=True, help="Your screen id, for example hud, main-menu, inventory.")
    add.add_argument("--game", default=None, help="Title of the game the capture comes from.")
    add.add_argument("--source-url", default=None, help="Where the capture came from (store page, press kit, video).")
    add.add_argument("--capture", default="own-capture", choices=CAPTURE_KINDS, help="How the image was obtained. Default: own-capture.")
    add.add_argument("--role", default="hero", choices=["hero", "support"], help="hero: the one anchor. support: fills one named gap (max 2).")
    add.add_argument("--borrow", default=None, help="Required for --role support: the one specific thing taken from this image.")
    add.add_argument("--note", default=None, help="Free-form note.")
    add.add_argument("--no-palette", action="store_true", help="Skip browser-based palette extraction.")
    add.add_argument("--force", action="store_true", help="Replace the existing hero and reset ANATOMY.md (the old one is kept as ANATOMY.previous.md).")
    add.set_defaults(func=command_anchor_add)

    show = anchor_sub.add_parser("show", help="List registered anchors, anatomy completeness, and rounds.")
    show.add_argument("--screen", default=None, help="Limit to one screen id.")
    show.set_defaults(func=command_anchor_show)

    shot = sub.add_parser("shot", help="Screenshot an HTML build or URL at shipping size (needs the browser extra).")
    shot.add_argument("target", help="HTML file or http(s) URL of your build.")
    shot.add_argument("--screen", default=None, help="Screen id: saves into the next round and writes the comparison sheet.")
    shot.add_argument("--out", default=None, help="Output PNG path (inside the project).")
    shot.add_argument("--viewport", default=None, help="WIDTHxHEIGHT. Default: the anchor's size, else 1920x1080.")
    shot.add_argument("--selector", default=None, help="Capture only this CSS selector.")
    shot.add_argument("--wait", type=int, default=400, help="Milliseconds to wait after load. Default 400.")
    shot.add_argument("--scale", type=float, default=1.0, help="Device scale factor. Default 1.")
    shot.set_defaults(func=command_shot)

    compare = sub.add_parser("compare", help="Build a side-by-side sheet of anchor vs candidate with squint, value, guide, and overlay tools.")
    compare.add_argument("candidate", help="Screenshot of your build (any source: browser, engine, device).")
    compare.add_argument("--screen", default=None, help="Screen id: starts the next round against its hero anchor.")
    compare.add_argument("--against", default=None, help="Ad-hoc mode: anchor image to compare with.")
    compare.add_argument("--out", default=None, help="Ad-hoc mode: output HTML path (inside the project).")
    compare.set_defaults(func=command_compare)

    check = sub.add_parser("audit", help="Deterministic floor checks on an HTML build: text size, contrast, safe area, clipping, focus.")
    check.add_argument("target", help="HTML file or http(s) URL of your build.")
    check.add_argument("--platform", default="desktop", choices=sorted(PLATFORMS), help="Platform floor preset. Default: desktop.")
    check.add_argument("--viewport", default=None, help="WIDTHxHEIGHT. Default: the platform preset.")
    check.add_argument("--min-text", type=float, default=None, help="Override the minimum text size in CSS px.")
    check.add_argument("--safe-area", type=float, default=None, help="Override the safe inset per edge as a fraction (0.05 = 90%% safe area).")
    check.add_argument("--min-target", type=float, default=None, help="Override the minimum touch target in CSS px (0 disables).")
    check.add_argument("--wait", type=int, default=400, help="Milliseconds to wait after load. Default 400.")
    check.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    check.set_defaults(func=command_audit)
