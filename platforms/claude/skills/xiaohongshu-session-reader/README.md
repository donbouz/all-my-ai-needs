# xiaohongshu-session-reader

## 作用
HTTP/API 优先读取小红书内容（主页卡片、详情），遇到风控时再降级到浏览器兜底。

## 能力范围
- 主页卡片标题抓取（适配“谁是卧底”词组整理）
- 详情页标题/描述提取
- 评论接口探测（命中风控时明确返回需要浏览器兜底）

## 快速验证
```bash
python3 ~/.claude/skills/xiaohongshu-session-reader/scripts/xhs_http_reader.py \
  --url "https://xhslink.com/m/18Xtbqr4KgO" \
  --mode profile \
  --max-items 5 \
  --pretty
```
