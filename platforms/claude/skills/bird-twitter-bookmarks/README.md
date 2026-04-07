# bird-twitter-bookmarks

## 作用
使用 `fieldtheory`（`ft`）同步并管理 X/Twitter 收藏夹的本地数据：检索、筛选、分类、统计、可视化。

## 平台支持
- Claude Code（已支持）
- Codex（已支持）

## 工作原理
- `ft sync` 从 X 拉取收藏夹到本地（默认 `~/.ft-bookmarks`）。
- `ft search/list/stats/viz` 在本地 SQLite FTS5 索引上执行。
- `ft classify` 为本地数据写分类标签，不直接改动 X 平台收藏结构。

## 配置命令

```bash
./setup.sh bird-twitter-bookmarks
# 或直接执行
platforms/claude/skills/bird-twitter-bookmarks/setup.sh
```

## 验证命令

```bash
node --version
npm --version
ft --version
NODE_USE_ENV_PROXY=1 HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 ft path
```

## 使用方式
- 详细触发词与命令映射见：`platforms/claude/skills/bird-twitter-bookmarks/SKILL.md`

## 依赖
- Node.js 20+
- npm
- fieldtheory CLI（`ft`）
- Chrome 登录态（x.com）
