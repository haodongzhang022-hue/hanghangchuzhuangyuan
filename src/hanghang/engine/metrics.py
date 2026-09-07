"""M7 能力/指标观测台"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List


class MetricsCollector:
    """
    M7 指标观测台：
    记录路由命中率、复合使用率、人工介入率、交接成功率等关键指标。
    """

    def __init__(self, data_file: Optional[str] = None):
        self.data_file = data_file or os.path.join(
            os.getcwd(), "data", "metrics.json")
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        self._metrics = self._load()
        # 线程锁：Web server 以 ThreadingHTTPServer 多线程复用模块级单例，
        # 并发 POST /api/route 会并行进入 record_route 做读-改-写并落盘，
        # 不加锁会丢更新 / 文件交错写。加锁串行化保证线程安全。
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 数据一致性保障：total_routes == 0 时 success_rate 必须为 None
                # （防止旧版本写入的 success_rate: 1.0 伪造"100%成功率"）
                total = data.get("total_routes", 0)
                if total == 0:
                    data["success_rate"] = None
                return data
            except Exception:
                pass
        return self._empty_metrics()

    def _empty_metrics(self) -> dict:
        return {
            "total_routes": 0,
            "direct_routes": 0,
            "composite_routes": 0,
            "handoffs": 0,
            "manual_confirmations": 0,
            "unit_hits": {},        # unit_id -> 次数
            "role_hits": {},        # role -> 次数
            "success_rate": None,
            "updated_at": "",
        }

    def record_route(self, mode: str, unit_id: str = "",
                     roles: List[str] = None) -> None:
        """记录一次路由事件（线程安全）"""
        with self._lock:
            m = self._metrics
            m["total_routes"] += 1
            if mode == "direct":
                m["direct_routes"] += 1
            elif mode == "composite":
                m["composite_routes"] += 1
            elif mode == "manual":
                m["manual_confirmations"] += 1
            elif mode == "handoff_required":
                m["handoffs"] += 1

            if unit_id:
                m["unit_hits"][unit_id] = m["unit_hits"].get(unit_id, 0) + 1
            for r in (roles or []):
                m["role_hits"][r] = m["role_hits"].get(r, 0) + 1

            # 计算成功率（直接+复合=自动成功）
            auto = m["direct_routes"] + m["composite_routes"]
            total = m["total_routes"]
            m["success_rate"] = round(auto / total, 3) if total > 0 else None
            m["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self._save()

    def get_summary(self) -> dict:
        """返回指标摘要（线程安全）"""
        with self._lock:
            m = self._metrics
            return {
                "total_routes": m["total_routes"],
                "auto_success_rate": m["success_rate"],
                "direct_routes": m["direct_routes"],
                "composite_routes": m["composite_routes"],
                "handoffs": m["handoffs"],
                "manual_confirmations": m["manual_confirmations"],
                "unit_hits": dict(m["unit_hits"]),  # 浅拷贝隔离外部引用，防并发修改
                "role_hits": dict(m["role_hits"]),  # 浅拷贝隔离外部引用，防并发修改
            }

    def _save(self):
        with open(self.data_file, "w", encoding="utf-8") as f:
            json.dump(self._metrics, f, ensure_ascii=False, indent=2)
