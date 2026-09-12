# -*- coding: utf-8 -*-
"""v34 回归断言 (七问题) —— 读 tools/snap.py 落的快照做秒级核对, 不碰熔件。

用法:
    先落快照:  tools\\py.ps1 tools\\snap.py 柳特佩特 38653 878.1.1 1
    再跑断言:  tools\\py.ps1 tools\\verify_v34.py
    一次熔化跑全套: tools\\py.ps1 tools\\verify_v34_once.py

退出码 0 = 全 PASS。也可 `import verify_v34; verify_v34.run(snap_path)`
由别的脚本内联调用 (避免子进程管道捕获)。
"""
import io
import json
import os
import re
import sys

def _repo_root():
    """仓库根: 从本文件向上找到含 facts.py 的目录 (兼容 tools/ 或 experiments/ 放置)。"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        if os.path.isfile(os.path.join(d, "facts.py")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


ROOT = _repo_root()
DEFAULT_SNAP = os.path.join(ROOT, "output", "柳特佩特", "data",
                            "snap_38653_878.1.1_d1.json")

_PRIVATE_NAMES = ("索丹·索丹", "安科马", "古布莱努·托尔基托留")
PUBLIC_BOARDS = ("benji", "friend", "enemy", "feuds", "chaoju", "assassins",
                 "youxia", "qunying", "artifacts")


def has_phrase(text, phrase):
    """词形匹配: 排除「事实为准」这类跨词巧合 (「实为」误报源)。"""
    return re.search(r"(?<!事)" + re.escape(phrase), text) is not None


class Checker(object):
    def __init__(self, stream):
        self.stream = stream
        self.ok = True

    def check(self, name, cond, detail=""):
        line = (("  PASS " if cond else "  FAIL ") + name
                + (f"  | {detail}" if detail else ""))
        self.stream.write(line + "\n")
        if not cond:
            self.ok = False
        return cond

    def skip(self, name):
        self.stream.write("  SKIP " + name + "\n")


def run(snap_path=None, stream=None):
    """跑全部断言; 返回 True/False (全 PASS)。"""
    if stream is None:
        import io as _io
        stream = _io.StringIO()
    c = Checker(stream)
    snap_path = snap_path or DEFAULT_SNAP
    if not os.path.isfile(snap_path):
        c.check(f"快照存在 ({snap_path})", False)
        return c.ok, stream
    d = json.load(open(snap_path, encoding="utf-8"))
    facts, shared, blocks = d["facts"], d.get("shared") or "", d["blocks"]
    msgs = d.get("messages") or {}

    stream.write("[1] 共享前缀瘦身 (问题5)\n")
    c.check("共享前缀 ≤ 400 字符", len(shared) <= 400, len(shared))
    c.check("共享前缀不含完整档案", "【人物档案】" not in shared)
    c.check("共享前缀不含逐年摘要", "【主角大事摘要】" not in shared)
    c.check("共享前缀仍含传主/家族/现状",
            all(x in shared for x in ("【传主】", "【家族】", "【现状】")))

    stream.write("[2] 披露分级: 公开篇目看不到揭底 (问题1)\n")
    for key in PUBLIC_BOARDS:
        for seg in ("lead", "mid"):
            blk = blocks.get(f"{key}_{seg}")
            if not blk:
                continue
            txt = json.dumps(blk, ensure_ascii=False)
            bad = [w for w in ("实为", "实父") if has_phrase(txt, w)]
            c.check(f"{key}_{seg} 无揭底句面", not bad, bad or "")
    jiashi = json.dumps(blocks.get("jiashi_mid") or {}, ensure_ascii=False)
    c.check("家室列传纪事**保留**实父 (内宅档)", has_phrase(jiashi, "实父"))
    secre = json.dumps(blocks.get("secrets_mid") or {}, ensure_ascii=False) \
        + json.dumps(blocks.get("secrets_lead") or {}, ensure_ascii=False)
    c.check("阴私录保留揭底 (内宅档)",
            has_phrase(secre, "实为") or has_phrase(secre, "实父")
            or "乱伦" in secre)

    stream.write("[3] 本纪档案隐去生育能力 (用户拍板「不留」)\n")
    prot = facts["protagonist"]
    c.check("公开档案 traits 无「不育」", "不育" not in (prot.get("traits") or ""),
            prot.get("traits"))
    dfp = prot.get("dramatic_facts_private") or []
    c.check("揭底链进 private 桶", any("实为" in x for x in dfp), f"{len(dfp)} 条")

    stream.write("[4] 同篇两板块不重复 (问题5)\n")
    lead = set((blocks.get("benji_lead", {}).get("大事年表") or "").split("\n"))
    mid = set((blocks.get("benji_mid", {}).get("大事年表") or "").split("\n"))
    lead.discard("")
    mid.discard("")
    if lead and mid:
        c.check("本纪开篇/纪事年表不相交", not (lead & mid),
                f"交集 {len(lead & mid)}")
    else:
        c.skip("本纪开篇/纪事年表不相交 (切分为空)")

    stream.write("[5] 朝廷职司政权门槛 (问题3)\n")
    realm = facts.get("realm") or {}
    mins = realm.get("ministers") or []
    c.check("独立领主的朝廷职司为空 (唐六部不再混入)", not mins, mins[:3])

    stream.write("[6] 特质表完整性 (问题4)\n")
    tr = prot.get("traits") or ""
    c.check("极小阴茎进「为人」句 (Mod 特质不再静默丢弃)", "极小阴茎" in tr, tr)

    stream.write("[7] 恩怨因果链 (问题6)\n")
    feuds = " ".join(e for fd in (facts.get("house_feuds") or [])
                     for e in fd.get("events") or [])
    c.check("恩怨史含战胜节点", "战胜" in feuds)
    c.check("恩怨史含失守节点", "失守" in feuds)
    c.check("恩怨史含无地冒险者", "无地冒险者" in feuds)
    c.check("恩怨史宣战句带战争类型", "征服战" in feuds or "发动开战" in feuds)

    stream.write("[8] 释放/囚禁口径 (问题7)\n")
    # 囚禁区间记在缓存 (v34 cache_lib), 三人不在档案集内 → 直读缓存文件
    cache_p = os.path.join(os.path.dirname(snap_path),
                           "player_%s.json" % facts.get("player_id"))
    cache = {}
    if os.path.isfile(cache_p):
        try:
            cache = json.load(open(cache_p, encoding="utf-8"))
        except Exception:
            cache = {}
    cch = cache.get("characters") or {}

    def _ph(cid):
        return (cch.get(cid) or {}).get("prison_history") or []

    ph = _ph("16819577")
    c.check("囚禁区间已入缓存 (妮卡蕾忒)", bool(ph), ph)
    c.check("妮卡蕾忒在押区间未闭合 (数据确证仍关着)",
            bool(ph) and ph[-1].get("to") is None, ph[-1] if ph else None)
    c.check("在押区间带囚禁起始日 (875.6.29)",
            bool(ph) and ph[-1].get("since") == "875.6.29",
            ph[-1].get("since") if ph else None)
    kph = _ph("12593")
    rel = [m for m in ((cch.get("12593") or {}).get("memories") or [])
           if m.get("type") == "released_from_prison_memory"]
    # 凯撒里奥斯在首档前已出狱 → prison_history 为空; 其「已出狱」由释放记忆证明
    c.check("凯撒里奥斯已出狱有凭 (释放记忆 875.12.31 或已闭合区间)",
            (bool(kph) and kph[-1].get("to") is not None)
            or any(m.get("creation_date") == "875.12.31" for m in rel),
            kph or [m.get("creation_date") for m in rel])
    c.check("囚禁区间表跨人可用 (缓存内 ≥1 人有区间)",
            any(v.get("prison_history") for v in cch.values()))

    stream.write("[9] 请求面 (messages)\n")
    for name in ("benji_lead", "benji_mid"):
        m = msgs.get(name) or {}
        txt = json.dumps(m, ensure_ascii=False)
        bad = [w for w in ("实为", "实父") if has_phrase(txt, w)]
        c.check(f"{name} 请求全文无揭底句面", not bad, bad or "")
    lead_msg = (msgs.get("benji_lead") or {}).get("user") or ""
    c.check("本篇主题 (focus) 已下发", "本篇主题" in lead_msg)
    sys_msg = (msgs.get("benji_lead") or {}).get("system") or ""
    c.check("写作规则「一篇一题」已下发", "一篇一题" in sys_msg)
    c.check("写作规则「互见法」已下发", "互见法" in sys_msg)

    stream.write("[10] 出生句归属 (问题8: 生母的生育不写成主角得子)\n")
    benji_all = json.dumps(blocks.get("benji_mid") or {}, ensure_ascii=False) \
        + json.dumps(blocks.get("benji_lead") or {}, ensure_ascii=False)
    births = re.findall(r"(?:添子|添女|得长子|得长女)([^，。（\n]{2,12})"
                        r"(?:（生父([^）]{1,20})）)?", benji_all)
    c.check("本纪收到出生记载", len(births) >= 6, f"{len(births)} 条")
    c.check("有出生句带「生父X」(非主角所出者)", "生父" in benji_all)
    for kid, father in births:
        if kid and father:
            c.check(f"{kid} 生父标注非主角", "潘杜尔夫" not in father, father)
    c.check("法霍·索丹生父标注为索丹·索丹",
            bool(re.search(r"法霍·索丹（生父[^）]*索丹·索丹）", benji_all)))

    stream.write("\n" + ("全 PASS" if c.ok else "有 FAIL") + "\n")
    return c.ok, stream


def main():
    ok, stream = run()
    sys.stdout.write(stream.getvalue())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
