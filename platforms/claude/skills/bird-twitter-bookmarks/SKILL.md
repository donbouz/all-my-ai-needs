---
name: bird-twitter-bookmarks
description: "Manage X/Twitter bookmarks locally with Field Theory CLI. Actions: sync, search, list, classify, stats, viz. Keywords: x bookmarks, twitter bookmarks, fieldtheory, ft."
---

# Field Theory Bookmarks Skill

使用 `fieldtheory`（`ft`）管理 X/Twitter 收藏夹的本地数据副本：同步、检索、筛选、分类、统计与可视化。

## 适用场景

触发关键词：

- `x 收藏夹` / `twitter bookmarks` / `bookmarks`
- `fieldtheory` / `ft`
- `同步收藏夹` / `搜索收藏` / `分类收藏`
- `收藏夹统计` / `收藏夹可视化`

## 前置条件

1. 已安装 `Node.js 20+` 与 `fieldtheory` CLI。
2. Chrome 已登录 `x.com`。
3. 当前网络环境访问 X 需要走本地代理，并启用 Node 环境代理：
   - `NODE_USE_ENV_PROXY=1`
   - `HTTP_PROXY=http://127.0.0.1:7897`
   - `HTTPS_PROXY=http://127.0.0.1:7897`

推荐命令前缀：

```bash
NODE_USE_ENV_PROXY=1 HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 ft <command>
```

## 核心命令

### 1) 首次同步

```bash
NODE_USE_ENV_PROXY=1 HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 ft sync
```

快速自测（只拉 1 页）：

```bash
NODE_USE_ENV_PROXY=1 HTTP_PROXY=http://127.0.0.1:7897 HTTPS_PROXY=http://127.0.0.1:7897 ft sync --max-pages 1
```

### 2) 搜索与查看

```bash
ft search "agent memory"
ft list --author wangray --limit 20
ft show <tweet_id>
```

### 3) 分类与统计

```bash
ft classify --regex
ft categories
ft domains
ft stats
ft viz
```

### 4) 路径与状态

```bash
ft path
ft status
```

## 数据路径

默认存储目录：

```bash
~/.ft-bookmarks/
```

可覆盖为自定义目录：

```bash
FT_DATA_DIR=/path/to/dir ft sync
```

## 安全说明

- 默认是本地落盘，不会自动修改 X 平台内的收藏夹结构。
- `ft classify` 会调用本机可用的 `claude` 或 `codex` CLI 做分类（非纯离线规则）。
- 若只想本地规则分类，可用 `ft classify --regex`。
- 若出现 `fetch failed`，优先检查是否缺少 `NODE_USE_ENV_PROXY=1`。
