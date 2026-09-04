"""亚马逊竞品工具：封装 amazon_matrix_mod 的两个入口。

- collect_amazon_data_tool → run_mod.collect_amazon_data（轻量采集摘要）
- competitor_matrix_tool  → run_mod.run_pipeline（完整 MOD 分析管线）

真实数据源为 Rainforest（按 credits 计费），mock 数据源可离线演示。
"""
from __future__ import annotations

import json
import logging
import os

from langchain.tools import tool

from ._bootstrap import ensure_qx_mod

logger = logging.getLogger(__name__)


def _source_or_default(source: str) -> str:
    return source or os.environ.get("QX_MOD_SOURCE", "rainforest")


def _rainforest_quota_check(estimated: int) -> str | None:
    """真实采集前校验 rainforest 余额；不足返回友好错误（JSON 字符串），通过返回 None。"""
    import json as _json

    from . import qxhttp

    resp = qxhttp.request("GET", "/credits/balance")
    if resp.status_code != 200:
        return None  # 计费不可用不阻断（降级放行）
    data = resp.json()
    if data.get("unlimited"):
        return None  # 管理员无限额
    left = (data.get("balances") or {}).get("rainforest")
    if left is None or left >= estimated:
        return None
    return _json.dumps(
        {"error": f"Rainforest 采集额度不足（剩 {left}，本次约需 {estimated} credits）：请让用户联系管理员补充，或改用 source=mock 演示"},
        ensure_ascii=False,
    )


def _rainforest_consume(actual: int, reason: str) -> None:
    """真实采集后按实际 credits 入账（失败仅记日志，不阻断结果返回）。"""
    import logging as _logging

    from . import qxhttp

    try:
        qxhttp.request(
            "POST", "/credits/consume",
            json={"kind": "rainforest", "amount": actual, "reason": reason, "enforce": False},
        )
    except Exception as exc:  # noqa: BLE001
        _logging.getLogger(__name__).warning("rainforest 计量失败: %s", exc)


@tool
def collect_amazon_data_tool(
    keyword: str,
    top_n: int = 20,
    marketplace: str = "amazon.com",
    source: str = "",
    product_id: str = "",
) -> str:
    """采集亚马逊竞品数据并返回轻量市场摘要（JSON）。

    适用场景：快速了解一个关键词/品类下的竞品格局——价格带、均价、评分、
    评论量、四区分布（premium/value/core/risk）、Top ASIN 榜。

    Args:
        keyword: 亚马逊搜索关键词（英文效果最佳，如 "wireless mouse"）。
        top_n: 采集竞品数量，默认 20。
        marketplace: 站点，默认 "amazon.com"。
        source: 数据源。"rainforest" 为真实数据（消耗 API credits），
            "mock" 为离线演示数据。留空取环境变量 QX_MOD_SOURCE。
        product_id: 可选，QX Studio 任务 ID，用于把产物归档到对应任务目录。

    Returns:
        JSON 字符串：n_products/credits/price_range/rating_avg/reviews_count/
        zone_counts/top_asins/data_dir 等；data_dir 可供后续矩阵分析复用（0 credit 回放）。
    """
    ensure_qx_mod()
    from amazon_matrix_mod.run_mod import collect_amazon_data

    src = _source_or_default(source)
    if src == "rainforest":
        # 计量（W3c）：预检余额（search 1 + 每竞品 1），采集后按实际 credits 入账
        err = _rainforest_quota_check(1 + max(1, top_n))
        if err:
            return err
    summary, _payload = collect_amazon_data(
        keyword=keyword,
        top_n=top_n,
        marketplace=marketplace,
        source=src,
        product_id=product_id or None,
    )
    if src == "rainforest" and summary.get("credits"):
        _rainforest_consume(int(summary["credits"]), f"采集 {keyword}")
    return json.dumps(summary, ensure_ascii=False, default=str)


@tool
def competitor_matrix_tool(
    keyword: str,
    top_n: int = 50,
    our_asin: str = "",
    marketplace: str = "amazon.com",
    source: str = "",
    product_id: str = "",
    skip_llm: bool = False,
    with_visuals: bool = False,
    theme_id: str = "",
) -> str:
    """生成完整的亚马逊竞品矩阵 MOD 分析报告（分区、指标、14 章洞察，可选图表与 PPTX）。

    耗时数分钟（真实源 + LLM 解读时更久）。若已有 collect_amazon_data_tool 的
    采集归档（data_dir），本工具会用 reuse 回放，不重复消耗 credits。

    Args:
        keyword: 亚马逊搜索关键词。
        top_n: 竞品数量，默认 50。
        our_asin: 可选，我方 ASIN（用于标注自身定位）。
        marketplace: 站点，默认 "amazon.com"。
        source: 数据源，"rainforest"（真实，计费）或 "mock"（离线）。留空取 QX_MOD_SOURCE。
        product_id: 可选，QX Studio 任务 ID（产物归档）。
        skip_llm: 跳过 LLM 章节解读（纯数据管线，更快更省 token）。
        with_visuals: 生成 SVG 光栅化图表与 PPTX（需要 Playwright/Chromium 环境）。
        theme_id: PPT 主题 ID（with_visuals 时生效）。

    Returns:
        JSON 字符串：zone_summary/cost_estimate/artifacts_paths（含 pptx、
        matrix_chart_png 路径）等；产物文件落在 QX_OUTPUT_DIR 下。
    """
    ensure_qx_mod()
    from amazon_matrix_mod.run_mod import run_pipeline

    src = _source_or_default(source)
    if src == "rainforest":
        err = _rainforest_quota_check(1 + max(1, top_n))
        if err:
            return err
    result = run_pipeline(
        keyword=keyword,
        top_n=top_n,
        our_asin=our_asin or None,
        marketplace=marketplace,
        source=src,
        product_id=product_id or None,
        skip_llm=skip_llm,
        with_visuals=with_visuals,
        theme_id=theme_id or None,
    )
    if src == "rainforest":
        actual = (result.get("cost_estimate") or {}).get("credits") or 0
        if actual > 0:
            _rainforest_consume(int(actual), f"MOD 矩阵 {keyword}")
    return json.dumps(result, ensure_ascii=False, default=str)
