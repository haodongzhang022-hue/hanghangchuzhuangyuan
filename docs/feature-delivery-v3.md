# 功能特性交付索引（Web 可视化聚合面板）

> 版本：auto/web-console | 2026-09-06 | 同步人：CodeBuddy
> 本文档向项目协作方同步本阶段开发的 Web 可视化聚合面板。

---

## 1. 总览

本阶段实现用户前期设定的「页面交互形态」，即前端只做聚合 + 可视化，作为 L2 人类端点的可视化入口。核心引擎 M1-M8 全部由 CLI 形态暴露，本期新增 **Web REST API + 单页控制台**双形态。

| 功能编号 | 功能名称 | 状态 |
|---------|---------|------|
| F-18 | Web HTTP API Server | ✅ 已完成 |
| F-19 | 单页聚合控制台页面 | ✅ 已完成 |
| F-20 | CLI serve 命令 | ✅ 已完成 |
| F-21 | Web API 自动化测试 | ✅ 已完成 |

---

## 2. 功能详述

### F-18 Web HTTP API Server

纯 Python 标准库实现（`http.server`），零新增第三方依赖。位于 `src/hanghang/web/server.py`。

提供以下 API 端点：

| 端点 | 方法 | 功能 | 对应引擎模块 |
|------|------|------|------------|
| `/api/units` | GET | 行业单元总览（全部8个单元 + 岗位 + 关键词 + 能力标签） | M2 |
| `/api/route?text=...` | GET | 意图路由识别（自然语言 → 行业/岗位） | M1/M4/M6 |
| `/api/route` | POST | 意图路由识别（JSON body） | M1/M4/M6 |
| `/api/search?kw=..&mode=..` | GET | 能力索引多维搜索（industry/capability/role/any） | M8 |
| `/api/index` | GET | 全量能力索引（能力标签 → 承接岗位） | M8 |
| `/api/metrics` | GET | 运行指标（自动成功率/复合/人工介入） | M7 |
| `/api/handoffs` | GET | 待处理交接卡 | M5 |
| `/api/prefixes` | GET | 各行业稳定前缀档案 | M3 |

每次 `/api/route` 调用自动记录到 M7 指标（触发持久化）。

### F-19 单页聚合控制台页面

`src/hanghang/web/static/index.html` — 一个零构建依赖的单页 HTML/CSS/JS 控制台。

七个标签页：
1. **路由测试**：输入一句话意图即时路由，可视化展示行业/岗位/置信度/模式/稳定前缀
2. **行业单元**：聚合展示8个行业单元（别名/能力标签/岗位/入口）
3. **能力检索**：M8 跨行业能力多维搜索
4. **能力索引**：全量能力标签 → 承接岗位映射表
5. **运行指标**：M7 统计卡片
6. **前缀档案**：各行业稳定前缀展示
7. **交接卡**：M5 待处理交接卡

顶部实时统计卡片聚合显示行业数/累计路由/自动成功率/复合装配/交接/人工介入。

### F-20 CLI serve 命令

新增 `hanghang serve --host --port` 子命令启动 Web 控制台。

### F-21 Web API 自动化测试

`tests/test_web.py` — 通过本地 HTTP server 逐端点验证 11 项测试用例，覆盖全部 API。

---

## 3. 数据文件变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/hanghang/web/server.py` | 新增 | HTTP API Server |
| `src/hanghang/web/__init__.py` | 新增 | web 包入口 |
| `src/hanghang/web/static/index.html` | 新增 | 单页聚合控制台 |
| `src/hanghang/cli/main.py` | 修改 | 新增 serve 子命令 |
| `tests/test_web.py` | 新增 | Web API 测试（11项） |
| `docs/feature-delivery-v3.md` | 新增 | 本文件 |

## 4. 测试覆盖

- **8 个测试文件全部通过**（89 原有 + 新增 11 项 web 测试）
- CLI 冒烟测试通过
- Web 测试通过本地 HTTP server 端到端验证

## 5. 使用方式

```bash
python3 src/hanghang/cli/main.py serve --port 8080
# 浏览器打开 http://localhost:8080/
```

