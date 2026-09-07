# 数据文件说明

本目录存储通用能力层路由编排系统的数据文件。

## 手动维护
- `industry-register.yaml` — 行业单元注册声明（M2 数据源）
- `unit-index.yaml` — 跨行业单元索引（M8，路由索引视图）
- `coverage-target.yaml` — 行业岗位覆盖**目标全集**（分母）；与 unit-index 比对得整体目标 vs 当前覆盖率的进度，多渠道搜集补全时在此登记

## 版本化数据（随代码提交）
- `prefix-archive.json` — M3 稳定前缀档案（含全部行业单元的岗位前缀快照，与注册数据保持同步）

## 运行期自动生成（gitignore）
- `metrics.json` — M7 运行指标（运行引擎时自动创建）
- `handoffs/` — M5 交接卡存储目录（运行时自动创建）
