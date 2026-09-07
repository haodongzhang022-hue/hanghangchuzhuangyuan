#!/usr/bin/env bash
# ============================================================
# 变更范围感知测试选择器（Change-Aware Test Selector）v3
# ------------------------------------------------------------
# 作用：
#  1) 根据本次 git 变更文件范围，只选择受影响的测试文件（公交攒批）；
#  2) 结合「测试结果哈希缓存」，对"代码+测试均未变化的用例"跳过不跑，
#     彻底杜绝"同一份代码反复全量跑 / 无任何变动也重复测试"。
#
# 用法：
#   bash scripts/change-aware-test.sh                # 自动检测变更（PR/push/本地）
#   bash scripts/change-aware-test.sh --all          # 强制全量跑（main push / 合并门禁用）
#   bash scripts/change-aware-test.sh --dry-run      # 只打印将运行的测试，不实际执行
#   bash scripts/change-aware-test.sh --base=SHA     # 指定比对基线（否则自动探测）
#   bash scripts/change-aware-test.sh --no-cache     # 忽略缓存，强制重跑本次选中的用例
#   bash scripts/change-aware-test.sh --purge-cache  # 清空结果缓存目录
#
# 环境变量：
#   CNB_PULL_REQUEST_TARGET_SHA  # PR 目标分支 SHA（CNB 内置变量）
#   CNB_COMMIT                   # 本次提交 SHA（CNB 内置变量）
#   HH_TEST_CACHE_DIR       # 结果缓存目录（默认 .testcache，可用 cache: 卷持久化）
#
# 缓存语义：
#   - 每个测试文件的"覆盖指纹" = hash( 测试文件内容 + 该测试 import 的 hanghang 源码 )
#   - 若某测试文件上次已跑且 PASS，且本次覆盖指纹未变 → 跳过（print 命中）；
#   - 只要其覆盖的任意源码或测试自身变了，指纹即变 → 必然重跑（不会漏测）。
#     main 全量回归（--all）永远全跑，不被缓存跳过，仍由 main.push 兜底不漏测。
# ============================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=false
FORCE_ALL=false
NO_CACHE=false
PURGE_CACHE=false
BASE_SHA=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --all) FORCE_ALL=true ;;
    --base=*) BASE_SHA="${arg#*=}" ;;
    --no-cache) NO_CACHE=true ;;
    --purge-cache) PURGE_CACHE=true ;;
  esac
done

# 结果缓存目录：可用环境变量 / CNB cache: 卷持久化，跨流水线复用
CACHE_DIR="${HH_TEST_CACHE_DIR:-${REPO_ROOT}/.testcache}"

if [ "$PURGE_CACHE" = "true" ]; then
  echo "==== [change-aware] 清空结果缓存: $CACHE_DIR ===="
  rm -rf "$CACHE_DIR"
fi

SELECTED_TESTS=""
if [ "$FORCE_ALL" = "true" ]; then
  echo "==== [change-aware] 强制全量模式（绕过缓存，全量回归） ===="
  SELECTED_TESTS=$(ls tests/test_*.py 2>/dev/null)
else
  # ---- 探测变更基线 ----
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

  SELECTED_TESTS=$(python3 - "$BASE_SHA" <<'PY'
import os, re, subprocess, sys
repo = os.getcwd()
base_sha = sys.argv[1] if len(sys.argv) > 1 else ""
def git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True,
                          text=True, cwd=repo).stdout.strip()
changed = []
if base_sha:
    try:
        changed = git("diff", "--name-only", f"{base_sha}...HEAD").split("\n")
    except Exception:
        changed = []
ws = git("diff", "--name-only").split("\n")
changed = [c for c in (changed + ws) if c]
changed = list(dict.fromkeys(changed))
if not changed:
    print("__ALL__")
    sys.exit(0)

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
    ("src/hanghang/engine/metrics.py", [
        "tests/test_web.py", "tests/test_state_cli_e2e.py",
    ]),
    ("src/hanghang/engine/prefix.py", [
        "tests/test_registry.py", "tests/test_dongjiagoushi_routing.py",
        "tests/test_web.py",
    ]),
    ("src/hanghang/state/", [
        "tests/test_state_manager.py", "tests/test_state_tree.py",
        "tests/test_batch_persist.py", "tests/test_state_cli_e2e.py",
        "tests/test_web.py",
    ]),
    ("src/hanghang/context/", ["tests/test_context_m10.py"]),
    ("src/hanghang/review/", ["tests/test_review.py"]),
    ("src/hanghang/web/", ["tests/test_web.py"]),
    ("src/hanghang/cli/", [
        "tests/test_state_cli_e2e.py", "tests/test_state_manager.py",
        "tests/test_web.py",
    ]),
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
DOC_ONLY_PATTERNS = ["docs/", "README.md", ".md", "poc/"]
def is_doc_only(cf):
    if not cf:
        return False
    for f in cf:
        f=f.strip()
        if not f:
            continue
        if not any(p in f for p in DOC_ONLY_PATTERNS):
            return False
    return True
selected, seen = [], set()
for f in changed:
    f=f.strip()
    if not f:
        continue
    if f.startswith("tests/test_") and f.endswith(".py"):
        if f not in seen:
            seen.add(f); selected.append(f)
        continue
    for pat, tests in MAP:
        if pat in f:
            for t in tests:
                if t not in seen:
                    seen.add(t); selected.append(t)
root_files = [".cnb.yml", "requirements.txt", "setup.py", "cli/route", "src/hanghang/__init__.py"]
for f in changed:
    if f.strip() in root_files:
        for t in ["tests/test_router.py","tests/test_registry.py",
                  "tests/test_handoff.py","tests/test_data_driven.py"]:
            if t not in seen:
                seen.add(t); selected.append(t)
if is_doc_only(changed):
    print("__NONE__")
elif not selected:
    print("__ALL__")
else:
    for t in selected:
        print(t)
PY
)
fi

# ---- 归一化 __ALL__/__NONE__ ----
MODE=""
if [ "$SELECTED_TESTS" = "__ALL__" ]; then
  MODE="全量（无法确定变更范围 / 根级变更 / 未知代码变更）"
  SELECTED_TESTS=$(ls tests/test_*.py 2>/dev/null)
elif [ "$SELECTED_TESTS" = "__NONE__" ]; then
  MODE="纯文档变更，跳过行为测试（跑轻量 CLI 冒烟即可）"
  SELECTED_TESTS=""
else
  MODE="变更感知"
fi
echo "==== [change-aware] $MODE ===="
echo "  缓存目录: $CACHE_DIR (可用 HH_TEST_CACHE_DIR 或 cache: 卷覆盖)"
echo "  选中测试文件($(echo "$SELECTED_TESTS" | grep -c . )):"
for t in $SELECTED_TESTS; do
  echo "    $t"
done

# ---- 指纹计算 + 缓存命中判定 + 生成执行计划 ----
python3 - "$REPO_ROOT" "$CACHE_DIR" "$SELECTED_TESTS" "$NO_CACHE" <<'PY'
import os, re, sys, json
repo, cache_dir, selected_arg, no_cache = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]=="true"
os.chdir(repo)
selected = [t for t in selected_arg.split() if t]

def walk_py(pkg_dir):
    out=[]
    for dp,_,fs in os.walk(pkg_dir):
        for fn in fs:
            if fn.endswith(".py"):
                out.append(os.path.join(dp,fn))
    return out

def covered_src(test_file):
    src=open(test_file).read()
    mods=set()
    for m in re.finditer(r'^(?:from|import)\s+([\w.]+)', src, re.M):
        mod=m.group(1)
        if mod.startswith("hanghang"):
            mods.add(mod)
    files=set()
    for mod in mods:
        p=mod.replace(".","/")
        for cand in (os.path.join("src",p)+".py", os.path.join("src",p)):
            if os.path.isfile(cand):
                files.add(cand)
            elif os.path.isdir(cand):
                files.update(walk_py(cand))
    if not files:
        for dp,_,fs in os.walk("src"):
            for fn in fs:
                if fn.endswith(".py"):
                    files.add(os.path.join(dp,fn))
    return sorted(files)

def blob_hash(path):
    import hashlib
    try:
        with open(path,"rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return "missing"

def compute_key(test_file):
    import hashlib
    h=hashlib.sha256()
    h.update(("TF:"+blob_hash(test_file)).encode())
    for s in covered_src(test_file):
        h.update(("|"+s+":"+blob_hash(s)).encode())
    return h.hexdigest()

os.makedirs(cache_dir, exist_ok=True)
cache_file=os.path.join(cache_dir,"results.json")
cache={}
if os.path.exists(cache_file):
    try:
        cache=json.load(open(cache_file))
    except Exception:
        cache={}

plan=[]
for t in sorted(selected):
    if not os.path.isfile(t):
        plan.append([t,"missing",None]); continue
    key=compute_key(t)
    prev=cache.get(t)
    if (not no_cache) and prev and prev.get("key")==key and prev.get("result")=="pass":
        plan.append([t,"skip",key])
    else:
        plan.append([t,"run",key])

run=[p for p in plan if p[1]=="run"]
skip=[p for p in plan if p[1]=="skip"]
print("\n  本次实跑 {} 个 / 命中缓存跳过 {} 个".format(len(run), len(skip)))
for t,act,_ in plan:
    if act=="run":
        print("    >> 运行  "+t)
    elif act=="skip":
        print("    -- 跳过  "+t+"（代码与测试均未变化，上次已 PASS）")

with open(os.path.join(cache_dir,".plan.json"),"w") as f:
    json.dump([p for p in plan if p[1] in ("run","skip")], f)
PY

if [ "$DRY_RUN" = "true" ]; then
  exit 0
fi

# ---- 读取执行计划（跳过命中缓存的用例，只跑变更影响的）----
PLAN_FILE="${CACHE_DIR}/.plan.json"
RUN_FILES=""
if [ -f "$PLAN_FILE" ]; then
  RUN_FILES=$(python3 - "$PLAN_FILE" <<'PY'
import json,sys
for t,act,_ in json.load(open(sys.argv[1])):
    if act=="run":
        print(t)
PY
)
  rm -f "$PLAN_FILE"
else
  RUN_FILES=$SELECTED_TESTS
fi

pip install -q -r requirements.txt 2>/dev/null || true

echo ""
FAILED=0
PASSED_FILES=""
for t in $RUN_FILES; do
  if [ ! -f "$t" ]; then
    echo "  ! 跳过不存在: $t"
    continue
  fi
  echo ""
  echo "==== 运行测试: python3 $t ===="
  if python3 "$t"; then
    echo "  OK $t 通过"
    PASSED_FILES="$PASSED_FILES $t"
  else
    echo "  FAIL $t 失败"
    FAILED=1
  fi
done

# ---- 回写缓存：记录本批实跑且 PASS 的测试指纹 ----
if [ "$FAILED" = "0" ] && [ -n "$PASSED_FILES" ]; then
  python3 - "$CACHE_DIR" "$PASSED_FILES" <<'PY'
import os, re, sys, json
cache_dir, passed_str = sys.argv[1], sys.argv[2]
def walk_py(pkg_dir):
    out=[]
    for dp,_,fs in os.walk(pkg_dir):
        for fn in fs:
            if fn.endswith(".py"): out.append(os.path.join(dp,fn))
    return out
def blob_hash(p):
    import hashlib
    try:
        return hashlib.sha256(open(p,"rb").read()).hexdigest()
    except OSError: return "missing"
def compute_key(test_file):
    import hashlib
    src=open(test_file).read()
    mods=set(m.group(1) for m in re.finditer(r'^(?:from|import)\s+([\w.]+)',src,re.M) if m.group(1).startswith("hanghang"))
    files=set()
    for mod in mods:
        p=mod.replace(".","/")
        for cand in (os.path.join("src",p)+".py", os.path.join("src",p)):
            if os.path.isfile(cand): files.add(cand)
            elif os.path.isdir(cand): files.update(walk_py(cand))
    if not files:
        for dp,_,fs in os.walk("src"):
            for fn in fs:
                if fn.endswith(".py"): files.add(os.path.join(dp,fn))
    h=hashlib.sha256()
    h.update(("TF:"+blob_hash(test_file)).encode())
    for s in sorted(files):
        h.update(("|"+s+":"+blob_hash(s)).encode())
    return h.hexdigest()
cache_file=os.path.join(cache_dir,"results.json")
cache={}
if os.path.exists(cache_file):
    try: cache=json.load(open(cache_file))
    except Exception: cache={}
os.makedirs(cache_dir, exist_ok=True)
for t in passed_str.split():
    t=t.strip()
    if t:
        cache[t]={"key":compute_key(t),"result":"pass"}
json.dump(cache, open(cache_file,"w"), ensure_ascii=False, indent=1)
print("  [cache] 已记录 {} 个 PASS 测试指纹 -> {}".format(len(passed_str.split()), cache_file))
PY
fi

echo ""
if [ "$FAILED" = "0" ]; then
  echo "==== [change-aware] 所有本次实跑测试通过 ===="
else
  echo "==== [change-aware] 存在失败测试 ===="
fi
exit $FAILED
