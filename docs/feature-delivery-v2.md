# 功能特性交付索引（行业扩展第二期 + 路由覆盖补全）

> 版本：auto/expand-industry | 2026-09-06 | 同步人：CodeBuddy
> 本文档向项目协作方同步本阶段开发的功能特性与进度。

---

## 1. 总览

本阶段围绕「**行业横向扩展 + 路由盲区覆盖**」两条主线开发：

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-09 | 软件研发覆盖盲区补全（网站/网页/小程序/前端等） | ✅ 已完成 | data/unit-index.yaml, src/router.py |
| F-10 | game_planner 裸词"策划"收敛，避免营销误判 | ✅ 已完成 | data/unit-index.yaml |
| F-11 | 新增 e-commerce 电商单元（3岗） | ✅ 已完成 | data/unit-index.yaml |
| F-12 | 新增 finance-accounting 财务会计单元（4岗） | ✅ 已完成 | data/unit-index.yaml |
| F-13 | 新增 marketing 市场营销单元（4岗） | ✅ 已完成 | data/unit-index.yaml |
| F-14 | 软件构建意图同分时跳过歧义回落 | ✅ 已完成 | src/router.py |
| F-15 | 行业单元总数 5→8 | ✅ 已完成 | data/unit-index.yaml |

---

## 2. 功能详述

### F-09 软件研发覆盖盲区补全

**问题**：dongjiagoushi 原关键词仅覆盖"软件/系统/工具/代码"等，大量常见 Web 开发请求无法被识别：
- "帮我做个网站" / "帮我做个小程序" / "帮我搭个前端页面" → 均无法命中，回落人工

**修复**：
- `industry_alias` 新增：网站、小程序、网页、前端、后端、程序员、编程、Web开发、官网、代码、程序、应用
- `developer` 岗位关键词新增：做网站、做网页、网页、前端、后端、小程序、爬虫、CRM、ERP、官网等
- `capability_tags` 新增：网站建设、Web开发、小程序开发、应用开发、软件开发

### F-10 game_planner 裸词"策划"收敛

**问题**："策划"单独出现在 game_planner 关键词中导致营销/活动策划类请求被误路由到游戏行业。

**修复**：game_planner 不再含裸词"策划"，仅保留游戏专属策划表达：玩法、数值策划、游戏设计、游戏策划、游戏玩法等。

### F-11 ~ F-13 新增三个行业单元

| 单元 | 行业 | 岗位 | 关键覆盖场景 |
|------|------|------|------------|
| e-commerce | 电子商务 | store_manager / ecom_marketer / customer_service | 开店/上架/运营推广/客服 |
| finance-accounting | 财务会计 | accountant / tax_advisor / finance_analyst / payroll_processor | 做账/报税/财务分析/工资核算 |
| marketing | 市场营销 | market_researcher / brand_planner / campaign_planner / pr_manager | 市场调研/品牌策划/活动策划/公关 |

全部纯数据驱动，仅更新 `data/unit-index.yaml` 即可新增，无需修改核心代码。

### F-14 软件构建意图同分时跳过歧义回落

**问题**："写一个合同管理功能的代码"场景下，dongjiagoushi 和 legal-services 同时获得 3.5 分，触发歧义回落人工。

**修复**：当最佳单元已是软件研发单元且文本确认为软件构建意图时，同样触发 `software_override` 跳过歧义回落，业务名词（如"合同"）仅是软件构建目标。

### F-15 行业单元总数 5→8

| 原5行业 | 新增3行业 |
|---------|----------|
| 软件研发 / 游戏研发 / 法律咨询 / 内容创作 / 数据分析 | 电商 / 财务会计 / 市场营销 |

---

## 3. 数据文件变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `data/unit-index.yaml` | 修改 | 新增3行业 + 软件关键词补全 |
| `data/industry-register.yaml` | 修改 | dongjiagoushi 数据同步 |
| `data/prefix-archive.json` | 修改 | 新增3行业前缀档案 |
| `src/hanghang/engine/router.py` | 修改 | SOFTWARE_BUILD_TERMS 扩展 + 同分软件改判修复 |
| `tests/test_industry_expansion_v2.py` | 新增 | 行业扩展第二期测试 |
| `README.md` | 修改 | 行业表更新至 8 行业 |

---

## 4. 测试覆盖

- 原有 **71+ 测试全部通过**（7 个测试文件）
- 新增 **tests/test_industry_expansion_v2.py**（约 200 行），覆盖：
  - 8 行业单元注册
  - 新行业单元路由（电商/财务/营销）
  - 软件 Web 开发盲区场景（网站/小程序/前端等）
  - 营销策划不再误判到游戏
  - 内容创作不受营销新增影响
  - 新行业前缀档案

## 5. 路由能力演示

```bash
# 软件 Web 开发盲区覆盖
python3 src/hanghang/cli/main.py route "帮我做个网站"  
# => dongjiagoushi@developer

python3 src/hanghang/cli/main.py route "帮我做个小程序"
# => dongjiagoushi@developer

# 营销策划不再误判游戏
python3 src/hanghang/cli/main.py route "帮我做市场营销策划"
# => marketing@campaign_planner

# 新行业
python3 src/hanghang/cli/main.py route "帮我在淘宝开个网店"
# => e-commerce@store_manager

python3 src/hanghang/cli/main.py route "帮我做财务分析"
# => finance-accounting@finance_analyst
```

---

## 6. 后续可开发方向

1. 更多行业单元扩展（设计/教育培训/翻译等）
2. Web 可视化聚合面板
3. 交接卡生命周期管理增强
