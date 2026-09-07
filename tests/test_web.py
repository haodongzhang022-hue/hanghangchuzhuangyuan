"""Web 可视化聚合面板 API 测试"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from hanghang.web.server import HanghangHTTPServer, MAX_BODY_SIZE


class TestWebAPI:
    """通过本地 HTTP 服务器测试各 API 端点"""

    @classmethod
    def setup_class(cls):
        cls.server = HanghangHTTPServer("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.2)  # 等服务起来

    @classmethod
    def teardown_class(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def _get(self, path: str):
        with urllib.request.urlopen(self.base_url + path) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_units_api(self):
        code, data = self._get("/api/units")
        assert code == 200
        assert data["total"] >= 8  # 至少8个行业单元
        unit_ids = [u["unit_id"] for u in data["units"]]
        assert "dongjiagoushi" in unit_ids
        assert "game-dev-unit" in unit_ids

    def test_route_api(self):
        code, data = self._get(
            "/api/route?text=" + urllib.parse.quote("既要架构设计又要落地开发"))
        assert code == 200
        rr = data["route_result"]
        assert rr["unit_id"] == "dongjiagoushi"
        assert "architect" in rr["roles"]
        assert "developer" in rr["roles"]

    def test_route_api_manual_fallback(self):
        code, data = self._get("/api/route?text=" + urllib.parse.quote("帮我点个外卖"))
        assert code == 200
        rr = data["route_result"]
        assert rr["needs_manual"] is True
        assert data["plan"]["mode"] == "manual"

    def test_route_post(self):
        body = json.dumps({"text": "帮我做个网站"}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/api/route",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rr = data["route_result"]
        assert rr["unit_id"] == "dongjiagoushi"

    def test_search_api(self):
        code, data = self._get("/api/search?kw=" + urllib.parse.quote("数据分析"))
        assert code == 200
        assert data["total"] >= 1
        # data-analytics 应该能命中
        unit_ids = [r["unit_id"] for r in data["results"]]
        assert "data-analytics" in unit_ids

    def test_search_role_mode(self):
        code, data = self._get(
            "/api/search?kw=" + urllib.parse.quote("记账") + "&mode=role")
        assert code == 200
        assert data["total"] >= 1
        unit_ids = [r["unit_id"] for r in data["results"]]
        assert "finance-accounting" in unit_ids

    def test_index_api(self):
        code, data = self._get("/api/index")
        assert code == 200
        assert data["total_units"] >= 8
        assert isinstance(data["index"], list)
        assert len(data["index"][0]["roles"]) >= 1

    def test_metrics_api(self):
        code, data = self._get("/api/metrics")
        assert code == 200
        # 断言必备字段存在（不依赖路由测试先后顺序）
        assert "total_routes" in data["metrics"]
        assert "auto_success_rate" in data["metrics"]
        assert "unit_hits" in data["metrics"]

    def test_prefixes_api(self):
        code, data = self._get("/api/prefixes")
        assert code == 200
        assert data["units"] >= 8
        assert "dongjiagoushi" in data["archive"]

    def test_handoffs_api(self):
        code, data = self._get("/api/handoffs")
        assert code == 200
        assert isinstance(data["cards"], list)

    def test_root_serves_html(self):
        with urllib.request.urlopen(self.base_url + "/") as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
            assert "行行出状元" in body

    # ---- 安全与幂等性测试 ----
    def test_get_route_is_read_only(self):
        """GET /api/route 只读，不应记录运行指标"""
        # 先读取当前指标
        code0, m0 = self._get("/api/metrics")
        assert code0 == 200
        total_before = m0["metrics"]["total_routes"]

        # GET 路由调用
        code, _ = self._get(
            "/api/route?text=" + urllib.parse.quote("帮我写一份商业计划书"))
        assert code == 200

        # 指标不应增加
        _, m1 = self._get("/api/metrics")
        assert m1["metrics"]["total_routes"] == total_before

    def test_post_route_records_metrics(self):
        """POST /api/route 应记录运行指标"""
        # 先读取当前指标
        code0, m0 = self._get("/api/metrics")
        total_before = m0["metrics"]["total_routes"]

        body = json.dumps({"text": "帮我开发一个电商平台"}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/api/route",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

        # 指标应 +1
        _, m1 = self._get("/api/metrics")
        assert m1["metrics"]["total_routes"] == total_before + 1

    def test_route_post_body_size_limit(self):
        """POST body 超过 1MB 应返回 413"""
        huge = {"text": "a" * (MAX_BODY_SIZE + 1)}
        body = json.dumps(huge).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/api/route",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                assert False, f"预期 413，实际 {resp.status}"
        except urllib.error.HTTPError as e:
            assert e.code == 413
            data = json.loads(e.read().decode("utf-8"))
            assert "请求体过大" in data.get("error", "")

    def test_prefixes_has_all_units(self):
        """GET /api/prefixes 应包含全部注册单元（非冗余多次注册）"""
        code, data = self._get("/api/prefixes")
        assert code == 200
        # 应包含至少8个行业单元
        assert data["units"] >= 8
        # 数据应为完整档案而非空
        assert len(data["archive"]) >= 8

    # ---- GET 只读语义：不写 prefix-archive.json 文件 ----
    def test_get_requests_do_not_write_prefix_archive(self):
        """GET /api/prefixes 与 GET /api/route 不应写 prefix-archive.json。

        评审指出：旧实现中每次 GET 都会重建 PrefixArchive 并 register_unit，
        register_unit 内部每次都会写文件 → 违反 GET 只读/幂等语义。
        本测试断言多次 GET 请求前后 prefix-archive.json 文件 mtime 不变。
        """
        import hanghang.web.server as web_server
        from hanghang.engine.prefix import PrefixArchive

        # 先确保引擎已初始化（server setup 时已触发一次注册持久化）
        web_server._init_engines()
        archive_file = os.path.join(os.getcwd(), "data", "prefix-archive.json")
        assert os.path.exists(archive_file)

        # 记录 GET 前的 mtime
        mtime_before = os.stat(archive_file).st_mtime
        time.sleep(0.01)  # 保证 mtime 粒度区分

        # 多次 GET 请求
        for _ in range(3):
            _, _ = self._get("/api/prefixes")
            _, _ = self._get(
                "/api/route?text=" + urllib.parse.quote("帮我设计一个系统架构"))
            _, _ = self._get("/api/units")

        time.sleep(0.01)
        mtime_after = os.stat(archive_file).st_mtime

        assert mtime_before == mtime_after, (
            f"GET 请求不应写 prefix-archive.json: "
            f"mtime 从 {mtime_before} 变为 {mtime_after}"
        )

    # ---- PrefixArchive.register_unit persist=False 不写盘 ----
    def test_register_unit_persist_false_no_file_write(self):
        """PrefixArchive.register_unit(persist=False) 不写磁盘。"""
        import tempfile
        from hanghang.engine.prefix import PrefixArchive
        from hanghang.engine.registry import Registry

        tmp_dir = tempfile.mkdtemp()
        tmp_file = os.path.join(tmp_dir, "test-archive.json")
        pa = PrefixArchive(archive_file=tmp_file)
        reg = Registry()

        # persist=False 不应创建文件
        for unit in reg.all_units():
            pa.register_unit(unit, persist=False)
        assert not os.path.exists(tmp_file), "persist=False 不应创建文件"

        # persist=True 应创建文件
        for unit in reg.all_units():
            pa.register_unit(unit, persist=True)
        assert os.path.exists(tmp_file), "persist=True 应创建文件"

    # ---- 500 不泄露内部异常细节 ----
    def test_error_response_hides_internal_path(self):
        """500 错误响应不应直接回显内部异常消息（如文件路径）。"""
        # 直接检查 server.py 源码：500 处理不应使用 str(e) 回显内部信息
        server_py = os.path.join(
            os.path.dirname(__file__), "../src/hanghang/web/server.py")
        with open(server_py, encoding="utf-8") as f:
            source = f.read()
        # 500 应返回通用错误信息
        assert '"内部服务错误"' in source
        # 不应使用 str(e) 直接拼入错误响应
        assert '_json_response(self, 500, {"error": str(e)})' not in source

    # ---- 交接卡缓存一致性回归测试 ----
    def test_composite_planner_uses_cached_handoff_bus(self):
        """回归：_do_route 中 CompositePlanner 应注入模块级缓存 handoff_bus。

        原问题：CompositePlanner(reg) 未注入交接总线时，内部自建独立 HandoffBus，
        导致 (1) GET /api/route 命中 handoff_required 分支时创建交接卡写盘，
        (2) 交接卡写入自建实例，/api/handoffs 读取模块级缓存 → 交接卡不可见（缓存不一致）。
        本测试通过 mock CompositePlanner 验证其收到的是缓存 handoff_bus 实例。
        """
        import hanghang.web.server as web_server
        from unittest import mock

        cached_bus = web_server._get_cached_handoffs()

        with mock.patch.object(web_server, 'CompositePlanner') as mock_planner:
            mock_planner.return_value.plan_from_result.return_value = {
                "mode": "direct", "unit_id": "test", "message": "ok"
            }
            # 触发一次 GET 路由请求（会调用 _do_route）
            self._get("/api/route?text=" + urllib.parse.quote("帮我做个网站"))

            assert mock_planner.called, "CompositePlanner 应被调用"
            call_args = mock_planner.call_args
            kwargs = call_args[1] if len(call_args) > 1 else {}
            injected_bus = kwargs.get("handoff_bus")
            assert injected_bus is cached_bus, (
                f"CompositePlanner 应注入缓存 handoff_bus，实际收到 {injected_bus}"
            )

    def test_handoff_card_shared_instance_consistency(self):
        """回归：交接卡应通过同一缓存总线实例读写，保证 /api/handoffs 可见。

        构造含 composite:false 岗位的场景，验证交接卡写入缓存总线后，
        同一缓存总线的 list_pending 能读到该卡（信息对称）。
        """
        import tempfile
        from hanghang.engine import CompositePlanner, HandoffBus
        from hanghang.engine.registry import Registry
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            bus = HandoffBus(data_dir=os.path.join(tmpdir, "handoffs"))

            # 构造 composite:false 岗位触发 handoff_required
            test_data = {
                "unit_id": "test-unit-x",
                "industry": "测试行业",
                "industry_alias": ["测试行业X"],
                "roles": [
                    {"name": "role_a", "prefix": "[A]", "composite": True,
                     "keywords": ["岗位A"]},
                    {"name": "role_b", "prefix": "[B]", "composite": False,
                     "keywords": ["岗位B"]},
                ],
            }
            test_file = os.path.join(tmpdir, "industry-register-test.yaml")
            with open(test_file, "w", encoding="utf-8") as f:
                yaml.dump(test_data, f, allow_unicode=True)

            reg = Registry(search_paths=[tmpdir])
            planner = CompositePlanner(reg, handoff_bus=bus)
            plan = planner.plan("我需要做岗位A并且做岗位B")

            assert plan["mode"] == "handoff_required", \
                f"预期 handoff_required，实际 {plan['mode']}"
            assert plan["handoff_card_id"] is not None

            # 关键断言：交接卡通过同一 bus 实例创建 → list_pending 可见
            pending = bus.list_pending()
            card_ids = [c.id for c in pending]
            assert plan["handoff_card_id"] in card_ids, (
                f"交接卡 {plan['handoff_card_id']} 应在同一 bus 的 list_pending 中可见"
            )

    def test_do_route_source_injects_handoff_bus(self):
        """源码检查：_do_route 中 CompositePlanner 必须注入 handoff_bus。"""
        import re
        server_py = os.path.join(
            os.path.dirname(__file__), "../src/hanghang/web/server.py")
        with open(server_py, encoding="utf-8") as f:
            source = f.read()
        assert 'handoff_bus=self._get_handoffs()' in source, (
            "_do_route 中 CompositePlanner 应注入缓存 handoff_bus"
        )
        # 不应存在未注入 handoff_bus 的裸 CompositePlanner(reg) 调用
        bare_calls = re.findall(
            r'CompositePlanner\s*\(\s*reg\s*\)', source)
        assert not bare_calls, f"存在未注入 handoff_bus 的调用: {bare_calls}"


    def _raw_get(self, path: str):
        """用原始 socket 发 GET，绕过 urllib 对 .. 的路径归一化。"""
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, body
        finally:
            conn.close()

    def test_static_serves_index_within_dir(self):
        """正常静态资源应可访问（回归防护，确保未破坏 /static/）。"""
        code, body = self._raw_get("/static/index.html")
        assert code == 200
        assert b"<!DOCTYPE html>" in body or b"<html" in body

    def test_static_blocks_traversal_double_slash(self):
        """/static//../../etc/passwd 应被 403 拒绝（Critical 目录穿越）。"""
        code, _ = self._raw_get("/static//../../etc/passwd")
        assert code == 403, f"目录穿越未被拦截: {code}"

    def test_static_blocks_traversal_encoded_dotdot(self):
        """URL 编码的 %2e%2e 穿越应被 403 拒绝。"""
        code, _ = self._raw_get("/static/%2e%2e/%2e%2e/etc/passwd")
        assert code == 403, f"编码穿越未被拦截: {code}"

    def test_static_blocks_absolute_path_escape(self):
        """多级 .. 逃逸出静态目录应被 403 拒绝。"""
        code, _ = self._raw_get("/static/../../../../etc/passwd")
        assert code == 403, f"多级穿越未被拦截: {code}"



    # ---- 评审加固：GET 只读不建交接卡 + 指标岗位维度 + 并发线程安全 ----
    def test_get_route_does_not_create_handoff_card(self):
        """评审#1：GET /api/route 命中 handoff_required 分支也不应建交接卡(写盘)。

        GET 是只读/测试观测语义，plan_from_result 传 create_handoff=False，
        即使触发 handoff_required 也只返回提示、不写卡。默认(CLI/POST)仍自动建卡。
        """
        import tempfile
        from hanghang.engine import (IntentRouter, CompositePlanner,
                                     HandoffBus, Registry)
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            bus = HandoffBus(data_dir=os.path.join(tmpdir, "handoffs"))
            # composite:True + composite:False 触发 handoff_required
            test_data = {
                "unit_id": "test-gho",
                "industry": "测试行业",
                "industry_alias": ["测试行业G"],
                "roles": [
                    {"name": "role_x", "prefix": "[X]", "composite": True,
                     "keywords": ["需求X"]},
                    {"name": "role_y", "prefix": "[Y]", "composite": False,
                     "keywords": ["需求Y"]},
                ],
            }
            tf = os.path.join(tmpdir, "industry-register-test.yaml")
            with open(tf, "w", encoding="utf-8") as f:
                yaml.dump(test_data, f, allow_unicode=True)
            reg = Registry(search_paths=[tmpdir])
            planner = CompositePlanner(reg, handoff_bus=bus)
            router = IntentRouter(reg)
            result = router.route("我要做需求X和需求Y")

            # 只读路径 create_handoff=False：返回 handoff_required 但不落卡
            plan_ro = planner.plan_from_result(result, "我要做需求X和需求Y",
                                               create_handoff=False)
            assert plan_ro["mode"] == "handoff_required"
            # 不写卡：无交接卡被创建
            assert len(bus.list_pending()) == 0

            # 状态变更路径(默认 create_handoff=True)：自动建卡
            plan_rw = planner.plan_from_result(result, "我要做需求X和需求Y")
            assert plan_rw["mode"] == "handoff_required"
            assert plan_rw["handoff_card_id"] is not None
            assert len(bus.list_pending()) >= 1

    def test_persist_state_false_no_state_card_created(self):
        """评审：persist_state=False 时 direct/composite 分支不创建 M9 StateCard。

        验证 GET 只读路径不会经 _ensure_state_card 写入 data/state/*.json。
        使用 mock 拦截 _ensure_state_card，确认 persist_state=False 时不触发调用。
        """
        import tempfile
        from unittest import mock
        from hanghang.engine import (IntentRouter, CompositePlanner,
                                     HandoffBus, Registry)
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            bus = HandoffBus(data_dir=os.path.join(tmpdir, "handoffs"))
            # 构造 single-role 单元触发 direct 分支
            test_data = {
                "unit_id": "test-nostate",
                "industry": "测试行业NS",
                "industry_alias": ["测试行业NS"],
                "roles": [
                    {"name": "role_solo", "prefix": "[S]", "composite": True,
                     "keywords": ["独立需求"]},
                ],
            }
            tf = os.path.join(tmpdir, "industry-register-test-ns.yaml")
            with open(tf, "w", encoding="utf-8") as f:
                yaml.dump(test_data, f, allow_unicode=True)
            reg = Registry(search_paths=[tmpdir])
            planner = CompositePlanner(reg, handoff_bus=bus)
            router = IntentRouter(reg)
            result = router.route("我要做独立需求")

            # 默认 persist_state=True（状态变更路径）：应调用 _ensure_state_card
            with mock.patch.object(planner, "_ensure_state_card",
                                   return_value="fake-sid") as mock_ensure:
                plan = planner.plan_from_result(result, "我要做独立需求")
                assert plan["mode"] == "direct"
                assert plan["state_card_id"] == "fake-sid"
                mock_ensure.assert_called_once()

            # persist_state=False（GET 只读路径）：不应调用 _ensure_state_card
            with mock.patch.object(planner, "_ensure_state_card",
                                   return_value="should-not-be-called") as mock_ensure2:
                plan_ro = planner.plan_from_result(
                    result, "我要做独立需求", persist_state=False)
                assert plan_ro["mode"] == "direct"
                assert plan_ro["state_card_id"] is None
                mock_ensure2.assert_not_called()

    def test_persist_state_false_no_state_file_written(self):
        """评审：persist_state=False 时直接验证磁盘无 state 文件新增。

        使用临时 cwd 和数据文件，GET 只读路径不触发任何 data/state/ 写入。
        """
        import tempfile
        from hanghang.engine import (IntentRouter, CompositePlanner,
                                     HandoffBus, Registry)
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            # 在 tmpdir 下建 data 目录和 state 目录
            data_dir = os.path.join(tmpdir, "data")
            state_dir = os.path.join(data_dir, "state")
            os.makedirs(state_dir, exist_ok=True)

            # 构造一个触发 direct 分支的单元文件
            test_data = {
                "unit_id": "test-nsf",
                "industry": "测试行业NSF",
                "industry_alias": ["测试行业NSF"],
                "roles": [
                    {"name": "role_f", "prefix": "[F]", "composite": True,
                     "keywords": ["独立文件需求"]},
                ],
            }
            tf = os.path.join(data_dir, "industry-register-test-nsf.yaml")
            with open(tf, "w", encoding="utf-8") as f:
                yaml.dump(test_data, f, allow_unicode=True)

            bus = HandoffBus(data_dir=os.path.join(tmpdir, "handoffs"))
            reg = Registry(search_paths=[data_dir])
            planner = CompositePlanner(reg, handoff_bus=bus)
            router = IntentRouter(reg)
            result = router.route("我要做独立文件需求")

            # 记录当前 state 目录文件数
            files_before = set(os.listdir(state_dir))

            # persist_state=False：不创建 state 卡文件
            plan_ro = planner.plan_from_result(
                result, "我要做独立文件需求", persist_state=False)
            assert plan_ro["mode"] == "direct"
            assert plan_ro["state_card_id"] is None

            files_after = set(os.listdir(state_dir))
            assert files_after == files_before, (
                f"persist_state=False 不应新增 state 文件: "
                f"{files_after - files_before}"
            )

    def test_web_route_get_passes_persist_state_read_only(self):
        """源码检查：Web GET 只读路径必须传 persist_state=False 关闭 StateCard。"""
        server_py = os.path.join(
            os.path.dirname(__file__), "../src/hanghang/web/server.py")
        with open(server_py, encoding="utf-8") as f:
            src = f.read()
        # _do_route 中 persist_state 应按 record_metrics(仅POST为True)联动
        assert "persist_state=record_metrics" in src, (
            "GET(record_metrics=False) 应传 persist_state=False 保持只读"
        )

    def test_init_engines_thread_safe(self):
        """评审：_init_engines() 惰性初始化需线程安全（双检查锁）。"""
        server_py = os.path.join(
            os.path.dirname(__file__), "../src/hanghang/web/server.py")
        with open(server_py, encoding="utf-8") as f:
            src = f.read()
        # 应有 import threading
        assert "import threading" in src, "应导入 threading"
        # _init_engines 应使用锁进行 double-check
        assert "_engine_lock" in src, "应定义 _engine_lock"
        assert "with _engine_lock:" in src, "应使用 with _engine_lock 保护初始化"

    def test_web_route_get_passes_create_handoff_read_only(self):
        """源码检查：Web GET 只读路径必须传 create_handoff 关闭自动建卡。"""
        import re
        server_py = os.path.join(
            os.path.dirname(__file__), "../src/hanghang/web/server.py")
        with open(server_py, encoding="utf-8") as f:
            src = f.read()
        # _do_route 中 create_handoff 应按 record_metrics(仅POST为True)联动
        assert "create_handoff=record_metrics" in src,             "GET(record_metrics=False) 应传 create_handoff=False 保持只读"

    def test_post_route_direct_records_role_hits(self):
        """评审#3：direct 模式记录指标时岗位维度取 result.roles，不得低估。

        旧实现取 plan.roles，而 direct 分支的 plan 无 roles 键(仅有单 role)
        → role_hits 空。修复后 direct 路由应如实累加岗位命中。
        """
        # 先读取当前 role_hits
        _, m0 = self._get("/api/metrics")
        before = m0["metrics"]["role_hits"].get("contract_advisor", 0)

        # POST 一条 direct 意图（命中 legal-services 的 contract_advisor 单岗位）
        body = json.dumps({"text": "帮我审一份采购合同"}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/api/route",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
        assert data["plan"]["mode"] == "direct"

        _, m1 = self._get("/api/metrics")
        assert m1["metrics"]["role_hits"].get("contract_advisor", 0) == before + 1, (
            "direct 路由的岗位命中应被记录到 role_hits"
        )

    def test_metrics_concurrent_updates_no_loss(self):
        """评审#2：MetricsCollector 并发记录不丢更新（线程安全）。"""
        from hanghang.engine.metrics import MetricsCollector
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            m = MetricsCollector(data_file=os.path.join(tmpdir, "m.json"))
            N = 40
            threads = []
            results = []
            def worker():
                for _ in range(10):
                    m.record_route(mode="direct", unit_id="u", roles=["r"])
            for _ in range(N):
                t = threading.Thread(target=worker)
                threads.append(t)
                t.start()
            for t in threads:
                t.join()
            summary = m.get_summary()
            # 40 线程 x 10 次 = 400 次，全部计入
            assert summary["total_routes"] == N * 10,                 f"并发丢更新: total_routes={summary['total_routes']} 预期 {N*10}"
            assert summary["role_hits"].get("r") == N * 10

    def test_handoff_concurrent_creation_no_corruption(self):
        """评审#2：HandoffBus 并发创建交接卡不产生文件交错/损坏。

        用不同的 source_unit 使 card_id 各异（避免同秒同 id 相互覆盖），
        验证多线程并发 create_handoff 落盘的每张卡均可完整读回、结构完好。
        """
        from hanghang.engine.handoff import HandoffBus
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            bus = HandoffBus(data_dir=os.path.join(tmpdir, "handoffs"))
            N = 30
            threads = []
            for i in range(N):
                t = threading.Thread(
                    target=lambda k=i: bus.create_handoff(f"src-{k}", "dst", "任务"))
                threads.append(t)
                t.start()
            for t in threads:
                t.join()
            # 全部成功落盘且均可解析
            nfiles = len([f for f in os.listdir(bus.data_dir) if f.endswith(".json")])
            assert nfiles == N, f"并发交接卡数量异常: {nfiles} 预期 {N}"
            # 每张卡都能读回且结构完好
            for f in os.listdir(bus.data_dir):
                if f.endswith(".json"):
                    card = bus.get(f[:-5])
                    assert card is not None
                    assert card.target_unit == "dst"
                    assert card.status == "created"


def run_tests():
    t = TestWebAPI()
    t.setup_class()
    methods = [m for m in dir(t) if m.startswith("test_")]
    failed = []
    for m in methods:
        try:
            getattr(t, m)()
            print(f"  ✅ {m}")
        except Exception as e:
            failed.append(m)
            print(f"  ❌ {m}: {e}")
    t.teardown_class()
    if failed:
        print(f"\n失败: {failed}")
        sys.exit(1)
    print("\n✅ test_web.py 全部通过")
    sys.exit(0)


if __name__ == "__main__":
    run_tests()

