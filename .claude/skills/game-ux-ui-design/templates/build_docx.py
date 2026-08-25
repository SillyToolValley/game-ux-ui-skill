#!/usr/bin/env python3
"""Render a UX/UI 디자인 문서 (markdown) to an EDITABLE landscape Word doc (.docx).

For when meeting participants need to edit the design document themselves (Word / Google Docs),
not just read a PDF. Markdown stays the source; this is the editable share format.

    pip install python-docx
    python build_docx.py design.md                 # -> design.docx next to it
    python build_docx.py design.md --append references/hud.md ... --out out/design.docx

Wireframe SVGs use a sibling PNG when available, otherwise this script rasterizes them with
optional CairoSVG or a local headless Chrome/Edge. Reference .jpg/.png files embed directly.
A line-based markdown reader handles the design's headings / tables / images / lists /
blockquotes / fenced code; landscape 16:9 page; Korean-capable font.
"""
import argparse, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlparse
from xml.etree import ElementTree
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.opc.constants import RELATIONSHIP_TYPE as RT

ACCENT = RGBColor(0x1E, 0x3A, 0x8A)
HEAD_BG = "1E3A8A"
ZEBRA = "F4F7FC"

LATIN = "JetBrains Mono"      # Latin / numbers / code
EAST_ASIA = "Malgun Gothic"

BROWSER_CANDIDATES = [
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "google-chrome", "chromium", "chrome", "msedge",
]


def configure_console():
    """Keep diagnostic output printable on Windows CP949 and similar consoles."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, OSError, TypeError, ValueError):
            pass


def find_browser():
    for candidate in BROWSER_CANDIDATES:
        if os.path.sep in candidate or "/" in candidate:
            if os.path.exists(candidate):
                return candidate
        else:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return None


def _svg_viewport(svg_path):
    """Return a practical browser viewport while tolerating CSS units and viewBox-only SVGs."""
    width = height = None
    try:
        root = ElementTree.parse(svg_path).getroot()
        for name in ("width", "height"):
            raw = root.attrib.get(name, "")
            match = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", raw)
            if match:
                if name == "width":
                    width = float(match.group(1))
                else:
                    height = float(match.group(1))
        view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
        if len(view_box) == 4:
            width = width or float(view_box[2])
            height = height or float(view_box[3])
    except (ElementTree.ParseError, OSError, TypeError, ValueError):
        pass
    width = width or 1600
    height = height or 900
    scale = min(1.0, 2400.0 / max(width, height))
    return max(320, int(round(width * scale))), max(180, int(round(height * scale)))


def _new_temp_png():
    handle, path = tempfile.mkstemp(prefix="ui-ref-svg-", suffix=".png")
    os.close(handle)
    os.remove(path)
    return path


def rasterize_svg(svg_path):
    """Return ``(temporary_png, diagnostics)`` using optional CairoSVG or a local browser."""
    diagnostics = []
    try:
        import cairosvg

        png_path = _new_temp_png()
        try:
            cairosvg.svg2png(url=svg_path, write_to=png_path)
            if os.path.exists(png_path) and os.path.getsize(png_path) > 0:
                return png_path, "CairoSVG"
            diagnostics.append("CairoSVG produced no image")
        except Exception as exc:
            diagnostics.append(f"CairoSVG failed: {exc}")
        if os.path.exists(png_path):
            os.remove(png_path)
    except ImportError:
        diagnostics.append("CairoSVG is not installed")

    browser = find_browser()
    if browser:
        png_path = _new_temp_png()
        width, height = _svg_viewport(svg_path)
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={width},{height}",
            f"--screenshot={png_path}",
            Path(svg_path).resolve().as_uri(),
        ]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            result = subprocess.CompletedProcess(cmd, 1, "", str(exc))
        if result.returncode == 0 and os.path.exists(png_path) and os.path.getsize(png_path) > 0:
            return png_path, "browser"
        diagnostic_text = (result.stderr or result.stdout or "no screenshot was created").strip()
        detail = diagnostic_text.splitlines()[-1] if diagnostic_text else "no screenshot was created"
        diagnostics.append(f"browser conversion failed: {detail}")
        if os.path.exists(png_path):
            os.remove(png_path)
    else:
        diagnostics.append("Chrome/Edge was not found")
    return None, "; ".join(diagnostics)

def detect_lang(text):
    if re.search(r'[가-힣]', text): return 'ko'
    if re.search(r'[ぁ-んァ-ヶ]', text): return 'ja'
    if re.search(r'[\u3400-\u9fff]', text): return 'zh'
    return 'en'

def east_asia_font(lang):
    return {"ko": "Malgun Gothic", "ja": "Yu Gothic", "zh": "Microsoft YaHei"}.get(lang, "Arial")

def _set_rfonts(rpr, latin, korean):
    rf = rpr.find(qn('w:rFonts'))
    if rf is None:
        rf = OxmlElement('w:rFonts'); rpr.append(rf)
    rf.set(qn('w:ascii'), latin); rf.set(qn('w:hAnsi'), latin)
    rf.set(qn('w:cs'), latin); rf.set(qn('w:eastAsia'), korean)

def set_doc_fonts(doc, size=12):
    st = doc.styles["Normal"]; st.font.size = Pt(size)
    _set_rfonts(st.element.get_or_add_rPr(), LATIN, EAST_ASIA)

def run_fonts(r, latin=LATIN, korean=None):
    korean = korean or EAST_ASIA
    _set_rfonts(r._element.get_or_add_rPr(), latin, korean)

def shade(cell_or_row_tc, hexcolor):
    tcPr = cell_or_row_tc._tc.get_or_add_tcPr()
    sh = OxmlElement('w:shd'); sh.set(qn('w:val'), 'clear'); sh.set(qn('w:fill'), hexcolor)
    tcPr.append(sh)

def add_hyperlink(p, label, url, base_size=None):
    scheme = urlparse(url).scheme.lower()
    if scheme and scheme not in {"http", "https", "mailto"}:
        r = p.add_run(label); run_fonts(r)
        return r
    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), p.part.relate_to(url, RT.HYPERLINK, is_external=True))
    run = OxmlElement('w:r'); rpr = OxmlElement('w:rPr')
    color = OxmlElement('w:color'); color.set(qn('w:val'), '0563C1'); rpr.append(color)
    underline = OxmlElement('w:u'); underline.set(qn('w:val'), 'single'); rpr.append(underline)
    _set_rfonts(rpr, LATIN, EAST_ASIA)
    if base_size:
        size = OxmlElement('w:sz'); size.set(qn('w:val'), str(int(base_size * 2))); rpr.append(size)
    run.append(rpr)
    node = OxmlElement('w:t'); node.text = label; run.append(node); hyperlink.append(run)
    p._p.append(hyperlink)
    return hyperlink

def add_runs(p, text, base_size=None):
    # inline **bold**, `code`, and live [text](url) hyperlinks
    text = text.replace('~~', '')
    for seg in re.split(r'(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))', text):
        if not seg: continue
        if seg.startswith('**') and seg.endswith('**'):
            r = p.add_run(seg[2:-2]); r.bold = True
        elif seg.startswith('`') and seg.endswith('`'):
            r = p.add_run(seg[1:-1]); r.font.name = 'JetBrains Mono'; r.font.size = Pt((base_size or 12) - 1)
        elif seg.startswith('['):
            match = re.fullmatch(r'\[([^\]]+)\]\(([^)]+)\)', seg)
            if match: add_hyperlink(p, match.group(1), match.group(2), base_size); continue
            r = p.add_run(seg)
        else:
            r = p.add_run(seg)
        run_fonts(r)
        if base_size:
            r.font.size = Pt(base_size)

def emit_table(doc, rows):
    rows = [r for r in rows if not re.match(r'^\s*\|?[\s:|-]+\|?\s*$', r)]  # drop --- separator
    grid = [[c.strip() for c in re.split(r'(?<!\\)\|', r.strip().strip('|'))] for r in rows]
    ncol = max(len(r) for r in grid)
    grid = [r + [''] * (ncol - len(r)) for r in grid]
    t = doc.add_table(rows=len(grid), cols=ncol); t.style = 'Table Grid'; t.autofit = True
    for ri, row in enumerate(grid):
        for ci, val in enumerate(row):
            cell = t.cell(ri, ci); cell.paragraphs[0].clear()
            add_runs(cell.paragraphs[0], val.replace('\\|', '|'), base_size=10)
            if ri == 0:
                shade(cell, HEAD_BG)
                for r in cell.paragraphs[0].runs:
                    r.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            elif ri % 2 == 0:
                shade(cell, ZEBRA)
    doc.add_paragraph()

def emit_image(doc, src_abs, alt=""):
    original_svg = src_abs.lower().endswith('.svg')
    temporary_png = None
    if original_svg:
        png = src_abs[:-4] + '.png'
        if os.path.exists(png):
            src_abs = png
        elif os.path.exists(src_abs):
            temporary_png, diagnostics = rasterize_svg(src_abs)
            if temporary_png:
                src_abs = temporary_png
            else:
                paragraph = doc.add_paragraph(
                    f"[SVG not embedded: {os.path.basename(src_abs)} - {diagnostics}. "
                    "Install CairoSVG or provide a sibling PNG.]"
                )
                paragraph.italic = True
                return
    if not os.path.exists(src_abs):
        doc.add_paragraph(f"[이미지 없음: {os.path.basename(src_abs)}]"); return
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    normalized = src_abs.replace('\\', '/').lower()
    wire = original_svg or '/wireframes/' in normalized or 'wireframe' in alt.lower()
    try:
        p.add_run().add_picture(src_abs, width=Inches(14.5 if wire else 7.2))
    except Exception as e:
        doc.add_paragraph(f"[Image insertion failed: {os.path.basename(src_abs)} - {e}]")
    finally:
        if temporary_png and os.path.exists(temporary_png):
            os.remove(temporary_png)

def md_to_docx(doc, md_text, src_dir):
    lines = md_text.splitlines()
    i = 0; in_code = False; code_buf = []
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith('```'):
            if in_code:
                p = doc.add_paragraph(); shade_para(p, "EEF1F6")
                r = p.add_run('\n'.join(code_buf)); r.font.name = 'Consolas'; r.font.size = Pt(8.5)
                code_buf = []; in_code = False
            else:
                in_code = True
            i += 1; continue
        if in_code:
            code_buf.append(ln); i += 1; continue
        m = re.match(r'^(#{1,4})\s+(.*)$', ln)
        if m:
            lvl = len(m.group(1)); txt = m.group(2)
            h = doc.add_heading(level=min(lvl, 4)); h.clear()
            add_runs(h, txt)
            hsize = {1: 22, 2: 17, 3: 14.5, 4: 12.5}.get(lvl, 12)
            for r in h.runs:
                r.font.color.rgb = ACCENT; r.font.size = Pt(hsize); run_fonts(r)
            i += 1; continue
        if ln.strip().startswith('|') and i + 1 < len(lines) and re.match(r'^\s*\|?[\s:|-]+\|?\s*$', lines[i+1]):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                tbl.append(lines[i]); i += 1
            emit_table(doc, tbl); continue
        im = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$', ln.strip())
        if im:
            image_path = unquote(im.group(2)).strip("<>")
            emit_image(doc, os.path.normpath(os.path.join(src_dir, image_path)), im.group(1)); i += 1; continue
        if ln.strip().startswith('>'):
            p = doc.add_paragraph(); p.paragraph_format.left_indent = Inches(0.2); shade_para(p, "F7F9FD")
            add_runs(p, ln.strip().lstrip('>').strip(), base_size=9)
            for r in p.runs: r.italic = True
            i += 1; continue
        lm = re.match(r'^(\s*)[-*]\s+(.*)$', ln)
        if lm:
            p = doc.add_paragraph(style='List Bullet'); add_runs(p, lm.group(2)); i += 1; continue
        if re.match(r'^-{3,}\s*$', ln.strip()):
            i += 1; continue
        if ln.strip():
            p = doc.add_paragraph(); add_runs(p, ln.strip())
        i += 1

def shade_para(p, hexc):
    pPr = p._p.get_or_add_pPr(); sh = OxmlElement('w:shd')
    sh.set(qn('w:val'), 'clear'); sh.set(qn('w:fill'), hexc); pPr.append(sh)

def build(md_path, out_docx, appends=None, lang="auto"):
    global EAST_ASIA
    configure_console()
    md_path = os.path.abspath(md_path); src_dir = os.path.dirname(md_path)
    with open(md_path, encoding='utf-8') as source:
        md_text = source.read()
    if lang == "auto": lang = detect_lang(md_text)
    EAST_ASIA = east_asia_font(lang)
    doc = Document()
    s = doc.sections[0]; s.orientation = WD_ORIENT.LANDSCAPE
    s.page_width, s.page_height = Inches(16), Inches(9)
    s.left_margin = s.right_margin = Inches(0.5); s.top_margin = s.bottom_margin = Inches(0.5)
    set_doc_fonts(doc, size=12)
    md_to_docx(doc, md_text, src_dir)
    for ap in (appends or []):
        ap = os.path.abspath(ap)
        if not os.path.exists(ap): continue
        doc.add_page_break()
        with open(ap, encoding='utf-8') as append_source:
            md_to_docx(doc, append_source.read(), os.path.dirname(ap))
    output_dir = os.path.dirname(os.path.abspath(out_docx)) or "."
    os.makedirs(output_dir, exist_ok=True)
    handle, temporary_docx = tempfile.mkstemp(prefix=f".{Path(out_docx).stem}.", suffix=".docx", dir=output_dir)
    os.close(handle)
    os.remove(temporary_docx)
    try:
        doc.save(temporary_docx)
        if not os.path.exists(temporary_docx) or os.path.getsize(temporary_docx) == 0:
            raise RuntimeError("DOCX writer produced no output")
        os.replace(temporary_docx, out_docx)
    finally:
        if os.path.exists(temporary_docx):
            os.remove(temporary_docx)
    print("DOCX:", out_docx, f"({os.path.getsize(out_docx)//1024} KB)")

if __name__ == "__main__":
    configure_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("md"); ap.add_argument("--out", default=None)
    ap.add_argument("--lang", default="auto", help="Document language (auto, ko, en, ja, zh...).")
    ap.add_argument("--append", action="append", default=[])
    a = ap.parse_args()
    out = a.out or os.path.splitext(os.path.abspath(a.md))[0] + ".docx"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    build(a.md, out, appends=a.append, lang=a.lang)
