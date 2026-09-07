# dongjiagoushi 走 M1 自动路由验证（T3 落地文档）

> 架构·开发 | T3「首行业单元外挂验证」 | dongjiagoushi = 本体系首个/旗舰行业单元
> 目标：证明 `dongjiagoushi`（软件研发 · 架构团队）能作为**首行业单元被通用能力层 M1
> 意图路由自动识别并落地**，为后续行业单元接入提供范式与回归护栏。

---

## 1. 验证对象

- **源单元**：`dongjiagoushi`（`https://cnb.cool/dongdongxiaozu/dongjiagoushi`）
- **行业**：软件研发
- **可路由岗位**：secretary / architect / developer / reviewer / product
- **注册数据源**：`data/unit-index.yaml`、`data/industry-register.yaml`

M1 自动路由按「行业识别 → 岗位识别」两级判定，命中后**无需人工切模式**即路由到 dongjiagoushi 对应岗位。

## 2. 路由用例与验证结论

以下用例均经真实 CLI `route` 命令跑通（`main` 基线）：

| # | 意图 | 期望行业 | 期望岗位 | 模式 | 结果 |
|---|------|---------|---------|------|------|
| R1 | 帮我做一套软件架构设计方案 | 软件研发 | architect | direct | ✅ |
| R2 | 既要架构设计又要开发编码，还要做产品规划 | 软件研发 | product+architect+developer | composite | ✅ |
| R3 | 帮我搭个前端网站 | 软件研发 | developer | direct（软件构建联合判定） | ✅ |
| R4 | 帮我设计并编码一个数据分析工具 | 软件研发 | developer | direct | ✅ |

### 验证细节

- **R1 单直连**：`unit=dongjiagoushi, roles=['architect'], 模式=direct, 会话前缀=[架构]`
- **R2 复合装配（M6）**：`roles=['product','architect','developer']`，
  稳定前缀集 `['[产品]','[架构]','[开发]']`，执行顺序 `product → architect → developer`，
  岗位经交接卡隔离传递产物（`role_isolation: handoff_card_only`）。
- **R3 软件构建意图**：制品词（网站/网页…）不再劫持行业识别，由
  `_is_software_build_intent` 联合判定（构建动词+产物名词）落回 dongjiagoushi@developer；
  置信度 0.6 放行。
- **R4 复合短语编码**：`设计并编码…工具` 命中文档能力标签，稳定路由 developer。

## 3. M3 稳定前缀约束（外挂验证要点）

dongjiagoushi 走 M1 后由 M3 前缀档案给出该单元**稳定前缀集**：
`['[秘书]','[架构]','[开发]','[评审]','[产品]']`。

- 一个 session 只路由 dongjiagoushi 一套岗位 → 前缀稳定、缓存命中不漂移。
- 复合装配时取命中岗位的稳定前缀并集，零突变。
- 数据档案在 `data/prefix-archive.json` 版本化，与注册表一致。

## 4. 导出回归护栏

验证脚本输出与 M8 能力索引一致：

```
dongjiagoushi [软件研发]  entry=https://cnb.cool/dongdongxiaozu/dongjiagoushi
  岗位: [秘书]secretary / [架构]architect / [开发]developer / [评审]reviewer / [产品]product
```

## 5. 结论

dongjiagoushi 作为首行业单元，M1 自动路由（单直连/复合装配/软件构建判定）全部正确落地，
M3 稳定前缀与 M8 能力索引同步一致，**外挂验证通过**，可作为其它行业单元接入本通用能力层的参照范式。

> 复跑：`python3 src/hanghang/cli/main.py route "<意图>"`
