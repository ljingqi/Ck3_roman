# -*- coding: utf-8 -*-
"""v86: 把 v86_870_deep.json 压成可读摘要 (不载熔件)。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "v86_870_deep.json"), encoding="utf-8"))


def p(*a):
    print(*a)


p("### top keys:", D.get("_top_keys"))
p("### rites_root_shape:", json.dumps(D.get("rites_root_shape"), ensure_ascii=False)[:600])
p("### rites_count:", D.get("rites_count"))
p("### rites_field_freq:", json.dumps(D.get("rites_field_freq"), ensure_ascii=False))
p("### rites_data_field_freq:", json.dumps(D.get("rites_data_field_freq"), ensure_ascii=False))
p("### rites_keys_sample:", json.dumps(D.get("rites_keys_sample"), ensure_ascii=False))
p("### head_of_rite_values:", json.dumps(D.get("head_of_rite_values"), ensure_ascii=False))
p("### rite_type_values:", json.dumps(D.get("rite_type_values"), ensure_ascii=False))
p("### faith_of_rite_values:", json.dumps(D.get("faith_of_rite_values"), ensure_ascii=False))
p("### origin_rite_values:", json.dumps(D.get("origin_rite_values"), ensure_ascii=False))
p("### rites_with_hor_player:", json.dumps(D.get("rites_with_hor_player"), ensure_ascii=False, indent=1))
p()
p("### rites_brief (前 60):")
b = D.get("rites_brief") or {}
for i, (k, v) in enumerate(b.items()):
    if i >= 60:
        break
    p(" ", k, json.dumps(v, ensure_ascii=False))
p("### rites_brief total:", len(b))
