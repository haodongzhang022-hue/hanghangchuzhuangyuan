# 行行出状元 · 通用能力层

跨行业/跨岗位的路由编排总层。把各「行业单元」（如 dongjiagoushi 架构团队）当原子收编，在其上叠一层「自动识别行业/岗位 → 路由 → 交接 → 交叉 → 复合装配」的总编排层。

## 架构分层

```
L2 人类端点    = 仅入口(意图确认) + 出口(复核)
L1 通用能力层  = 本仓库：识别路由(M1) / 注册表(M2) / 前缀档案(M3)
               / 会话编排(M4) / 交接总线(M5) / 复合装配(M6)
               / 指标观测(M7) / 能力索引(M8)
L0 行业单元层  = 各行业单元(如 dongjiagoushi)，原子化收编
```

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

# 查看运行指标
python3 src/hanghang/cli/main.py metrics

# 创建跨单元交接卡
python3 src/hanghang/cli/main.py handoff --source dongjiagoushi --target game-dev-unit --intent "需要游戏单元提供策划支持"
```

### 运行测试
```bash
python3 tests/test_router.py
python3 tests/test_registry.py
python3 tests/test_handoff.py
```

## 数据文件

- `data/industry-register.yaml` — 行业单元注册声明（M2 数据源）
- `data/unit-index.yaml` — 跨行业单元索引（M8）
- `data/prefix-archive.json` — 稳定前缀档案（M3，自动生成）
- `data/metrics.json` — 运行指标（M7，自动生成）

## 文档索引

- 顶层架构: `docs/architecture/ARCHITECTURE.md`
- 需求基线: `docs/architecture/通用能力-需求澄清基线.md`
- 单元接入规范: `docs/industry/register-spec.md`
- POC验证记录: `poc/`
