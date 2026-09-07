# 功能特性交付索引（行业扩展第三期：教育培训/健康医疗/家装设计）

> 版本：行业横向扩展 v3 | 2026-09-08 | 同步人：CodeBuddy
> 场景：新增教育培训/健康医疗/家装设计 3 个行业单元，填补常见需求场景路由盲区
> 前置：行业扩展前 2 期已交付（8→11 行业）

---

## 1. 总览

本阶段围绕「**行业横向扩展 + 常见需求盲区覆盖**」主线开发，新增 3 个行业单元、8 个岗位，行业单元总数从 8 扩展至 11。纯数据驱动，无核心代码改动。

| 功能编号 | 功能名称 | 状态 | 涉及文件 |
|---------|---------|------|---------|
| F-41 | 新增 education-training 教育培训单元（3岗） | ✅ 已完成 | data/unit-index.yaml |
| F-42 | 新增 healthcare 健康医疗单元（4岗） | ✅ 已完成 | data/unit-index.yaml |
| F-43 | 新增 home-design 家装设计单元（3岗） | ✅ 已完成 | data/unit-index.yaml |
| F-44 | prefix-archive.json 扩展至 11 单元 | ✅ 已完成 | data/prefix-archive.json |
| F-45 | 新增行业路由回归测试 | ✅ 已完成 | tests/test_industry_expansion_v3.py |

---

## 2. 新增行业详情

### F-41 education-training 教育培训

覆盖场景：课程设计 / 教学辅导 / 培训方案 / 学习规划 / 留学规划 / 找家教 / 报班

| 岗位 | 前缀 | 核心关键词 |
|------|------|-----------|
| curriculum_designer | [课程设计] | 课程设计/培训方案/教案/备课/课件/教学大纲 |
| teacher | [讲师] | 授课/教学/辅导/教师/老师/家教/英语教学 |
| learning_advisor | [学习规划] | 学习规划/学习计划/学英语/报班/留学/学Python |

### F-42 healthcare 健康医疗

覆盖场景：健康咨询 / 体检报告解读 / 心理咨询 / 就医建议 / 健身计划

| 岗位 | 前缀 | 核心关键词 |
|------|------|-----------|
| health_consultant | [健康顾问] | 健康咨询/体检报告/养生/减脂/营养 |
| psychologist | [心理] | 心理咨询/情绪疏导/焦虑/压力管理 |
| medical_advisor | [医疗顾问] | 在线问诊/就医建议/挂号/用药咨询 |
| fitness_coach | [健身教练] | 健身计划/训练计划/瑜伽/私教 |

### F-43 home-design 家装设计

覆盖场景：室内设计 / 户型改造 / 软装搭配 / 找装修公司

| 岗位 | 前缀 | 核心关键词 |
|------|------|-----------|
| interior_designer | [室内设计] | 室内设计/户型设计/装修方案/效果图/家装设计 |
| soft_furnish | [软装] | 软装搭配/家具搭配/色彩搭配/灯光设计 |
| project_manager | [装修经理] | 装修施工/监理/预算/材料/验收 |

---

## 3. 此前路由盲区（本期填补）

以下场景此前全部回落人工（无法自动识别），本期后均自动路由：

| 用户意图 | 路由前 | 路由后 |
|---------|--------|--------|
| 帮我设计一个英语培训方案 | manual | education-training@curriculum_designer |
| 帮我做课程体系规划 | manual | education-training@curriculum_designer |
| 帮我做心理咨询 | manual | healthcare@psychologist |
| 帮我解读体检报告 | manual | healthcare@health_consultant |
| 帮我制定健身计划 | manual | healthcare@fitness_coach |
| 帮我找个装修公司 | manual | home-design@project_manager |
| 帮我做个卧室装修方案 | manual | home-design@interior_designer |
| 帮我做软装搭配 | manual | home-design@soft_furnish |

---

## 4. 验证

- 全量 **17 个测试文件** 全部通过（16 原有 + 1 新增 v3 测试）
- 新增 7 项测试覆盖：3 新行业注册、各岗位路由、已有行业不回归、新行业不过度抢占、prefix-archive 完整性
- CLI 冒烟测试通过

## 5. 数据文件变更

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `data/unit-index.yaml` | 修改 | 新增 3 行业单元 + 岗位定义 + 关键词 |
| `data/prefix-archive.json` | 修改 | 新增 3 行业的前缀档案 |
| `tests/test_industry_expansion_v3.py` | 新增 | 行业扩展第三期测试 |
| `README.md` | 修改 | 行业表更新 8→11 |
| `docs/feature-delivery-v6.md` | 新增 | 本索引文档 |
