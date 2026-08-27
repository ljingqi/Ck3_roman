---
name: respect-user-instructions
description: Use whenever proposing or implementing plans, designs, or fixes in this Journal project (or any task in this session) — any proposed plan must strictly follow the user's explicitly stated instructions and intent; when the user has already decided a direction, implement it faithfully instead of proposing alternatives that contradict it.
---

# 方案服从用户指令铁律（respect-user-instructions）

本技能适用于本 Journal 项目（V3 报纸/杂志生成）以及本会话中的任何构想、方案与实施。**铁律：构想出来的方案必须服从用户已明确给出的指令与意图。**

## 适用范围

- 提出修复方案、设计方案、重构方案时；
- 用户已对某个问题给出明确方向（如「问题1用C」「改成按TAG匹配」）之后继续细化或实施时；
- 用户陈述过原意（如「生活水平这么低的pop不可能吃得起这么多数量的食品」）之后，任何相关方案都要以该原意为前提。

## 要求

1. **先核对用户指令再提方案**：动笔列方案前，逐条重读用户本轮及历轮给出的指令，确认方案与每一条指令方向一致。
2. **已定方向不得另提相悖方案**：用户已选定方案（A/B/C、D1/D2、E1/E2 等）后，实施该方案即可；不得再抛出与该选择矛盾的新方向，也不得把用户已否决的选项换个名字重新建议。
3. **方案以用户原意为锚**：用户描述过期望效果（穷人吃不起、汇率要动态、匹配要稳定）时，方案必须服务于该效果；解释取舍时可说明边界与代价，但方向不得偏离。
4. **实施忠实于选定方案**：编码与提示词改动按选定的方案落地，不夹带未获批的额外方向改动；确有必要的新增修改，单独列出并说明理由，交由用户决定。
5. **正向表述**：本技能自身与写给模型的任何提示词一律按正向表述（见 no-negative-prompts 技能），不出现「不要/避免/禁止」式禁令词。

## 自检清单（提出方案后自查）

- [ ] 用户本轮每条指令是否都有对应落地？
- [ ] 方案中是否出现与用户已定选择相反的内容？
- [ ] 是否把用户已否决的方向以新名义重新提出？
- [ ] 实施是否只包含获批方案，未夹带未经确认的额外方向？

命中任何一项即先修正方案，再交用户审阅。
