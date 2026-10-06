# -*- coding: utf-8 -*-
"""v108 归因：三处改错是不是**最后一个提交 f9929b0**引入的（对比 646a903 的行为）。

把 646a903 的 biography.py 取出来单独加载（不改工作树），对同一批成稿句子跑 `_fix_kin_roles`：
若旧版逐字保留、新版改写，则 f9929b0 的「无名字时逐句回退取上一句首个人名」是引入源。
"""
import glob
import importlib.util
import io
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "tests"))
import facts as F                    # noqa: E402
import v108_probe_d_repro as RP      # noqa: E402

TMP = os.path.join(ROOT, "logs", "_bio_646a903.py")


def load_old(rev):
    src = subprocess.run(["git", "show", "%s:biography.py" % rev], cwd=ROOT,
                         capture_output=True)
    io.open(TMP, "wb").write(src.stdout)
    spec = importlib.util.spec_from_file_location("bio_%s" % rev, TMP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    cache, facts = RP.load()
    out = []
    for rev in ("646a903", "HEAD"):
        mod = __import__("biography") if rev == "HEAD" else load_old(rev)
        out.append((rev, mod))
    lines = ["=" * 88,
             "v108 归因：成稿被改错是哪个提交引入的（646a903 = f9929b0 的父提交）",
             "=" * 88]
    for label, src, subs, keep in RP.CASES:
        lines.append("-" * 88)
        lines.append("%s   段落主语=%s   应保留：%s" % (label, subs, keep))
        for rev, mod in out:
            got = mod._fix_kin_roles(src, facts, cache, subject_ids=subs)
            lines.append("  %-8s %s  %s" % (rev, "保留 OK" if keep in got else "★改错  ",
                                            got if keep not in got else ""))
    lines.append("=" * 88)
    io.open(os.path.join(ROOT, "logs", "v108_repro_attrib.txt"), "w",
            encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    for ln in lines:
        print(ln)


if __name__ == "__main__":
    main()
