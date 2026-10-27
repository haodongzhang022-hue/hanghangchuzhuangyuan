# 功能交付 v12 · M11 行业分区定义库

**来源**：ISSUE #19（进度和目标掌控）后续诉求 ——
"把目前各个行业的分区形成定义表/数据库；先把都包含什么行业形成表；
列出人类和 AI 存在的行业/职业、付费方与服务提供者/生产力提供者；
有市场产值列表；**把他们聚类，这才形成行业**——
之前的职业才是真正解耦合的单目标，不会被命名方式影响和缺漏。"

## 交付内容

| 项 | 位置 |
|---|---|
| 职业表（最小单目标，稳定主键） | `data/industry-occupations.yaml`（147 个职业，基线 139） |
| 分区表（聚类结果 + 付费方 + 产值口径） | `data/industry-partitions.yaml`（37 分区：14 已建 / 18 待建 / 5 评估不建） |
| 引擎 | `src/hanghang/engine/industry_db.py` |
| CLI | `src/hanghang/cli/industry_commands.py`（`industry partitions/partition/occupations/check/export`） |
| REST | `GET /api/industry-db`（只读，含 `problems` 自检） |
| 文档 | `docs/industry/industry-partition-db.md` |
| 测试 | `tests/test_industry_db.py`（9 项）+ `test_coverage.py` 权威性断言 + `test_web.py` 端点断言 |

## 当前进度快照

```
分区: 14/32 已建单元 (43.8%)   另 5 个评估后不建单元(不计分母)
职业: 50/139 基线 (36.0%)      全量登记 147 个
供给结构(按成员职业加权): AI 46.0% / 混合 42.4% / 纯人 11.6%
```

## 设计取舍

1. **不让分区重复存职业清单**。成员一律由 `occupation.unit_id` 反查，
   从根本上消灭"两份清单分叉"这一类脏数据。
2. **`evaluated` 状态**。评估后明确不建单元的分区（矿业、公用事业、水利海洋、
   国际组织、公共安全）不进分母，否则覆盖率永远追不满。
3. **产值留空而非填 0**。`admin-office`/`public-affairs`/`international-org`
   没有市场付费口径，`gdp_cny: null` 且 `gdp_source: 不适用，刻意留空`。
   排序时 `null` 不参与，不会把"无口径"误读成"零产值"。
4. **不引入外部数据库服务**。yaml 作为权威源；`export` 产出 sqlite + csv，
   借 CNB 制品库分发，零部署、可 diff、可被知识库直接切片。
5. **coverage 岗位基线改以职业库为准**。`coverage-target.yaml` 的 `target_roles`
   降级为兜底，避免两处手写岗位漂移。

## 验证

- `python3 tests/test_industry_db.py` → 通过
- `bash scripts/change-aware-test.sh` → 24 个测试文件全部通过（含 CLI 冒烟）
- `python3 src/hanghang/cli/main.py industry check` → 37 分区 / 147 职业，双向对齐无缺口

## 后续（待拍板）

- 待建 18 个分区的职业需按渠道补齐（每个分区已登记 `channels` 数据来源）。
- 二级聚类：制造业/建筑工程这类大分区目前只做一级，需要按子行业再聚一次。
- 产值口径校准：当前为量级估算，需要用国家统计局分行业增加值/营业收入逐年对齐。
