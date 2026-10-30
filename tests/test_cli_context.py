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


def _run_cli_rc(args, cwd=None):
    """调用真实 CLI，返回 (退出码, stdout)，用于断言失败退非 0"""
    result = subprocess.run(
        [sys.executable, _CLI] + args,
        capture_output=True, text=True, cwd=cwd or _PROJECT_ROOT,
        timeout=30,
    )
    return result.returncode, result.stdout


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


def test_context_assemble_smoke():
    """context assemble 冒烟：三层结构 + 前缀自动获取 + 层B目标

    用临时 cwd 运行，验证 data/ 目录回落（读仓库真实 data/），
    同时让运行期写盘的 bindings/ 落在临时目录，不污染仓库。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        out = _run_cli([
            "context", "assemble",
            "--session", "ctx_test_demo",
            "--unit", "dongjiagoushi",
            "--role", "architect",
            "--text", "修改代码实现测试",
            "--objective", "装配冒烟",
        ], cwd=tmpdir)
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
    """会话未绑定且未给 unit_id → 友好提示（不抛栈）+ 退非 0"""
    rc, out = _run_cli_rc([
        "context", "assemble",
        "--session", "ctx_no_unit",
        "--role", "secretary",
        "--text", "hello",
    ])
    assert "未提供 unit_id" in out or "无法确定装配" in out
    assert "--unit" in out
    assert "Traceback" not in out
    assert rc != 0, f"装配失败应退非 0，实际 {rc}"


def test_context_validate_pass():
    """context validate：合规静态层通过"""
    out = _run_cli([
        "context", "validate",
        "--layer-a", "[架构] | unit=dongjiagoushi | session_context_static=true",
    ])
    assert "校验通过" in out
    assert "无动态内容混入" in out


def test_context_validate_violation():
    """context validate：动态内容混入静态层 → 判违规 + 退非 0"""
    rc, out = _run_cli_rc([
        "context", "validate",
        "--layer-a", "动态内容### 会话态上下文 ###混入",
    ])
    assert "校验未通过" in out
    assert "违规" in out
    assert rc != 0, f"违规应退非 0，实际 {rc}"


def test_context_validate_records_baseline():
    """context validate --session：首轮落盘基线（不再输出自比出来的假"缓存命中"）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        out = _run_cli([
            "context", "validate",
            "--layer-a", "[架构] | unit=dongjiagoushi | session_context_static=true",
            "--session", "ctx_validate_cache",
        ], cwd=tmpdir)
    assert "缓存命中: ✅" not in out
    assert "首次记录基线" in out
    assert "校验通过" in out


def test_context_assemble_binding_industry_is_real_name():
    """首次自动绑定写入的 industry 是注册表真实行业名，而非 unit_id"""
    import json
    with tempfile.TemporaryDirectory() as tmpdir:
        _run_cli([
            "context", "assemble",
            "--session", "ctx_bind_industry",
            "--unit", "dongjiagoushi",
            "--role", "architect",
        ], cwd=tmpdir)
        path = os.path.join(tmpdir, "data", "bindings", "ctx_bind_industry.json")
        assert os.path.isfile(path), f"绑定文件未生成: {path}"
        with open(path, encoding="utf-8") as f:
            binding = json.load(f)
    assert binding["unit_id"] == "dongjiagoushi"
    # 真实行业名应为「软件研发」，不能是 unit_id 兜底
    assert binding["industry"] != "dongjiagoushi", binding
    assert binding["industry"] == "软件研发", binding


def test_context_assemble_rejects_unknown_unit():
    """无效 unit_id：报错退非 0、不写绑定，且同会话随后仍可绑定合法单元"""
    with tempfile.TemporaryDirectory() as tmpdir:
        rc, out = _run_cli_rc([
            "context", "assemble",
            "--session", "ctx_bad_unit",
            "--unit", "no-such-unit",
            "--role", "architect",
        ], cwd=tmpdir)
        assert rc != 0, f"无效单元应退非 0，实际 {rc}\n{out}"
        assert "行业单元不存在" in out
        assert "dongjiagoushi" in out  # 列出可用单元
        assert not os.path.isfile(
            os.path.join(tmpdir, "data", "bindings", "ctx_bad_unit.json")), \
            "无效单元不应写入会话绑定"

        # 会话未被占死：随后绑定合法单元应成功
        out2 = _run_cli([
            "context", "assemble",
            "--session", "ctx_bad_unit",
            "--unit", "dongjiagoushi",
            "--role", "architect",
        ], cwd=tmpdir)
    assert "SLIB 装配守卫拦截" not in out2
    assert "session_context_static=true" in out2


def test_context_validate_cross_process_baseline():
    """validate --session：跨进程基线三态（首次记录 / ✅一致 / ❌漂移）"""
    good = "[架构] | unit=dongjiagoushi | session_context_static=true"
    other = "[秘书] | unit=dongjiagoushi | session_context_static=true"
    with tempfile.TemporaryDirectory() as tmpdir:
        out1 = _run_cli(["context", "validate", "--layer-a", good,
                         "--session", "ctx_baseline"], cwd=tmpdir)
        assert "首次记录基线" in out1, out1
        assert "data/state/context_baseline" in out1

        out2 = _run_cli(["context", "validate", "--layer-a", good,
                         "--session", "ctx_baseline"], cwd=tmpdir)
        assert "✅ 与上次落盘基线一致" in out2, out2

        # 层A变化 → 漂移分支必须可达（旧实现此处恒为「缓存命中」）
        rc, out3 = _run_cli_rc(["context", "validate", "--layer-a", other,
                                "--session", "ctx_baseline"], cwd=tmpdir)
    assert "❌ 层A签名与上次基线不一致" in out3, out3
    assert rc != 0, "漂移应退非 0"


if __name__ == "__main__":
    test_context_rules_list_loads_yaml()
    test_context_rules_match_hits()
    test_context_rules_match_no_hit()
    test_context_assemble_smoke()
    test_context_assemble_no_unit_friendly_hint()
    test_context_validate_pass()
    test_context_validate_violation()
    test_context_validate_records_baseline()
    test_context_assemble_binding_industry_is_real_name()
    test_context_assemble_rejects_unknown_unit()
    test_context_validate_cross_process_baseline()
    print("✅ M10 context CLI 三子命令测试通过")
