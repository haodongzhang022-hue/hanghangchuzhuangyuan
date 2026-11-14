# docs/industry · 行业相关文档

本目录集中**行业单元**相关的接入规范与面向 Agent 的使用说明。

## 目录结构

```
docs/industry/
├── register-spec.md               # 单元接入规范（L1-M2 抓取 industry-register.yaml 的契约）
├── industry-partition-db.md       # M11 行业分区定义库（职业=最小单位，行业=聚类结果）
├── industry-db-import.md          # 可导入产物：双方言 DDL + 数据 SQL，怎么把库装进去
├── industry-scales-and-money-flows.md  # 六口径规模账 + 资金流守恒账（行业不会隐身 / 钱不会漏）
├── occupation-catalog.md          # 职业分类大典参考表（1636 个职业 + 国家标准编码）
├── global-framework.md            # 全球分类框架（职业/行业/税收/产出 四根轴 + 国外体系与接法）
├── dongjiagoushi-m1-routing.md    # 首行业单元外挂验证（dongjiagoushi × M1 自动路由）
└── units/                         # 面向 AI Agent 的行业使用说明（按行业一份 README）
    ├── INDEX.md                   # 全行业汇总索引
    ├── _template/README.md        # 新增行业的标准模板
    └── <unit_id>/README.md        # 每个行业一份 agent 使用说明
```

## 两类文档的定位

| 文档 | 读者 | 用途 |
|------|------|------|
| `register-spec.md` | **行业单元开发者** | 接入规范：如何写 `industry-register.yaml` 让本层能路由 |
| `units/<unit_id>/README.md` | **上层/下游 AI Agent** | 使用说明：某行业「是什么/能做什么/有哪些岗位/怎么触发/受什么约束」 |

> **关键**：`units/` 下的行业使用说明面向 Agent，会被 `.cnb.yml` 知识库收录，
> 可通过检索注入到需要使用该行业的 Agent 提示词中。即使某行业机制尚不完善，
> 也可先用 `_template/` 建占位目录（状态标 `🟡 placeholder`），后续再补。
