"""行行出状元 · 通用能力层 Web 可视化聚合面板

纯 Python 标准库实现的轻量级 HTTP 服务。
不引入额外第三方依赖（仅依赖 pyyaml，已为本仓库核心依赖）。

提供以下页面/API：
- GET /                     — 主控制台页面（单页，聚合展示行业单元+路由能力）
- GET /api/units            — 全部行业单元总览
- GET /api/route?text=...   — 意图路由调用（M1）
- GET /api/search?kw=..&mode=.. — 跨行业能力索引搜索（M8）
- GET /api/index            — 全量能力索引
- GET /api/metrics          — 运行指标（M7）
- GET /api/handoffs         — 待处理交接卡（M5）
- GET /api/prefixes         — 稳定前缀档案（M3）
- POST /api/route           — 意图路由调用（JSON body）

运行方式:
    python3 -m hanghang.web.server [--host 0.0.0.0] [--port 8080]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

# 保证可从 src 或仓库根直接运行
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from hanghang.engine import (  # noqa: E402
    Registry, IntentRouter, CompositePlanner, HandoffBus,
    MetricsCollector, PrefixArchive,
)

# 默认前端静态页面目录
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_STATIC_DIR = os.path.join(_HERE, "static")

# POST 请求体最大字节数（1MB）
MAX_BODY_SIZE = 1024 * 1024

# ---------------------------------------------------------------------------
# 模块级引擎缓存
#
# Web server 仅做「聚合 + 可视化」，引擎模块（Registry/PrefixArchive）在进程
# 生命周期内数据不变。若每次请求都重新实例化并 register_unit，会反复重写
# data/prefix-archive.json —— GET 只读路径必须避免该副作用。
# 因此此处做模块级单例缓存：首次创建时注册一次（含持久化），后续直接复用。
# ---------------------------------------------------------------------------
_engine_cache: Dict[str, object] = {}


def _init_engines():
    """初始化引擎缓存（首次调用触发，含前缀档案一次注册 + 持久化）。

    将 Registry/PrefixArchive/MetricsCollector/HandoffBus 统一缓存为模块级
    单例，避免每次 GET 请求重建实例而触发目录/文件副作用（如 makedirs、
    重写 prefix-archive.json）。POST 状态变更与 GET 读取共用同一实例，保持
    内存与磁盘语义一致。
    """
    if "initialized" in _engine_cache:
        return
    registry = Registry()
    pa = PrefixArchive()
    # 注册全部单元到前缀档案。默认 persist=True，首次启动时写入一次。
    for unit in registry.all_units():
        pa.register_unit(unit)
    _engine_cache["registry"] = registry
    _engine_cache["prefixes"] = pa
    _engine_cache["metrics"] = MetricsCollector()
    _engine_cache["handoffs"] = HandoffBus()
    _engine_cache["initialized"] = True


def _get_cached_registry() -> Registry:
    _init_engines()
    return _engine_cache["registry"]  # type: ignore


def _get_cached_prefixes() -> PrefixArchive:
    _init_engines()
    return _engine_cache["prefixes"]  # type: ignore


def _get_cached_metrics() -> MetricsCollector:
    _init_engines()
    return _engine_cache["metrics"]  # type: ignore


def _get_cached_handoffs() -> HandoffBus:
    _init_engines()
    return _engine_cache["handoffs"]  # type: ignore


def _apply_cors(handler):
    """按请求来源添加受限 CORS 头。

    前端页面与 API 由同一 server 提供（同源请求），不需要 CORS。
    仅当存在 Origin 头且来源为回环地址(localhost/127.0.0.1/::1)时
    才放行跨域访问；非回环来源一律不设 Access-Control-Allow-Origin，
    浏览器将自动拦截跨域响应（纵深防御）。
    """
    origin = handler.headers.get("Origin", "")
    if not origin:
        return  # 同源请求无需 CORS
    parsed = urllib.parse.urlparse(origin)
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "::1"):
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")


def _json_response(handler, code: int, payload: dict):
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _apply_cors(handler)
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler, html: str, code: int = 200):
    body = html.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _query_param(handler, key: str, default: str = "") -> str:
    """从 query string 读取参数"""
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)
    return qs.get(key, [default])[0]


class HanghangHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器，聚合各引擎模块能力到可调用 API。"""

    server_version = "HanghangRouter/1.0"

    # ---- 基础设施 ----
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[hanghang-web] {self.address_string()} {fmt % args}\n")

    def _get_registry(self) -> Registry:
        """获取注册表（模块级缓存，避免每次请求重读磁盘）。"""
        return _get_cached_registry()

    def _get_prefixes(self) -> PrefixArchive:
        """获取稳定前缀档案（模块级缓存，首次注册已持久化，后续只读复用）。"""
        return _get_cached_prefixes()

    def _get_metrics(self) -> MetricsCollector:
        """获取 M7 指标采集器（模块级缓存实例，避免 GET 每次重建触发目录副作用）。"""
        return _get_cached_metrics()

    def _get_handoffs(self) -> HandoffBus:
        """获取 M5 交接总线（模块级缓存实例，避免 GET 每次重建触发目录副作用）。"""
        return _get_cached_handoffs()

    # ---- 路由 ----
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/" or path == "/index.html":
                self._serve_index()
            elif path == "/api/units":
                self._api_units()
            elif path == "/api/route":
                self._api_route()
            elif path == "/api/search":
                self._api_search()
            elif path == "/api/index":
                self._api_index()
            elif path == "/api/metrics":
                self._api_metrics()
            elif path == "/api/handoffs":
                self._api_handoffs()
            elif path == "/api/prefixes":
                self._api_prefixes()
            elif path.startswith("/static/"):
                self._serve_static(path)
            else:
                _json_response(self, 404, {"error": f"未找到: {path}"})
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            # 500 不直接回显异常消息（避免泄露路径/内部细节）
            _json_response(self, 500, {"error": "内部服务错误"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/route":
            self._api_route_post()
        else:
            _json_response(self, 404, {"error": f"未找到: {path}"})

    def do_OPTIONS(self):
        """处理 CORS 预检请求（仅回环来源放行）"""
        self.send_response(204)
        _apply_cors(self)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- API 实现 ----
    def _api_units(self):
        """行业单元总览"""
        reg = self._get_registry()
        units = []
        for u in sorted(reg.all_units(), key=lambda x: x.unit_id):
            units.append({
                "unit_id": u.unit_id,
                "industry": u.industry,
                "industry_alias": u.industry_alias,
                "capability_tags": u.capability_tags,
                "entry_ref": u.entry_ref,
                "register_version": u.register_version,
                "roles": [
                    {
                        "name": r.name,
                        "prefix": r.prefix,
                        "composite": r.composite,
                        "handoff": r.handoff,
                        "description": r.description,
                        "keywords": r.get_keywords(),
                    }
                    for r in u.roles
                ],
            })
        _json_response(self, 200, {
            "total": len(units),
            "units": units,
        })

    def _do_route(self, text: str, record_metrics: bool = False) -> dict:
        """意图路由（统一逻辑，供 GET/POST 调用）。

        GET 请求为只读语义（幂等），不记录运行指标；
        POST 请求可改状态，由调用方通过 record_metrics=True 显式要求记录。
        """
        reg = self._get_registry()
        router = IntentRouter(reg)
        planner = CompositePlanner(reg, handoff_bus=self._get_handoffs())
        prefixes = self._get_prefixes()

        result = router.route(text)
        plan = planner.plan_from_result(result, text)
        if record_metrics:
            metrics = self._get_metrics()
            metrics.record_route(
                mode=plan.get("mode", "manual"),
                unit_id=plan.get("unit_id", ""),
                roles=plan.get("roles", []),
            )

        # 前缀档案（从缓存实例读取，只读）
        unit_prefixes = []
        if result.unit_id:
            up = prefixes.get_unit_prefixes(result.unit_id)
            if up:
                unit_prefixes = up

        return {
            "intent": text,
            "route_result": {
                "unit_id": result.unit_id,
                "industry": result.industry,
                "roles": result.roles,
                "confidence": result.confidence,
                "matched_keywords": result.matched_keywords,
                "is_ambiguous": result.is_ambiguous,
                "needs_manual": result.needs_manual,
                "fallback_reason": result.fallback_reason,
            },
            "plan": plan,
            "unit_prefixes": unit_prefixes,
        }

    def _api_route(self):
        """GET /api/route?text=...（只读，不记录指标）"""
        text = _query_param(self, "text", "")
        if not text:
            _json_response(self, 400, {"error": "缺少 text 参数"})
            return
        _json_response(self, 200, self._do_route(text, record_metrics=False))

    def _api_route_post(self):
        """POST /api/route body={"text": "..."}（状态变更，记录指标）"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        if length > MAX_BODY_SIZE:
            # 先读取/丢弃已到达的部分 body，避免客户端 broken pipe
            # （客户端可能在收到响应前继续写数据）
            if length > 0:
                try:
                    self.rfile.read(min(length, 64 * 1024))
                except Exception:
                    pass
            _json_response(self, 413, {"error": "请求体过大（最大 1MB）"})
            self.close_connection = True
            return
        try:
            body_raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(body_raw) if body_raw else {}
        except Exception:
            body = {}
        text = body.get("text", "")
        if not text:
            _json_response(self, 400, {"error": "缺少 text 字段"})
            return
        _json_response(self, 200, self._do_route(text, record_metrics=True))

    def _api_search(self):
        """GET /api/search?kw=..&mode=.."""
        kw = _query_param(self, "kw", "")
        mode = _query_param(self, "mode", "any")
        if not kw:
            _json_response(self, 400, {"error": "缺少 kw 参数"})
            return
        reg = self._get_registry()
        results = reg.search_capability(kw, mode=mode)
        _json_response(self, 200, {
            "keyword": kw,
            "mode": mode,
            "total": len(results),
            "results": results,
        })

    def _api_index(self):
        """GET /api/index — 全量能力索引"""
        reg = self._get_registry()
        index = reg.capability_index()
        _json_response(self, 200, {
            "total_units": len(index),
            "index": index,
        })

    def _api_metrics(self):
        """GET /api/metrics — M7 运行指标（模块级缓存实例，只读无目录副作用）"""
        metrics = self._get_metrics()
        _json_response(self, 200, {"metrics": metrics.get_summary()})

    def _api_handoffs(self):
        """GET /api/handoffs — M5 待处理交接卡（模块级缓存实例）"""
        bus = self._get_handoffs()
        pending = bus.list_pending()
        cards = [{
            "id": c.id,
            "source_unit": c.source_unit,
            "target_unit": c.target_unit,
            "intent": c.intent,
            "status": c.status,
            "created_at": c.created_at,
        } for c in pending]
        _json_response(self, 200, {"total": len(cards), "cards": cards})

    def _api_prefixes(self):
        """GET /api/prefixes — M3 稳定前缀档案（只读）"""
        pa = self._get_prefixes()
        archive = pa.get_archive()  # 通过公开方法读取，不暴露私有字段
        _json_response(self, 200, {"units": len(archive), "archive": archive})

    def _serve_index(self):
        """返回单页 HTML 控制台"""
        index_path = os.path.join(DEFAULT_STATIC_DIR, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                html = f.read()
            _html_response(self, html)
        else:
            # 无静态文件时的内联默认页
            html = _inline_default_index()
            _html_response(self, html)

    def _serve_static(self, path: str):
        """服务 /static/ 下的静态文件"""
        # 先做一次 URL 解码，避免 %2e%2e（编码的 ..）绕过 normpath 判定
        rel = urllib.parse.unquote(path.replace("/static/", "", 1))
        safe = os.path.normpath(rel)
        # 白名单判定：realpath 会解析 .. 与符号链接，折叠后必须仍位于静态目录内，
        # 否则拒绝访问（彻底封堵 /static//../../etc/passwd 等绝对路径/穿越攻击）
        base = os.path.realpath(DEFAULT_STATIC_DIR)
        full = os.path.realpath(os.path.join(DEFAULT_STATIC_DIR, safe))
        if not (full == base or full.startswith(base + os.sep)):
            _json_response(self, 403, {"error": "禁止访问"})
            return
        if not os.path.isfile(full):
            _json_response(self, 404, {"error": f"文件不存在: {path}"})
            return
        with open(full, "rb") as f:
            body = f.read()
        ctype = "text/plain"
        if full.endswith(".html"):
            ctype = "text/html; charset=utf-8"
        elif full.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif full.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HanghangHTTPServer(ThreadingHTTPServer):
    """行行出状元 HTTP 服务器（多线程 + 端口复用）"""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host: str, port: int):
        super().__init__((host, port), HanghangHandler)


def _inline_default_index() -> str:
    """无静态目录时的内联兜底页面（简单聚合展示）"""
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>行行出状元 · 通用能力控制台</title></head>
<body>
<h1>行行出状元 · 通用能力控制台</h1>
<p>页面渲染文件未找到。请确保 <code>src/hanghang/web/static/index.html</code> 存在。</p>
<p>API 仍可访问：<code>/api/units</code>、<code>/api/route?text=...</code> 等。</p>
</body></html>
"""


def serve_forever(host: str = "127.0.0.1", port: int = 8080):
    """启动 HTTP 服务"""
    _init_engines()  # 启动时先初始化缓存（含首次前缀档案注册 + 持久化）
    server = HanghangHTTPServer(host, port)
    print(f"行行出状元 · 通用能力层控制台已启动")
    print(f"  页面入口: http://{host}:{port}/")
    print(f"  API 文档: http://{host}:{port}/api/units")
    print(f"  Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="行行出状元 · Web 控制台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    args = parser.parse_args()
    serve_forever(args.host, args.port)


if __name__ == "__main__":
    main()
