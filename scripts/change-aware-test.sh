#!/usr/bin/env bash
# ============================================================
# 变更范围感知测试选择器（Change-Aware Test Selector）v2
# ------------------------------------------------------------
# 作用：根据本次 git 变更的文件范围，只运行受影响的测试模块，
#       避免全量跑测试造成 CPU 浪费（"公交车攒批"思想：只跑
#       受影响的那一班，而非每个 commit 全量发车）。
#
# 用法：
#   bash scripts/change-aware-test.sh                # 自动检测变更（PR/push/本地）
#   bash scripts/change-aware-test.sh --all          # 强制全量跑（main push / 合并门禁用）
#   bash scripts/change-aware-test.sh --dry-run      # 只打印将运行的测试，不实际执行
#   bash scripts/change-aware-test.sh --base=SHA     # 指定比对基线（否则自动探测）
#
# 环境变量：
#   CNB_PULL_REQUEST_TARGET_SHA  # PR 目标分支 SHA（CNB 内置变量）
#   CNB_COMMIT                   # 本次提交 SHA（CNB 内置变量）
#
# 设计说明：
#   - 模块→测试映射表集中在下方 PY_MAP 中，随模块演进增补。
#   - engine 内部改动波及面大（因 __init__ 聚合导出），映射至
#     全部引擎回归；外围模块（state/web/context/review/cli）改动
#     只跑自身域测试。
#   - 数据文件（data/*.yaml）变更会重路由，映射至行业/数据驱动回归。
# ============================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=false
FORCE_ALL=false
BASE_SHA=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --all) FORCE_ALL=true ;;
    --base=*) BASE_SHA="${arg#*=}" ;;
  esac
done

# 选择测试文件列表（由内嵌 Python 输出，每行一个文件）
SELECTED_TESTS=""
if [ "$FORCE_ALL" = "true" ]; then
  echo "==== [change-aware] 强制全量模式 ===="
  SELECTED_TESTS=$(ls tests/test_*.py 2>/dev/null)
else
  # 探测变更基线
  if [ -z "$BASE_SHA" ] && [ -n "${CNB_PULL_REQUEST_TARGET_SHA:-}" ]; then
    BASE_SHA="$CNB_PULL_REQUEST_TARGET_SHA"
  elif [ -z "$BASE_SHA" ] && [ -n "${CNB_COMMIT:-}" ] && git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
    BASE_SHA="HEAD~1"
  elif [ -z "$BASE_SHA" ]; then
    if git rev-parse --verify origin/main >/dev/null 2>&1; then
      BASE_SHA="origin/main"
    elif git rev-parse --verify main >/dev/null 2>&1; then
      BASE_SHA="main"
    elif git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
      BASE_SHA="HEAD~1"
    fi
  fi

  SELECTED_TESTS=$(python3 - "$BASE_SHA" << 'PY'
import os, re, subprocess, sys

repo = os.getcwd()
base_sha = sys.argv[1] if len(sys.argv) > 1 else ""

# ---- 变更文件收集 ----
def git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True,
                          text=True, cwd=repo).stdout.strip()

changed = []
if base_sha:
    try:
        changed = git("diff", "--name-only", f"{base_sha}...HEAD").split("\n")
    except Exception:
        changed = []
ws = git("diff", "--name-only").split("\n")  # 工作区未提交变更
changed = [c for c in (changed + ws) if c]
changed = list(dict.fromkeys(changed))  # 去重保序

if not changed:
    print("__ALL__")
    sys.exit(0)

# ---- 模块 → 测试文件映射（路径前缀 → 该变更触发的测试） ----
# engine 核心改动波及面大 → 引擎全量回归；外围改动只跑自身域。
MAP = [
    ("src/hanghang/engine/router.py", [
        "tests/test_router.py", "tests/test_data_driven.py",
        "tests/test_industry_expansion.py", "tests/test_industry_expansion_v2.py",
        "tests/test_dongjiagoushi_routing.py", "tests/test_state_manager.py",
        "tests/test_state_tree.py", "tests/test_web.py",
    ]),
    ("src/hanghang/engine/registry.py", [
        "tests/test_registry.py", "tests/test_router.py",
        "tests/test_data_driven.py", "tests/test_industry_expansion.py",
        "tests/test_industry_expansion_v2.py", "tests/test_dongjiagoushi_routing.py",
        "tests/test_state_tree.py",
    ]),
    ("src/hanghang/engine/models.py", [
        "tests/test_registry.py", "tests/test_router.py",
        "tests/test_data_driven.py", "tests/test_handoff.py",
        "tests/test_industry_expansion.py", "tests/test_industry_expansion_v2.py",
    ]),
    ("src/hanghang/engine/handoff.py", [
        "tests/test_handoff.py", "tests/test_data_driven.py",
        "tests/test_state_tree.py", "tests/test_batch_persist.py",
        "tests/test_web.py",
    ]),
    ("src/hanghang/engine/metrics.py", ["tests/test_web.py"]),
    ("src/hanghang/engine/prefix.py", [
        "tests/test_registry.py", "tests/test_dongjiagoushi_routing.py",
        "tests/test_web.py",
    ]),
    # M9 状态管理层
    ("src/hanghang/state/", [
        "tests/test_state_manager.py", "tests/test_state_tree.py",
        "tests/test_batch_persist.py", "tests/test_state_cli_e2e.py",
        "tests/test_web.py",
    ]),
    # M10 上下文装配器
    ("src/hanghang/context/", ["tests/test_context_m10.py"]),
    # 评审基础设施
    ("src/hanghang/review/", ["tests/test_review.py"]),
    # Web 可视化面板
    ("src/hanghang/web/", ["tests/test_web.py"]),
    # CLI
    ("src/hanghang/cli/", [
        "tests/test_state_cli_e2e.py", "tests/test_state_manager.py",
        "tests/test_web.py",
    ]),
    # 数据文件
    ("data/industry-register.yaml", [
        "tests/test_data_driven.py", "tests/test_router.py",
        "tests/test_industry_expansion.py", "tests/test_industry_expansion_v2.py",
        "tests/test_registry.py", "tests/test_dongjiagoushi_routing.py",
        "tests/test_state_tree.py",
    ]),
    ("data/unit-index.yaml", [
        "tests/test_industry_expansion.py", "tests/test_industry_expansion_v2.py",
        "tests/test_data_driven.py",
    ]),
    ("data/context-rules.yaml", ["tests/test_context_m10.py"]),
    ("data/prefix-archive.json", ["tests/test_registry.py", "tests/test_dongjiagoushi_routing.py"]),
    ("cli/units.yaml", [
        "tests/test_data_driven.py", "tests/test_router.py",
        "tests/test_industry_expansion.py", "tests/test_industry_expansion_v2.py",
        "tests/test_dongjiagoushi_routing.py",
    ]),
]

# 纯文档/注释变更集合（不触发行为回归，避免改个注释就全量跑）
DOC_ONLY_PATTERNS = [
    "docs/", "README.md", ".md", "poc/",
]

def is_doc_only(changed_files):
    """判断变更是否全部为纯文档类（不涉及行为）。"""
    if not changed_files:
        return False
    for f in changed_files:
        f = f.strip()
        if not f:
            continue
        matched_doc = any(p in f for p in DOC_ONLY_PATTERNS)
        if not matched_doc:
            return False
    return True

# ---- 匹配 ----
selected = []
seen = set()
for f in changed:
    f = f.strip()
    if not f:
        continue
    # 测试文件自身变更 → 跑自身
    if f.startswith("tests/test_") and f.endswith(".py"):
        if f not in seen:
            seen.add(f)
            selected.append(f)
        continue
    for pat, tests in MAP:
        if pat in f:
            for t in tests:
                if t not in seen:
                    seen.add(t)
                    selected.append(t)

# 根级工程文件变更 → 兜底引擎回归
root_files = [".cnb.yml", "requirements.txt", "setup.py", "cli/route",
              "src/hanghang/__init__.py"]
for f in changed:
    if f.strip() in root_files:
        for t in ["tests/test_router.py", "tests/test_registry.py",
                  "tests/test_handoff.py", "tests/test_data_driven.py"]:
            if t not in seen:
                seen.add(t)
                selected.append(t)

if is_doc_only(changed):
    # 纯文档变更：不触发任何行为测试
    print("__NONE__")
elif not selected:
    # 未知代码/数据变更：无法判断影响面 → 全量兜底
    print("__ALL__")
else:
    for t in selected:
        print(t)
PY
)
fi

if [ "$SELECTED_TESTS" = "__ALL__" ]; then
  echo "  模式: 全量（无法确定变更范围 / 根级变更 / 未知代码变更）"
  SELECTED_TESTS=$(ls tests/test_*.py 2>/dev/null)
elif [ "$SELECTED_TESTS" = "__NONE__" ]; then
  echo "  模式: 纯文档变更，跳过行为测试（跑轻量 CLI 冒烟即可）"
  SELECTED_TESTS=""
else
  echo "  模式: 变更感知"
fi

echo "  将运行的测试文件($(echo "$SELECTED_TESTS" | grep -c . )):"
for t in $SELECTED_TESTS; do
  echo "    python3 $t"
done

# ---- 执行（--dry-run 只打印） ----
if [ "$DRY_RUN" = "true" ]; then
  exit 0
fi

pip install -q -r requirements.txt 2>/dev/null || true

echo ""
FAILED=0
for t in $SELECTED_TESTS; do
  if [ ! -f "$t" ]; then
    echo "  ⚠️ 跳过不存在: $t"
    continue
  fi
  echo ""
  echo "==== 运行测试: python3 $t ===="
  if python3 "$t"; then
    echo "  ✅ $t 通过"
  else
    echo "  ❌ $t 失败"
    FAILED=1
  fi
done

echo ""
if [ "$FAILED" = "0" ]; then
  echo "==== [change-aware] 所有选定测试通过 ===="
else
  echo "==== [change-aware] 存在失败测试 ===="
fi
exit $FAILED
