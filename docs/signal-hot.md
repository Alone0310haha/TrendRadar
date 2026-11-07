# Signal 韩国热搜

`signal-hot` 获取 [Signal](https://signal.bz/) 的第三方韩国热搜榜，**不是 Naver 官方热搜**。榜单来自 Signal，点击热词打开 Naver 新闻搜索。

## 配置

在 `config/config.yaml` 的 `platforms.sources` 中追加（保留已有平台）：

```yaml
- id: "signal-hot"
  name: "Signal 韩国热搜（第三方）"
  expected_domain: "naver.com"
```

确保 `platforms.enabled: true`。此源直接请求 `https://api.signal.bz/news/realtime`，读取 `top10`，按 `rank` 排序；不需要 Naver API 密钥，也不经过 `platforms.api_url` 配置的 NewsNow 实例。链接域名校验检查的是 Naver 搜索链接，不能用来证明榜单来自 Naver。

韩文热词可能无法匹配中文关键词。完整展示可设置：

```yaml
display:
  regions:
    standalone: true
  standalone:
    platforms: ["signal-hot"]
    max_items: 20
```

合并到现有 `display` 配置中，不要重复添加顶层键；已有其他独立展示平台时可把 `signal-hot` 追加到列表。本项目中文配置已启用 Signal 的独立展示。英文配置提供禁用的源示例，需按需启用。

如需中文显示，启用 `ai_translation.enabled`、`ai_translation.scope.standalone`，设置 `ai_translation.language: "中文"`，并配置可用的 AI 模型。翻译发生在筛选之后，不能代替韩文关键词匹配；不使用 AI 时仍可展示原始韩文榜单。

## GitHub Actions 使用

将本次代码和配置更新推送到仓库默认分支后，已有的 `Get Hot News` 工作流会在下次运行时自动加载 Signal 数据源，无需新增依赖或 Signal/Naver 密钥，原有 AI、推送和云存储 Secrets 继续使用。

当前 `.github/workflows/crawler.yml` 按北京时间每天 09:00 定时运行，也支持手动运行。推送代码本身不会触发抓取；如需立即使用，在 GitHub 仓库的 **Actions → Get Hot News → Run workflow** 中选择默认分支并运行。手动运行会按原配置执行抓取、AI 分析和通知推送。

抓取成功时，日志会出现 `获取 signal-hot 成功`，报告的独立展示区会显示“Signal 韩国热搜（第三方）”。

## 请求与故障处理

- 沿用热榜抓取器的代理、10 秒超时和重试设置。
- 校验关键词、排名唯一性及连续性，避免异常数据造成名次错误。
- 接口失败或榜单格式变化时记录抓取失败，不自动替换成新闻排行或其他榜单。
- 该接口是 Signal 网站使用的接口，并非有稳定性承诺的官方开放 API；接口变化时需更新适配器。

运行相关测试（不会请求网络或发送通知）：

```console
uv run python -m unittest discover -s tests -p "test_signal_source.py"
```
