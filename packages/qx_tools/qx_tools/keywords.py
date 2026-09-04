"""关键词资产工具：研究产出 → 设计种子（W7 Schema v2）。

方法论（产品理解本体，而非产品分析标签）：
  搜索/采集 → 特征抽取 → 产品结构理解 → 语义→视觉转换（不可视觉化的词必须实体化）
  → Visualizability 评分过滤（<2 不进生图层）→ 冲突检测消解 → 8 层双语规格落库。
人群信息只经「定位→设计约束」间接传导，绝不直接作为关键词。
"""
from __future__ import annotations

import json
import logging

from langchain.tools import tool

from . import qxhttp

logger = logging.getLogger(__name__)

_LAYERS = (
    "identity 产品定义 / architecture 总体结构 / geometry 几何比例 / components 组件 / "
    "materials 材料表面 / hardware 功能硬件 / mechanism 机构关系 / environment 使用环境"
)


@tool("save_keyword_asset")
def save_keyword_asset_tool(
    schema_json: str,
    name: str = "",
    project_id: str = "",
    groups_json: str = "",
) -> str:
    """保存产品设计关键词资产（Schema v2：8 层双语设计规格），入库后聊天面板出现可编辑规格卡。

    Schema v2 结构（groups_json 仅作旧格式兼容）：
    {
      "layers": [
        {"key": "identity|architecture|geometry|components|materials|hardware|mechanism|environment",
         "items": [{"zh": "中文视觉化短语", "en": "English visual phrase",
                    "visualizability": 0-3, "priority": "must|optional",
                    "source": ["ASIN/页面来源"]}]}
      ],
      "conflicts": [{"type": "hard|tension", "items": [...], "resolution": "..."}],
      "positioning": {"audience": "...", "positioning_en": "...", "derived_constraints": [...]},
      "spec_tree": "组件装配树（文本树形）"
    }

    质量硬规则：
    - 每条 en 必须可视觉执行：[对象]+[属性]+[几何]+[位置/关系]（如 "low-profile cylindrical RTK
      GNSS antenna mounted on the top centerline of the fuselage"）；
    - 不可视觉化的概念（RTK导航/精准喷洒/大载重）必须转换成可见硬件实体后才能入库；
    - hard conflict（如 四旋翼 vs 六旋翼）入库前必须消解；
    - 人群/客户信息只写入 positioning，不进 layers。

    Args:
        schema_json: 上述 Schema v2 的 JSON 字符串。
        name: 资产名。project_id: 可选挂载任务。groups_json: 旧 5 组格式（兼容，二选一）。
    """
    try:
        schema = json.loads(schema_json)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"schema_json 不是合法 JSON: {exc}"}, ensure_ascii=False)
    if not isinstance(schema, dict) or not schema.get("layers"):
        return json.dumps({"error": "schema_json 需含非空 layers 数组"}, ensure_ascii=False)

    payload: dict = {"schema": schema}
    if name:
        payload["name"] = name
    if project_id:
        payload["project_id"] = project_id
    resp = qxhttp.request("POST", "/assets/keywords", json=payload)
    if resp.status_code not in (200, 201):
        return json.dumps({"error": f"save failed ({resp.status_code})", "detail": resp.text[:300]},
                          ensure_ascii=False)
    a = resp.json()
    return json.dumps(
        {
            "asset_id": a.get("id"),
            "saved": True,
            "hint": "规格卡已在右侧面板展示（8 层可编辑）；询问用户：调整规格 / 选视图套装生图 / 存档",
        },
        ensure_ascii=False,
    )
