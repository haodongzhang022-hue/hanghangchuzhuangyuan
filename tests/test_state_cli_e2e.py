"""M9 × CLI 全链路联调回归测试

验证 M9 状态管理层通过 CLI 的完整可操作闭环：
    state init → add → update → fold → submit → show → compact → list
    + 秘书长多级树 init → register → link → show → rollup
    + 落盘 JSON 与「导出回归」一致（feature-delivery 索引同步前提）。

设计要点：
- 全程经 src/hanghang/cli/main.py 真实 CLI 入口（subprocess）调用，
  证明 M9 与 CLIs 已全链路打通，而非仅 API 层可用。
- 将 cwd 切到临时目录运行，StateManager 会把卡落到 <tmp>/data/state，
  不污染仓库真实 data/state，退出自动清理。
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLI = os.path.join(_PROJECT_ROOT, "src", "hanghang", "cli", "main.py")

_SESSION = "cli_e2e_demo"


def _run_cli(args, cwd):
    """调用真实 CLI，返回 (returncode, stdout)"""
    result = subprocess.run(
        [sys.executable, _CLI] + args,
        capture_output=True, text=True, cwd=cwd, timeout=30,
    )
    assert result.returncode == 0, (
        f"CLI 失败: hanghang {' '.join(args)}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout


def _state_card_path(cwd):
    return os.path.join(cwd, "data", "state", f"{_SESSION}.json")


def test_state_cli_full_chain():
    """M9 CLI 全链路：init→add→update→fold→submit→show→compact→list"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1) init：创建 StateCard
        out = _run_cli(["state", "init", "--session", _SESSION,
                        "--objective", "CLI联调", "--unit", "dongjiagoushi"], tmpdir)
        assert "StateCard 已创建" in out
        assert os.path.exists(_state_card_path(tmpdir)), "init 应落盘生成 JSON"

        # 2) add：加一个普通任务 + 一个末端交付任务
        out = _run_cli(["state", "add", "--session", _SESSION,
                        "--title", "准备基线", "--files", "engine/router.py"], tmpdir)
        assert "#cli_e2e_demo-0001" in out
        out = _run_cli(["state", "add", "--session", _SESSION,
                        "--title", "落地联调", "--type", "deliverable"], tmpdir)
        assert "#cli_e2e_demo-0002" in out

        # 3) update：状态迁移 todo→in_progress→done
        out = _run_cli(["state", "update", "--session", _SESSION,
                        "--task", "cli_e2e_demo-0001", "--state", "in_progress"], tmpdir)
        assert "in_progress" in out
        out = _run_cli(["state", "update", "--session", _SESSION,
                        "--task", "cli_e2e_demo-0001", "--state", "done"], tmpdir)
        assert "done" in out
        # 当前执行态任务进入 in_progress（交付任务 0002）
        _run_cli(["state", "update", "--session", _SESSION,
                  "--task", "cli_e2e_demo-0002", "--state", "in_progress"], tmpdir)

        # 4) fold：折叠策略只保留交付/执行态展开
        out = _run_cli(["state", "fold", "--session", _SESSION], tmpdir)
        assert "cli_e2e_demo-0002" in out and "已折叠" in out

        # 5) submit：向上级提交汇总（含计数）
        out = _run_cli(["state", "submit", "--session", _SESSION], tmpdir)
        assert "已提交 cli_e2e_demo → root" in out
        assert "完成: 1" in out

        # 6) show / compact：导航与压缩上下文可渲染
        out = _run_cli(["state", "show", "--session", _SESSION], tmpdir)
        assert "cli_e2e_demo-0002" in out and "进度: 1/2" in out
        out = _run_cli(["state", "compact", "--session", _SESSION], tmpdir)
        assert "落地联调" in out

        # 7) list：应能看到该 session
        out = _run_cli(["state", "list"], tmpdir)
        assert _SESSION in out

        # 8) 导出回归：落盘 JSON 与 CLI 视图状态一致（done 1 / in_progress 1）
        import json
        with open(_state_card_path(tmpdir), "r", encoding="utf-8") as f:
            card = json.load(f)
        states = {t["task_id"]: t["state"] for t in card["tasks"]}
        assert states["cli_e2e_demo-0001"] == "done"
        assert states["cli_e2e_demo-0002"] == "in_progress"


def test_state_tree_cli_chain():
    """秘书长多级树 CLI：init→register→link→show→rollup"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tree = "cli_tree"
        root = "cli_root"
        child = "cli_child"

        _run_cli(["tree", "init", "--name", tree, "--root", root,
                  "--display", "秘书长", "--objective", "顶层目标"], tmpdir)
        _run_cli(["tree", "register", "--name", tree, "--session", child,
                  "--role", "developer", "--display", "开发", "--parent", root], tmpdir)

        # 每个节点应有 StateCard（rollup 需卡汇总）
        _run_cli(["state", "init", "--session", root,
                  "--objective", "根目标"], tmpdir)
        _run_cli(["state", "init", "--session", child,
                  "--objective", "子目标"], tmpdir)
        _run_cli(["state", "add", "--session", child,
                  "--title", "子任务A"], tmpdir)

        out = _run_cli(["tree", "show", "--name", tree], tmpdir)
        assert root in out and child in out

        out = _run_cli(["tree", "rollup", "--name", tree], tmpdir)
        assert "秘书树 Rollup" in out and root in out


if __name__ == "__main__":
    test_state_cli_full_chain()
    test_state_tree_cli_chain()
    print("✅ M9 × CLI 全链路联调回归测试通过")
