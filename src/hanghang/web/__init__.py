"""Web 可视化聚合面板（L2 人类端点入口）
提供页面入口，聚合展示行业单元、路由能力、指标等，供人工入口/出口复核使用。
"""
from .server import HanghangHTTPServer, serve_forever

__all__ = ["HanghangHTTPServer", "serve_forever"]
