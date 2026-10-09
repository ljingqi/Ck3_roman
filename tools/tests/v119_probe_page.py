# -*- coding: utf-8 -*-
"""v119 probe: the reading page carries the 封档总评 button only when the file exists."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import htmlview  # noqa: E402
import llm       # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"


def main():
    cfg = llm.load_config()
    page = htmlview.rebuild_folder(cfg["output_dir"], FOLDER)
    html = open(page, encoding="utf-8").read()
    m = html.split('const DATA = ', 1)[1].split(';\n', 1)[0]
    data = json.loads(m)
    epi = data.get("epilogue")
    print("page        :", page, len(html), "bytes")
    print("tree chain  :", len((data.get("tree") or {}).get("chain") or []))
    print("chars       :", len(data.get("chars") or []))
    print("epilogue    :", (epi or {}).get("file"), "| toc",
          len((epi or {}).get("toc") or []), "| html", len((epi or {}).get("html") or ""))
    print("epi-btn 标记 :", "epi-btn" in html)
    print("tree-mode CSS:", "body.tree-mode #stage{max-width:none}" in html)


if __name__ == "__main__":
    main()
