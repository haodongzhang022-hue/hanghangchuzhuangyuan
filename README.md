# 行行出状元 · 通用能力层

跨行业/跨岗位的路由编排总层。把各「行业单元」（如 dongjiagoushi 架构团队）当原子收编，在其上叠一层「自动识别行业/岗位 → 路由 → 交接 → 交叉 → 复合装配」的总编排层。

## 架构分层

```
L2 人类端点    = 仅入口(意图确认) + 出口(复核)
L1 通用能力层  = 本仓库：识别路由(M1) / 注册表(M2) / 前缀档案(M3)
               / 会话编排(M4) / 交接总线(M5) / 复合装配(M6)
               / 指标观测(M7) / 能力索引(M8) / 状态管理(M9)
L0 行业单元层  = 各行业单元(如 dongjiagoushi)，原子化收编
```

## 数据驱动设计（核心亮点）

**新增行业单元只需更新注册数据，无需修改代码。**

各单元在其注册文件中声明 `keywords`（岗位触发词），路由引擎从数据动态读取识别信号。当前已注册（8个行业单元）：

| 单元 | 行业 | 岗位 |
|------|------|------|
| dongjiagoushi | 软件研发 | secretary / architect / developer / reviewer / product |
| game-dev-unit | 游戏研发 | game_planner / level_designer / game_dev |
| legal-services | 法律咨询 | legal_counsel / contract_advisor / compliance_advisor |
| content-creation | 内容创作 | copywriter / media_operator / content_editor |
| data-analytics | 数据分析 | data_analyst / data_scientist / bi_engineer |
| e-commerce | 电子商务 | store_manager / ecom_marketer / customer_service |
| finance-accounting | 财务会计 | accountant / tax_advisor / finance_analyst / payroll_processor |
| marketing | 市场营销 | market_researcher / brand_planner / campaign_planner / pr_manager |

> 非重点/非大型行业默认集中本仓（`repo_ref` 留空待回填），较大行业才拆独立仓。

新增单元时只需在 `data/unit-index.yaml` 或 `data/industry-register.yaml` 中追加声明。

## 快速开始

### 安装依赖
```bash
pip install -r requirements.txt
```

### 命令行用法

```bash
# 路由识别：对一句话意图做路由判定
python3 src/hanghang/cli/main.py route "既要架构设计又要落地开发"
# => 复合装配: dongjiagoushi 同session并装岗位 ['architect', 'developer']

python3 src/hanghang/cli/main.py route "帮我点个外卖"
# => 置信度不足，回落 L2 人工确认

# 列出已注册单元
python3 src/hanghang/cli/main.py units

# 按关键词多维搜索行业能力索引（M8，可加 --mode 指定 industry/capability/role 维度）
python3 src/hanghang/cli/main.py search "合同"
python3 src/hanghang/cli/main.py search "数据" --mode role

# 导出全量跨行业能力索引（含 能力标签→承接岗位 映射，供可视化聚合）
python3 src/hanghang/cli/main.py index

# 检测跨行业诉求并自动编排交接（M5）
python3 src/hanghang/cli/main.py cross-unit "需要软件架构设计并做游戏关卡策划"

# 查看运行指标
python3 src/hanghang/cli/main.py metrics

# 创建跨单元交接卡
python3 src/hanghang/cli/main.py handoff --source dongjiagoushi --target game-dev-unit --intent "需要游戏单元提供策划支持"

# M9 状态管理（StateCard/折叠/层级提交/秘书长多级树）
python3 src/hanghang/cli/main.py state init --session demo --objective "实现状态管理"
python3 src/hanghang/cli/main.py state add --session demo --title "设计数据模型" --files "models.py"
python3 src/hanghang/cli/main.py state add --session demo --title "实现折叠引擎" --files "fold_engine.py"
python3 src/hanghang/cli/main.py state add --session demo --title "交付完整模块" --type deliverable
python3 src/hanghang/cli/main.py state update --session demo --task demo-0001 --state done
python3 src/hanghang/cli/main.py state fold --session demo
python3 src/hanghang/cli/main.py state show --session demo
python3 src/hanghang/cli/main.py state compact --session demo
python3 src/hanghang/cli/main.py state submit --session demo --upstream parent

# M9 秘书长多级树（多级拓扑管理）
python3 src/hanghang/cli/main.py tree init --name project --display "秘书长" --objective "全局管理"
python3 src/hanghang/cli/main.py tree register --name project --session sub-a --display "秘书A" --parent project
python3 src/hanghang/cli/main.py tree register --name project --session leaf-1 --role developer --parent sub-a
python3 src/hanghang/cli/main.py tree show --name project          # 渲染树导航视图
python3 src/hanghang/cli/main.py tree rollup --name project        # 逐级向上汇总
python3 src/hanghang/cli/main.py tree submit-chain --name project --session leaf-1

# M9 秘书并发归属与冲突仲裁（多 Agent 协作写同一状态）
python3 src/hanghang/cli/main.py state claim   --session demo --role 秘书A   # 声明归属/占用
python3 src/hanghang/cli/main.py state status  --session demo --role 秘书A   # 查看 owner/version
python3 src/hanghang/cli/main.py state release --session demo --role 秘书A   # 释放归属
# 说明：多秘书并发写同一 StateCard 时，基于乐观版本号(base_version)仲裁；
#       基于旧版本写会抛 StateConflict 而非静默覆盖，归属越权写会抛 OwnershipDenied。

# M9 POC 量化验证（状态管理 vs 全量历史对比）
python3 poc/state_m9_benchmark.py --steps 50 --verbose
```

### 运行测试
```bash
python3 tests/test_router.py        # 路由引擎
python3 tests/test_registry.py      # 注册表与元数据
python3 tests/test_handoff.py       # 交接总线
python3 tests/test_data_driven.py   # 数据驱动 + 复合边界 + 交接自动集成
python3 tests/test_review.py        # 评审机制
python3 tests/test_industry_expansion.py  # 行业扩展 + M8 能力索引增强
python3 tests/test_state_manager.py    # M9 状态管理层（StateCard/折叠/层级提交）
python3 tests/test_state_tree.py       # M9 秘书长多级树 + 主链路集成
python3 tests/test_state_ownership.py # M9 秘书并发归属与冲突仲裁

# 或全部一键
python3 scripts/run_all_tests.py
```

## 数据文件

- `data/industry-register.yaml` — 行业单元注册声明（M2 数据源）
- `data/unit-index.yaml` — 跨行业单元索引（M8）
- `data/prefix-archive.json` — 稳定前缀档案（M3，含全部5单元，版本化提交）
- `data/metrics.json` — 运行指标（M7，自动生成）
- `data/state/` — 状态卡 JSON（M9，自动生成）

## 复合装配的边界规则（评审补强① 已落实）

同一行业多岗位复合时，自动按**依赖序**排列（如 `product → architect → developer → reviewer`）。
岗位间通过交接卡传递产物，不互相污染记忆（`role_isolation: handoff_card_only`）。

```
产品规划 → 架构方案 → 编码实现 → 评审
（前一岗位产物作为下一岗位输入，各自session独立）
```

## 文档索引

- 顶层架构: `docs/architecture/ARCHITECTURE.md`
- 需求基线: `docs/architecture/通用能力-需求澄清基线.md`
- 单元接入规范: `docs/industry/register-spec.md`
- POC验证记录: `poc/`

## 自动评审机制

本仓库已同步自动代码评审闭环机制（参考自 dongjiagoushi / youxikaifaxilieagent）。

### 机制流程

```
PR 提交 → 测试信号灯 → NPC 代码审查 → 需修改？→ CodeBuddy 自动修复
                                              │           │
                                              │ 不需要     │ 修复后触发下一轮
                                              ▼           ▼
                                        评审通过 → 合并门禁 → 自动合并
                                              │
                                              ▼
                                        main 合并 → 全量回归
```

### 触发事件

| 事件 | 动作 |
|------|------|
| `pull_request` | 自动跑测试 + NPC 代码审查 + 修复闭环 |
| `pull_request.mergeable` | 评审通过后自动合并 |
| `pull_request.changes_requested` | CodeBuddy 自动修复 |
| `pull_request.comment@npc` | 手动 @CodeBuddy 兜底 |
| `main.push` | 全量回归 + 知识库更新 |

### 评审相关文件

- 流水线配置: `.cnb.yml`
- NPC 角色: `.cnb/settings.yml`
- 评审闭环规则: `docs/评审修复闭环护栏.md`
- 测试脚本: `scripts/`
