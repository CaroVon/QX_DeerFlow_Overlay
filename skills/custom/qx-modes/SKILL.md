---
name: qx-modes
description: QX mode commands for product research pipelines. Trigger via /qx-full (complete pipeline with PPT delivery), /qx-research (market research only), /qx-matrix (MOD competitor matrix only), /qx-image (product image generation). Use when the user wants to launch a scoped QX task from chat.
---

# QX Mode Commands

## Modes

- **/qx-full `<idea>`** — 完整流水线：调用 `submit_studio_job`（默认审核模式；用户说"自动/放手"时传
  `auto_approve_gates=true`，并在每个门到达时向用户播报资料/大纲摘要以保持透明）。
  提交后轮询 `get_studio_job_status`，向用户汇报节点推进；任务面板会自动打开可视化。
- **/qx-research `<keyword>`** — 仅市场研究：`collect_amazon_data_tool`（真实源需确认 credits）+
  `knowledge_search_tool` + web 检索，汇总市场洞察。不启动长任务。
- **/qx-matrix `<keyword>`** — 仅竞品矩阵：优先复用已有采集（`collect_amazon_data_tool` 的 data_dir
  可 0-credit 回放），然后 `competitor_matrix_tool` 产出 MOD 报告与图表。
- **/qx-image `<description>`** — 产品概念图：`generate_design_image`（关键词组合成 prompt），
  轮询 `get_design_image_status` 直至出图并给出链接。

## Rules

- 真实 Rainforest 采集消耗 credits，先确认再执行；mock 源可直接跑。
- 长任务提交后不要阻塞等待完成：报告 job_id 与预期时长，让用户在任务面板跟进。
- 部分模式（重做某页/查关键词）的目标任务默认取最近活跃任务，用户显式指定时以指定为准。
- 重做 PPT 某页用 `rework_ppt_page`（page_number 为人类口径页码）。
