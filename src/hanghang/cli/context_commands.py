"""M10 × CLI 上下文装配命令：assemble / rules / validate

T1 交付（Issue #14）：把 M10 上下文装配器的三大能力挂到 CLI：
  - context assemble  —— 三层物理隔离装配（SLIB 会话级，assemble_bound）
  - context rules     —— 规则表动态加载（--list / --match）
  - context validate  —— 静态/动态缓存隔离校验（CacheGuard）

纯新增 CLI 入口，不触碰 M10 核心模块。
"""
from __future__ import annotations

import json
import os
import sys

# context_commands.py 位于 <repo>/src/hanghang/cli/ → 向上 3 层 = <repo>/src
_SRC = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
# 仓库根：在 <repo>/src 基础上再向上 1 层
_REPO_ROOT = os.path.dirname(_SRC)

from hanghang.context import (  # noqa: E402
    ContextAssembler, CacheGuard, RuleEngine,
    SLIBAssemblyGuard, SLIBBoundMismatch,
)
from hanghang.engine import Registry  # noqa: E402


def _data_candidates():
    """候选 data/ 目录：当前工作目录优先，仓库根兜底（与 Registry 一致）。"""
    return [
        os.path.join(os.getcwd(), "data"),
        os.path.join(_REPO_ROOT, "data"),
    ]


def _data_file(filename):
    """定位某个数据文件：在候选 data/ 中优先取真实存在该文件的目录。

    原因：assemble 会先在 cwd/data 创建运行期目录（bindings/ 等），
    若仅凭目录存在就选中 cwd/data，会因其中没有 prefix-archive.json /
    context-rules.yaml 而取不到数据。故改按「文件是否存在」判定：
      1) cwd/data 里有该文件 → 用之（用户在仓库根运行时命中）；
      2) 否则回落仓库根 data（测试临时 cwd 场景，读真实数据）；
      3) 都没有 → 返回 cwd/data 下的路径（交由调用方判定不存在）。
    """
    for data_dir in _data_candidates():
        candidate = os.path.join(data_dir, filename)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(_data_candidates()[0], filename)


def _prefix_file():
    return _data_file("prefix-archive.json")


def _rules_file():
    return _data_file("context-rules.yaml")


def _auto_prefix_provider(unit_id: str, role_name: str):
    """从 data/prefix-archive.json 自动取某单元某岗位的稳定前缀。

    供 ContextAssembler.static_prefix_provider 回调使用；未命中返回 None，
    由装配器回落为「岗位骨架」层A，不让 CLI 因取前缀失败而中断。
    """
    prefix_file = _prefix_file()
    if not os.path.exists(prefix_file):
        return None
    try:
        from hanghang.engine.prefix import PrefixArchive
        archive = PrefixArchive(prefix_file)
        return archive.get_role_prefix(unit_id, role_name)
    except Exception:
        return None


def _load_registry():
    """加载行业注册表：cwd/data 优先，仓库根 data 兜底（与 _data_file 一致）。

    临时 cwd 下 Registry 默认搜索路径取不到 data/，会导致所有 --unit
    被误判为"单元不存在"，故显式传入候选路径。
    """
    paths = [d for d in _data_candidates() if os.path.isdir(d)]
    return Registry(search_paths=paths or None)


def _baseline_dir() -> str:
    """层A基线落盘目录：<cwd>/data/state/context_baseline（跨进程）。

    与 _data_file 的"回落仓库根读真实数据"不同：基线是**运行期写入**数据，
    必须严格落在 cwd 下，否则在临时 cwd/测试里会把基线写进仓库工作区。
    """
    return os.path.join(os.getcwd(), "data", "state", "context_baseline")


def _read_baseline(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("signature") if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_baseline(path: str, signature: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"signature": signature}, f)
    os.replace(tmp, path)


def _render_result(result: dict, session_id: str):
    """人类可读渲染一次装配结果"""
    print("=" * 60)
    print(f"上下文装配结果 (session={session_id or '(无会话)'})")
    print("-" * 60)
    sizes = result.get("layer_sizes", {})
    print(f"缓存键 cache_key : {result.get('cache_key', '') or '(空)'}")
    print(f"层尺寸  A={sizes.get('A', 0)}B  B={sizes.get('B', 0)}B  C={sizes.get('C', 0)}B")

    hit_ids = result.get("hit_rule_ids", [])
    print(f"命中规则: {', '.join(hit_ids) if hit_ids else '(无，未触发任何上下文注入)'}")

    print("\n【层A · 静态上下文(缓存键域)】")
    print(result.get("layer_a", "") or "(空)")
    if result.get("layer_b"):
        print("\n【层B · 会话态上下文】")
        print(result["layer_b"])
    if result.get("layer_c"):
        print("\n【层C · 规则注入上下文】")
        print(result["layer_c"])
    print("=" * 60)


def cmd_context_assemble(args):
    """context assemble：SLIB 会话级三层上下文装配

    用法:
        python3 src/hanghang/cli/main.py context assemble --session S --unit U [--role R] [--text T] [--static-prefix P] [--objective O]

    - 不传 --static-prefix 时，自动从 data/prefix-archive.json 取该岗位稳定前缀；
    - 经 assemble_bound（SLIB 装配守卫）：会话已绑定其他行业会友好拦截，避免 403/抛栈。
    """
    session_id = getattr(args, "session", "") or ""
    unit_id = getattr(args, "unit", "") or ""
    role_name = getattr(args, "role", "") or "secretary"
    user_text = getattr(args, "text", "") or ""
    static_prefix = getattr(args, "static_prefix", None)
    objective = getattr(args, "objective", "") or ""

    # 会话已绑定某行业但未显式给 unit_id → 自动从绑定取，方便单发装配
    if not unit_id and session_id:
        try:
            from hanghang.engine.session_binding import SessionBindingStore
            binding = SessionBindingStore().get_binding(session_id)
            if binding is not None:
                unit_id = binding.unit_id
        except Exception:
            pass

    # 行业名须取注册表真实 industry（不是 unit_id），否则绑定文件显示成
    # industry=dongjiagoushi 这种伪行业名。同时校验单元存在性：
    # 不存在的单元若被写入绑定，会把会话永久占死（后续合法单元被 SLIB 拦截）。
    industry = ""
    if unit_id:
        registry = _load_registry()
        unit = registry.get_unit(unit_id)
        if unit is None:
            print(f"⚠️  行业单元不存在: {unit_id}")
            print("    可用单元:")
            for u in registry.all_units():
                print(f"      {u.unit_id} ({u.industry})")
            print("    未写入任何会话绑定，请换一个 --unit 重试。")
            return 1
        industry = unit.industry

    assembler = ContextAssembler(
        rule_engine=RuleEngine(_rules_file()) if os.path.exists(_rules_file())
        else RuleEngine(),
        static_prefix_provider=_auto_prefix_provider,
        slib_guard=SLIBAssemblyGuard(),
    )

    try:
        result = assembler.assemble_bound(
            session_id=session_id,
            role_name=role_name,
            unit_id=unit_id,
            industry=industry,  # 注册表真实行业名（首次绑定写入）
            user_text=user_text,
            static_prefix=static_prefix,
            objective=objective,
        )
    except SLIBBoundMismatch as exc:
        # D-1 SLIB 守卫友好捕获：不抛栈，给出可操作提示
        print(f"⚠️  SLIB 装配守卫拦截: {exc}")
        print(f"    会话 {exc.session_id} 已绑定行业「{exc.bound_industry}」"
              f"({exc.bound_unit})，不能装配 {exc.attempt_unit} 的上下文。")
        print("    跨行业请开新会话。")
        return 1
    except ValueError as exc:
        # 无法确定装配行业（会话未绑定且未提供 unit_id）→ 友好提示
        print(f"⚠️  {exc}")
        print("    请用 --unit 指定行业单元，或先 bind 该会话。")
        print("    示例: context assemble --session S --unit dongjiagoushi --role developer")
        return 1

    _render_result(result, session_id)
    return 0


def cmd_context_rules(args):
    """context rules：规则表动态加载与命中测试

    用法:
        python3 src/hanghang/cli/main.py context rules --list
        python3 src/hanghang/cli/main.py context rules --match "修改代码实现测试"
    """
    engine = RuleEngine(_rules_file()) if os.path.exists(_rules_file()) \
        else RuleEngine()

    if getattr(args, "list", False):
        print(f"上下文规则表（{os.path.abspath(_rules_file())}）")
        print(f"共 {len(engine.list_rules())} 条启用规则:\n")
        print(engine.summary())
        return 0

    text = getattr(args, "match", "") or ""
    if not text:
        print("请用 --list 查看规则表，或用 --match \"文本\" 做命中测试。")
        return 1
    hits = engine.match(text)
    print(f"输入: {text}")
    if not hits:
        print("未命中任何规则 → 本次调用无需额外装配上下文。")
        return 0
    print(f"命中 {len(hits)} 条规则（按优先级排序）:")
    for r in hits:
        layer_desc = {"A": "静态层", "B": "会话态层", "C": "规则注入层"}
        print(f"  - {r.rule_id} {r.name} [目标{r.target_layer} "
              f"{layer_desc.get(r.target_layer, '')}] src={r.data_source}")
        print(f"      描述: {r.description}")
    return 0


def cmd_context_validate(args):
    """context validate：静态/动态缓存隔离校验（CacheGuard）

    用法:
        python3 src/hanghang/cli/main.py context validate --layer-a "静态内容..." [--session S]

    校验层A是否误混入动态内容/缺少静态声明标记。

    说明（缓存命中 / 层A稳定性）：
      CacheGuard 的 _a_signatures 存于进程内存，而 CLI 每次调用都是独立进程，
      进程内自比签名恒相等 → 恒判"命中"，该分支永远为真、毫无判别力。
      故改用**跨进程落盘基线**：层A签名写 data/state/context_baseline/<session>.json，
      下次调用读回比对，给出「首次记录基线」/「与基线一致」/「层A漂移」三态。
    """
    layer_a = getattr(args, "layer_a", "") or ""
    session_id = getattr(args, "session", "") or ""
    if not layer_a:
        print("缺少 --layer-a：请输入待校验的静态层(层A)文本。")
        print('示例: context validate --layer-a "[秘书] | unit=dongjiagoushi | '
              'session_context_static=true" --session demo')
        return 1

    guard = CacheGuard()
    result = guard.validate_isolation(layer_a=layer_a, session_id=session_id)
    signature = result["layer_a_signature"]
    drifted = False

    print(f"缓存隔离校验 (session={session_id or '(无会话)'})")
    print(f"层A签名: {signature}")
    if not session_id:
        print("层A稳定性: -（未指定 --session，跳过跨进程基线比对）")
    else:
        baseline_path = os.path.join(_baseline_dir(), f"{session_id}.json")
        previous = _read_baseline(baseline_path)
        if previous is None:
            _write_baseline(baseline_path, signature)
            print(f"层A稳定性: 首次记录基线 → {baseline_path}")
        elif previous == signature:
            print("层A稳定性: ✅ 与上次落盘基线一致（层A未漂移）")
        else:
            drifted = True
            print("层A稳定性: ❌ 层A签名与上次基线不一致 → 静态层发生漂移")
            print(f"    上次基线: {previous}")

    exit_code = 0
    if result["valid"]:
        print("✅ 校验通过：层A无动态内容混入，且包含静态声明标记。")
    else:
        print("❌ 校验未通过，违规项:")
        for v in result["violations"]:
            print(f"   - {v}")
        exit_code = 1
    if drifted:
        exit_code = 1
    stats = result.get("stats", {})
    print(f"(累计检查 {stats.get('checks', 0)} 次 / 违规 {stats.get('violations', 0)} 次)")
    return exit_code
