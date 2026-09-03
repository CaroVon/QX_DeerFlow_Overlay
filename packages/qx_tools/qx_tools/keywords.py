"""关键词资产工具：研究产出 → 设计种子（黄金路径的落库环节）。

qx-researcher 采集+搜索后提炼 5 组关键词，调 save_keyword_asset 入库；
聊天右侧面板会展示可编辑的关键词卡，用户可直接「用关键词生图」。
研究 agent 本身不持有生图工具（边界：提炼关键词，不做设计）。
"""
from __future__ import annotations

import json
import logging

from langchain.tools import tool

from . import qxhttp

logger = logging.getLogger(__name__)


@tool("save_keyword_asset")
def save_keyword_asset_tool(
    groups_json: str,
    name: str = "",
    project_id: str = "",
) -> str:
    """保存关键词资产（产品设计种子），入库后聊天面板会出现可编辑的关键词卡。

    产出关键词的标准流程：真实采集（先向用户确认 credits）+ 网络搜索 →
    提炼为 5 组关键词。保存后应主动询问用户下一步：调整关键词 / 直接生图 / 存档。

    Args:
        groups_json: JSON 对象字符串，键为组名（design/function/appearance/
            audience/scenario），值为关键词数组。例：
            {"design": ["圆柱形", "钛金属"], "function": ["便携"], ...}
        name: 资产名（如 "便携咖啡机关键词"），可选。
        project_id: 可选，挂载的 QX 任务 ID。
    """
    try:
        groups = json.loads(groups_json)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"groups_json 不是合法 JSON: {exc}"}, ensure_ascii=False)
    if not isinstance(groups, dict) or not groups:
        return json.dumps({"error": "groups_json 需为非空对象 {组名: [关键词]}"}, ensure_ascii=False)

    resp = qxhttp.request(
        "POST", "/assets/keywords",
        json={"groups": groups, "name": name or None, "project_id": project_id or None},
    )
    if resp.status_code not in (200, 201):
        return json.dumps({"error": f"save failed ({resp.status_code})", "detail": resp.text[:300]},
                          ensure_ascii=False)
    a = resp.json()
    return json.dumps(
        {
            "asset_id": a.get("id"),
            "saved": True,
            "hint": "关键词卡已在右侧面板展示（可编辑）；询问用户：调整关键词 / 直接生图 / 存档",
        },
        ensure_ascii=False,
    )
