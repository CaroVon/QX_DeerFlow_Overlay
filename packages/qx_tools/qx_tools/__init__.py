"""qx-tools：把 QX Product Studio 的能力封装为 DeerFlow 可挂载的工具。

在 deer-flow/config.yaml 的 tools: 段以 use: qx_tools.<module>:<tool> 引用，
模块级单例即工具实例（DeerFlow 的 resolve_variable 按实例解析）。
"""

__version__ = "0.1.0"
