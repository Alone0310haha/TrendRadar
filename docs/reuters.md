# 路透社报道

`reuters` 获取 [Google News 收录的 Reuters 报道](https://news.google.com/rss/search?q=site%3Areuters.com+when%3A1d&hl=en-US&gl=US&ceid=US%3Aen)，显示名称为“路透社（Google News）”。这是第三方新闻索引，不是路透社官方 API，不抓取付费正文；点击通过 Google News 跳转到报道。

在 `config/config.yaml` 的 `platforms.sources` 中配置：

```yaml
- id: "reuters"
  name: "路透社（Google News）"
  expected_domain: "news.google.com"
  translate_before_filter: true
```

中文配置已启用。直接访问 Google News RSS，不依赖 NewsNow，不需要新增密钥或依赖。每次保留最近 24 小时内最新的 30 条不同标题/链接，校验发布者名称及 Reuters 域名。Google News 单次返回数量有限，不能保证覆盖路透社所有报道。展示中的排名数字代表本次新闻列表顺序，**不代表路透社热搜或阅读热度**。

沿用已有 AI 配置：`ai_translation.enabled: true`、`language: "中文"`。英文标题先翻译，再匹配现有关键词，合并至“热点词汇统计”的相应主题；未匹配的报道不展示。原文用于历史记录与新增判定，译文用于展示。翻译失败时回退到原文匹配。

现有 GitHub Actions 在下次运行时自动加载；原有 AI、通知和存储 Secrets 继续使用。抓取日志包含 `获取 reuters 成功`。接口失败、没有新报道或格式变化时会记录源失败，不拿旧新闻补位，也不影响其他数据源。

该订阅依赖 Google News 索引与网络可用性。当地无法连接 Google News 时，本地运行需使用项目已有代理配置；GitHub Actions 使用运行器的网络。
