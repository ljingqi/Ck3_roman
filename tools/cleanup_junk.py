# -*- coding: utf-8 -*-
"""清理 output/ 与 cache/ 里的历史冗余 (v48 方案① 步骤 7)。

清什么 (全部是"改版过程遗留的副本", 与运行期数据无关):
  output/*/data/player_*.json.bak-v*   各次 refresh_* 工具写的备份
  output/*/data/*.json.corrupt.*       缓存损坏留证副本
  cache/_bak_* , cache/v4*anc          v4 迁移前的旧缓存目录
  cache/_auto2.json                    旧自动缓存 (已被 output/<家族>/data 取代)
  output/*/data/melt_*_idx.json[.gz]   孤儿边车 (对应熔件已不存在)
  output/*/*_上轮_*.md                 上一轮生成废弃的旧稿
  output/*/data/.tmp_melt_*.json       异常退出的临时熔件

默认 **--dry-run** (只列不删); 确认后加 --apply。删除前对每份算大小并汇总。
用法:
  & tools\\tools\\py.ps1 tools\\cleanup_junk.py              # 只列
  & tools\\tools\\py.ps1 tools\\cleanup_junk.py --apply       # 真删
  & tools\\tools\\py.ps1 tools\\cleanup_junk.py --apply --no-bak    # 连 .bak-v* 也删
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402
import llm  # noqa: E402

BAK_RE = re.compile(r"^player_\d+\.json\.bak-v[\w.]+$")
CORRUPT_RE = re.compile(r"\.corrupt\.\d{8}_\d{6}$")
TMP_RE = re.compile(r"^\.tmp_melt_.*\.json$")
UPLOAD_OLD_RE = re.compile(r"_上轮_.*\.md$")


def _melts_in(data):
    pat = re.compile(r"^melt_(\d+_\d{2}_\d{2})(?:_p\d+)?\.json(?:\.gz|\.xz)?$")
    return [f for f in os.listdir(data) if pat.match(f)]


def collect(root, no_bak=False):
    """返回 [(路径, 类别, 字节)]。"""
    out = []
    out_dir = os.path.join(root, "output")
    if os.path.isdir(out_dir):
        for folder in sorted(os.listdir(out_dir)):
            base = os.path.join(out_dir, folder)
            data = os.path.join(base, "data")
            if os.path.isdir(data):
                melts = _melts_in(data)
                stems = {cl._index_stem(m) for m in melts}
                for fn in sorted(os.listdir(data)):
                    p = os.path.join(data, fn)
                    if not os.path.isfile(p):
                        continue
                    if BAK_RE.match(fn):
                        if not no_bak:
                            out.append((p, "缓存备份", os.path.getsize(p)))
                    elif CORRUPT_RE.search(fn):
                        out.append((p, "损坏留证", os.path.getsize(p)))
                    elif TMP_RE.match(fn):
                        out.append((p, "残留临时熔件", os.path.getsize(p)))
                    elif "_idx.json" in fn:
                        stem = fn.split("_idx.json")[0]
                        if stem not in stems:
                            out.append((p, "孤儿边车", os.path.getsize(p)))
            for fn in sorted(os.listdir(base)) if os.path.isdir(base) else []:
                p = os.path.join(base, fn)
                if os.path.isfile(p) and UPLOAD_OLD_RE.search(fn):
                    out.append((p, "旧稿", os.path.getsize(p)))
    cache_dir = os.path.join(root, "cache")
    if os.path.isdir(cache_dir):
        for fn in sorted(os.listdir(cache_dir)):
            p = os.path.join(cache_dir, fn)
            # 只清 `_bak_*` 备份目录 (cache/v46anc 里放的是脚本, 不动)
            if os.path.isdir(p) and fn.startswith("_bak_"):
                n = b = 0
                for dp, _dn, fns in os.walk(p):
                    for f in fns:
                        n += 1
                        b += os.path.getsize(os.path.join(dp, f))
                out.append((p, f"旧缓存目录 ({n} 文件)", b))
            elif os.path.isfile(p) and fn == "_auto2.json":
                out.append((p, "旧自动缓存", os.path.getsize(p)))
    return out


def main():
    apply = "--apply" in sys.argv
    no_bak = "--no-bak" in sys.argv
    cfg = llm.load_config()
    root = os.path.dirname(os.path.abspath(cfg.get("output_dir", ROOT)) or ROOT)
    items = collect(ROOT, no_bak=no_bak)
    by_kind = {}
    for p, kind, size in items:
        by_kind.setdefault(kind, [0, 0])
        by_kind[kind][0] += 1
        by_kind[kind][1] += size
    print(f"扫描根: {ROOT}   (模式: {'删除' if apply else '只列 (--dry-run)'}"
          f"{', 含 .bak' if not no_bak else ', 跳过 .bak'})")
    for kind, (n, b) in sorted(by_kind.items(), key=lambda kv: -kv[1][1]):
        print(f"  {kind:16s} {n:4d} 项  {b / 1048576:9.1f} MiB")
    total = sum(b for _p, _k, b in items)
    print(f"  合计             {len(items):4d} 项  {total / 1048576:9.1f} MiB")
    if not apply:
        print("\n示例 (前 10 项):")
        for p, kind, size in items[:10]:
            print(f"  [{kind}] {os.path.relpath(p, ROOT)}  {size / 1048576:.1f} MiB")
        print("\n加 --apply 执行删除。")
        return 0
    import shutil
    done = freed = 0
    for p, kind, size0 in items:
        try:
            size = size0
            if os.path.isdir(p):
                size = 0
                for dp, _dn, fns in os.walk(p):
                    for f in fns:
                        size += os.path.getsize(os.path.join(dp, f))
                shutil.rmtree(p)
            else:
                os.remove(p)
            done += 1
            freed += size
        except Exception as e:            # noqa: BLE001
            print(f"  [失败] {p}: {e}")
    print(f"\n已清理 {done} 项, 释放 {freed / 1048576:.1f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
