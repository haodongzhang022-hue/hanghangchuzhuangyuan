"""Web 可视化聚合面板 API 测试"""
import json
import os
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

