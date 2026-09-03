"""QX 流水线编排工具：提交/状态/审批/取消/暂停/续跑/删除/局部重跑/资料清单。

替代 qx_mcp MCP 服务器（stdio 子进程）：作为 config.yaml 声明式工具运行在
gateway 进程内，受 tool_groups 按 agent 隔离——qx-designer 等专业 agent
不再能看到全流程编排工具（F1：agent 边界修齐）。
"""
from __future__ import annotations

import json
import logging
import threading
import time as _time

from langchain.tools import tool

from . import qxhttp

logger = logging.getLogger(__name__)


def _paused_node(job_id: str) -> str | None:
    resp = qxhttp.request("GET", f"/product/{job_id}")
    if resp.status_code != 200:
        return None
    err = resp.json().get("error_message") or ""
    if "节点:" in err:
        return err.split("节点:", 1)[1].strip() or None
    return None


@tool("submit_studio_job")
def submit_studio_job_tool(idea: str, auto_approve_gates: bool = False) -> str:
    """提交 QX AI Product Studio 任务：从一句话产品想法出发，自动完成
    亚马逊市场研究 → 竞品矩阵 → 策略/PRD → 设计 → 演示文稿 → PPT 交付。

    长任务（真实运行约 30-70 分钟），返回 job_id 后应轮询 get_studio_job_status。
    管线含人工审批门（资料审核），到达时会进入 waiting_approval 状态。

    Args:
        idea: 一句话产品想法（例："Build an AI fitness application for home workouts"）。
        auto_approve_gates: 自动模式——门到达时自动批准（agent 仍应在门到达时向用户
            播报资料摘要以保持透明）。默认 False（审核模式，等人工批准）。
    """
    resp = qxhttp.request("POST", "/product/create", json={"idea": idea})
    if resp.status_code not in (200, 201):
        return json.dumps({"error": f"submit failed ({resp.status_code})", "detail": resp.text[:400]},
                          ensure_ascii=False)
    data = resp.json()
    result = {
        "job_id": data.get("product_id") or data.get("id"),
        "status": data.get("status"),
        "idea": data.get("idea", idea),
    }
    if result["job_id"] and auto_approve_gates:
        _start_auto_approver(result["job_id"])
        result["auto_approve_gates"] = True
    result.setdefault("hint", "long-running; poll get_studio_job_status")
    return json.dumps(result, ensure_ascii=False, default=str)


@tool("get_studio_job_status")
def get_studio_job_status_tool(job_id: str) -> str:
    """查询 QX studio 任务状态：当前节点、进度日志摘要、审批门与产物清单。

    Returns JSON: status(running/waiting_approval/completed/failed/cancelled)、
    paused_node(等待审批的节点名，waiting_approval 时必看)、node_status(各节点完成情况)、
    gate_report、critic_score、error_message、progress_tail(最近进度日志)。
    status=waiting_approval 时应调用 approve_studio_gate（带 paused_node）。
    """
    resp = qxhttp.request("GET", f"/product/{job_id}")
    if resp.status_code != 200:
        return json.dumps({"error": f"status failed ({resp.status_code})", "detail": resp.text[:400]},
                          ensure_ascii=False)
    data = resp.json()
    logs_resp = qxhttp.request("GET", f"/product/{job_id}/logs")
    progress_tail: list = []
    if logs_resp.status_code == 200:
        progress_tail = (logs_resp.json().get("logs") or [])[-5:]
    err = data.get("error_message") or ""
    paused_node = None
    if data.get("status") == "waiting_approval" and "节点:" in err:
        paused_node = err.split("节点:", 1)[1].strip() or None
    return json.dumps(
        {
            "job_id": data.get("product_id", job_id),
            "status": data.get("status"),
            "paused_node": paused_node,
            "node_status": data.get("node_status"),
            "gate_report": data.get("gate_report"),
            "critic_score": data.get("critic_score"),
            "error_message": data.get("error_message"),
            "progress_tail": progress_tail,
        },
        ensure_ascii=False, default=str,
    )


@tool("approve_studio_gate")
def approve_studio_gate_tool(job_id: str, node: str = "", selected_urls: list[str] | None = None) -> str:
    """批准 QX studio 的人工审批门，让流水线继续执行。

    门出现在 status=waiting_approval 时（get_studio_job_status 的 paused_node 字段）。
    - source_gathering 门（资料审核）：默认全部采纳；也可用 selected_urls 指定保留的资料 URL 子集（至少一条）。
    - presentation/大纲门：直接批准即可。

    Args:
        job_id: 任务 ID。
        node: 等待审批的节点名；留空则自动从任务状态检测。
        selected_urls: 可选，source_gathering 门勾选保留的资料 URL 列表。
    """
    node = node or _paused_node(job_id) or ""
    if not node:
        return json.dumps({"error": "无法确定等待审批的节点，请在 node 参数中显式提供"}, ensure_ascii=False)
    body: dict = {"node": node}
    if selected_urls is not None:
        body["selected_urls"] = selected_urls
    resp = qxhttp.request("POST", f"/product/{job_id}/approve-node", json=body)
    return json.dumps({"job_id": job_id, "node": node, "http": resp.status_code, "detail": resp.text[:300]},
                      ensure_ascii=False)


@tool("reject_studio_gate")
def reject_studio_gate_tool(job_id: str, feedback: str, node: str = "") -> str:
    """否决 QX studio 的审批门（任务将标记失败，反馈供后续 regenerate 使用）。

    Args:
        job_id: 任务 ID。
        feedback: 否决原因/修改意见。
        node: 等待审批的节点名；留空则自动检测。
    """
    node = node or _paused_node(job_id) or ""
    if not node:
        return json.dumps({"error": "无法确定等待审批的节点，请在 node 参数中显式提供"}, ensure_ascii=False)
    resp = qxhttp.request("POST", f"/product/{job_id}/reject-node", json={"node": node, "feedback": feedback})
    return json.dumps({"job_id": job_id, "node": node, "http": resp.status_code, "detail": resp.text[:300]},
                      ensure_ascii=False)


@tool("cancel_studio_job")
def cancel_studio_job_tool(job_id: str) -> str:
    """取消一个运行中的 QX studio 任务（终态=cancelled，与失败区分）。"""
    resp = qxhttp.request("POST", f"/product/{job_id}/cancel")
    return json.dumps({"job_id": job_id, "cancel_http": resp.status_code, "detail": resp.text[:200]},
                      ensure_ascii=False)


@tool("list_collected_sources")
def list_collected_sources_tool(job_id: str) -> str:
    """列出任务已采集的资料明细（资料审核门/研究中）：Tavily 来源清单（标题/URL/权重摘要）
    + 亚马逊真实数据摘要（价格带/评分/Top ASIN/分区）。用户想"看看采集到了什么"时调用。"""
    resp = qxhttp.request("GET", f"/product/{job_id}/sources")
    if resp.status_code != 200:
        return json.dumps({"error": f"sources failed ({resp.status_code})"}, ensure_ascii=False)
    d = resp.json()
    return json.dumps(
        {
            "sources": [
                {"title": s.get("title"), "url": s.get("url"),
                 "weight": s.get("weight_label"), "summary": (s.get("content") or "")[:120]}
                for s in (d.get("sources") or [])
            ],
            "amazon_summary": d.get("amazon"),
        },
        ensure_ascii=False, default=str,
    )


@tool("pause_studio_job")
def pause_studio_job_tool(job_id: str) -> str:
    """暂停运行中的 QX studio 任务（当前节点完成后停住，可 resume 续跑）。"""
    resp = qxhttp.request("POST", f"/product/{job_id}/pause")
    return json.dumps({"job_id": job_id, "http": resp.status_code, "detail": resp.text[:200]}, ensure_ascii=False)


@tool("resume_studio_job")
def resume_studio_job_tool(job_id: str) -> str:
    """续跑已暂停的 QX studio 任务。"""
    resp = qxhttp.request("POST", f"/product/{job_id}/resume")
    return json.dumps({"job_id": job_id, "http": resp.status_code, "detail": resp.text[:200]}, ensure_ascii=False)


@tool("delete_studio_job")
def delete_studio_job_tool(job_id: str) -> str:
    """删除 QX studio 任务记录（软删：列表不再显示，产物文件保留）。"""
    resp = qxhttp.request("DELETE", f"/product/{job_id}")
    return json.dumps({"job_id": job_id, "http": resp.status_code, "detail": resp.text[:200]}, ensure_ascii=False)


@tool("regenerate_studio_asset")
def regenerate_studio_asset_tool(product_id: str, asset: str, instruction: str = "") -> str:
    """重新生成任务的某个资产（局部重跑，不走全流程）。

    asset ∈ research / competitor_matrix / competitor_analysis / strategy / design / presentation；
    instruction 为修改意见（可选）。competitor_matrix 重跑时会自动刷新关键词（除非用户编辑过）。
    """
    resp = qxhttp.request("POST", f"/product/{product_id}/regenerate",
                          json={"asset": asset, "instruction": instruction})
    return json.dumps({"product_id": product_id, "asset": asset, "http": resp.status_code,
                       "detail": resp.text[:300]}, ensure_ascii=False)


# ─── 自动过门（auto_approve_gates）─────────────────────────────
_AUTO_JOBS: dict[str, bool] = {}


def _start_auto_approver(job_id: str) -> None:
    """后台线程：轮询任务，到达 waiting_approval 时自动批准（每门只批一次）。"""
    if _AUTO_JOBS.get(job_id):
        return
    _AUTO_JOBS[job_id] = True

    def _loop() -> None:
        approved: set[str] = set()
        deadline = _time.time() + 120 * 60  # 2h 上限
        while _time.time() < deadline and _AUTO_JOBS.get(job_id):
            _time.sleep(15)
            try:
                resp = qxhttp.request("GET", f"/product/{job_id}")
                if resp.status_code != 200:
                    continue
                s = resp.json()
                err = s.get("error_message") or ""
                node = None
                if s.get("status") == "waiting_approval" and "节点:" in err:
                    node = err.split("节点:", 1)[1].strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("auto-approver poll error: %s", exc)
                continue
            status = s.get("status")
            if status == "waiting_approval" and node and node not in approved:
                logger.info("[auto-approve] job=%s gate=%s → approving", job_id, node)
                approve_studio_gate_tool.invoke({"job_id": job_id, "node": node})
                approved.add(node)
            if status in {"completed", "failed", "cancelled"}:
                break
        _AUTO_JOBS.pop(job_id, None)

    threading.Thread(target=_loop, daemon=True, name=f"qx-auto-{job_id[:8]}").start()
