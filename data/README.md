# 数据文件说明

本目录存储通用能力层路由编排系统的数据文件。

## 手动维护
- `industry-register.yaml` — 行业单元注册声明（M2 数据源）
- `unit-index.yaml` — 跨行业单元索引（M8，路由索引视图）

## 自动生成
- `prefix-archive.json` — M3 稳定前缀档案（运行引擎时自动创建，已 gitignore）
- `metrics.json` — M7 运行指标（运行引擎时自动创建，已 gitignore）
- `handoffs/` — M5 交接卡存储目录（运行时自动创建，已 gitignore）
