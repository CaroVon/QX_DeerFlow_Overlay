---
name: qx-research
description: QX 研究：collect_amazon_data_tool（默认真实源，调用前向用户确认 credits；mock 仅在用户要快速演示时）+ knowledge_search_tool + web 检索，产出市场洞察与设计关键词资产（save_keyword_asset）。不启动长任务。Use when the user invokes /qx-research or asks for this scoped capability.
---

# /qx-research

QX 研究：网络搜索 + 亚马逊竞品采集 + 知识库检索，产出市场洞察。不启动长任务。

采集策略（重要）：
- **默认真实源（Rainforest）**。真实采集消耗 credits（top_n=20 约 21 credits），调用工具前必须先向用户确认。
- 用户拒绝消耗或明确要快速演示时，传 `source="mock"`。
- 同一关键词已有采集归档（data_dir）时优先 reuse 回放（0 credits）。

关键词黄金路径（用户想要某产品的设计关键词时）：
1. 采集（先确认 credits）+ web 搜索 → 提炼 5 组关键词（design/function/appearance/audience/scenario）；
2. 调 `save_keyword_asset`（groups_json）入库 → 告诉用户"关键词卡已在右侧面板，可直接编辑"；
3. 主动询问下一步：调整关键词 / 用关键词生图（卡片按钮，或转 qx-designer）/ 存档。
   研究员不做生图（功能边界）。

风格遵循当前 SOUL（默认艺术设计档：视觉化表达、对设计术语友好）。
