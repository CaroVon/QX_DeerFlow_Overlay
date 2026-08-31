"""QX studio 管线的 MCP 工具服务。

DeerFlow 通过 extensions_config.json 以 stdio 拉起本模块：
    {"qx-studio": {"type": "stdio", "command": "<venv-python>",
                   "args": ["-m", "qx_mcp.server"]}}

工具契约（对齐 DeerFlow main 分支 task_toolsets 语义，升级 ≥2.1 后可声明式注册）：
    submit_studio_job(idea)            -> job_id
    get_studio_job_status(job_id)      -> 状态 + 进度节点 + 产物
    cancel_studio_job(job_id)          -> 取消
"""
from __future__ import annotations

import json
import logging
import os

import httpx
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("qx-mcp")

QX_API_BASE = os.environ.get("QX_API_BASE", "http://localhost:8000").rstrip("/")
QX_API_PREFIX = f"{QX_API_BASE}/api/v1"
# direct：绕过 QX FastAPI，直连 Celery broker + Postgres（Phase 2 v1）
# http：适配器模式（Phase 2 v0，默认）
QX_MCP_MODE = os.environ.get("QX_MCP_MODE", "http").lower()

mcp = FastMCP("qx-studio")

_TOKEN: str | None = None


def _client() -> httpx.Client:
    headers = {}
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    return httpx.Client(base_url=QX_API_PREFIX, headers=headers, timeout=60.0)


def _bootstrap_token(client: httpx.Client) -> str | None:
    """QX 开启 AUTH_ENABLED 时匿名拿 token（单用户工作区模式）。"""
    try:
        resp = client.post("/auth/bootstrap")
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("token") or data.get("access_token")
            if token:
                logger.info("QX auth: bootstrap token acquired")
                return token
    except Exception as exc:  # noqa: BLE001
        logger.warning("QX auth bootstrap failed: %s", exc)
    return None


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    global _TOKEN
    with _client() as client:
        resp = client.request(method, path, **kwargs)
        if resp.status_code == 401 and not _TOKEN:
            _TOKEN = _bootstrap_token(client)
            if _TOKEN:
                client.headers["Authorization"] = f"Bearer {_TOKEN}"
                resp = client.request(method, path, **kwargs)
        return resp


@mcp.tool()
def submit_studio_job(idea: str, auto_approve_gates: bool = False) -> str:
    """提交 QX AI Product Studio 任务：从一句话产品想法出发，自动完成
    亚马逊市场研究 → 竞品矩阵 → 策略/PRD → 设计 → 演示文稿 → PPT 交付。

    长任务（真实运行约 30-70 分钟），返回 job_id 后应轮询 get_studio_job_status。
    管线含人工审批门（资料审核），到达时会进入 waiting_approval 状态。

    Args:
        idea: 一句话产品想法（例："Build an AI fitness application for home workouts"）。
        auto_approve_gates: 自动模式——门到达时由本服务自动批准（agent 应在门到达时
            向用户播报资料摘要以保持透明）。默认 False（审核模式，等人工批准）。
    """
    if QX_MCP_MODE == "direct":
        from qx_mcp import _direct

        result = _direct.submit_direct(idea)
    else:
        resp = _request("POST", "/product/create", json={"idea": idea})
        if resp.status_code not in (200, 201):
            return json.dumps({"error": f"submit failed ({resp.status_code})", "detail": resp.text[:400]})
        data = resp.json()
        product = data if "product_id" in data or "id" in data else (data.get("product") or {})
        result = {
            "job_id": product.get("product_id") or product.get("id"),
            "status": product.get("status"),
            "idea": product.get("idea", idea),
        }
    job_id = result.get("job_id")
    if job_id and auto_approve_gates:
        _start_auto_approver(job_id)
        result["auto_approve_gates"] = True
    result.setdefault("hint", "long-running; poll get_studio_job_status")
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def get_studio_job_status(job_id: str) -> str:
    """查询 QX studio 任务状态：当前节点、进度日志摘要、审批门与产物清单。

    Returns JSON: status(running/waiting_approval/completed/failed/cancelled)、
    paused_node(等待审批的节点名，waiting_approval 时必看)、node_status(各节点完成情况)、
    gate_report、critic_score、error_message、progress_tail(最近进度日志)。
    status=waiting_approval 时应调用 approve_studio_gate（带 paused_node）。
    """
    if QX_MCP_MODE == "direct":
        from qx_mcp import _direct

        return json.dumps(_direct.status_direct(job_id), ensure_ascii=False, default=str)
    resp = _request("GET", f"/product/{job_id}")
    if resp.status_code != 200:
        return json.dumps({"error": f"status failed ({resp.status_code})", "detail": resp.text[:400]})
    data = resp.json()
    logs_resp = _request("GET", f"/product/{job_id}/logs")
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
        ensure_ascii=False,
        default=str,
    )


@mcp.tool()
def approve_studio_gate(job_id: str, node: str = "", selected_urls: list[str] | None = None) -> str:
    """批准 QX studio 的人工审批门，让流水线继续执行。

    门出现在 status=waiting_approval 时（get_studio_job_status 的 paused_node 字段）。
    - source_gathering 门（资料审核）：默认全部采纳；也可用 selected_urls 指定保留的资料 URL 子集（至少一条）。
    - presentation/大纲门：直接批准即可。

    Args:
        job_id: 任务 ID。
        node: 等待审批的节点名；留空则自动从任务状态检测。
        selected_urls: 可选，source_gathering 门勾选保留的资料 URL 列表。
    """
    if not node:
        resp = _request("GET", f"/product/{job_id}")
        if resp.status_code == 200:
            err = resp.json().get("error_message") or ""
            if "节点:" in err:
                node = err.split("节点:", 1)[1].strip()
    if not node:
        return json.dumps({"error": "无法确定等待审批的节点，请在 node 参数中显式提供"}, ensure_ascii=False)
    body: dict = {"node": node}
    if selected_urls is not None:
        body["selected_urls"] = selected_urls
    resp = _request("POST", f"/product/{job_id}/approve-node", json=body)
    return json.dumps(
        {"job_id": job_id, "node": node, "http": resp.status_code, "detail": resp.text[:300]},
        ensure_ascii=False,
    )


@mcp.tool()
def reject_studio_gate(job_id: str, feedback: str, node: str = "") -> str:
    """否决 QX studio 的审批门（任务将标记失败，反馈供后续 regenerate 使用）。

    Args:
        job_id: 任务 ID。
        feedback: 否决原因/修改意见。
        node: 等待审批的节点名；留空则自动检测。
    """
    if not node:
        resp = _request("GET", f"/product/{job_id}")
        if resp.status_code == 200:
            err = resp.json().get("error_message") or ""
            if "节点:" in err:
                node = err.split("节点:", 1)[1].strip()
    if not node:
        return json.dumps({"error": "无法确定等待审批的节点，请在 node 参数中显式提供"}, ensure_ascii=False)
    resp = _request("POST", f"/product/{job_id}/reject-node", json={"node": node, "feedback": feedback})
    return json.dumps(
        {"job_id": job_id, "node": node, "http": resp.status_code, "detail": resp.text[:300]},
        ensure_ascii=False,
    )


@mcp.tool()
def cancel_studio_job(job_id: str) -> str:
    """取消一个运行中的 QX studio 任务。"""
    if QX_MCP_MODE == "direct":
        from qx_mcp import _direct

        return json.dumps(_direct.cancel_direct(job_id), ensure_ascii=False, default=str)
    resp = _request("POST", f"/product/{job_id}/cancel")
    return json.dumps(
        {"job_id": job_id, "cancel_http": resp.status_code, "detail": resp.text[:200]},
        ensure_ascii=False,
    )


def main() -> None:
    logger.info("qx-mcp starting (QX_API_BASE=%s)", QX_API_BASE)
    mcp.run()


# ─── 自动过门（auto_approve_gates）─────────────────────────────
_AUTO_JOBS: dict[str, bool] = {}


def _start_auto_approver(job_id: str) -> None:
    """后台线程：轮询任务，到达 waiting_approval 时自动批准（每门只批一次）。"""
    import threading
    import time as _time

    if _AUTO_JOBS.get(job_id):
        return
    _AUTO_JOBS[job_id] = True

    def _loop() -> None:
        approved: set[str] = set()
        deadline = _time.time() + 120 * 60  # 2h 上限
        while _time.time() < deadline and _AUTO_JOBS.get(job_id):
            _time.sleep(15)
            try:
                if QX_MCP_MODE == "direct":
                    from qx_mcp import _direct

                    s = _direct.status_direct(job_id)
                else:
                    resp = _request("GET", f"/product/{job_id}")
                    if resp.status_code != 200:
                        continue
                    s = resp.json()
                    err = s.get("error_message") or ""
                    if s.get("status") == "waiting_approval" and "节点:" in err:
                        s["paused_node"] = err.split("节点:", 1)[1].strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("auto-approver poll error: %s", exc)
                continue
            status = s.get("status")
            node = s.get("paused_node")
            if status == "waiting_approval" and node and node not in approved:
                logger.info("[auto-approve] job=%s gate=%s → approving", job_id, node)
                approve_studio_gate(job_id, node)
                approved.add(node)
            if status in {"completed", "failed"}:
                break
        _AUTO_JOBS.pop(job_id, None)

    threading.Thread(target=_loop, daemon=True, name=f"qx-auto-{job_id[:8]}").start()


# ─── 设计生图（异步 submit/status）─────────────────────────────
_DESIGN_JOBS: dict[str, dict] = {}


@mcp.tool()
def generate_design_image(prompt: str, product_id: str = "") -> str:
    """用配置好的生图后端（MiniMax/Seedance，QX IMAGE_BACKEND）生成产品/概念图。

    异步任务：返回 generation_id 后轮询 get_design_image_status（约 30s-6min）。
    prompt 建议由产品关键词组合而成（设计/功能/外观/人群/场景）。

    Args:
        prompt: 生图提示词（产品描述+风格，中英文均可）。
        product_id: 可选，关联的 QX 任务 ID（无则独立生成）。
    """
    import threading
    import uuid as _uuid

    gen_id = _uuid.uuid4().hex[:12]
    _DESIGN_JOBS[gen_id] = {"status": "running", "prompt": prompt, "product_id": product_id}

    def _run() -> None:
        try:
            # 独立生成走 QX design-studio 的通用生图通道（硅基/MiniMax 脚本）
            resp = _request("POST", f"/design-studio/{product_id or 'standalone'}/items",
                            json={"kind": "standalone", "name": prompt[:40], "text": prompt})
            if resp.status_code not in (200, 201):
                _DESIGN_JOBS[gen_id].update(status="failed", detail=resp.text[:300])
                return
            item_id = resp.json().get("id")
            gen_resp = _request("POST", f"/design-studio/{product_id or 'standalone'}/items/{item_id}/generate")
            if gen_resp.status_code == 200:
                data = gen_resp.json()
                _DESIGN_JOBS[gen_id].update(status="done", item_id=item_id, **{
                    k: data.get(k) for k in ("image", "image_url", "url")})
            else:
                _DESIGN_JOBS[gen_id].update(status="failed", detail=gen_resp.text[:300])
        except Exception as exc:  # noqa: BLE001
            _DESIGN_JOBS[gen_id].update(status="failed", detail=str(exc)[:300])

    threading.Thread(target=_run, daemon=True, name=f"qx-img-{gen_id}").start()
    return json.dumps(
        {"generation_id": gen_id, "status": "running", "hint": "poll get_design_image_status"},
        ensure_ascii=False,
    )


@mcp.tool()
def get_design_image_status(generation_id: str) -> str:
    """查询生图任务状态。Returns JSON: status(running/done/failed), image(url), detail。"""
    job = _DESIGN_JOBS.get(generation_id)
    if not job:
        return json.dumps({"error": "unknown generation_id"}, ensure_ascii=False)
    return json.dumps(job, ensure_ascii=False, default=str)


# ─── PPT 单页返工 ────────────────────────────────────────────
@mcp.tool()
def rework_ppt_page(product_id: str, page_number: int, feedback: str = "") -> str:
    """重做 QX 任务 PPT 的某一页（LLM 重创作该页并重新导出 PPTX）。

    Args:
        product_id: QX 任务 ID。
        page_number: 页码（人类口径，P1=第 1 页；服务端自动换算 0 基索引）。
        feedback: 可选修改意见（≤200 字）。
    """
    body = {"page_index": max(0, page_number - 1), "feedback": feedback or "用户标记此页需要改进"}
    resp = _request("POST", f"/product/{product_id}/ppt-rework", json=body)
    return json.dumps(
        {"product_id": product_id, "page_number": page_number, "http": resp.status_code, "detail": resp.text[:300]},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
