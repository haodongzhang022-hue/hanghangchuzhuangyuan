"""M10 × CLI context 子命令测试（Issue #14 T1）

验证 context assemble / rules / validate 三子命令经真实 CLI 入口可用：
  - assemble：三层装配 + 前缀自动获取（data/prefix-archive.json）+ SLIB 守卫友好捕获
  - rules：从 data/context-rules.yaml 动态加载，--list 列全 / --match 命中
  - validate：隔离校验通过 / 违规两类结果

与 test_state_cli_e2e 一致：subprocess 调 src/hanghang/cli/main.py，走真实入口。
用临时 cwd 运行以验证数据目录回落（读仓库 data/），并避免污染运行期数据。
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLI = os.path.join(_PROJECT_ROOT, "src", "hanghang", "cli", "main.py")


def _run_cli(args, cwd=None):
    """调用真实 CLI，成功则返回 stdout；失败断言报错（附 stderr）"""
    result = subprocess.run(
        [sys.executable, _CLI] + args,
        capture_output=True, text=True, cwd=cwd or _PROJECT_ROOT,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"CLI 失败: hanghang {' '.join(args)}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout


def test_context_rules_list_loads_yaml():
    """context rules --list：从 data/context-rules.yaml 动态加载全部启用规则"""
    out = _run_cli(["context", "rules", "--list"])
    assert "R3-FILE-01" in out
    assert "R3-STAT-01" in out
    assert "R3-HAND-01" in out
    assert "R3-ARCH-01" in out
    # 标题行确认来源为 data/context-rules.yaml
    assert "context-rules.yaml" in out


def test_context_rules_match_hits():
    """context rules --match：命中文件/代码操作与测试规则"""
    out = _run_cli(["context", "rules", "--match", "帮我修改代码实现测试"])
    assert "R3-FILE-01" in out
    assert "R3-TEST-01" in out


def test_context_rules_match_no_hit():
    """context rules --match：无命中时不误报"""
    out = _run_cli(["context", "rules", "--match", "今天天气怎么样"])
    assert "未命中" in out


def test_context_assemble_smoke(tmp_path):
    """context assemble 冒烟：三层结构 + 前缀自动获取 + 层B目标"""
    out = _run_cli([
        "context", "assemble",
        "--session", "ctx_test_demo",
        "--unit", "dongjiagoushi",
        "--role", "architect",
        "--text", "修改代码实现测试",
        "--objective", "装配冒烟",
    ], cwd=str(tmp_path))
    # 三层结构均出现
    assert "【层A · 静态上下文" in out
    assert "【层B · 会话态上下文" in out
    # 前缀自动从 data/prefix-archive.json 取到架构岗稳定前缀 [架构]
    assert "[架构]" in out
    assert "session_context_static=true" in out
    # 层B含目标
    assert "装配冒烟" in out
    # 命中文件/测试规则
    assert "R3-FILE-01" in out


def test_context_assemble_no_unit_friendly_hint():
    """会话未绑定且未给 unit_id → 友好提示指定行业单元（而非抛栈）"""
    out = _run_cli([
        "context", "assemble",
        "--session", "ctx_no_unit",
        "--role", "secretary",
        "--text", "hello",
    ])
    assert "未提供 unit_id" in out or "无法确定装配" in out
    assert "--unit" in out


def test_context_validate_pass():
    """context validate：合规静态层通过"""
    out = _run_cli([
        "context", "validate",
        "--layer-a", "[架构] | unit=dongjiagoushi | session_context_static=true",
    ])
    assert "校验通过" in out
    assert "无动态内容混入" in out


def test_context_validate_violation():
    """context validate：动态内容混入静态层 → 判违规"""
    out = _run_cli([
        "context", "validate",
        "--layer-a", "动态内容### 会话态上下文 ###混入",
    ])
    assert "校验未通过" in out
    assert "违规" in out
