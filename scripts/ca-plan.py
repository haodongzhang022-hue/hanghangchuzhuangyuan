#!/usr/bin/env python3
# 通用变更感知测试选择内核（Generic CA planner）v4 - Python 移植
# 输入: --all / --base=SHA / --src=... / --testglob=... / --map=... / --skip=... / --cachedir=... / --no-cache
# 输出(stdout): 执行计划 JSON [[testFile,"run"|"skip",key],...]；日志走 stderr。
# 说明: 本内核与 python 测试生态天然同源（仓库/CI 均为 python），
#       与同目录 change-aware-test.sh 配套使用，取代原 node(ca-plan.mjs) 依赖。
import hashlib
import json
import os
import re
import subprocess
import sys

repo = os.getcwd()


def _get(k, default=""):
    prefix = "--" + k + "="
    for a in sys.argv[1:]:
        if a.startswith(prefix):
            return a[len(prefix):]
    return default


def _flag(k):
    return "--" + k in sys.argv[1:]


FORCE_ALL = _flag("all")
NO_CACHE = _flag("no-cache")
BASE_SHA = _get("base")
SRC_GLOB = _get("src", "src/ lib/ packages/ core/ engine/ app/")
TEST_GLOB = _get("testglob")
MAP_FILE = _get("map")
SKIP_EXTRA = _get("skip", "docs/,README.md,.md,poc/,examples/,.github/,CHANGELOG.md")
CA_TOOL = [
    t for t in _get(
        "tool",
        "scripts/ .cnb/ ci/ .github/ Makefile package.json package-lock.json "
        "pnpm-lock.yaml yarn-lock Dockerfile .dockerignore .gitlab-ci.yml",
    ).split()
    if t
]
CACHE_DIR = _get("cachedir", os.path.join(repo, ".testcache"))


def _rel(p):
    return os.path.relpath(p, repo).replace(os.sep, "/")


def walk_rel(d, out=None):
    if out is None:
        out = []
    if not os.path.exists(d):
        return out
    if os.path.isdir(d):
        for n in sorted(os.listdir(d)):
            walk_rel(os.path.join(d, n), out)
    elif os.path.isfile(d):
        r = _rel(d)
        if "node_modules" not in r and not r.startswith(".git"):
            out.append(r)
    return out


def git(*a):
    try:
        return subprocess.run(
            ["git"] + list(a), capture_output=True, text=True, cwd=repo
        ).stdout.strip()
    except Exception:
        return ""


# ---- 测试识别 ----
_TEST_RE = [
    re.compile(r"^test_.*\.(?:py|sh|bash|mjs|cjs|js|ts)$"),
    re.compile(r"_test\.(?:py|mjs|cjs|js|ts)$"),
    re.compile(r"\.(?:test|spec)\.(?:mjs|cjs|js|ts)$"),
]


def is_test_file(r):
    b = r.split("/")[-1]
    return any(rex.search(b) for rex in _TEST_RE)


def _glob_to_regex(pat):
    # 将简单 glob（支持 **/*）转换为正则
    out = ""
    i = 0
    while i < len(pat):
        c = pat[i]
        if c in ".+^${}()|[\\]":
            out += "\\" + c
        elif c == "*":
            if pat[i + 1:i + 2] == "*":
                out += "(?:.*)?"
                i += 1
            else:
                out += "[^/]*"
        else:
            out += c
        i += 1
    return re.compile("^" + out + "$")


def find_tests():
    all_files = walk_rel(".")
    found = set()
    # 优先常见测试目录
    for d in ["tests", "test", "spec", "__tests__", "local-agent/tests", "test_data"]:
        for f in walk_rel(d):
            if is_test_file(f):
                found.add(f)
    # 全仓兜底
    for f in all_files:
        if is_test_file(f):
            found.add(f)
    if TEST_GLOB:
        pats = [p for p in TEST_GLOB.split() if p]
        res = [_glob_to_regex(p) for p in pats]
        found = {f for f in found if any(rex.match(f) for rex in res)}
    return sorted(found)


# ---- 依赖引用解析 ----
SRC_ROOTS = [s for s in SRC_GLOB.split() if s]
_PY_IMPORT = re.compile(
    r"(?:^\s*from\s+)([A-Za-z_][\w.]*)(?=\s+import|\s*$)"
    r"|(?:^\s*import\s+)([A-Za-z_][\w.]+)",
    re.MULTILINE,
)
_ES_IMPORT = re.compile(
    r"""(?:from\s+['"])(\.[^'"]*)|(?:import\s*\(\s*['"])(\.[^'"]*)|(?:require\s*\(\s*['"])(\.[^'"]*)"""
)


def parse_refs(text):
    # 保持模块在文件中首次出现顺序（与 node Set 插入序一致，保证指纹稳定）
    order = []
    for m in _PY_IMPORT.finditer(text):
        v = m.group(1) or m.group(2)
        if v not in order:
            order.append(v)
    for m in _ES_IMPORT.finditer(text):
        v = m.group(1) or m.group(2) or m.group(3)
        if v not in order:
            order.append(v)
    return order


def resolve_file(mod):
    exts = [".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".jsx", ".tsx", ".json", ""]
    cand = []
    if mod.startswith("."):
        rp = re.sub(r"^\.\.?/?", "", mod)
        for d in ["tests", "test", "spec", "src", "lib", "local-agent", "packages"]:
            for e in exts:
                cand.append(os.path.join(d, rp + e))
    else:
        rp = mod.replace(".", "/")
        for r in SRC_ROOTS:
            for e in exts:
                cand.append(os.path.join(r, rp + e))

    def exists(c):
        return os.path.isfile(c)

    for c in cand:
        if exists(c):
            return _rel(c)
    for c in cand:
        for e in exts:
            ix = c + "/index" + e
            if exists(ix):
                return _rel(ix)
    return None


def covered_files(tf):
    text = open(os.path.join(repo, tf), encoding="utf-8", errors="replace").read()
    files = []
    for mod in parse_refs(text):
        rf = resolve_file(mod)
        if rf and rf not in files:
            files.append(rf)
    return files


# ---- 依赖索引 ----
test_files = find_tests()
if not test_files:
    sys.stderr.write("__NO_TESTS_FOUND__; use --testglob / CA_TEST_GLOB to locate tests.\n")
    sys.exit(2)

src2tests = {}
test2src = {}
for tf in test_files:
    cfs = covered_files(tf)
    test2src[tf] = cfs
    for sf in cfs:
        if sf not in src2tests:
            src2tests[sf] = []
        if tf not in src2tests[sf]:
            src2tests[sf].append(tf)

static_map = []
if MAP_FILE:
    try:
        for raw in open(os.path.join(repo, MAP_FILE), encoding="utf-8", errors="replace"):
            line = raw.split("#")[0].strip()
            if not line:
                continue
            idx = line.find("|")
            if idx < 0:
                continue
            tests = [t.strip() for t in line[idx + 1:].split(",") if t.strip()]
            static_map.append([line[:idx].strip(), tests])
    except Exception:
        pass

# ---- 变更收集（repo 相对路径）----
changed = []
if not FORCE_ALL:
    if BASE_SHA:
        changed = git("diff", "--name-only", BASE_SHA + "...HEAD").split("\n")
    changed += git("diff", "--name-only").split("\n")
    seen = set()
    uniq = []
    for c in changed:
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    changed = [_rel(c) for c in uniq]

skip_prefixes = [s.strip() for s in SKIP_EXTRA.split(",") if s.strip()]
_is_non_trigger = lambda f: any(p in f for p in skip_prefixes)

selected = set()
if FORCE_ALL or not changed:
    selected = set(test_files)
else:
    triggers = [f for f in changed if f and not _is_non_trigger(f)]
    if not triggers:
        sys.stdout.write("[]")
        sys.stderr.write("纯文档/非触发变更 → 无需跑行为测试")
        sys.exit(0)
    for f in triggers:
        if f in test_files:
            selected.add(f)
            continue
        hit = False
        if f in src2tests:
            for tf in src2tests[f]:
                selected.add(tf)
            hit = True
        for pat, tlist in static_map:
            if pat in f:
                for tf in tlist:
                    selected.add(tf)
                hit = True
        if not hit:
            is_tool = any(f.startswith(p) or f == p or "/" + p in f for p in CA_TOOL)
            base = f.split("/")[-1]
            is_dot_cfg = (
                re.match(r"^\.[\w.-]+$", base) is not None
                or re.search(r"\.(?:yml|yaml|json|toml|ini|cfg|lock|md|markdown)$", base) is not None
                or base in ("Makefile", "Dockerfile", "justfile", "Procfile")
            )
            in_src_root = any(f == p or f.startswith(p) for p in SRC_ROOTS)
            looks_src = (
                re.search(r"\.(?:py|js|mjs|cjs|ts|tsx|jsx|go|rs|java|c|cpp|h|hpp|cs|rb|php)$", base) is not None
                or "." not in base
            )
            if not (is_tool or is_dot_cfg) and (in_src_root or (looks_src and not is_tool)):
                selected = set(test_files)

# ---- 指纹缓存 ----
def sha1(s):
    return hashlib.sha1(s if isinstance(s, bytes) else s.encode()).hexdigest()


def blob_hash(fp):
    try:
        with open(os.path.join(repo, fp), "rb") as fh:
            return sha1(fh.read())
    except Exception:
        return "missing"


def compute_key(tf):
    parts = ["TF:" + blob_hash(tf)]
    for sf in (test2src.get(tf) or []):
        parts.append("|" + sf + ":" + blob_hash(sf))
    return sha1("".join(parts))


os.makedirs(CACHE_DIR, exist_ok=True)
cf = os.path.join(CACHE_DIR, "results.json")
cache = {}
if os.path.exists(cf):
    try:
        cache = json.load(open(cf, encoding="utf-8"))
    except Exception:
        cache = {}

plan = []
for tf in sorted(selected):
    key = compute_key(tf)
    prev = cache.get(tf) or {}
    can_skip = (not NO_CACHE) and prev.get("key") == key and prev.get("result") == "pass"
    plan.append([tf, "skip" if can_skip else "run", key])

runs = sum(1 for p in plan if p[1] == "run")
skips = sum(1 for p in plan if p[1] == "skip")
sys.stderr.write(
    "测试文件 %d；选中受影响 %d；本批实跑 %d / 缓存跳过 %d"
    % (len(test_files), len(selected), runs, skips)
)
sys.stdout.write(json.dumps(plan))

# ---- 缓存回写入口：--writecache --cachedir=... --files="t1 t2 ..." ----
if _flag("writecache"):
    files = [x for x in _get("files", "").split() if x]
    cdir = _get("cachedir", os.path.join(repo, ".testcache"))
    os.makedirs(cdir, exist_ok=True)
    cfp = os.path.join(cdir, "results.json")
    wcache = {}
    if os.path.exists(cfp):
        try:
            wcache = json.load(open(cfp, encoding="utf-8"))
        except Exception:
            wcache = {}
    for tf in files:
        # 与主计划共用同一 compute_key（依赖推断/指纹与运行路径完全一致，
        # 确保回写后可被再次命中，不产生 key 漂移）。
        wcache[tf] = {"key": compute_key(tf), "result": "pass"}
    with open(cfp, "w", encoding="utf-8") as fh:
        json.dump(wcache, fh, indent=1)
    sys.stdout.write("cache written %d entries\n" % len(files))
    sys.exit(0)
