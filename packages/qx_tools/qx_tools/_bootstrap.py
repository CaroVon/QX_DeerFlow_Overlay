"""运行时引导：让 QX 源码树（agent-platform / amazon_matrix_mod 等）可被导入。

QX 的包（amazon_matrix_mod、agent_platform、agents）没有发布到 PyPI，
这里通过 QX_SOURCES_DIR 把源码平铺根目录加入 sys.path。
注意：不能把 QX_product_agent 根目录加进来——它的顶层包名是 ``app``，
会与 deer-flow backend 的 gateway 包 ``app`` 冲突。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_INJECTED = False


def qx_sources_dir() -> Path:
    return Path(os.environ.get("QX_SOURCES_DIR", Path.home() / "dev" / "agents"))


def default_output_dir() -> Path:
    """QX 产物落盘目录（QX_OUTPUT_DIR），默认在集成仓库 runtime/ 下。"""
    root = Path(__file__).resolve().parents[3]
    out = Path(os.environ.get("QX_OUTPUT_DIR", root / "runtime" / "outputs"))
    out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QX_OUTPUT_DIR", str(out))
    return out


def ensure_qx_mod() -> None:
    """幂等地把 QX 源码根注入 sys.path（延迟到工具首次调用，避免拖慢进程启动）。"""
    global _INJECTED
    if _INJECTED:
        return
    root = qx_sources_dir()
    if not (root / "amazon_matrix_mod").is_dir():
        raise ImportError(
            f"未找到 amazon_matrix_mod（期望位于 {root}）。"
            "请设置 QX_SOURCES_DIR 指向 QX 源码平铺根目录。"
        )
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    default_output_dir()
    _INJECTED = True
