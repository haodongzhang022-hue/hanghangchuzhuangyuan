"""云仓检索层：把类目词表落到 CNB 知识库（云仓），按语义查回来。

为什么还要一层：仓库里的目录化词表解决「谁在维护、怎么分工」；
数据库形态解决「怎么 join、怎么统计」；
但 Agent 干活时问的是「这个行业的上游大概是干嘛的」——这句话没有精确类目名，
需要**语义检索**。CNB 知识库（云仓）干的就是这件事。

设计取舍：
  · 只读，不写。知识库由 main.push 的 knowledge:update 流水线重建（见 .cnb.yml），
    这里不重复实现一遍入库逻辑，避免两套口径打架。
  · 没配 token / 没网 / 接口挂了，一律「降级为本地检索」，绝不阻断主流程。
    云仓是加速层，不是依赖。
  · 只回传命中类目 + 分数 + 来源，不回传整段文档：Agent 要的是"往哪查"，
    不是一篇散文。

环境变量：CNB_TOKEN（访问令牌，需 repo-code:r），CNB_API（默认 https://api.cnb.cool）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

API = os.environ.get("CNB_API", "https://api.cnb.cool")
TIMEOUT = 8

# 这些 kind 不从「自然语言里的词」直接命中：单元名是行业别名、岗位类满地都是，
# 拿它们当检索结果只会干扰判断。
LOCAL_SKIP = ("单元", "岗位类")


class CloudUnavailable(Exception):
    """云仓不可用（无 token / 网络失败 / 接口报错）。调用方应降级。"""


def repo_slug() -> str:
    return os.environ.get("CNB_REPO_SLUG") or "dongdongxiaozu/hanghangchuzhuangyuan"


def _token() -> str:
    token = os.environ.get("CNB_TOKEN") or os.environ.get("CNB_ACCESS_TOKEN") or ""
    if not token:
        raise CloudUnavailable("未配置 CNB_TOKEN，云仓检索不可用（本地词表仍然可用）")
    return token


def query(text: str, top_k: int = 5, threshold: float = 0.0,
          slug: Optional[str] = None) -> List[dict]:
    """查知识库，返回 [{score, chunk, path, url}]。

    失败一律抛 CloudUnavailable，由调用方决定怎么降级 —— 不在这里静默吞掉，
    否则"检索没结果"和"检索没接通"会被混为一谈，那就没法排查了。
    """
    url = (f"{API}/{slug or repo_slug()}/-/knowledge/base/query?"
           + urllib.parse.urlencode({"query": text, "top_k": top_k,
                                     "score_threshold": threshold}))
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise CloudUnavailable(f"知识库检索失败：HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CloudUnavailable(f"知识库检索失败：{exc}") from exc

    hits = []
    for item in payload if isinstance(payload, list) else []:
        meta = item.get("metadata") or {}
        hits.append({
            "score": round(float(item.get("score") or 0), 4),
            "chunk": str(item.get("chunk") or ""),
            "path": str(meta.get("path") or ""),
            "url": str(meta.get("url") or ""),
        })
    return hits


def locate_class(text: str, classes, top_k: int = 5) -> Dict[str, object]:
    """问一句话，回它能对上的类目：命中词 + 云仓来源 + 本地词表兜底。

    本地兜底很简单：句子里的类目名/别名直接扫一遍。这不是要跟云仓竞争，
    而是保证「云仓没接通时 CLI 也不至于哑掉」。
    """
    # 本地兜底只在「词整段出现在查询里」时命中，且不进单字类目：
    # 中文里「开发」「产品」这种词到处都是，一命中反而把真答案淹了。
    local = [name for name in classes.classes
             if len(name) >= 2 and name in text and kind_of(classes, name) not in LOCAL_SKIP]
    for alias, canon in classes.alias_map.items():
        if (alias != canon and len(alias) >= 2 and alias in text
                and canon not in local and kind_of(classes, canon) not in LOCAL_SKIP):
            local.append(canon)

    result: Dict[str, object] = {"query": text, "classes": local, "cloud": [], "source": "local"}
    try:
        hits = query(text, top_k=top_k)
    except CloudUnavailable as exc:
        result["note"] = str(exc)
        return result

    result["cloud"] = hits
    result["source"] = "cloud+local" if local else "cloud"
    return result


def kind_of(classes, name: str) -> str:
    return str(((classes.classes.get(name) or {}).get("kind")) or "")
