# -*- coding: utf-8 -*-
"""v104 取证探针 1：把 logs/prompts.log 的请求分块，定位耀国（135480）的
《家室列传》/《纪事·门庭恩怨·...》请求，并逐行引出「妻室…子…女…」素材行。
只读。输出 UTF-8 到 logs/v104_prompt_blocks.txt
"""
import re
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG = os.path.join(ROOT, "logs", "prompts.log")
OUT = os.path.join(ROOT, "logs", "v104_prompt_blocks.txt")

lines = open(LOG, encoding="utf-8").read().split("\n")

# 请求边界
starts = [i for i, l in enumerate(lines) if l.startswith("===== ")]
reqs = []
for k, s in enumerate(starts):
    e = starts[k + 1] - 1 if k + 1 < len(starts) else len(lines) - 1
    reqs.append((s + 1, e + 1))  # 1-based inclusive

out = []
def w(s=""):
    out.append(s)

w(f"# prompts.log 请求分块（共 {len(reqs)} 个请求），文件 {len(lines)} 行")
w()

# 每个请求摘要
summary = []
for (a, b) in reqs:
    body = lines[a - 1:b]
    txt = "\n".join(body)
    head = next((l for l in body if l.startswith("【传主】")), "")
    ask = next((l for l in body if l.startswith("请撰写板块")), "")
    m = re.search(r"请撰写板块《([^》]*)》", ask)
    sec = m.group(1) if m else ""
    m2 = re.search(r"【现状】([^\n]*)", txt)
    cur = m2.group(1) if m2 else ""
    m3 = re.search(r"请撰写板块《[^》]*》。(要求：[^\n]*)", ask)
    req_txt = m3.group(1) if m3 else ask[:60]
    summary.append((a, b, head, sec, cur, req_txt))

w("## 一、全部请求摘要")
w()
w("| 起行 | 止行 | 传主 | 板块 | 现状 | 要求摘要 |")
w("| --- | --- | --- | --- | --- | --- |")
for (a, b, head, sec, cur, req_txt) in summary:
    w(f"| {a} | {b} | {head} | {sec} | {cur} | {req_txt} |")
w()

# 目标：传主为耀国·洪堡，且板块含「家室」或「门庭恩怨」或「诸子行迹」或「结缡」
TARGET = ("家室", "门庭恩怨", "结缡")
w("## 二、耀国家室相关请求：素材块逐行")
w()
for (a, b, head, sec, cur, req_txt) in summary:
    if "耀国" not in head:
        continue
    if not any(t in sec for t in TARGET) and "结缡" not in "\n".join(lines[a - 1:b]):
        continue
    body = lines[a - 1:b]
    w(f"### 请求 {LOG}:{a}-{b}｜板块《{sec}》｜{cur}")
    w()
    w(f"要求全文：{req_txt}")
    w()
    # 相关事实：之后的行
    idx = next((i for i, l in enumerate(body) if l.strip() == "相关事实："), None)
    if idx is not None:
        w("「相关事实：」位于 %s:%d，其后素材如下：" % (LOG, a + idx))
        for i in range(idx, len(body)):
            ln = body[i]
            if ln.startswith("请撰写板块"):
                w("--- 以下为板块要求行 ---")
                w(f"{LOG}:{a+i}  {ln}")
                break
            w(f"{LOG}:{a+i}  {ln}")
    else:
        w("（本请求无「相关事实：」行）")
    w()

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(out))
print("wrote", OUT, len(out), "lines")
