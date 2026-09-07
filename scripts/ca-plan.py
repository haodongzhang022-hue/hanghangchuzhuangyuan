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
# 自动依赖推断：把测试文件的 import 精确解析为"真正会被改动"的源码文件。
# 对形如 "from hanghang.engine import Registry" 的【包面引用】，穿透包 __init__.py
# 的再导出，落到 Registry 实际定义所在的子模块（registry.py / router.py），
# 从而改动引擎子模块时能选中直测它的测试（修复 v2 MAP 以来的测试安全性回退）。
SRC_ROOTS = [s.rstrip("/") for s in SRC_GLOB.split() if s]
_EXTS = [".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".jsx", ".tsx", ".json"]
# 各语言包目录入口文件名（__init__.py / index.js ...）
_PKG_INIT = {".py": "__init__", ".js": "index", ".mjs": "index",
             ".cjs": "index", ".ts": "index", ".mts": "index",
             ".jsx": "index", ".tsx": "index"}
# 兼容旧命名的扩展清单（含空串）
exts = list(_EXTS) + [""]

# from hanghang.engine import A, B as C, ( D, E )   —— 跨行括号
_IMPORT_FROM = re.compile(
    r"^\s*from\s+((?:\.)*[A-Za-z_][\w.]*)\s+import\s+(.+?)(?=\n|$)",
    re.MULTILINE | re.DOTALL,
)
# import hanghang.engine  /  import hanghang.engine as eng
_IMPORT_BARE = re.compile(
    r"^\s*import\s+([A-Za-z_][\w.]+)(?:\s+as\s+[\w_]+)?",
    re.MULTILINE,
)
# JS/node 点相对导入
_ES_IMPORT = re.compile(
    r"""(?:from\s+['"])(\.[^'"]*)|(?:import\s*\(\s*['"])(\.[^'"]*)|(?:require\s*\(\s*['"])(\.[^'"]*)"""
)


def _split_import_names(raw):
    """把 'A, B as C, (D,E)' 拆为纯名字列表（去别名/括号/注释/星号）。"""
    raw = re.sub(r"#.*", "", raw)
    out = []
    for part in raw.replace("(", " ").replace(")", " ").split(","):
        toks = part.split()
        if not toks or toks[0] in ("as", "*"):
            continue
        # 'X as Y' 取 X
        out.append(toks[0])
    return out


def _locate_abs(mod):
    """定位绝对模块（可多层点）到仓库源文件。

    返回 (kind, rel)：
      kind "file"    -> 单个源文件（.py / .js / ...）
      kind "package" -> 该包的 __init__ 入口文件（供穿透再导出）
    定位不到返回 None。
    """
    rp = mod.replace(".", "/")
    for r in SRC_ROOTS:
        base = os.path.join(r, rp)
        for e in _EXTS:
            if os.path.isfile(base + e):
                return ("file", _rel(base + e))
        if os.path.isdir(base):
            for e in _EXTS:
                entry = _PKG_INIT.get(e)
                if not entry:
                    continue
                p = os.path.join(base, entry + e)
                if os.path.isfile(p):
                    return ("package", _rel(p))
    return None


def _rel_sub_from(pkg_dir_rel, sub):
    """包 __init__ 内相对再导出（from .X import ...）按同目录定位到文件。"""
    base = os.path.join(repo, pkg_dir_rel, sub.replace(".", "/"))
    for e in _EXTS:
        if os.path.isfile(base + e):
            return ("file", _rel(base + e))
    if os.path.isdir(base):
        for e in _EXTS:
            entry = _PKG_INIT.get(e)
            if not entry:
                continue
            p = os.path.join(base, entry + e)
            if os.path.isfile(p):
                return ("package", _rel(p))
    return None


# ---- 包再导出穿透索引（缓存） ----
_pkg_index_cache = {}


def _pkg_surface(init_rel):
    """解析包 __init__ 的完整再导出面。

    返回 (files_set, name2file)：
      files_set  : 该包直接+递归再导出的所有源文件（覆盖面，用于整包/兜底）
      name2file  : {导出名 -> 最终定义所在的源文件}
    结果按 init_rel 缓存（防环：解析中把占位先入缓存）。
    """
    if init_rel in _pkg_index_cache:
        return _pkg_index_cache[init_rel]
    # 占位防环
    _pkg_index_cache[init_rel] = (set(), {})
    files = set()
    name2file = {}
    ip = os.path.join(repo, init_rel)
    pkg_dir_rel = os.path.dirname(init_rel)
    if not os.path.isfile(ip):
        _pkg_index_cache[init_rel] = (files, name2file)
        return files, name2file
    src = open(ip, encoding="utf-8", errors="replace").read()

    def absorb(got, batch_names, want_subname2file):
        """把一次 from 再导出的目标文件并入索引。"""
        if not got:
            return
        kind, rel = got
        if kind == "file":
            files.add(rel)
            for nm in batch_names:
                name2file.setdefault(nm, rel)
                want_subname2file.setdefault(nm, rel)
            return
        # 目标是子包：递归其再导出面
        sf, nf = _pkg_surface(rel)
        files.update(sf)
        files.add(rel)
        for nm in batch_names:
            sub = nf.get(nm)
            if sub:
                name2file.setdefault(nm, sub)
                want_subname2file.setdefault(nm, sub)
            else:
                # 该名不在子包精确导出里 → 把子包面全部兜底
                for x in sf:
                    files.add(x)
                    want_subname2file.setdefault(nm, x)
                name2file.setdefault(nm, rel)

    dummy = {}
    for fm in _IMPORT_FROM.finditer(src):
        target = fm.group(1).strip()
        batch = _split_import_names(fm.group(2))
        if target.startswith("."):
            # from .router import ... —— 相对再导出（本包 __init__ 常见形态）
            absorb(_rel_sub_from(pkg_dir_rel, target.lstrip(".")), batch, dummy)
        else:
            absorb(_locate_abs(target), batch, dummy)
    # __init__ 内裸 import（import hanghang.state as st）——整模块展开
    for bm in _IMPORT_BARE.finditer(src):
        target = bm.group(1).strip()
        got = _locate_abs(target)
        if got and got[0] == "package":
            sf, nf = _pkg_surface(got[1])
            files.update(sf)
            files.add(got[1])
            for nm, f in nf.items():
                name2file.setdefault(nm, f)
        elif got and got[0] == "file":
            files.add(got[1])
    _pkg_index_cache[init_rel] = (files, name2file)
    return files, name2file


def parse_refs(text):
    """解析文本 import，返回结构化引用列表（保序去重）。

    每项 (tag, mod, names)：
      ("abs",  "hanghang.engine",  ["Registry","IntentRouter"])  包面 from 点名
      ("all",  "hanghang.engine",  [])                            整模块 import
      ("es",   "tests/helper",     [])                            点相对(node/helper)
    """
    order = []
    seen = set()

    def push(tag, mod, names):
        k = (tag, mod, tuple(sorted(names)))
        if k in seen:
            return
        seen.add(k)
        order.append((tag, mod, names))

    for m in _IMPORT_FROM.finditer(text):
        mod = m.group(1).strip()
        if not mod:
            continue
        names = _split_import_names(m.group(2))
        push("abs", mod, names)
    for m in _IMPORT_BARE.finditer(text):
        push("all", m.group(1).strip(), [])
    for m in _ES_IMPORT.finditer(text):
        v = m.group(1) or m.group(2) or m.group(3)
        if v:
            push("es", re.sub(r"^\.\.?/?", "", v), [])
    return order


def resolve_file(mod):
    """兼容旧接口：模块 -> 相对文件路径或 None（包返回其 __init__）。"""
    if mod.startswith("."):
        rp = re.sub(r"^\.\.?/?", "", mod)
        for d in ["tests", "test", "spec", "src", "lib", "local-agent", "packages"]:
            for e in exts:
                if os.path.isfile(os.path.join(d, rp + e)):
                    return _rel(os.path.join(d, rp + e))
        return None
    got = _locate_abs(mod)
    return got[1] if got else None


def covered_files(tf):
    """返回测试文件直接/间接依赖的源码文件（相对路径），穿透包 __init__ 再导出。"""
    text = open(os.path.join(repo, tf), encoding="utf-8", errors="replace").read()
    files = []
    add = lambda rf: rf not in files and files.append(rf)
    for tag, mod, names in parse_refs(text):
        if tag == "es" or mod.startswith("."):
            rf = resolve_file(mod.lstrip("."))
            if rf:
                add(rf)
            continue
        got = _locate_abs(mod)
        if not got:
            continue
        kind, rel = got
        if kind == "file":
            add(rel)
            continue
        # 包：解析其再导出面
        pkg_files, n2f = _pkg_surface(rel)
        if tag == "all" or not names:
            # 整模块/无可点名 -> 保守覆盖整个再导出面（含包入口自身文件）
            add(rel)
            for f in pkg_files:
                add(f)
            continue
        # 点名：精确命中已匹配名字；未匹配名字走包面兜底，保证不漏
        matched_any = False
        for nm in names:
            f = n2f.get(nm)
            if f:
                add(f)
                matched_any = True
        # 包入口本身：若测试 import 了包内再导出，包 __init__ 改动也应触发
        add(rel)
        if not matched_any:
            # 测试点名一个都不在包导出里精确找到（可能是更深再导出/星号）-> 保守整面
            for f in pkg_files:
                add(f)
    return files

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
