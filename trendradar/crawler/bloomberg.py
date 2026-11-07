"""Bloomberg headlines from its public RSS feed (not full articles or a hot list)."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


SOURCE_ID = "bloomberg"
FEED_URL = "https://www.bloomberg.com/feeds/news.rss"
MAX_ITEMS = 30


def parse_bloomberg_feed(content: str, now: datetime | None = None) -> dict:
    """Validate article links and return unique, recent headlines, newest first."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("Bloomberg RSS 格式异常") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("Bloomberg 响应不是 RSS 订阅")

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=1)
    articles = []
    for entry in channel.findall("item"):
        title = unescape(entry.findtext("title", "")).strip()
        link = entry.findtext("link", "").strip()
        try:
            parsed = urlparse(link)
            if not title or parsed.scheme != "https" or parsed.netloc not in {"www.bloomberg.com", "bloomberg.com"}:
                continue
            if not parsed.path.strip("/"):
                continue
            published = parsedate_to_datetime(entry.findtext("pubDate", ""))
            if published.tzinfo is None or not cutoff <= published <= now:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        articles.append((published, title, link))

    items = []
    seen_urls = set()
    seen_titles = set()
    for _, title, link in sorted(articles, key=lambda article: article[0], reverse=True):
        if link in seen_urls or title in seen_titles:
            continue
        seen_urls.add(link)
        seen_titles.add(title)
        items.append({"title": title, "url": link, "mobileUrl": link})
        if len(items) == MAX_ITEMS:
            break
    if not items:
        raise ValueError("Bloomberg RSS 未返回最近 24 小时内可验证的彭博社报道")
    return {"status": "success", "items": items}
