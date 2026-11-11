# 功能交付索引 · v12（M11 岗位画像层）

> Issue #31 | 2026-10-29

## 交付内容

| # | 能力 | 入口 | 文件 |
|---|------|------|------|
| 1 | 岗位画像六维评估表（分析/画像/插件/工作流/利益链条/核心能力） | 数据 | `data/role-profiles/*.yaml`（14 单元，注册岗位全覆盖） |
| 2 | 数据契约与评分口径（不做在代码里） | 数据 | `data/rolecard-schema.yaml` |
| 3 | 可复用工作流模板（通用工序，岗位只写覆盖） | 数据 | `data/workflow-templates/*.yaml`（5 套） |
| 4 | 岗位卡渲染器（画像×注册表×模板×上游技能包） | `scripts/gen_rolecards.py` | 产物 `data/rolecards/*.yaml` |
| 5 | 就绪度评分（0-100 + A/B/C/D + 缺口清单） | `role readiness` / `role list` | `src/hanghang/rolecard/readiness.py` |
| 6 | 工作流 playbook（text/json/n8n/code 四形态导出） | `role playbook --format` | `src/hanghang/rolecard/workflow.py` |
| 7 | 岗位卡查看/上下文渲染 | `role show` / `role context` | `src/hanghang/cli/rolecard_commands.py` |
| 8 | M1 路由接入画像激活权重 | `route` | `engine/router.py::_activation_weight` |
| 9 | M10 装配注入岗位卡（层A静态块，缓存稳定） | `context assemble`（可 `--no-rolecard` 关闭） | `context/assembler.py::rolecard_provider` |
| 10 | 上游快照收编（只读，离线渲染数据源） | — | `vendor/upstream/knowledge-work-plugins/` |

## 关键设计决定

1. **双源分离**：人写画像基线（慢变），机器渲岗位卡（可 diff/review）。改画像不被生成覆盖，改生成不乱改画像。
2. **缺字段不报错**：行业成熟度不齐是常态。缺就扣分 + 记缺口，让"还差什么"可见，而不是拒收半成品。
3. **工作流按步骤 id 合并**：岗位只覆盖要改的步骤，模板演进能自动继承到所有岗位。
4. **路由权重数据化**：岗位承接意愿写在画像 `activation.weight`，不再硬编码在路由引擎里。
5. **缓存安全**：岗位卡只进层A，且内容只由画像数据决定 → 同岗位跨 session 缓存键一致（有测试断言）。

## 验收

```bash
python3 tests/test_rolecard_m11.py                 # M11 专项 13 用例
python3 scripts/gen_rolecards.py --readiness        # 就绪度总览
python3 src/hanghang/cli/main.py role list          # 岗位就绪度表
python3 src/hanghang/cli/main.py role show architect --unit dongjiagoushi   # 六维全貌
bash scripts/change-aware-test.sh                   # 变更感知回归
python3 scripts/run_all_tests.py                    # 全量回归
```

## 追加：与 M11 行业分区库合并后的收口（PR #32 × main）

两条 M11 线（岗位画像层 / 行业分区定义库）原先各自占用了 v12 编号，合到一条分支上时撞在一次。
现在按先进 main 的顺序定号：**v12 = 行业分区定义库**（已在 main），**v13 = 补全与视角分离**，
**v14 = 本文（岗位画像层）**。

合并不只是挪文件，两处语义冲突按「谁的主张更硬」判：

1. **单个岗位的分必须允许被权重放大，但单元总分不许**。
   `main` 的跨单元让位规则（长词认领）与画像权重是正交的：让位决定「这次命中算不算」，
   权重决定「算多少」。合并后 `1.5 × weight` 只作用于岗位分与单元内排序，
   `_score_units` 不因权重抬高整个行业得分——共享词照样走歧义护栏。
   实测 `直播选品` / `直播间的选品` 归 `content-creation@live_host`，
   裸 `选品` / `商品选品` 归 `e-commerce@store_manager`，`核算工资` 不串到财务。
2. **画像缺失必须在库里也表达为「缺失」**。
   合并后暴露出一个真缺陷：注册表有、画像还没写的岗位，写库时会落一行全空的
   `role_profile`，读回来变成「有画像但六维全空」，`build_role_db.py --check` 直接误报，
   调用方也分不清「没写」和「写了空」。现在缺行就是缺行，读回 `profile=None`；
   `workflow` 的外键也从 `role_profile` 改挂 `industry_role`——**工序来自模板与注册表信号，
   不该因为画像还没写就落不进去**。

顺带给合并带进来的 `live_host` 补了六维画像（原先只有路由关键词、没有画像，
就绪度 D/0 分）。写画像时一并暴露了两处数据缺口：链条要用的「观众」类目没登记
（已补进 `data/industry-classes/demand.yaml`，带索引），
「打赏/佣金」双口径混用会让复盘失真（写进 `risk_notes`，不做数字合并）。

守卫各一条，都做过「改回缺陷 → 确认变红 → 还原」：
`test_role_without_profile_roundtrips_as_none`、`test_coverage_summary_follows_filter`。
