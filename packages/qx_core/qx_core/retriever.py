"""
============================================================
混合检索引擎 (Hybrid Retriever)
—— 向量检索 (Chroma) + BM25 关键词检索 + Source Ranking RRF 融合
   支持 per-project 向量库隔离（根治多项目并发覆盖）
============================================================
"""
import os
import pickle
import logging
import warnings

import jieba
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class LocalEmbeddingModel:
    """Embedding 模型封装 —— 模型路径从配置读取，支持 HuggingFace 自动下载。"""

    def __init__(self):
        import os as _os
        model_name = _os.getenv(
            "EMBEDDING_MODEL_PATH",
            "BAAI/bge-small-zh-v1.5",
        )
        logger.info("加载 embedding 模型: %s (首次使用将从 HuggingFace 下载)...", model_name)
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts):
        return self.model.encode(texts).tolist()

    def embed_query(self, text):
        return self.model.encode(text).tolist()


# 保持模块级单例
embedding_model = LocalEmbeddingModel()


def jieba_tokenizer(text: str):
    """中文分词器——供 BM25 使用。"""
    return list(jieba.cut(text))


# ══════════════════════════════════════════════════════════════════
# Source Ranking Engine —— 信息源分级权重
# ══════════════════════════════════════════════════════════════════

def get_source_weight(url: str) -> float:
    """
    信息源分级与权重计算引擎 (Source Ranking Engine)。

    权重档位：
      T0 (1.5x): 权威来源——PDF 报告、政府、交易所、官方白皮书
      T1 (1.2x): 专业媒体——深度研报、商业分析
      T2 (1.0x): 普通新闻
      T3 (0.5x): UGC/自媒体——知乎、B站、微博等（重度降权）
    """
    if not url or url == "unknown":
        return 1.0  # 未知来源，不奖不惩

    # 本地上传资料享有 T0 级最高权重
    if url.startswith("local://"):
        return 1.5
    # Obsidian Vault 笔记（人工维护，权威性高）
    if url.startswith("obsidian://"):
        return 1.3
    # 领域经验包（LLM 压缩的可信经验）
    if url.startswith("experience://"):
        return 1.2
    # 图片分析文本（VL 提取，作为补充证据）
    if url.startswith("image://"):
        return 1.0

    url_lower = url.lower()

    # T0 级 (权重 1.5): 绝对权威
    if any(ext in url_lower for ext in [
        ".pdf", ".gov", "sse.com.cn", "szse.cn", "hkex.com.hk",
    ]):
        return 1.5

    # T1 级 (权重 1.2): 深度研报/专业商业媒体
    if any(domain in url_lower for domain in [
        "bloomberg", "36kr.com", "caixin.com", "xueqiu.com",
        "huxiu.com", "yicai.com",
    ]):
        return 1.2

    # T3 级 (权重 0.5): UGC 社区/自媒体
    if any(domain in url_lower for domain in [
        "zhihu.com", "bilibili.com", "weibo.com",
        "tieba.baidu.com", "xiaohongshu.com",
    ]):
        return 0.5

    # T2 级 (权重 1.0): 其他普通新闻网站
    return 1.0


# ══════════════════════════════════════════════════════════════════
# RRF 融合排序
# ══════════════════════════════════════════════════════════════════

def reciprocal_rank_fusion(
    vector_results: list,
    bm25_results: list,
    k: int = 60,
) -> list:
    """
    引入 Source Ranking 的加强版 RRF 算法。

    使用 (page_content + "|" + url) 作为唯一键，防止不同 URL
    引用同一段内容的文本被去重吃掉。
    """
    fused_scores: dict[str, float] = {}
    doc_map: dict[str, object] = {}

    # 处理向量检索结果
    for rank, doc in enumerate(vector_results, start=1):
        url = doc.metadata.get("url", "unknown")
        doc_key = doc.page_content + "|" + url
        doc_map[doc_key] = doc

        source_weight = get_source_weight(url)
        base_score = 1.0 / (rank + k)
        fused_scores[doc_key] = fused_scores.get(doc_key, 0.0) + (base_score * source_weight)

    # 处理 BM25 检索结果
    for rank, doc in enumerate(bm25_results, start=1):
        url = doc.metadata.get("url", "unknown")
        doc_key = doc.page_content + "|" + url
        doc_map[doc_key] = doc

        source_weight = get_source_weight(url)
        base_score = 1.0 / (rank + k)
        fused_scores[doc_key] = fused_scores.get(doc_key, 0.0) + (base_score * source_weight)

    # 根据叠加权重后的最终分倒序排列
    reranked = [
        doc_map[doc_key]
        for doc_key, _score in sorted(
            fused_scores.items(), key=lambda x: x[1], reverse=True
        )
    ]
    return reranked


# ══════════════════════════════════════════════════════════════════
# 公共检索接口
# ══════════════════════════════════════════════════════════════════

def _resolve_persist_dirs(project_id: str | None = None, scope: str | None = None):
    """
    解析向量库持久化目录路径。

    三层知识库统一目录规划（与 vector_store.build_vector_store 一致）：
      - 任务库: {base}/{project_id}
      - 全局库: {base}/global
      - 领域库: {base}/domain_{sanitized_tag}

    scope 优先于 project_id。
    """
    try:
        from app.core.config import get_settings
        settings = get_settings()
        chroma_base = settings.CHROMA_PERSIST_DIR
        bm25_base = settings.BM25_PERSIST_DIR
    except ImportError:
        # CLI 模式回退（backend 包不在 sys.path 上时）
        chroma_base = os.environ.get("CHROMA_PERSIST_DIR", "./chroma_db")
        bm25_base = os.environ.get("BM25_PERSIST_DIR", "./bm25_db")

    key: str | None = None
    if scope:
        import re
        key = re.sub(r"[^0-9a-zA-Z_\-.:\u4e00-\u9fff]", "_", scope)
    elif project_id:
        key = project_id
    else:
        warnings.warn(
            "retrieve() 未提供 project_id/scope——使用共享向量库目录。"
            "多项目并发时可能导致数据互相覆盖。"
            "请尽快在调用方传入 project_id。",
            FutureWarning,
            stacklevel=3,
        )
        chroma_dir = chroma_base
        bm25_dir = bm25_base
        return chroma_dir, bm25_dir

    chroma_dir = os.path.join(chroma_base, key)
    bm25_dir = os.path.join(bm25_base, key)
    return chroma_dir, bm25_dir


def retrieve(
    query: str,
    k: int = 5,
    project_id: str | None = None,
    scope: str | None = None,
) -> list:
    """
    对外暴露的统一混合检索接口。

    Args:
        query:      检索查询字符串
        k:          返回文档数量
        project_id: 项目 UUID 字符串（任务层 L2 库）。
        scope:      知识范围键（全局库 "global" / 领域库 "domain:{tag}"）。

    Returns:
        按 RRF 融合分数排序的 LangChain Document 列表（最多 k 个）。
    """
    chroma_dir, bm25_dir = _resolve_persist_dirs(project_id, scope)

    # ── 1. 向量检索 (Chroma) ────────────────────────────────
    vector_results: list = []
    if os.path.isdir(chroma_dir):
        try:
            db = Chroma(
                persist_directory=chroma_dir,
                embedding_function=embedding_model,
            )
            vector_retriever = db.as_retriever(search_kwargs={"k": k * 2})
            vector_results = vector_retriever.invoke(query)
        except Exception as e:
            logger.warning("Chroma 向量检索失败 (%s)，降级为空结果", e)
    else:
        logger.warning("Chroma 持久化目录不存在: %s，向量检索结果为空", chroma_dir)

    # ── 2. BM25 关键词检索 ──────────────────────────────────
    bm25_results: list = []
    bm25_path = os.path.join(bm25_dir, "docs.pkl")
    if os.path.isfile(bm25_path):
        try:
            with open(bm25_path, "rb") as f:
                docs = pickle.load(f)
            bm25_retriever = BM25Retriever.from_documents(
                docs, preprocess_func=jieba_tokenizer,
            )
            bm25_retriever.k = k * 2
            bm25_results = bm25_retriever.invoke(query)
        except Exception as e:
            logger.warning("BM25 语料加载失败 (%s)，降级为纯向量检索", e)
    else:
        logger.warning("BM25 语料文件不存在: %s", bm25_path)

    # ── 3. RRF 融合排序并截断 ──────────────────────────────
    final_results = reciprocal_rank_fusion(vector_results, bm25_results)
    return final_results[:k]


def _retrieve_from_scope(
    query: str,
    k: int,
    chroma_dir: str,
    bm25_dir: str,
) -> list:
    """在给定持久化目录上执行单库混合检索（向量 + BM25 + RRF）。"""
    # ── 1. 向量检索 (Chroma) ────────────────────────────────
    vector_results: list = []
    if os.path.isdir(chroma_dir):
        try:
            db = Chroma(
                persist_directory=chroma_dir,
                embedding_function=embedding_model,
            )
            vector_retriever = db.as_retriever(search_kwargs={"k": k * 2})
            vector_results = vector_retriever.invoke(query)
        except Exception as e:
            logger.warning("Chroma 向量检索失败 (%s)，降级为空结果", e)
    else:
        logger.debug("Chroma 持久化目录不存在: %s，向量检索结果为空", chroma_dir)

    # ── 2. BM25 关键词检索 ──────────────────────────────────
    bm25_results: list = []
    bm25_path = os.path.join(bm25_dir, "docs.pkl")
    if os.path.isfile(bm25_path):
        try:
            with open(bm25_path, "rb") as f:
                docs = pickle.load(f)
            bm25_retriever = BM25Retriever.from_documents(
                docs, preprocess_func=jieba_tokenizer,
            )
            bm25_retriever.k = k * 2
            bm25_results = bm25_retriever.invoke(query)
        except Exception as e:
            logger.warning("BM25 语料加载失败 (%s)，降级为纯向量检索", e)
    else:
        logger.debug("BM25 语料文件不存在: %s", bm25_path)

    return reciprocal_rank_fusion(vector_results, bm25_results)


def retrieve_scoped(
    query: str,
    scopes: list[tuple[str, str | None, float]],
    k: int = 8,
) -> list:
    """
    三层融合检索（任务 L2 / 领域 L1 / 全局 L0）。

    Args:
        query:  检索查询
        scopes: [(scope_key, project_id, weight), ...]，例如
                [("", pid, 1.0), ("domain:消费电子", None, 0.8), ("global", None, 0.6)]
                其中 scope_key 为空字符串表示任务库（用 project_id）。
        k:      最终返回条数

    Returns:
        跨层 RRF 融合（带层权重）排序后的文档列表。
    """
    fused_scores: dict[str, float] = {}
    doc_map: dict[str, object] = {}

    for scope_key, project_id, weight in scopes:
        chroma_dir, bm25_dir = _resolve_persist_dirs(project_id, scope_key or None)
        if not os.path.isdir(chroma_dir) and not os.path.isdir(bm25_dir):
            continue  # 该层无数据
        per_scope_k = max(2, k)
        results = _retrieve_from_scope(query, per_scope_k, chroma_dir, bm25_dir)
        layer = scope_key or ("task" if project_id else "shared")
        for doc in results:
            # 记录层级标记（供上层格式化时展示）
            doc.metadata = {**doc.metadata, "layer": layer}
        for rank, doc in enumerate(results, start=1):
            url = doc.metadata.get("url", "unknown")
            doc_key = doc.page_content + "|" + url
            doc_map[doc_key] = doc
            base_score = 1.0 / (rank + 60)
            fused_scores[doc_key] = fused_scores.get(doc_key, 0.0) + (
                base_score * weight * get_source_weight(url)
            )

    reranked = [
        doc_map[doc_key]
        for doc_key, _score in sorted(
            fused_scores.items(), key=lambda x: x[1], reverse=True
        )
    ]
    return reranked[:k]


# ══════════════════════════════════════════════════════════════════
# 自测入口
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        q = sys.argv[1]
        pid = sys.argv[2] if len(sys.argv) > 2 else None
    else:
        q = "Micro-OLED"
        pid = None

    results = retrieve(q, k=3, project_id=pid)
    print("\n========== HYBRID RETRIEVAL ==========\n")
    for r in results:
        print(r.page_content[:200])
        print("\n-----------------\n")
