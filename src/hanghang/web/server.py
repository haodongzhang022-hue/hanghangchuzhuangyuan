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
- GET /api/state            — M9 状态卡聚合（编排/交接任务进度，只读）
- POST /api/route           — 意图路由调用（JSON body）

运行方式:
    python3 -m hanghang.web.server [--host 0.0.0.0] [--port 8080]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional

# 保证可从 src 或仓库根直接运行
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from hanghang.engine import (  # noqa: E402
    Registry, IntentRouter, CompositePlanner, HandoffBus,
    MetricsCollector, PrefixArchive,
)
from hanghang.engine.coverage import CoverageTracker  # noqa: E402

logger = logging.getLogger(__name__)

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
_engine_lock = threading.Lock()


def _init_engines():
    """初始化引擎缓存（首次调用触发，含前缀档案一次注册 + 持久化）。

    将 Registry/PrefixArchive/MetricsCollector/HandoffBus 统一缓存为模块级
    单例，避免每次 GET 请求重建实例而触发目录/文件副作用（如 makedirs、
    重写 prefix-archive.json）。POST 状态变更与 GET 读取共用同一实例，保持
    内存与磁盘语义一致。

    线程安全：多线程冷启动时（handler 并发首次请求）仅允许一个线程执行
    初始化，其余线程等待锁后直接返回缓存结果，避免重复注册/重复写盘。
    """
    if "initialized" in _engine_cache:
        return
    with _engine_lock:
        # double-check：等待锁期间可能已被其它线程完成初始化
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
        # M9 状态管理器：读取 data/state 下的 StateCard（路由自动落卡 + 交接关联卡）。
        # GET /api/state 仅做只读聚合，绝不在此路径写入。
        from hanghang.state.manager import StateManager
        _engine_cache["state"] = StateManager()
        # M11 行业库：yaml 是静态数据，每次请求重新读盘构造纯属浪费。
        # 复用缓存的 registry，避免同一份 unit-index 被读两遍。
        from hanghang.engine.industry_db import IndustryDatabase
        _engine_cache["industry_db"] = IndustryDatabase(registry=registry)
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


def _get_cached_state() -> "StateManager":
    _init_engines()
    return _engine_cache["state"]  # type: ignore


def _get_cached_industry_db():
    """M11 行业库（静态数据，进程内一份）：/api/industry-db 与 /api/coverage 共用。"""
    _init_engines()
    return _engine_cache["industry_db"]


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

    def _get_state(self) -> "StateManager":
        """获取 M9 状态管理器（模块级缓存实例，指向 data/state，GET 只读）。"""
        return _get_cached_state()

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
            elif path == "/api/coverage":
                self._api_coverage()
            elif path == "/api/industry-db":
                self._api_industry_db()
            elif path == "/api/handoffs":
                self._api_handoffs()
            elif path == "/api/prefixes":
                self._api_prefixes()
            elif path == "/api/session":
                self._api_session()
            elif path == "/api/state":
                self._api_state()
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


    def _api_coverage(self):
        """行业岗位覆盖进度：目标全集 vs 当前覆盖

        必须复用 `_engine_cache` 里的 IndustryDatabase：`CoverageTracker` 构造时
        若自建一个，就要重读 178 职业 + 41 分区 + 186 边 + 大典/ISCO 参考表，
        实测 ~1000 ms；复用缓存实例后回到 ~几十 ms。职业库是静态数据，
        不该按请求重建。
        """
        tracker = CoverageTracker(registry=self._get_registry(),
                                  industry_db=_get_cached_industry_db())
        payload = tracker.compute()
        payload["rows"] = sorted(
            payload["rows"],
            key=lambda r: (r["status"] != "registered", r["name"]))
        _json_response(self, 200, payload)

    @staticmethod
    def _gb_fields(catalog, occ_id: str):
        """职业 →（gb_code, 大典中文名, 分类路径），带进程内缓存。

        大典映射是**纯静态外键**（yaml 读进来就不变），但旧实现每个职业每次请求
        都线性查两次表；178 个职业 × 每请求 = 白算。缓存成 dict 后请求路径只做
        O(1) 拼装。缓存键带 catalog 对象 id，换实例（换 data 目录）自动失效。
        """
        if catalog is None:
            return "", "", ""
        cache = _engine_cache.setdefault("gb_fields_cache", {})
        key = (id(catalog), occ_id)
        hit = cache.get(key)
        if hit is not None:
            return hit
        code = catalog.gb_code_of(occ_id) or ""
        if not code:
            value = ("", "", "")
        else:
            entry = catalog.entry(code) or {}
            if not isinstance(entry, dict):
                raise TypeError(f"entry({code}) 返回 {type(entry).__name__}")
            value = (code, entry.get("name", ""), catalog.path_of(code))
        cache[key] = value
        return value

    def _api_industry_db(self):
        """GET /api/industry-db — M11 行业分区定义库（分区表+职业表+覆盖+产值，只读）

        职业条目附带 gb_code（《职业分类大典 2022》细类编码）与大典中文名，
        前端不必再自己维护一份编码表；`catalog` 段给映射率与分类覆盖快照。
        """
        db = _get_cached_industry_db()
        # compute()/validate() 仍每次现算：它们是"当前数据的一致性快照"，
        # 缓存的是实例（含读盘后的 yaml），不是结论。
        payload = db.compute()
        degrade_notes: List[str] = []   # 降级记录单独收集，最后与 validate() 合并
        occupations = []
        for o in db.occupations:
            row = dict(o)
            try:
                gb, gb_name, gb_path = self._gb_fields(db.catalog, o.get("id", ""))
            except Exception as exc:  # 大典表坏了不能把整个只读出口打成 500
                degrade_notes.append(
                    f"职业 {o.get('id')} 的大典映射读取失败（{type(exc).__name__}），"
                    f"已降级为空字段")
                gb = gb_name = gb_path = ""
            if gb:
                row["gb_code"] = gb
                row["gb_name"] = gb_name
                row["gb_path"] = gb_path
            occupations.append(row)
        payload["occupations"] = occupations
        # 降级记录必须并进来：compute() 返回的字典里没有 problems 键，
        # 早先用 setdefault 追加会被这一行整体覆盖，等于降级一条也留不下来。
        payload["problems"] = list(db.validate()) + degrade_notes
        _json_response(self, 200, payload)

    def _do_route(self, text: str, record_metrics: bool = False) -> dict:
        """意图路由（统一逻辑，供 GET/POST 调用）。

        GET 请求为只读语义（幂等）：
          - 不记录运行指标；
          - 命中 handoff_required 分支时不自动创建交接卡（无写盘副作用）；
          - 不创建 M9 StateCard（无写盘副作用）。
        POST 请求可改状态：
          - 由调用方通过 record_metrics=True 显式要求记录指标；
          - handoff_required 分支自动创建交接卡（状态变更路径）；
          - direct/composite 分支自动创建 M9 StateCard（状态变更路径）。
        """
        reg = self._get_registry()
        router = IntentRouter(reg)
        planner = CompositePlanner(reg, handoff_bus=self._get_handoffs())
        prefixes = self._get_prefixes()

        result = router.route(text)
        # GET(只读/测试观测) 不建交接卡/不建 StateCard；POST(状态变更) 自动建卡接力。
        # record_metrics=True 仅用于 POST（状态变更）；False 对应 GET（只读）。
        plan = planner.plan_from_result(
            result, text,
            create_handoff=record_metrics,
            persist_state=record_metrics,
        )
        if record_metrics:
            metrics = self._get_metrics()
            # 岗位维度取 result.roles（路由结果恒有 roles 字段）：
            # plan 仅在 composite/handoff_required 分支含 roles，direct 分支仅含单 role
            # （无 roles 键），沿用 plan.roles 会导致 direct 模式岗位命中被低估。
            # ⚠️ manual(人工确认)分支若 roles 有值同样计入 role_hits（候选命中岗位），
            #    人工介入由 manual_confirmations 单独统计——与 CLI cmd_route 口径一致。
            metrics.record_route(
                mode=plan.get("mode", "manual"),
                unit_id=plan.get("unit_id", "") or result.unit_id,
                roles=result.roles,
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
        """POST /api/route body={"text": "..."}（状态变更，记录指标）

        body 解析同时支持：
        - application/json        → {"text": "..."}
        - application/x-www-form-urlencoded → text=...（按 content-type 真实解析）
        Content-Type 宽松校验：期望 application/json，但对缺失/宽松类型保持兼容。
        仅拒绝明确声明的非 JSON/非表单类型（如 application/xml）；text/*、+json
        与缺失 Content-Type 均放行，避免误伤未显式设置的 curl 等客户端。
        """
        ctype = (self.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
        is_form = ctype == "application/x-www-form-urlencoded"
        if ctype and ctype != "application/json" \
                and not ctype.endswith("+json") \
                and not ctype.startswith("text/") \
                and not is_form:
            _json_response(self, 415, {
                "error": f"不支持的 Content-Type: {ctype}（期望 application/json）"
            })
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        if length > MAX_BODY_SIZE:
            # 完整读取并丢弃请求体，避免客户端 broken pipe。
            # 仅读取部分 body 就关闭连接，会导致还在向 socket 写入
            # 剩余 body 数据的客户端遇到 EPIPE/BrokenPipeError。
            remaining = length
            while remaining > 0:
                try:
                    chunk = self.rfile.read(min(remaining, 64 * 1024))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                except Exception:
                    break
            _json_response(self, 413, {"error": "请求体过大（最大 1MB）"})
            self.close_connection = True
            return
        body_raw = self.rfile.read(length).decode("utf-8") if length else ""
        if is_form:
            # 表单：application/x-www-form-urlencoded，逐字段解析（兼容重复键取末值）
            try:
                fields = urllib.parse.parse_qs(body_raw, keep_blank_values=True)
                body = {k: (v[-1] if isinstance(v, list) and v else "") for k, v in fields.items()}
            except Exception:
                body = {}
        else:
            try:
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

    def _api_state(self):
        """GET /api/state — M9 状态卡聚合（编排/交接任务进度，只读）。

        只读聚合 data/state 下各 StateCard：
          - 路由自动落卡（session 以 rt- 开头）与交接关联卡（ho- 开头）分桶统计；
          - 汇总任务进度（done/in_progress/blocked/todo）；
          - 供 L2 出口复核端可视化"编排/交接进度"，不做任何写盘。
        """
        sm = self._get_state()
        cards = sm.list_cards()  # 只读：遍历磁盘 JSON 重建，无写盘副作用
        cards.sort(key=lambda c: c.created_at or "", reverse=True)

        stats = {"total_cards": 0, "total_tasks": 0,
                 "todo_tasks": 0, "done_tasks": 0, "in_progress_tasks": 0,
                 "blocked_tasks": 0, "failed_tasks": 0, "cancelled_tasks": 0,
                 "route_cards": 0, "handoff_cards": 0, "other_cards": 0}

        per_unit = {}
        items = []
        for c in cards:
            sid = c.session_id or ""
            if sid.startswith("rt-"):
                kind = "route"
                stats["route_cards"] += 1
            elif sid.startswith("ho-"):
                kind = "handoff"
                stats["handoff_cards"] += 1
            else:
                kind = "other"
                stats["other_cards"] += 1

            summary = c.summarize_for_upstream()
            item = {
                "session_id": sid,
                "kind": kind,
                "unit_id": c.unit_id or "",
                "role_name": c.role_name or "",
                "objective": c.objective or "",
                "created_at": c.created_at or "",
                "updated_at": c.updated_at or "",
                "task_count": summary.get("task_count", 0),
                "todo_count": summary.get("todo_count", 0),
                "done_count": summary.get("done_count", 0),
                "in_progress_count": summary.get("in_progress_count", 0),
                "blocked_count": summary.get("blocked_count", 0),
                "failed_count": summary.get("failed_count", 0),
                "cancelled_count": summary.get("cancelled_count", 0),
                "tasks": summary.get("tasks", []),
            }
            stats["total_cards"] += 1
            stats["total_tasks"] += item["task_count"]
            stats["todo_tasks"] += item["todo_count"]
            stats["done_tasks"] += item["done_count"]
            stats["in_progress_tasks"] += item["in_progress_count"]
            stats["blocked_tasks"] += item["blocked_count"]
            stats["failed_tasks"] += item["failed_count"]
            stats["cancelled_tasks"] += item["cancelled_count"]

            uid = item["unit_id"] or "未标注单元"
            pu = per_unit.setdefault(uid, {"cards": 0, "tasks": 0, "done": 0})
            pu["cards"] += 1
            pu["tasks"] += item["task_count"]
            pu["done"] += item["done_count"]
            items.append(item)

        _json_response(self, 200, {
            "stats": stats,
            "per_unit": [{"unit_id": u, **v} for u, v in per_unit.items()],
            "cards": items,
        })


    def _api_session(self):
        """GET /api/session?id=<session_id> — 单会话编排快照 + 续传锚点（只读）。

        落 RFC-ECO-01 阶段4（生态闭环·轮询拉取形态）：外部 agent / L2 出口复核
        可按 session 拉取某一编排/交接会话的「待办 + 结果 + 交接关联」，用于续传
        或承接，而无需依赖 CLI 或对话记忆。

        返回：
          - session 概要（objective/unit/role/时间）
          - 任务分桶统计 + 全量任务明细
          - 树/上下级联动（upstream/downstream）
          - 交接关联（handoff 会话时，从交接仓反查 source→target/状态）
          - resume（续传锚点）：未完结任务清单 + resume_key = session@version
        """
        sid = _query_param(self, "id") or _query_param(self, "session")
        if not sid:
            _json_response(self, 400, {"error": "缺少 session id 参数 (?id=...)"})
            return
        sm = self._get_state()
        card = sm.get_card(sid)
        if card is None:
            _json_response(self, 404, {
                "error": f"未找到会话 {sid}",
                "hint": "路由/交接自动落卡在 data/state/ 下，可用 /api/state 查看全部",
            })
            return

        # 卡片概要 + 任务汇总
        summary = card.summarize_for_upstream()
        kind = "handoff" if sid.startswith("ho-") else (
            "route" if sid.startswith("rt-") else "other")

        # 联动：本卡 upstream/downstream + 反向扫描下级（谁的 upstream==本会话）
        children = list(card.downstream or [])
        for other in sm.list_cards():
            if other.session_id == sid:
                continue
            if other.upstream == sid:
                children.append(other.session_id)
        children = sorted(set(children))

        # 交接关联：ho- 会话反查交接仓记录（source→target / 状态）
        handoff_link = None
        if kind == "handoff":
            handoff_link = self._resolve_handoff_link(sid)

        # 续传锚点：未完结/需承接任务 + 确定性 resume_key
        # 显式区分失败/全取消，避免 failed 被 in_progress 吞掉、全 cancelled 落成 done
        task_count = summary.get("task_count", 0)
        done_count = summary.get("done_count", 0)
        blocked_count = summary.get("blocked_count", 0)
        failed_count = summary.get("failed_count", 0)
        cancelled_count = summary.get("cancelled_count", 0)
        tasks = summary.get("tasks", [])
        open_tasks = [
            t for t in tasks
            if t.get("state") in ("todo", "in_progress", "blocked", "failed")
        ]
        # 是否有真正"待续传/推进中"任务（todo / in_progress）
        has_active = any(
            t.get("state") in ("todo", "in_progress") for t in tasks
        )
        if task_count == 0:
            status = "empty"
        elif done_count == task_count:               # 全部完成 → 无续传负担
            status = "delivered"
        elif cancelled_count == task_count:          # 全取消：会话无实际推进
            status = "cancelled"
        elif failed_count > 0:                       # 含失败任务（含已 done 并存）→ 需人工关注
            status = "needs_attention"
        elif has_active:                             # 仍有 todo/in_progress 待续传
            status = "in_progress"
        elif blocked_count > 0:
            status = "blocked"
        else:
            # done+cancelled 混合（无 failed、无 active、非全 done/全 cancel）
            # 无任何可续传清单却非纯终态，显式标 needs_attention 避免空 pending 误标"进行中"
            status = "needs_attention"
        resume = {
            "status": status,
            "open_task_count": len(open_tasks),
            "pending": open_tasks,
            "resume_key": f"{sid}@{card.version or 0}",
        }

        _json_response(self, 200, {
            "session_id": sid,
            "kind": kind,
            "card": {
                "unit_id": card.unit_id or "",
                "role_name": card.role_name or "",
                "objective": card.objective or "",
                "owner": card.owner or "",
                "version": card.version or 0,
                "created_at": card.created_at or "",
                "updated_at": card.updated_at or "",
            },
            "stats": {
                "task_count": summary.get("task_count", 0),
                "todo_count": summary.get("todo_count", 0),
                "done_count": summary.get("done_count", 0),
                "in_progress_count": summary.get("in_progress_count", 0),
                "blocked_count": summary.get("blocked_count", 0),
                "failed_count": summary.get("failed_count", 0),
                "cancelled_count": summary.get("cancelled_count", 0),
            },
            "tasks": summary.get("tasks", []),
            "linkage": {
                "upstream": card.upstream or None,
                "downstream": children,
            },
            "handoff_link": handoff_link,
            "resume": resume,
        })

    def _resolve_handoff_link(self, session_id: str):
        """反查交接仓：找出 state_card_id == session_id 的交接记录。只读。

        直接扫描交接数据目录内全部交接 JSON（不依赖 list_pending 的
        status 过滤，以同时覆盖已回传 done/failed 与进行中记录）。
        """
        try:
            hb = self._get_handoffs()
            data_dir = getattr(hb, "data_dir", None)
            if not data_dir or not os.path.isdir(data_dir):
                return {"status": "no_handoff_record"}
            for fn in os.listdir(data_dir):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(data_dir, fn), "r",
                              encoding="utf-8") as f:
                        rec = json.load(f)
                except Exception as e:
                    # G1: 半写/损坏 JSON 不再静默吞掉，记 warning 便于排障
                    logger.warning(
                        "handoff 交接记录解析失败，跳过 %s: %s", fn, e)
                    continue
                if isinstance(rec, dict) and rec.get("state_card_id") == session_id:
                    return {
                        "source_unit": rec.get("source_unit"),
                        "target_unit": rec.get("target_unit"),
                        "intent": rec.get("intent"),
                        "status": rec.get("status") or "created",
                        "card_id": rec.get("id") or rec.get("card_id") or fn[:-5],
                    }
            return {"status": "no_handoff_record"}
        except Exception:
            return {"status": "lookup_error"}

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
        # 先做一次 URL 解码，避免 %2e%2e（编码的 ..）绕过 normpath 判定。
        # 移除 /static/ 前缀后再 strip 一次前导 '/'：/static//index.html 这类
        # 双斜杠（URL 不规范但常见）经 replace 后会残留 '/'，若直接 normpath 会
        # 变成绝对路径被下方 realpath 白名单误拒为 403。归一化后既能服务双斜杠
        # URL，又保留对目录穿越的封堵（../ 仍会被 realpath 折叠出静态目录拒绝）。
        rel = urllib.parse.unquote(path.replace("/static/", "", 1)).lstrip("/")
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


def _is_loopback(host: str) -> bool:
    """判断绑定地址是否为回环地址。"""
    import ipaddress
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        # 非 IP 字面量（如 hostname 'localhost'）也视为回环安全
        return host in ("localhost", "")


def serve_forever(host: str = "127.0.0.1", port: int = 8080):
    """启动 HTTP 服务"""
    _init_engines()  # 启动时先初始化缓存（含首次前缀档案注册 + 持久化）
    server = HanghangHTTPServer(host, port)
    print(f"行行出状元 · 通用能力层控制台已启动")
    print(f"  页面入口: http://{host}:{port}/")
    print(f"  API 文档: http://{host}:{port}/api/units")
    print(f"  Ctrl+C 停止")
    # 非回环绑定的安全告警横幅：服务含状态变更接口(POST /api/route)，
    # 对外暴露必须置于认证/网关之后，避免未授权访问。
    if not _is_loopback(host):
        print("=" * 60)
        print("  ⚠️  [安全告警] 监听非回环地址，服务已暴露到网络！")
        print(f"  ⚠️  当前绑定: {host}:{port}")
        print("  ⚠️  本服务含状态变更接口(POST /api/route，写指标/交接/StateCard)")
        print("  ⚠️  请确保已置于反向代理/认证/网关之后，避免未授权访问！")
        print("=" * 60)
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
