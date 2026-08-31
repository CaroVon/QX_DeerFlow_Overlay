"""知识库工具：qx-core 三层检索（Chroma+BM25 混合）的 DeerFlow 工具封装。

持久化目录由环境变量控制（与 QX 同一套约定）：
- CHROMA_PERSIST_DIR / BM25_PERSIST_DIR：默认 qx-deerflow/runtime/ 下独立库；
  指向 QX backend/{chroma_db,bm25_db} 即可共享其已积累的知识资产。
- HF_ENDPOINT：bge-small-zh 嵌入模型下载镜像（沿用 QX 的镜像配置）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from langchain.tools import tool

logger = logging.getLogger(__name__)

_RUNTIME = Path(__file__).resolve().parents[3] / "runtime"
os.environ.setdefault("CHROMA_PERSIST_DIR", str(_RUNTIME / "chroma_db"))
os.environ.setdefault("BM25_PERSIST_DIR", str(_RUNTIME / "bm25_db"))


@tool
def knowledge_search_tool(query: str, k: int = 5, task_id: str = "") -> str:
    """检索 QX 三层知识库（向量 + BM25 混合，RRF 融合 + 来源域名加权）。

    知识库沉淀了历史产品研究的市场洞察、竞品情报与领域经验。做亚马逊/
    产品研究类任务时，先查这里再决定是否需要联网搜索。

    Args:
        query: 检索问题（中英文均可，中文语料为主）。
        k: 返回条数，默认 5。
        task_id: 可选的任务级库 ID（限定检索该任务沉淀的知识；
            不传则检索全局库）。

    Returns:
        JSON 数组：[{content, url, score}, ...]；空结果返回 []。
    """
    from qx_core import retrieve

    docs = retrieve(query=query, k=k, project_id=task_id or None, scope=None)
    results = []
    for d in docs:
        meta = getattr(d, "metadata", None) or {}
        results.append(
            {
                "content": str(getattr(d, "page_content", d))[:600],
                "url": meta.get("url"),
                "score": getattr(d, "metadata", {}).get("score"),
            }
        )
    return json.dumps(results, ensure_ascii=False, default=str)


@tool
def knowledge_ingest_tool(text: str, task_id: str = "", url: str = "") -> str:
    """把文本知识切片入库（Chroma + BM25 双写），供后续 knowledge_search_tool 检索。

    适用：把研究发现、会议结论、报告要点等沉淀为可检索资产。

    Args:
        text: 要入库的文本（自动切片）。
        task_id: 可选任务 ID（入任务级库；不传入全局库）。
        url: 可选来源 URL（作为元数据，参与来源域名权重）。

    Returns:
        JSON: {"chunks": 切片数, "scope": "task|global", "dir": 持久化目录}。
    """
    from qx_core import build_vector_store, chunk_text

    chunks = chunk_text(text)
    payload = [{"content": c, "url": url} for c in chunks if str(c).strip()]
    build_vector_store(payload, project_id=task_id or None)
    return json.dumps(
        {
            "chunks": len(payload),
            "scope": "task" if task_id else "global",
            "dir": os.environ.get("CHROMA_PERSIST_DIR"),
        },
        ensure_ascii=False,
    )
