# coding=utf-8
"""Signal 韩国热搜适配器（第三方榜单，不是 Naver 官方热搜）。"""

from typing import Dict
from urllib.parse import urlencode


SOURCE_ID = "signal-hot"
API_URL = "https://api.signal.bz/news/realtime"


def parse_signal_response(data: object) -> Dict:
    """将 Signal 的 top10 转为热榜格式；排名异常时拒绝生成错误榜单。"""
    if not isinstance(data, dict):
        raise ValueError("Signal 响应必须是 JSON 对象")
    entries = data.get("top10")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Signal 响应缺少非空 top10 榜单")

    ranked_keywords = {}
    keywords = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Signal 热搜条目格式异常")
        rank = entry.get("rank")
        keyword = entry.get("keyword")
        if type(rank) is not int or rank < 1 or rank in ranked_keywords:
            raise ValueError("Signal 热搜排名无效或重复")
        if not isinstance(keyword, str) or not keyword.strip():
            raise ValueError("Signal 热搜关键词为空或格式异常")
        keyword = keyword.strip()
        if keyword in keywords:
            raise ValueError("Signal 热搜关键词重复")
        ranked_keywords[rank] = keyword
        keywords.add(keyword)

    # DataFetcher 按列表位置生成排名，不允许缺失条目导致名次前移。
    if sorted(ranked_keywords) != list(range(1, len(entries) + 1)):
        raise ValueError("Signal 热搜排名不连续")

    items = []
    for rank in sorted(ranked_keywords):
        keyword = ranked_keywords[rank]
        # 与 Signal 页面一致：点击关键词打开 Naver 新闻搜索。
        # 自行编码关键词，不使用上游返回的任意跳转链接。
        items.append({
            "title": keyword,
            "url": "https://search.naver.com/search.naver?" + urlencode({
                "where": "news", "query": keyword,
            }),
            "mobileUrl": "https://m.search.naver.com/search.naver?" + urlencode({
                "where": "m_news", "query": keyword,
            }),
        })

    return {"status": "success", "items": items}
