"""把新增分区同步进千层饼 L8_05（sublayer=industry）。

口径与已有 82 行完全一致：
  capability_id = industry:<pid>
  module        = hanghangchuzhuangyuan.industry.strategy
  entrypoint    = industry strategy --partition <pid>
  category      = industry-partition
  status        = available / pending
  judgement     = 战略视图压成的判断文本
  pointer       = 策略文件锚点 + cli
  checksum      = sha256('L8_05|industry|<content>')[:32]
幂等：按 capability_id 先删后写。
"""
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

import lancedb
import pyarrow as pa

DB = r'E:\1shuju\knowledge-layers-export-20260925\db\knowledge_layers.lance'
ROOT = r'E:\CNBcool\hanghangchuzhuangyuan'
LAYER = 'L8_05'
SUBL = 'industry'
DIM = 1024

sys.path.insert(0, os.path.join(ROOT, 'src'))
import types
import importlib.util

pkg = os.path.join(ROOT, 'src', 'hanghang')
for n, p in (("hanghang", pkg), ("hanghang.engine", os.path.join(pkg, "engine"))):
    if n not in sys.modules:
        sh = types.ModuleType(n)
        sh.__path__ = [p]
        sys.modules[n] = sh
spec = importlib.util.spec_from_file_location(
    "hanghang.engine.industry_db", os.path.join(pkg, "engine", "industry_db.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["hanghang.engine.industry_db"] = mod
spec.loader.exec_module(mod)
db_i = mod.IndustryDatabase()


def summary_of(row):
    parts = []
    if row.get('position'):
        parts.append('议价位置：' + row['position'])
    if row.get('value_chain'):
        parts.append('价值链：' + ' → '.join(row['value_chain']))
    if row.get('profit_pool'):
        parts.append('利润池：' + '、'.join(x.get('where', '') for x in row['profit_pool']))
    if row.get('leverage'):
        parts.append('杠杆：' + '、'.join(row['leverage']))
    if row.get('drivers'):
        parts.append('驱动：' + '、'.join(row['drivers']))
    if row.get('risks'):
        parts.append('风险：' + '、'.join(row['risks']))
    if row.get('ai_boundary'):
        parts.append('AI 边界：' + row['ai_boundary'])
    if row.get('role_focus_valid'):
        parts.append('岗位落点：' + '、'.join(row['role_focus_valid']))
    return '；'.join(parts)


db = lancedb.connect(DB)
t = db.open_table(LAYER)
df = t.to_pandas()
have = set()
for _, r in df[df['sublayer'] == SUBL].iterrows():
    try:
        have.add(json.loads(r['content']).get('capability_id'))
    except Exception:
        pass

missing = [p for p in db_i.partitions
           if f"industry:{p['id']}" not in have]
print('库里缺的分区:', [p['id'] for p in missing])
if not missing:
    print('无需同步')
    sys.exit(0)

now = datetime.now(timezone.utc)
zeros = [0.0] * DIM
rows = []
for p in missing:
    pid = p['id']
    sv = db_i.strategy.row(pid)
    name = p.get('name', pid)
    judge = f"{name}（{pid}）：{summary_of(sv)}"
    content = json.dumps({
        'capability_id': f'industry:{pid}',
        'module': 'hanghangchuzhuangyuan.industry.strategy',
        'entrypoint': f'python3 src/hanghang/cli/main.py industry strategy --partition {pid}',
        'version': '1.0.0',
        'name': name,
        'category': 'industry-partition',
        'status': 'available' if p.get('status') == 'covered' else 'pending',
        'judgement': judge,
        'pointer': (f'E:/CNBcool/hanghangchuzhuangyuan/data/industry-strategy.yaml#{pid}; '
                    f'cli=python3 src/hanghang/cli/main.py industry strategy --partition {pid}'),
    }, ensure_ascii=False)
    ck = hashlib.sha256(f'{LAYER}|{SUBL}|{content}'.encode()).hexdigest()[:32]
    rows.append({
        'layer_id': LAYER, 'sublayer': SUBL, 'content': content,
        'embedding': zeros,
        'metadata': json.dumps({'cap_id': f'industry:{pid}', 'category': 'industry-partition'},
                               ensure_ascii=False),
        'source': 'hanghangchuzhuangyuan/industry-strategy',
        'checksum': ck, 'created_at': now,
    })

# 已有 82 行而分区只有 41 个 → 每个分区有 2 行重复（历史上被写了两次）。
# 本次只补缺的 4 个，每个写 **1 行**，不复制这个重复。
from collections import Counter
cnt = Counter()
for _, r in df[df['sublayer'] == SUBL].iterrows():
    try:
        cnt[json.loads(r['content']).get('capability_id')] += 1
    except Exception:
        pass
dup = {k: v for k, v in cnt.items() if v > 1}
print(f'注意：已有 {len(dup)} 个分区各写了 2 行（历史重复），本次新分区只写 1 行')

if '--write' not in sys.argv:
    print('（dry-run；加 --write 才落库）')
    sys.exit(0)

stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = os.path.join(os.path.dirname(DB),
                      f'knowledge_layers.lance.bak-pre-sync45-{stamp}')
print('备份 →', os.path.basename(backup))
shutil.copytree(DB, backup)

schema = pa.schema([
    pa.field("layer_id", pa.string()),
    pa.field("sublayer", pa.string()),
    pa.field("content", pa.string()),
    pa.field("embedding", pa.list_(pa.float32(), DIM)),
    pa.field("metadata", pa.string()),
    pa.field("source", pa.string()),
    pa.field("checksum", pa.string()),
    pa.field("created_at", pa.timestamp('us')),
])
before = t.count_rows()
t.add(pa.Table.from_pylist(rows, schema=schema))
print(f'行数: {before} → {t.count_rows()}（写入 {len(rows)} 行）')

df2 = t.to_pandas()
parts2 = set()
for _, r in df2[df2['sublayer'] == SUBL].iterrows():
    try:
        parts2.add(json.loads(r['content']).get('capability_id'))
    except Exception:
        pass
print(f'回读：覆盖分区 {len(parts2)} 个')
