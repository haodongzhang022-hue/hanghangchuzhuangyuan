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
