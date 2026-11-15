"""段落形状归一：五本账 `_load()` 的统一入口。

为什么单独立一个模块，而不是在每个消费点各兜一次 `(it or {})`：
`(it or {})` 只兜得住 `None`，兜不住字符串。而**数据是人或模型手写的，
列表里混进一个字符串是最常见的一种手滑**。这类错会在消费点炸成
`AttributeError: 'str' object has no attribute 'get'` —— 于是
`industry check` 这个 CI 闸自己 traceback，红灯既不是"数据坏了"也不是"绿"。

已经想到的路各兜一次，想到之外的路照样炸。**只能靠入口收口。**

两条约定，与这几本账的既有立场一致：

1. **不静默丢**：写歪的那一项会记一条 problem，由 `validate()` 报成人话。
   悄悄丢掉等于把缺陷说成"没有这一项"——那是这两轮一直在拆的那种错。
2. **不当成"没填"**：写歪 ≠ 空。前者要改数据，后者要补数据，两句话不能说成一句。
"""

from typing import Iterable, List, Optional


def dict_list(raw, section: str, problems: List[str], where: str = "") -> List[dict]:
    """取一个"对象列表"段落：过滤掉非 mapping 项，并逐条记下它们。

    `section` 是 yaml 里的段名（报错要用它定位），`where` 是文件名。
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        problems.append(
            f"{where} 的 {section} 应写成列表，实际是 {type(raw).__name__}: {raw!r}"
            f"（整段读不出来，等于这一段全部判断/登记都消失了）")
        return []
    out: List[dict] = []
    bad = 0
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        else:
            bad += 1
    if bad:
        problems.append(
            f"{where} 的 {section} 里有 {bad} 项不是映射（写成了 "
            f"{type(next(i for i in raw if not isinstance(i, dict))).__name__} 等）"
            f"（当作不存在会让这一项静默消失，而它在报告里本该占一行）")
    return out


def mapping(raw, section: str, problems: List[str], where: str = "") -> dict:
    """取一个"映射"段落：不是 mapping 就返回空 dict，并记一条 problem。

    `{}` 与"写歪了"在报告里必须能分开：前者是这一格确实没有，后者是这格写坏了。
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    problems.append(
        f"{where} 的 {section} 应写成 {{键: 值}} 映射，实际是 "
        f"{type(raw).__name__}: {raw!r}"
        f"（读不成映射会让整段内容消失，而「说不出」和「忘了写」在报告里长得一样）")
    return {}


def str_list(raw, section: str, problems: List[str], where: str = "") -> List[str]:
    """取一个"字符串列表"段落。

    单独抽出来的理由：`list("规划设计→施工")` 会把一个字符串拆成一个个汉字，
    得到的是一串看起来非空、实际毫无意义的项 —— 比报错更难查。
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        problems.append(
            f"{where} 的 {section} 应写成列表，实际是一个字符串: {raw!r}"
            f"（当成列表会把它逐字拆开，得到一串看着非空、其实没有意义的项）")
        return []
    if not isinstance(raw, list):
        problems.append(
            f"{where} 的 {section} 应写成列表，实际是 {type(raw).__name__}: {raw!r}")
        return []
    out: List[str] = []
    bad = 0
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item)
        elif item is not None:
            bad += 1
    if bad:
        problems.append(
            f"{where} 的 {section} 里有 {bad} 项不是非空字符串（数字/嵌套写混了）")
    return out


def add_all(target: List[str], extra: Optional[Iterable[str]]) -> List[str]:
    """把 `_load()` 记下的问题接到 `validate()` 的名单前面。

    顺序有意：**结构读不出来要排在最前**。它在最上游，下游那几十条判断
    全是基于残缺的数据算出来的，先读那几十条只会让人以为是数据填错了。
    """
    return list(extra or []) + list(target)
