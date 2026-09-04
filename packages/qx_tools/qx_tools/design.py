"""设计生图工具（独立生图优先）：产物持久化到 QX 资产库（qx_assets）。

与旧 MCP 内存态（_DESIGN_JOBS）不同：资产行落库 + Celery 执行，
重启不丢、任务面板「生图记录」可直接列取，URL 稳定可点开。
"""
from __future__ import annotations

import json
import logging

from langchain.tools import tool

from . import qxhttp

logger = logging.getLogger(__name__)


@tool("generate_design_image")
def generate_design_image_tool(prompt: str = "", product_id: str = "", schema_asset_id: str = "", view: str = "atlas", style_key: str = "auto") -> str:
    """生成产品/概念图（MiniMax）。无需任何任务：product_id 留空即可独立生成。

    两条路径（同源 Prompt Forge，优先推荐 schema 路径）：
    - schema_asset_id + view（atlas 解构图鉴/hero/ortho 三视图/detail 细节/cutaway 剖面）
      + style_key：后端按关键词 Schema 统一组装，带预算报告，质量最稳。
    - prompt 直发（兼容）。

    异步执行：立即返回 generation_id（约 30s-6min），轮询 get_design_image_status。

    Args:
        prompt: 直发模式的生图提示词。
        product_id: 可选，挂载的 QX 任务 ID。
        schema_asset_id: 关键词资产 ID（save_keyword_asset 的返回值）。
        view: 视图类型，默认 atlas（解构图鉴）。
        style_key: 风格预设 key，默认 auto。
    """
    payload: dict = {"project_id": product_id or None}
    if schema_asset_id:
        payload.update({"schema_asset_id": schema_asset_id, "view": view, "style_key": style_key})
    else:
        payload["prompt"] = prompt
    resp = qxhttp.request("POST", "/assets/generate", json=payload)
    if resp.status_code not in (200, 201):
        return json.dumps({"error": f"generate failed ({resp.status_code})", "detail": resp.text[:300]},
                          ensure_ascii=False)
    data = resp.json()
    return json.dumps(
        {
            "generation_id": data.get("generation_id"),
            "status": data.get("status", "pending"),
            "hint": "poll get_design_image_status（约 30s-6min）",
        },
        ensure_ascii=False,
    )


@tool("get_design_image_status")
def get_design_image_status_tool(generation_id: str) -> str:
    """查询独立生图状态。Returns JSON: status(pending/running/done/failed), image_url(可直接点开), detail。"""
    resp = qxhttp.request("GET", f"/assets/{generation_id}")
    if resp.status_code != 200:
        return json.dumps({"error": f"status failed ({resp.status_code})", "detail": resp.text[:300]},
                          ensure_ascii=False)
    a = resp.json()
    return json.dumps(
        {
            "generation_id": a.get("id"),
            "status": a.get("status"),
            "image_url": qxhttp.public_file_url(a.get("image_url")),
            "detail": (a.get("error") or "")[:300] or None,
        },
        ensure_ascii=False,
    )


@tool("list_design_images")
def list_design_images_tool(limit: int = 10) -> str:
    """列出最近的独立生图记录（含历史产物）。Returns JSON: images[{id,status,image_url,prompt,name}]。"""
    resp = qxhttp.request("GET", f"/assets?kind=image&limit={max(1, min(limit, 50))}")
    if resp.status_code != 200:
        return json.dumps({"error": f"list failed ({resp.status_code})"}, ensure_ascii=False)
    assets = resp.json().get("assets") or []
    return json.dumps(
        {
            "images": [
                {
                    "id": a.get("id"),
                    "status": a.get("status"),
                    "image_url": qxhttp.public_file_url(a.get("image_url")),
                    "prompt": (a.get("prompt") or "")[:80],
                    "name": a.get("name"),
                }
                for a in assets
            ]
        },
        ensure_ascii=False,
    )
