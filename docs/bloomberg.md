# 彭博社报道

`bloomberg` 直接获取 [彭博社官方 RSS](https://www.bloomberg.com/feeds/news.rss) 的标题与报道链接，显示名称为“彭博社”。不依赖 NewsNow、Google News 或额外密钥，不抓取文章正文。

在 `config/config.yaml` 的 `platforms.sources` 中配置（中文配置已启用）：

```yaml
- id: "bloomberg"
  name: "彭博社"
  expected_domain: "bloomberg.com"
  translate_before_filter: true
```

每次从官方订阅中保留最近 24 小时内的报道，按发布时间倒序排列并按标题、链接去重，最多 30 条。实际数量受官方 RSS 返回内容限制，不保证覆盖全部报道。列表序号表示新闻顺序，不代表阅读量或热搜排名。只接受 HTTPS 的 Bloomberg 正站链接。

使用现有 `ai_translation.enabled: true` 和 `language: "中文"`：标题先翻译，再匹配现有关键词，合并到“热点词汇统计”的相应主题，不设独立展示区。未匹配的内容不展示。历史记录按英文原文识别；翻译失败时按原文匹配。

GitHub Actions 下次运行自动使用，无需新增依赖或 Secrets。成功日志为 `获取 bloomberg 成功`。如果订阅失效、没有近期报道或返回非 RSS 页面，记录该源失败并继续其他数据源。仅采集公开订阅中的标题；打开原文时遵循彭博社自身的订阅访问规则。
