"""
============================================================
RAG Pipeline —— 知识库构建 + 三层上下文检索（任务/领域/全局）
============================================================
"""
import json
import logging

# tavily/firecrawl 为可选依赖（仅 build_knowledge_base 的 v1 入库路径使用）
from qx_core.chunker import chunk_text
from qx_core.vector_store import build_vector_store
from qx_core.retriever import retrieve, retrieve_scoped

logger = logging.getLogger(__name__)


def build_knowledge_base(query: str, project_id: str | None = None):
    """
    搜索 + 爬取 + 切片 + 向量化，构建项目知识库。

    Args:
        query:      搜索主题
        project_id: 项目 UUID（用于 per-project 向量库隔离）
    """
    try:
        from app.search.tavily_search import tavily_search
        from app.crawler.firecrawl_crawler import crawl_url
    except ImportError as exc:
        raise RuntimeError(
            "build_knowledge_base 需要 QX 搜索栈（tavily/firecrawl）；"
            "qx-core 场景请改用 ingest_knowledge 入库或 DeerFlow 自带 web_search 工具"
        ) from exc
    search_results = tavily_search(query)
    results = search_results.get("results", [])

    all_chunks_with_meta: list[dict] = []

    for item in results[:3]:
        url = item.get("url")
        if not url:
            continue

        logger.info("爬取: %s", url)
        try:
            crawl_result = crawl_url(url)
            markdown = getattr(crawl_result, "markdown", "")

            if markdown:
                chunks = chunk_text(markdown)
                for chunk in chunks:
                    all_chunks_with_meta.append({
                        "content": chunk,
                        "url": url,
                    })
                logger.info("  ✓ %d chunks from %s", len(chunks), url)

        except Exception as e:
            logger.error("爬取失败 %s: %s", url, e)

    build_vector_store(all_chunks_with_meta, project_id=project_id)
    logger.info("知识库构建完成: %d 个切片 (project=%s)",
                len(all_chunks_with_meta), project_id or "(共享)")


def _get_scope_weights() -> dict[str, float]:
    """读取三层融合权重配置（task/domain/global），失败回退默认。"""
    try:
        from app.core.config import get_settings
        raw = get_settings().RETRIEVE_SCOPE_WEIGHTS
        weights = json.loads(raw or "{}")
        return {
            "task": float(weights.get("task", 1.0)),
            "domain": float(weights.get("domain", 0.8)),
            "global": float(weights.get("global", 0.6)),
        }
    except Exception:  # noqa: BLE001
        return {"task": 1.0, "domain": 0.8, "global": 0.6}


def _get_project_domain_tags(project_id: str) -> list[str]:
    """读取项目的领域标签（用于 L1 领域库检索）。"""
    try:
        from app.repositories import ProjectRepo
        project = ProjectRepo().get_project(project_id)
        if project.domain_tags:
            return json.loads(project.domain_tags)
    except Exception as e:  # noqa: BLE001
        logger.debug("领域标签读取失败: %s", e)
    return []


def build_scopes(
    project_id: str | None,
    domain_tags: list[str] | None = None,
) -> list[tuple[str, str | None, float]]:
    """
    构建三层检索范围列表。

    Returns:
        [(scope_key, project_id, weight), ...]
        scope_key 为空字符串 = 任务库（用 project_id）
    """
    weights = _get_scope_weights()
    scopes: list[tuple[str, str | None, float]] = []

    if project_id:
        scopes.append(("", project_id, weights["task"]))

    for tag in (domain_tags or [])[:3]:
        scopes.append((f"domain:{tag}", None, weights["domain"]))
    if domain_tags:
        # 兜底通用领域库（经验包 general 归档）
        scopes.append(("domain:general", None, weights["domain"] * 0.5))

    scopes.append(("global", None, weights["global"]))
    return scopes


def retrieve_context(
    query: str,
    k: int = 5,
    project_id: str | None = None,
    use_global: bool = True,
) -> str:
    """
    三层融合检索并格式化为 LLM 可消费的上下文块。

    Args:
        query:       检索查询字符串
        k:           总返回文档数量
        project_id:  项目 UUID（任务库键；为空时仅检索全局库）
        use_global:  是否包含全局库（默认 True）

    Returns:
        格式化的上下文字符串（含来源 URL 与层级标记）。
    """
    scopes = build_scopes(
        project_id,
        _get_project_domain_tags(project_id) if project_id else None,
    )
    if not use_global:
        scopes = [s for s in scopes if s[0] != "global"]

    results = retrieve_scoped(query, scopes, k=k) if scopes else []
    context_parts: list[str] = []

    for idx, r in enumerate(results, start=1):
        source_url = r.metadata.get("url", "unknown")
        layer = r.metadata.get("layer", "")
        layer_tag = f" [{layer}]" if layer else ""
        context_parts.append(
            f"[Chunk {idx}{layer_tag} | 来源: {source_url}]\n\n{r.page_content}\n"
        )

    return "\n".join(context_parts)


# 兼容旧行为：单库检索（编辑器/报告撰写仍可显式只查任务库）
def retrieve_task_context(query: str, k: int = 5, project_id: str | None = None) -> str:
    """仅检索任务级知识库（L2），返回格式化上下文。"""
    if not project_id:
        return ""
    results = retrieve(query, k=k, project_id=project_id)
    context_parts: list[str] = []
    for idx, r in enumerate(results, start=1):
        source_url = r.metadata.get("url", "unknown")
        context_parts.append(
            f"[Chunk {idx} | 来源: {source_url}]\n\n{r.page_content}\n"
        )
    return "\n".join(context_parts)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        topic = sys.argv[1]
        pid = sys.argv[2] if len(sys.argv) > 2 else None
    else:
        topic = "AI眼镜行业"
        pid = None

    print("========== 1. 构建知识库 ==========")
    build_knowledge_base(topic, project_id=pid)

    print("\n========== 2. 混合检索测试 ==========")
    ctx = retrieve_context("AI眼镜市场规模与竞争格局", k=3, project_id=pid)
    print(ctx)
