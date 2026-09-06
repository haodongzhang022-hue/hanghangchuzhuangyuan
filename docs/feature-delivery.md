# 功能特性交付索引（PR #6 开发同步）

> 版本：PR #6 (auto/expand-a464) | 2026-09-06 | 同步人：CodeBuddy
> 本文档用于向项目协作方同步本阶段开发的功能特性与进度，避免脱节。

---

## 1. 总览

本阶段开发围绕「**横向扩展 + 能力索引增强**」两条主线，经过多轮评审闭环后全部合入 PR #6。核心能力从「2 行业单元路由」升级为「5 行业路由 + 跨行业能力多维检索 + 可自动索引导出」。

| 功能编号 | 功能名称 | 状态 | 涉及模块 |
|---------|---------|------|---------|
| F-01 | 行业横向扩展（2→5） | ✅ 已完成 | data/unit-index.yaml |
| F-02 | M8 能力索引多维检索 | ✅ 已完成 | src/hanghang/engine/registry.py |
| F-03 | M8 全量能力索引导出 | ✅ 已完成 | src/hanghang/engine/registry.py |
| F-04 | CLI search 多维检索 + index 命令 | ✅ 已完成 | src/hanghang/cli/main.py |
| F-05 | 软件构建意图联合判定收敛 | ✅ 已完成 | src/hanghang/engine/router.py |
| F-06 | 弱信号回落护栏 | ✅ 已完成 | src/hanghang/engine/router.py |
| F-07 | 新领域通用业务词补充 | ✅ 已完成 | data/unit-index.yaml |
| F-08 | M3 稳定前缀档案同步 | ✅ 已完成 | data/prefix-archive.json |

---

## 2. 功能详述

### F-01 行业横向扩展（2 → 5）

**背景**：「行行出状元」定位覆盖各行各业，原仅 2 个行业单元（软件研发/游戏研发），广度不足。

**新增行业单元**：
- `legal-services`（法律咨询）：legal_counsel / contract_advisor / compliance_advisor
- `content-creation`（内容创作）：copywriter / media_operator / content_editor
- `data-analytics`（数据分析）：data_analyst / data_scientist / bi_engineer

**设计要点**：纯数据驱动。仅更新 `data/unit-index.yaml` 注册数据即可新增行业，零核心代码改动。

### F-02 M8 能力索引多维检索

将 `search_capability` 从「哪个单元含词」升级为**多维检索**：
- `mode=any`：行业别名 + 能力标签 + 岗位关键词任一命中即返回
- `mode=industry`：仅按行业别名命中
- `mode=capability`：仅按 capability_tags 命中
- `mode=role`：仅按岗位关键词/描述命中

返回精确到**承接岗位 + 路由入口地址**。

### F-03 M8 全量能力索引导出

新增 `capability_index()` 方法，全量导出 **能力标签 → 承接岗位** 映射，供上层编排 / 可视化面板聚合。

### F-04 CLI 增强

- `search` 支持 `--mode` 维度过滤
- 新增 `index` 命令导出全量能力索引

### F-05 软件构建意图联合判定收敛

解决「为某业务领域开发软件被误判到业务域」的路由误判问题。修复要点：
1. **明确构建动词必需**：排除副词用法（"系统地学法律"中的"系统"）
2. **产物名词须为构建目标**：其后紧跟业务交付名词时不判构建（如"APP推广文案"）
3. **排除非构建标的**：法律著作权登记等专业业务不判软件构建
4. **单字业务词独立成词判断**：避免"审"在"审核"中被误拦

### F-06 弱信号回落护栏

软件单元自身无正分信号（仅"做一个软件"弱表达）时，不再强制抬置信到 0.6 静默放行，而是降置信 / 回落人工确认。

### F-07 新领域通用业务词补充

按评审建议，为 `data-analytics` 补充行业别名与岗位关键词：
- `industry_alias` 新增：`分析报告`、`数据报告`
- `data_analyst` 岗位新增：`分析报告`、`数据报告`
- `bi_engineer` 岗位新增：`数据报告`

提升领域召回，解决 `做一份软件使用分析报告` 等场景被误路由到软件研发的问题。

### F-08 M3 稳定前缀档案同步

将 `data/prefix-archive.json` 纳入版本控制，同步包含全部 5 个行业单元的稳定前缀档案，避免档案与注册表不一致。

---

## 3. 数据与文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `data/unit-index.yaml` | 修改 | 新增 3 个行业单元 + data-analytics 补充业务词 |
| `src/hanghang/engine/registry.py` | 修改 | M8 search_capability 多维检索 + capability_index |
| `src/hanghang/engine/router.py` | 修改 | 软件构建联合判定收敛 + 弱信号回落护栏 |
| `src/hanghang/cli/main.py` | 修改 | search --mode + index 命令 |
| `tests/test_industry_expansion.py` | 新增 | 行业扩展 + M8 索引 + 评审回归测试 |
| `data/prefix-archive.json` | 新增 | M3 稳定前缀档案（版本化） |
| `.gitignore` | 修改 | prefix-archive.json 纳入版本控制 |
| `docs/feature-delivery.md` | 新增 | 本功能交付索引文档 |

---

## 4. 测试覆盖情况

- 全量 **71+ 项测试通过**（原 57 项 + 评审回归新增）
- 新增 `tests/test_industry_expansion.py`（438 行），覆盖：
  - 5 行业单元注册
  - 法律/内容/数据分析行业路由
  - 跨行业交接（M5）
  - M8 多维检索 + 全量索引导出
  - 软件构建联合判定收敛回归护栏
  - 弱信号回落护栏
  - 新领域通用业务词领域召回

---

## 5. 路由能力演示

```bash
# 5 行业路由
python3 src/hanghang/cli/main.py route "帮我审一份劳动纠纷的劳动合同"
# => legal-services@contract_advisor

python3 src/hanghang/cli/main.py route "给新品写一条卖点文案"
# => content-creation@copywriter

python3 src/hanghang/cli/main.py route "做一份本季度销售经营分析报表"
# => data-analytics@data_analyst

# M8 能力索引检索
python3 src/hanghang/cli/main.py search "合同" --mode any
python3 src/hanghang/cli/main.py index

# 评审回归场景
python3 src/hanghang/cli/main.py route "开发一个合同管理系统"
# => dongjiagoushi@developer（正确软件构建）

python3 src/hanghang/cli/main.py route "做一份软件使用分析报告"
# => data-analytics@data_analyst（数据分析报告）
```

---

## 6. 给协作方的说明

本 PR (#6) 已通过多轮自动评审（含 critical 路由回归修复），评审最终结论 **approved**。

如需要进一步了解，可参考：
- 顶层架构：`docs/architecture/ARCHITECTURE.md`
- 需求基线：`docs/architecture/通用能力-需求澄清基线.md`
- PR 评审记录：PR #6 评论区
