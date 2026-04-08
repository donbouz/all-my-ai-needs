# bird-twitter-bookmarks

## 作用
使用 `fieldtheory`（`ft`）同步并管理 X/Twitter 收藏夹的本地数据：检索、筛选、分类、统计、可视化，以及 unknown 条目 L2 细分标签管理。

## 平台支持
- Codex（已支持）

## 工作原理
- `ft sync` 从 X 拉取收藏夹到本地（默认 `~/.ft-bookmarks`）。
- `ft search/list/stats/viz` 在本地 SQLite FTS5 索引上执行。
- `ft classify` 为本地数据写分类标签，不直接改动 X 平台收藏结构。
- `scripts/bookmark_l2_labels.py` 在本地数据库中补充链接上下文、L2 标签和复核队列。

## 配置命令

```bash
./setup.sh bird-twitter-bookmarks
# 或直接执行
platforms/codex/skills/bird-twitter-bookmarks/setup.sh
```

## 验证命令

```bash
node --version
npm --version
ft --version
NODE_USE_ENV_PROXY=1 HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 ft path
python3 platforms/codex/skills/bird-twitter-bookmarks/scripts/bookmark_l2_labels.py --help
```

## L2 标签命令

```bash
SCRIPT="platforms/codex/skills/bird-twitter-bookmarks/scripts/bookmark_l2_labels.py"
python3 "$SCRIPT" bootstrap
HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 python3 "$SCRIPT" classify-unknown --engine auto --min-confidence 0.7
python3 "$SCRIPT" report
python3 "$SCRIPT" review --limit 20
```

推荐（质量优先）：

```bash
HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 python3 "$SCRIPT" classify-unknown \
  --engine codex --single-stage --stage1-model gpt-5.4-mini --stage1-effort medium \
  --batch-size 10 --skip-link-fetch --min-confidence 0.7 --min-context-chars 24 --low-context-cap 0.55
```

## 使用方式
- 详细触发词与命令映射见：`platforms/codex/skills/bird-twitter-bookmarks/SKILL.md`

## 依赖
- Node.js 20+
- npm
- fieldtheory CLI（`ft`）
- Python3（运行 L2 标签脚本）
- Chrome 登录态（x.com）
