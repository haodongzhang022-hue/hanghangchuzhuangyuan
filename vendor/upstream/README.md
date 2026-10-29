# 上游快照目录（vendor/upstream）

本目录**只存放第三方上游项目的原样快照**，用于离线复现与岗位画像生成，
不是本仓库主线代码。禁止在此目录内直接修改业务逻辑。

## 快照清单

| 目录 | 上游 | 用途 | 许可 |
|------|------|------|------|
| `knowledge-work-plugins/` | [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) | 岗位插件结构/技能包装的参考实现，供 M11 岗位画像 `plugin_artifacts` 与工作流模板生成器离线渲染 | Apache-2.0（见其 `LICENSE`） |

## 刷新方式（可复现，不依赖运行期网络）

```bash
# 1) 拉取指定 commit 的上游快照
git clone --depth 1 https://github.com/anthropics/knowledge-work-plugins.git /tmp/kwp
cd /tmp/kwp && git rev-parse HEAD        # 记录 commit，写进对应 README

# 2) 去 .git 后原样拷回本目录
rsync -a --exclude .git /tmp/kwp/ vendor/upstream/knowledge-work-plugins/

# 3) 重新生成岗位画像（见 docs/architecture/M11-岗位画像层.md）
pip install -r requirements.txt
python3 scripts/gen_rolecards.py --from-kwp vendor/upstream/knowledge-work-plugins
bash scripts/change-aware-test.sh
```

## 约束

- 上游快照**只读**：需要改动请在 `data/role-profiles/`（我方画像数据）或
  `scripts/gen_rolecards.py`（渲染器）中做，不要直接改快照内容。
- 上游目录内含 `.claude-plugin/`、`.mcp.json` 等 Claude 生态文件，本仓库
  **不加载**它们，只解析 `skills/*/SKILL.md` 的 frontmatter（`name`/`description`/`argument-hint`）。
