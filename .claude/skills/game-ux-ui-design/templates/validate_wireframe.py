#!/usr/bin/env python3
"""Validate an annotated-wireframe SVG against the game-ux-ui-design kit rules.

Dependency-free (stdlib only). Run on every wireframe before embedding:

    python validate_wireframe.py wireframes/hud.svg [more.svg ...]

Checks (each a PASS/FAIL line):
  - XML well-formed
  - full-canvas background <rect> present as an early element (dark-mode label safety)
  - <= 10 callouts per frame
  - callout group IDs are unique/sequential and map 1:1 to two matching badges + one leader
  - leader polylines (class~="lead") have exactly 4 orthogonal points
  - no two leader segments cross (ccw segment-intersection, shared endpoints ignored)
  - gutter balance: labels live only in the gutters (x<200 or x>frame_right); neither side > 6;
    left/right imbalance <= 2
  - no text clips off-canvas (x + estimated width <= viewBox width; CJK glyphs counted ~2x)

Exit code 0 if all pass, 1 otherwise. The legend-row<->badge mapping must still be
eyeballed against the .md (the SVG alone can't see the table).
"""
import re, sys, xml.dom.minidom as M

def seg_cross(p, q, r, s):
    # TRUE X-crossing only: segments intersect at an interior point of BOTH.
    # T-junctions / collinear touches (the legitimate "shared gutter channel" pattern)
    # have a zero ccw and are NOT reported here — use gutter-stagger guidance for those.
    def ccw(a, b, c): return (c[1]-a[1])*(b[0]-a[0]) - (b[1]-a[1])*(c[0]-a[0])
    if p in (r, s) or q in (r, s): return False
    d1, d2 = ccw(r, s, p), ccw(r, s, q)
    d3, d4 = ccw(p, q, r), ccw(p, q, s)
    if 0 in (d1, d2, d3, d4): return False   # endpoint-on-segment / collinear → touch, not cross
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))

def text_px(t, font=18):
    # CJK/Hangul ~1.0 em, Latin ~0.55 em at this font size
    w = 0.0
    for ch in t:
        w += font * (1.0 if ord(ch) > 0x1100 else 0.55)
    return w

def check(path):
    fails = []
    try:
        d = M.parse(path)
    except Exception as e:
        print(f"FAIL {path}: XML not well-formed: {e}"); return False
    svg = d.getElementsByTagName("svg")[0]
    vb = (svg.getAttribute("viewBox") or "0 0 1760 820").split()
    W = float(vb[2]); frame_right = 1480.0
    # background rect
    rects = d.getElementsByTagName("rect")
    bg = any(abs(float(r.getAttribute("width") or 0) - W) < 2 for r in rects[:3])
    if not bg: fails.append("no full-canvas background <rect> among first elements (labels may vanish in light mode)")
    # callout groups
    cgs = [g for g in d.getElementsByTagName("g") if g.getAttribute("id").startswith("c")]
    if len(cgs) > 10: fails.append(f"{len(cgs)} callouts > 10 cap (split into a second diagram)")
    # Every XML ID is unique; callouts use c1..cN and own two matching badges + one leader.
    all_ids = [node.getAttribute("id") for node in d.getElementsByTagName("*") if node.getAttribute("id")]
    from collections import Counter
    duplicate_ids = sorted(value for value, count in Counter(all_ids).items() if count > 1)
    if duplicate_ids: fails.append(f"duplicate XML id(s): {', '.join(duplicate_ids)}")
    callout_numbers = []
    for group in cgs:
        match = re.fullmatch(r'c(\d+)', group.getAttribute("id"))
        if not match:
            fails.append(f"callout group id '{group.getAttribute('id')}' must be c<number>")
            continue
        number = match.group(1); callout_numbers.append(int(number))
        group_badges = [t.firstChild.data.strip() for t in group.getElementsByTagName("text")
                        if "badgeT" in t.getAttribute("class") and t.firstChild]
        if group_badges != [number, number]:
            fails.append(f"callout c{number} must contain exactly two badge texts '{number}' (found {group_badges})")
        group_leads = [p for p in group.getElementsByTagName("polyline") if "lead" in p.getAttribute("class")]
        if len(group_leads) != 1:
            fails.append(f"callout c{number} contains {len(group_leads)} leaders (expected 1)")
    if sorted(callout_numbers) != list(range(1, len(cgs) + 1)):
        fails.append(f"callout numbers must be sequential 1..{len(cgs)} (found {sorted(callout_numbers)})")
    # Badge numbers appear twice globally too, catching loose badges outside callout groups.
    badges = [t.firstChild.data.strip() for t in d.getElementsByTagName("text")
              if "badgeT" in t.getAttribute("class") and t.firstChild]
    if len(badges) != len(cgs) * 2:
        fails.append(f"{len(badges)} badge texts for {len(cgs)} callouts (expected {len(cgs) * 2})")
    for num, c in Counter(badges).items():
        if c != 2: fails.append(f"badge '{num}' appears {c}x (expected 2: on-region + gutter label)")
    # leaders: point count + crossings
    leads = [p for p in d.getElementsByTagName("polyline") if "lead" in p.getAttribute("class")]
    segs = []
    for p in leads:
        pts = [tuple(map(float, xy.split(","))) for xy in p.getAttribute("points").split()]
        if len(pts) != 4:
            fails.append(f"a leader has {len(pts)} points (expected exactly 4)")
        elif not (pts[0][1] == pts[1][1] and pts[1][0] == pts[2][0] and pts[2][1] == pts[3][1]):
            fails.append("a leader must follow horizontal → vertical → horizontal orthogonal routing")
        for i in range(len(pts)-1): segs.append((pts[i], pts[i+1]))
    for i in range(len(segs)):
        for j in range(i+1, len(segs)):
            if seg_cross(segs[i][0], segs[i][1], segs[j][0], segs[j][1]):
                fails.append(f"two leader segments cross near {segs[i][0]}"); break
    # gutter labels: callTb text x-position -> side
    left = right = 0
    for t in d.getElementsByTagName("text"):
        if "callTb" not in t.getAttribute("class"): continue
        # resolve x via parent <g transform="translate(x,y)">
        x = None
        par = t.parentNode
        tr = par.getAttribute("transform") if par.nodeType == 1 else ""
        if "translate" in tr:
            x = float(tr.split("translate(")[1].split(",")[0])
        if x is None: continue
        if x < 200: left += 1
        elif x > frame_right: right += 1
        else: fails.append(f"label at x={x} is inside the mock area (200..{int(frame_right)}), not a gutter")
    if left > 6: fails.append(f"left gutter has {left} labels > 6 cap")
    if right > 6: fails.append(f"right gutter has {right} labels > 6 cap")
    if abs(left - right) > 2: fails.append(f"gutter imbalance {left}L/{right}R > 2 (rebalance)")
    # clipping
    for t in d.getElementsByTagName("text"):
        cls = t.getAttribute("class")
        if cls not in ("callT", "callTb") or not t.firstChild: continue
        par = t.parentNode
        bx = 0.0
        tr = par.getAttribute("transform") if par.nodeType == 1 else ""
        if "translate" in tr: bx = float(tr.split("translate(")[1].split(",")[0])
        x = bx + float(t.getAttribute("x") or 0)
        anchor = (t.getAttribute("text-anchor") or "start")
        rt = x + (0 if anchor == "end" else text_px(t.firstChild.data.strip()))
        if rt > W + 1: fails.append(f"text '{t.firstChild.data.strip()[:14]}' extends to x={rt:.0f} > {W:.0f} (clips off-canvas)")
    ok = not fails
    print(f"{'PASS' if ok else 'FAIL'} {path}  ({len(cgs)} callouts, {left}L/{right}R)")
    for f in fails: print("   - " + f)
    return ok

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    # check ALL files (do not short-circuit on first failure — every file must be linted)
    results = [check(p) for p in sys.argv[1:]]
    sys.exit(0 if all(results) else 1)
