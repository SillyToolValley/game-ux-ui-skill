#!/usr/bin/env python3
"""Render a UX/UI 디자인 문서 (markdown) to a wide landscape PDF (+ HTML).

Markdown stays the editable source; this produces the shareable deliverable in the
format design teams expect (16:9 landscape, wide tables that don't wrap to mush).

    pip install markdown
    python build_pdf.py design.md                 # -> design.html + design.pdf next to it
    python build_pdf.py design.md --css design-pdf.css --out out/design.pdf

Needs a headless Chrome or Edge (ships with Windows). Relative image/SVG paths
(wireframes/*.svg, references/ui/*.jpg) are rebased when HTML is written elsewhere.
"""
import argparse, html, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

CHROME_CANDIDATES = [
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

def find_chrome():
    for c in CHROME_CANDIDATES:
        if os.path.sep in c or "/" in c:
            if os.path.exists(c): return c
        elif shutil.which(c): return shutil.which(c)
    return None

def md_to_html(md_text):
    # task-list checkboxes -> symbols (python-markdown has no built-in tasklist)
    md_text = re.sub(r'^(\s*[-*]\s+)\[ \]\s', r'\1☐ ', md_text, flags=re.M)
    md_text = re.sub(r'^(\s*[-*]\s+)\[[xX]\]\s', r'\1☑ ', md_text, flags=re.M)
    import markdown
    html = markdown.markdown(md_text, extensions=['tables', 'fenced_code', 'attr_list', 'sane_lists'])
    # per-screen section (### 5.x) starts a new page
    html = re.sub(r'<h3>(\s*5\.\d)', r'<h3 class="screen-break">\1', html)
    # Canonical ui-ref specs use `## Screen name (`screen-id`)` instead of
    # numbered 5.x headings. Give those screens the same clean page boundary.
    html = re.sub(r'<h2>([^<]*\(<code>[^<]+</code>\))</h2>',
                  r'<h2 class="screen-break">\1</h2>', html)
    # Keep the dense canonical token table together on its own page instead of
    # orphaning a header and one row at the bottom of the overview page.
    html = re.sub(r'<h2>(Design tokens)</h2>', r'<h2 class="major-break">\1</h2>', html)
    html = re.sub(
        r'(<h2 class="major-break">Design tokens</h2>\s*)<table>',
        r'\1<table class="dense-table">',
        html,
    )
    # tag the big legend/state tables (optional hook for finer CSS)
    return html

def _rewrite_paths(html, reldir):
    # prefix relative img src so an appended page's images resolve from the main doc's dir
    if not reldir or reldir == ".":
        return html
    return re.sub(r'(<img\b[^>]*\bsrc=")(?![A-Za-z][A-Za-z0-9+.-]*:|/|\\\\|#)([^"]+)"',
                  lambda m: f'{m.group(1)}{reldir}/{m.group(2)}"', html)

def detect_lang(text):
    if re.search(r'[가-힣]', text): return 'ko'
    if re.search(r'[ぁ-んァ-ヶ]', text): return 'ja'
    if re.search(r'[\u3400-\u9fff]', text): return 'zh'
    return 'en'

GENERATED_MARKER = "<!-- generated-by: game-ux-ui-design/build_pdf.py -->"


def build(md_path, css_path, out_pdf, appends=None, lang="auto", html_out=None):
    configure_console()
    md_path = os.path.abspath(md_path)
    out_pdf = os.path.abspath(out_pdf)
    src_dir = os.path.dirname(md_path)
    title = os.path.splitext(os.path.basename(md_path))[0]
    with open(md_path, encoding='utf-8') as source:
        md_text = source.read()
    if lang == "auto": lang = detect_lang(md_text)
    if not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*', lang):
        raise ValueError(f"Invalid document language: {lang!r}")
    if css_path and os.path.exists(css_path):
        with open(css_path, encoding='utf-8') as css_source:
            css = css_source.read()
    else:
        css = ""
    body = md_to_html(md_text)
    # append reference pages (etc.) as a self-contained appendix in the shared PDF
    for ap in (appends or []):
        ap = os.path.abspath(ap)
        if not os.path.exists(ap):
            print("  (skip append, not found):", ap); continue
        reldir = os.path.relpath(os.path.dirname(ap), src_dir).replace(os.sep, '/')
        with open(ap, encoding='utf-8') as append_source:
            ap_html = _rewrite_paths(md_to_html(append_source.read()), reldir)
        body += '<div style="break-before:page"></div>\n' + ap_html
    html_path = os.path.abspath(html_out) if html_out else os.path.join(src_dir, title + ".html")
    if not html_out and os.path.exists(html_path):
        with open(html_path, encoding="utf-8", errors="replace") as existing_html:
            if GENERATED_MARKER not in existing_html.read(512):
                # `ui-ref spec build` already owns design-spec.html. Preserve it
                # and keep the print-oriented intermediate beside it.
                html_path = os.path.join(src_dir, title + ".print.html")
    # The caller may place the print HTML/PDF outside the Markdown directory.
    # Rebase every relative image exactly once from that final HTML location.
    html_dir = os.path.dirname(html_path) or "."
    source_from_html = os.path.relpath(src_dir, html_dir).replace(os.sep, '/')
    body = _rewrite_paths(body, source_from_html)
    os.makedirs(os.path.dirname(html_path) or ".", exist_ok=True)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(f'{GENERATED_MARKER}\n<!doctype html><html lang="{html.escape(lang)}"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{html.escape(title)}</title><style>{css}</style></head><body>{body}</body></html>')
    print("HTML:", html_path)

    chrome = find_chrome()
    if not chrome:
        print("No Chrome/Edge found - HTML written; open it and Print-to-PDF (landscape) manually.")
        return html_path, None
    output_dir = os.path.dirname(out_pdf) or "."
    os.makedirs(output_dir, exist_ok=True)
    temp_handle, temp_pdf = tempfile.mkstemp(prefix=f".{Path(out_pdf).stem}.", suffix=".pdf", dir=output_dir)
    os.close(temp_handle)
    os.remove(temp_pdf)
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={temp_pdf}", Path(html_path).resolve().as_uri()]
    try:
        # Chromium writes UTF-8 diagnostics even when the Windows console code
        # page is CP949. Decode explicitly for CJK document paths.
        result = subprocess.run(cmd, check=False, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except OSError as exc:
        result = subprocess.CompletedProcess(cmd, 1, "", str(exc))
    if result.returncode == 0 and os.path.exists(temp_pdf) and os.path.getsize(temp_pdf) > 0:
        os.replace(temp_pdf, out_pdf)
        print("PDF :", out_pdf, f"({os.path.getsize(out_pdf)//1024} KB)")
        generated_pdf = out_pdf
    else:
        diagnostic_text = (result.stderr or result.stdout or "unknown browser error").strip()
        detail = diagnostic_text.splitlines()[-1] if diagnostic_text else "unknown browser error"
        print("PDF generation failed; previous PDF was preserved; HTML is available at", html_path, "-", detail)
        generated_pdf = None
    if os.path.exists(temp_pdf):
        os.remove(temp_pdf)
    return html_path, generated_pdf

if __name__ == "__main__":
    configure_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--css", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "design-pdf.css"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--html-out", default=None,
                    help="Print-oriented HTML path. By default, an existing HTML owned by another tool is preserved.")
    ap.add_argument("--lang", default="auto", help="HTML language tag (auto, ko, en, ja, zh...).")
    ap.add_argument("--append", action="append", default=[],
                    help="Extra markdown to append as an appendix (e.g. reference pages); repeatable.")
    a = ap.parse_args()
    out = a.out or os.path.splitext(os.path.abspath(a.md))[0] + ".pdf"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    _, generated = build(a.md, a.css, out, appends=a.append, lang=a.lang, html_out=a.html_out)
    raise SystemExit(0 if generated else 1)
