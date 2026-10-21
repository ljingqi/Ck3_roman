# -*- coding: utf-8 -*-
"""v119 probe: how wide the 家谱 SVG really is, and how narrow it becomes once the layout stops
reserving room for collapsed branches.

The real `renderTree` (the JS inside output/<folder>/index.html) is measured by the existing node
harness `logs/v113/v113_tree_harness.mjs`; this script only writes the patched variants of the page that
the harness reads. Nothing under output/ is modified: the copies live in logs/.

Usage:  python tools/tests/v119_probe_tree.py [家族文件夹]      (default 洪氏2)
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"
PAGE = os.path.join(ROOT, "output", FOLDER, "index.html")
HARNESS = os.path.join(ROOT, "logs", "v113_tree_harness.mjs")
NODE = r"C:\Users\Maoha\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"

KEEP_LINE = "  const keep = (TREE.nodes || []).filter(n => (n.from_k || 1) <= k);"
KEEP_HEADS = """  const __rs = {}; (TREE.red_edges || []).forEach(e => { __rs[e[0]] = 1; __rs[e[1]] = 1; });
  (TREE.red_dashed || []).forEach(e => { __rs[e[0]] = 1; __rs[e[1]] = 1; });
  const __cs = {}; (TREE.chain || []).slice(0, k).forEach(c => { __cs[c.id] = 1; });
  const keep = (TREE.nodes || []).filter(n => (n.from_k || 1) <= k && (__cs[n.id] || __rs[n.id]));"""
KEEP_SPOUSE = KEEP_HEADS + """
  const __in = {}; keep.forEach(n => { __in[n.id] = 1; });
  (TREE.nodes || []).forEach(n => { if(n.spouse_of != null && __in[n.spouse_of] && !__in[n.id]) keep.push(n); });"""
# 「传主与配偶」: the narrow state the v119 default used to be — collapse everything `defaultOpen`
# does not vouch for. The shipped default now opens every clansman, so the narrow variant is measured
# by patching the init line back.
NARROW_FROM = "    sc.nodes.forEach(n => { collapsed[n.id] = 0; });"
NARROW_TO = "    sc.nodes.forEach(n => { collapsed[n.id] = defaultOpen(sc, n) ? 0 : 1; });"


def measure(tag, keep_block=None, narrow=False):
    html = open(PAGE, encoding="utf-8").read()
    if keep_block is not None:
        if KEEP_LINE not in html:
            raise SystemExit("keep line not found — htmlview.py layout changed")
        html = html.replace(KEEP_LINE, keep_block)
    if narrow:
        if NARROW_FROM not in html:
            raise SystemExit("init line not found — htmlview.py layout changed")
        html = html.replace(NARROW_FROM, NARROW_TO, 1)
    path = os.path.join(ROOT, "logs", f"v119_tree_{tag}.html")
    open(path, "w", encoding="utf-8").write(html)
    out = subprocess.run([NODE, HARNESS, path], capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise SystemExit(f"{tag}: harness failed\n{out.stderr[:800]}")
    data = json.loads(out.stdout)
    case = [c for c in data["cases"] if c["k"] == data["K"]][0]
    return {"tag": tag, "k": data["K"], "beads": case["bead_count"], "view": case["view"],
            "tog": sum(1 for b in case["beads"] if b["tog"])}


# 2K 屏：treeFontSize 会算出 14px —— 用一个植桩版本量出该字号下的画布 (几何同比例放大)
FS_RE = re.compile(r"function treeFontSize\(\)\{.*?\n\}", re.S)


def measure_fs(fs):
    html = open(PAGE, encoding="utf-8").read()
    html = FS_RE.sub(f"function treeFontSize(){{ return {fs}; }}", html, count=1)
    path = os.path.join(ROOT, "logs", f"v119_tree_fs{fs}.html")
    open(path, "w", encoding="utf-8").write(html)
    out = subprocess.run([NODE, HARNESS, path], capture_output=True, text=True, encoding="utf-8")
    if out.returncode:
        raise SystemExit(f"fs{fs}: harness failed\n{out.stderr[:800]}")
    data = json.loads(out.stdout)
    case = [c for c in data["cases"] if c["k"] == data["K"]][0]
    os.remove(path)
    return {"tag": f"默认@{fs}px", "k": data["K"], "beads": case["bead_count"],
            "view": case["view"], "tog": sum(1 for b in case["beads"] if b["tog"])}


rows = [measure("默认(全族)"),
        measure_fs(14),
        measure("传主与配偶", narrow=True),
        measure("只留传主", KEEP_HEADS),
        measure("传主线+配偶", KEEP_SPOUSE)]
print(f"{'变体':<14}{'珠子':>6}{'宽':>8}{'高':>7}{'▶钮':>5}   屏幕数@2K(2280px 视口)")
for r in rows:
    w, h = r["view"]
    print(f"{r['tag']:<14}{r['beads']:>6}{w:>8}{h:>7}{r['tog']:>5}   {w / 2280:.2f}")
json.dump(rows, open(os.path.join(ROOT, "logs", "v119_tree_size.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
for r in rows:
    p = os.path.join(ROOT, "logs", f"v119_tree_{r['tag']}.html")
    if os.path.exists(p):
        os.remove(p)
