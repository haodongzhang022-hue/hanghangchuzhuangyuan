# 功能特性交付索引（行业扩展第二期 + 路由覆盖补全）

> 版本：auto/expand-industry | 2026-09-06 | 同步人：CodeBuddy
> 本文档向项目协作方同步本阶段开发的功能特性与进度。

---

## 1. 总览

本阶段围绕「**行业横向扩展 + 路由盲区覆盖 + 制品词劫持修复**」三条主线开发：

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-09 | 软件研发 Web 覆盖补全（网站/小程序/网页/前端等） | ✅ 已完成 | data/unit-index.yaml, src/router.py |
| F-10 | game_planner 裸词"策划"收敛，避免营销误判 | ✅ 已完成 | data/unit-index.yaml |
| F-11 | 新增 e-commerce 电商单元（3岗） | ✅ 已完成 | data/unit-index.yaml |
| F-12 | 新增 finance-accounting 财务会计单元（4岗） | ✅ 已完成 | data/unit-index.yaml |
| F-13 | 新增 marketing 市场营销单元（4岗） | ✅ 已完成 | data/unit-index.yaml |
| F-14 | 软件构建意图同分时跳过歧义回落 | ✅ 已完成 | src/router.py |
| F-15 | 行业单元总数 5→8 | ✅ 已完成 | data/unit-index.yaml |
| F-16 | 软件制品名词不再劫持行业识别（评审 critical 修复） | ✅ 已完成 | data/*.yaml, src/router.py, tests/ |
| F-17 | 业务域单元补齐网页相关作业信号 | ✅ 已完成 | data/unit-index.yaml |

---

## 2. 功能详述

### F-09 软件研发 Web 覆盖补全（评审修正版）

**问题**：dongjiagoushi 原关键词仅覆盖"软件/系统/工具/代码"等，大量常见 Web 开发请求无法被识别。

**初版方案（已被评审驳回）**：将 网站/小程序/网页/前端/后端/官网/代码/程序/应用 直接加入 industry_alias（2.0 权重）。
**问题**：凡句子含这些制品词即自动路由软件研发，使 marketing(SEO)、content(翻译/校对)、legal(版权审查)、data-analytics(运营数据) 等网页相关业务作业被误吞。

**修正方案**：
- `industry_alias` 仅保留软件工程描述词：研发、架构师、软件开发、dev、架构、软件、程序员、编程、Web开发、网站建设
- 制品名词从行业别名撤下，仅以 **构建动词/复合短语**（如"做个网站"/"搭个前端"/"搭建小程序"）承载 Web 开发落地
- 软件构建意图由 router.py 的 `_is_software_build_intent` 联合判定捕获（构建动词 + 产物名词双重信号）

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

**问题**："写一个合同管理功能的代码"场景下，dongjiagoushi 和 legal-services 同时得分，触发歧义回落人工。

**修复**：当文本确认为软件构建意图时，软件研发单元拥有决定性改判权，跳过歧义回落。业务名词（如"合同"）仅是软件被构建对象。当前已通过自动化测试验证：
- "写一个合同管理功能的代码" → dongjiagoushi@developer，conf=0.6，无需人工

### F-15 行业单元总数 5→8

| 原5行业 | 新增3行业 |
|---------|----------|
| 软件研发 / 游戏研发 / 法律咨询 / 内容创作 / 数据分析 | 电商 / 财务会计 / 市场营销 |

### F-16 软件制品名词不再劫持行业识别

**问题**：`网站/小程序/网页/前端/后端/官网/代码/程序/应用` 被作为 2.0 权重行业别名挂到软件研发，凡句子含这些制品词即自动路由软件研发，造成行业识别被制品名词劫持。

**修复**：
1. 从 dongjiagoushi `industry_alias` 撤下全部制品名词
2. 从 developer 岗位关键词撤下裸制品词（网站/网页/小程序/前端/后端/官网），保留复合构建短语
3. 将"构建动词 + 制品名词"的软件构建意图交由 `_is_software_build_intent` 联合判定
4. 当无任何行业信号命中但为明确软件构建意图时，仍可路由到软件研发

**验证**：
- "帮我的网站做SEO优化和推广" → marketing ✓（不再是软件）
- "帮我翻译这个网页内容" → content-creation ✓（不再是软件）
- "帮我审核这个网站版权风险" → legal-services ✓（不再是软件）
- "帮我分析一下网站运营数据" → data-analytics ✓（不再是软件）
- "帮我做电商网站运营" → e-commerce ✓（不再是软件）

### F-17 业务域单元补齐网页相关作业信号

为 marketing/content/legal/data-analytics/e-commerce 等行业补充网页场景作业关键词：
- **marketing**：SEO、SEO优化、搜索引擎优化、网站推广、网络推广、线上推广方案
- **content-creation**：翻译、网页文案、网站文案、网页翻译、网站翻译、改写、校对、网页编辑、网页排版
- **legal-services**：版权（industry_alias + role keywords）、版权保护、版权纠纷、版权风险、用户协议、隐私政策、服务条款
- **data-analytics**：网站数据分析、运营数据分析、流量分析、用户行为分析、流量数据、访问数据、浏览数据、点击数据
- **e-commerce**：电商网站、商城网站、电商小程序、网店小程序、电商平台运营

---

## 3. 数据文件变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `data/unit-index.yaml` | 修改 | 新增3行业 + 软件关键词收敛 + 各行业网页作业信号 |
| `data/industry-register.yaml` | 修改 | dongjiagoushi 数据同步（制品词收敛） |
| `data/prefix-archive.json` | 修改 | 新增3行业前缀档案 |
| `src/hanghang/engine/router.py` | 修改 | SOFTWARE_BUILD_TERMS 扩展 + 软件构建意图兜底路由 + 同分软件改判修复 |
| `tests/test_industry_expansion_v2.py` | 新增 | 行业扩展第二期测试 + 负向路由回归 |
| `docs/feature-delivery-v2.md` | 修改 | 本文件 |

---

## 4. 测试覆盖

- **87 个测试全部通过**（8 个测试文件）
- 新增 **负向路由回归测试**：
  - 含"网站/网页/小程序"的业务域作业不落入软件研发（marketing/content/legal/data/e-commerce）
  - 含构建动词的软件构建意图仍正确路由软件研发
- 原有全量测试（电商/财务/营销/游戏/路由/评审）全部保持通过

## 5. 路由能力演示

```bash
# 软件 Web 开发盲区覆盖（构建动词触发）
python3 src/hanghang/cli/main.py route "帮我做个网站"
# => dongjiagoushi@developer

python3 src/hanghang/cli/main.py route "帮我搭个前端页面"
# => dongjiagoushi@developer

# 网页业务作业不再误吞
python3 src/hanghang/cli/main.py route "帮我的网站做SEO优化"
# => marketing@campaign_planner

python3 src/hanghang/cli/main.py route "帮我翻译这个网页内容"
# => content-creation@copywriter

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
