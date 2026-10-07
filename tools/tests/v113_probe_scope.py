# -*- coding: utf-8 -*-
"""v113 probe: why the default collapse differs per piece (JS scope internals, no melt)."""
import io
import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

EXTRA = """
const probe = (k) => {
  const sc = api.scopeOf(k);
  let nsub = 0, nred = 0;
  const names = [];
  sc.nodes.forEach(n => { if(sc.isSubj(n)) nsub++; if(sc.redNodes[n.id]) { nred++; names.push(n.name); } });
  return {k: k, nodes: sc.nodes.length, subj: nsub, red: nred, rednames: names,
          roots: sc.roots.length,
          collapsible: sc.nodes.filter(n => (sc.kids[n.id]||[]).length).length};
};
console.log(JSON.stringify([probe(9), probe(2), probe(1)]));
"""


def main():
    spec = importlib.util.spec_from_file_location(
        "verify_v113", os.path.join(ROOT, "tools", "tests", "verify_v113.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    src = io.open(mod.write_harness(), encoding="utf-8").read()
    src = src.replace("console.log(JSON.stringify(out));", EXTRA)
    dst = os.path.join(ROOT, "logs", "v113_probe_scope.mjs")
    io.open(dst, "w", encoding="utf-8", newline="\n").write(src)
    raw = subprocess.run(["node", dst, os.path.join(ROOT, "output", "洪氏2", "index.html")],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    print(raw.stdout.strip()[-1200:])
    if raw.stderr.strip():
        print("STDERR:", raw.stderr.strip()[-500:])


if __name__ == "__main__":
    main()
