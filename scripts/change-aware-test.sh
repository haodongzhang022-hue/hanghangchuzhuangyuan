#!/usr/bin/env bash
# ============================================================================
# 通用变更感知测试选择器（Generic Change-Aware Test Selector）v4
# ----------------------------------------------------------------------------
# 跨仓库 / 跨语言生态通用的「增量测试」基建。解决三个问题：
#   1) 无任何代码/测试变动时，不再重复全量跑 → 结果指纹缓存，沿用上次 PASS；
#   2) 有变动时只跑「受本次变更影响」那批 → 公交攒批，不逐个分别构建/测试/关闭；
#   3) 复制到任意仓库即用 → 靠【自动依赖推断 + 可选静态映射】驱动，不人肉维护
#      硬编码"源码→测试"映射表。
#
# 用法（复制到目标仓库 scripts/ 后）：
#   bash scripts/change-aware-test.sh              # 自动探测变更，跑受影响测试
#   bash scripts/change-aware-test.sh --all        # 强制全量（main push / 合并门禁兜底）
#   bash scripts/change-aware-test.sh --dry-run    # 只打印选中测试，不实跑
#   bash scripts/change-aware-test.sh --base=SHA   # 指定变更比对基线
#   bash scripts/change-aware-test.sh --no-cache   # 忽略缓存，本次选中全重跑
#   bash scripts/change-aware-test.sh --purge-cache# 清空结果缓存
#   bash scripts/change-aware-test.sh --config=ca-test.conf  # 用仓库外部配置
#
# 配套：同目录 ca-plan.mjs 为依赖解析内核（node 实现，语言无关）。
#
# 外部配置键（ca-test.conf 或环境变量，均带 CA_ 前缀）：
#   CA_SRC_GLOB     源码根/glob （默认 src/ lib/ packages/ core/ engine/ app/）
#   CA_TEST_GLOB    测试文件 glob（默认自动识别 test_* / *.test / *.spec 等）
#   CA_MAP_FILE     可选静态映射：为无 import 的脚本测试(bash)提供 "路径|测试1,测试2"
#   CA_SKIP_EXTRA   额外跳过"非触发"路径，逗号分隔（默认 docs/,README.md,.md,...）
#   CA_CACHE_DIR    结果缓存目录（默认 .testcache，可用 CNB cache: 卷跨流水线复用）
#   CA_PY_CMD       运行 python 测试的命令（默认 python3）
#   CA_NODE_CMD     运行 node 测试的命令（默认 node）
#   CA_BASH_CMD     运行 bash/shell 测试的命令（默认 bash）
#
# 示例 .cnb.yml 接入（同一份代码第二次不重复全跑）：
#   volumes: [ "cache:/root/.catest:rw" ]   env: { CA_CACHE_DIR: /root/.catest }
#   script: bash scripts/change-aware-test.sh
# ============================================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
ME_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FORCE_ALL=false; DRY_RUN=false; NO_CACHE=false; PURGE_CACHE=false
BASE_SHA=""; CONF_FILE=""
for arg in "$@"; do
  case "$arg" in
    --all) FORCE_ALL=true ;; --dry-run) DRY_RUN=true ;;
    --no-cache) NO_CACHE=true ;; --purge-cache) PURGE_CACHE=true ;;
    --base=*) BASE_SHA="${arg#*=}" ;; --config=*) CONF_FILE="${arg#*=}" ;;
  esac
done

# ---------- 配置（conf 文件 + 环境变量覆盖） ----------
SRC_GLOB="src/ lib/ packages/ core/ engine/ app/"
TEST_GLOB=""; MAP_FILE=""
SKIP_EXTRA="docs/,README.md,.md,poc/,examples/,.github/,CHANGELOG.md"
CACHE_DIR="${CA_CACHE_DIR:-${HH_TEST_CACHE_DIR:-${REPO_ROOT}/.testcache}}"
PY_CMD="${CA_PY_CMD:-python3}"; NODE_CMD="${CA_NODE_CMD:-node}"; BASH_CMD="${CA_BASH_CMD:-bash}"

if [ -n "$CONF_FILE" ] && [ -f "$CONF_FILE" ]; then
  while IFS= read -r line; do
    line="${line%%#*}"; [ -z "${line// }" ] && continue
    k="${line%%=*}"; v="${line#*=}"; v="${v%\"}"; v="${v#\"}"
    case "$k" in
      CA_SRC_GLOB) SRC_GLOB="$v" ;; CA_TEST_GLOB) TEST_GLOB="$v" ;;
      CA_MAP_FILE) MAP_FILE="$v" ;; CA_SKIP_EXTRA) SKIP_EXTRA="$v" ;;
      CA_CACHE_DIR) CACHE_DIR="$v" ;;
      CA_PY_CMD) PY_CMD="$v" ;; CA_NODE_CMD) NODE_CMD="$v" ;; CA_BASH_CMD) BASH_CMD="$v" ;;
    esac
  done < "$CONF_FILE"
fi
[ -n "${CA_SRC_GLOB:-}" ] && SRC_GLOB="$CA_SRC_GLOB"
[ -n "${CA_TEST_GLOB:-}" ] && TEST_GLOB="$CA_TEST_GLOB"
[ -n "${CA_MAP_FILE:-}" ] && MAP_FILE="$CA_MAP_FILE"
[ -n "${CA_CACHE_DIR:-}" ] && CACHE_DIR="$CA_CACHE_DIR"

if [ "$PURGE_CACHE" = "true" ]; then
  echo "==== [ca-test] 清空结果缓存: $CACHE_DIR ===="
  rm -rf "$CACHE_DIR"
fi

# ---------- 探测基线 ----------
if [ "$FORCE_ALL" != "true" ] && [ -z "$BASE_SHA" ]; then
  if [ -n "${CNB_PULL_REQUEST_TARGET_SHA:-}" ]; then BASE_SHA="$CNB_PULL_REQUEST_TARGET_SHA"
  elif [ -n "${CNB_COMMIT:-}" ] && git rev-parse --verify HEAD~1 >/dev/null 2>&1; then BASE_SHA="HEAD~1"
  else for b in origin/main main HEAD~1; do git rev-parse --verify "$b" >/dev/null 2>&1 && { BASE_SHA="$b"; break; }; done; fi
fi

MODE_LABEL="变更感知"
if [ "$FORCE_ALL" = "true" ]; then MODE_LABEL="强制全量"; fi
echo "==== [ca-test] $MODE_LABEL 模式（基线: ${BASE_SHA:-<全部>}） ===="

# ---------- 依赖解析内核是否同目录可用 ----------
PLANNER="$ME_DIR/ca-plan.mjs"
if [ ! -f "$PLANNER" ] && [ -f "$REPO_ROOT/scripts/ca-plan.mjs" ]; then PLANNER="$REPO_ROOT/scripts/ca-plan.mjs"; fi
if [ ! -f "$PLANNER" ]; then
  echo "!! 未找到 ca-plan.mjs（需与脚本同目录或 scripts/ 下）。中止。" >&2; exit 2
fi

# ---------- 调用内核生成执行计划 ----------
PLAN_ARGS=""
[ "$FORCE_ALL" = "true" ] && PLAN_ARGS="$PLAN_ARGS --all"
[ "$NO_CACHE" = "true" ] && PLAN_ARGS="$PLAN_ARGS --no-cache"
[ -n "$BASE_SHA" ] && PLAN_ARGS="$PLAN_ARGS --base=$BASE_SHA"
[ -n "$SRC_GLOB" ] && PLAN_ARGS="$PLAN_ARGS --src=$SRC_GLOB"
[ -n "$TEST_GLOB" ] && PLAN_ARGS="$PLAN_ARGS --testglob=$TEST_GLOB"
[ -n "$MAP_FILE" ] && PLAN_ARGS="$PLAN_ARGS --map=$MAP_FILE"
[ -n "$SKIP_EXTRA" ] && PLAN_ARGS="$PLAN_ARGS --skip=$SKIP_EXTRA"
[ -n "$CACHE_DIR" ] && PLAN_ARGS="$PLAN_ARGS --cachedir=$CACHE_DIR"

PLAN_JSON="$("$NODE_CMD" "$PLANNER" $PLAN_ARGS 2>/tmp/ca-plan.log)"
PLAN_EXIT=$?
cat /tmp/ca-plan.log >&2 || true

if [ "$PLAN_EXIT" != "0" ]; then
  echo "!! ca-plan.mjs 出错（exit $PLAN_EXIT），中止。" >&2
  exit "$PLAN_EXIT"
fi
if [ "$PLAN_JSON" = "[]" ]; then
  echo "== 本次为纯文档/非触发变更，或无需行为测试，直接通过。=="
  exit 0
fi

# 把 JSON 计划落盘供执行与回写阶段使用
printf '%s' "$PLAN_JSON" > .ca-plan.json
RUN_FILES=$(printf '%s' "$PLAN_JSON" | "$NODE_CMD" -e "let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{const p=JSON.parse(d);process.stdout.write(p.filter(x=>x[1]==='run').map(x=>x[0]).join('\\n'))})")
[ -f .ca-plan.json ] && rm -f .ca-plan.json

if [ -z "$RUN_FILES" ]; then
  echo "== 命中缓存：本批无需要实跑的测试，沿用上次全部 PASS。=="
  exit 0
fi

# ---------- dry-run 只打印 ----------
if [ "$DRY_RUN" = "true" ]; then
  echo "将运行的测试批次:"
  for t in $RUN_FILES; do echo "    $t"; done
  exit 0
fi

# ---------- 公交攒批执行 ----------
echo ""
echo "==== [ca-test] 公交攒批执行（一次构建、一批测试、一个退出码） ===="
echo "  缓存目录: $CACHE_DIR"
FAILED=0; PASSED=""; N=0
for t in $RUN_FILES; do
  [ -f "$t" ] || { echo "  ! 跳过不存在: $t"; continue; }
  case "$t" in
    *.py)  CMD="$PY_CMD" ;;
    *.sh|*.bash) CMD="$BASH_CMD" ;;
    *)     CMD="$NODE_CMD" ;;
  esac
  N=$((N+1))
  echo ""
  echo "  [$N] $CMD $t"
  if "$CMD" "$t"; then echo "  ✅ 通过: $t"; PASSED="$PASSED $t"
  else echo "  ❌ 失败: $t"; FAILED=1; fi
done

# ---------- 回写缓存（记录 PASS 指纹，供下次无变动跳过） ----------
if [ "$FAILED" = "0" ] && [ -n "$PASSED" ]; then
  "$NODE_CMD" "$PLANNER" --writecache --cachedir="$CACHE_DIR" --files="$PASSED" >/dev/null 2>&1 \
    || echo "  ! 缓存回写失败（不影响结果）"
fi

echo ""
if [ "$FAILED" = "0" ]; then
  echo "==== [ca-test] 本批全部通过（实跑 $N 个） ===="
else
  echo "==== [ca-test] 本批存在失败（$N 个中） ===="
fi
exit "$FAILED"
