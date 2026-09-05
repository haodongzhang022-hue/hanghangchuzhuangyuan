#!/usr/bin/env bash
# ============================================================
# 变更范围感知测试选择器（Change-Aware Test Selector）
# ------------------------------------------------------------
# 作用：根据本次 git 变更的文件范围，只运行受影响的测试模块，
#       避免全量跑测试造成 CPU 浪费。
#
# 用法：
#   bash scripts/change-aware-test.sh                 # 自动检测变更（PR/push 均适用）
#   bash scripts/change-aware-test.sh --all           # 强制全量跑
#   bash scripts/change-aware-test.sh --dry-run       # 只打印将运行的测试，不实际执行
#
# 环境变量：
#   CNB_PULL_REQUEST_TARGET_SHA    # PR 目标分支 SHA（CNB 内置变量）
#   CNB_COMMIT                     # 本次提交 SHA（CNB 内置变量）
# ============================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=false
FORCE_ALL=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --all) FORCE_ALL=true ;;
  esac
done

# ------------------------------------------------------------
# 1. 确定变更文件列表
# ------------------------------------------------------------
CHANGED_FILES=""
if [ "$FORCE_ALL" = "true" ]; then
  CHANGED_FILES="__ALL__"
elif [ -n "${CNB_PULL_REQUEST_TARGET_SHA:-}" ]; then
  # PR 事件：对比目标分支 SHA 与当前 HEAD
  CHANGED_FILES=$(git diff --name-only "$CNB_PULL_REQUEST_TARGET_SHA" "HEAD" 2>/dev/null)
elif [ -n "${CNB_COMMIT:-}" ]; then
  # push 事件：对比上一个 commit
  CHANGED_FILES=$(git diff --name-only "HEAD~1" "HEAD" 2>/dev/null)
else
  # 本地开发：对比 main
  if git rev-parse --verify main >/dev/null 2>&1; then
    CHANGED_FILES=$(git diff --name-only "main...HEAD" 2>/dev/null)
  elif git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
    CHANGED_FILES=$(git diff --name-only "HEAD~1" "HEAD" 2>/dev/null)
  else
    CHANGED_FILES="__ALL__"
  fi
fi

# 也包含未提交的工作区更改
WORKING_CHANGES=$(git diff --name-only 2>/dev/null || true)
if [ -n "$WORKING_CHANGES" ]; then
  if [ "$CHANGED_FILES" = "__ALL__" ]; then
    CHANGED_FILES="$WORKING_CHANGES"
  else
    CHANGED_FILES="$CHANGED_FILES
$WORKING_CHANGES"
  fi
fi

if [ -z "$CHANGED_FILES" ]; then
  CHANGED_FILES="__ALL__"
fi

echo "==== [change-aware] 变更范围感知测试选择 ===="
if [ "$CHANGED_FILES" = "__ALL__" ]; then
  echo "  模式: 全量（无法确定变更范围或强制 --all）"
else
  echo "  变更文件数: $(echo "$CHANGED_FILES" | grep -c . )"
  echo "  变更文件:"
  echo "$CHANGED_FILES" | sed 's/^/    /'
fi

# ------------------------------------------------------------
# 2. 模块 → 测试文件 映射表
# ------------------------------------------------------------
# 每个条目: "路径模式|测试文件1,测试文件2,..."
declare -a MODULE_MAP=(
  # ---- 核心源码变更 → 对应测试 ----
  "src/hanghang/engine/router.py|tests/test_router.py"
  "src/hanghang/engine/registry.py|tests/test_registry.py,tests/test_router.py"
  "src/hanghang/engine/handoff.py|tests/test_handoff.py"
  "src/hanghang/engine/prefix.py|tests/test_registry.py"
  "src/hanghang/engine/metrics.py|tests/test_router.py"
  "src/hanghang/engine/models.py|tests/test_router.py,tests/test_registry.py,tests/test_handoff.py"

  # ---- 评审基础设施模块 → test_review.py ----
  "src/hanghang/review/|tests/test_review.py"

  # ---- 数据文件变更 → 全量路由相关测试 ----
  "data/|tests/test_router.py,tests/test_registry.py"
  "cli/units.yaml|tests/test_router.py,tests/test_registry.py"
  "cli/route|tests/test_router.py"

  # ---- 测试文件自身变更 → 全量 ----
  "tests/|tests/test_router.py,tests/test_registry.py,tests/test_handoff.py,tests/test_review.py"

  # ---- 根级文件 → 全量 ----
  ".cnb.yml|tests/test_router.py,tests/test_registry.py,tests/test_handoff.py"
  "requirements.txt|tests/test_router.py,tests/test_registry.py,tests/test_handoff.py"
  "setup.py|tests/test_router.py,tests/test_registry.py,tests/test_handoff.py"
)

# ------------------------------------------------------------
# 3. 匹配变更文件 → 选测试
# ------------------------------------------------------------
SELECTED_TESTS=""
declare -A SEEN=()

select_test() {
  local test="$1"
  if [ -z "${SEEN[$test]:-}" ]; then
    SEEN[$test]=1
    if [ -n "$SELECTED_TESTS" ]; then
      SELECTED_TESTS="$SELECTED_TESTS $test"
    else
      SELECTED_TESTS="$test"
    fi
  fi
}

if [ "$CHANGED_FILES" = "__ALL__" ]; then
  echo "  选定: ALL（全量模式）"
  SELECTED_TESTS="tests/test_router.py tests/test_registry.py tests/test_handoff.py tests/test_review.py"
else
  for file in $CHANGED_FILES; do
    [ -z "$file" ] && continue
    for entry in "${MODULE_MAP[@]}"; do
      pattern="${entry%%|*}"
      tests="${entry#*|}"
      if [[ "$file" == *"$pattern"* ]]; then
        IFS=',' read -ra test_arr <<< "$tests"
        for t in "${test_arr[@]}"; do
          select_test "$t"
        done
      fi
    done
  done

  # 兜底：如果没有任何测试被选中，跑全部测试
  if [ -z "$SELECTED_TESTS" ]; then
    echo "  未匹配到任何模块，跑全部测试兜底"
    SELECTED_TESTS="tests/test_router.py tests/test_registry.py tests/test_handoff.py tests/test_review.py"
  fi
fi

echo "  选定的测试($(echo $SELECTED_TESTS | wc -w)个):"
for t in $SELECTED_TESTS; do
  echo "    python3 $t"
done

# ------------------------------------------------------------
# 4. 执行测试（--dry-run 只打印）
# ------------------------------------------------------------
if [ "$DRY_RUN" = "true" ]; then
  exit 0
fi

# 确保依赖已安装
pip install -q -r requirements.txt 2>/dev/null || true

echo ""
FAILED=0
for t in $SELECTED_TESTS; do
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
