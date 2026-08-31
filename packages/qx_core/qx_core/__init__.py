"""qx-core：QX Product Studio 必迁 v1 子集（知识检索层）。

来源：QX_product_agent/app/rag/（import 前缀 app.rag.* → qx_core.*）。
与 QX 共享同一套持久化目录约定（CHROMA_PERSIST_DIR / BM25_PERSIST_DIR 环境变量），
指向 QX 现有库时可直接检索已积累的知识资产。

模块：
- chunker        文本切片
- vector_store   Chroma + BM25 持久化（bge-small-zh 嵌入）
- retriever      三层混合检索（L2 任务 / L1 领域 / L0 全局，RRF 融合 + 域名权重）
- rag_pipeline   scope 构建 + retrieve_context（tavily/firecrawl 已剥离为可选）
- local_parser   本地 PDF/文本解析
"""

from qx_core.chunker import chunk_text
from qx_core.local_parser import parse_local_pdf, parse_local_file
from qx_core.rag_pipeline import build_scopes, retrieve_context
from qx_core.retriever import retrieve, retrieve_scoped
from qx_core.vector_store import build_vector_store

__all__ = [
    "chunk_text",
    "parse_local_file",
    "parse_local_pdf",
    "build_scopes",
    "retrieve_context",
    "retrieve",
    "retrieve_scoped",
    "build_vector_store",
]
