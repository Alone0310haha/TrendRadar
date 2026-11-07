"""Reuters headlines indexed by Google News (not a Reuters API or popularity chart)."""

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urlencode, urlparse
import xml.etree.ElementTree as ET


SOURCE_ID = "reuters"
FEED_URL = "https://news.google.com/rss/search?" + urlencode({
    "q": "site:reuters.com when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en",
})
MAX_ITEMS = 30


def parse_reuters_feed(content: str, now: datetime | None = None) -> dict:
    """Keep verified Reuters items from the last 24 hours, newest first."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("Reuters/Google News RSS 格式异常") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("Reuters/Google News 响应不是 RSS 订阅")

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=1)
    articles = []
    for entry in channel.findall("item"):
        source = entry.find("source")
        if source is None or (source.text or "").strip().casefold() != "reuters":
            continue
        publisher = urlparse(source.get("url", ""))
        if publisher.scheme not in {"http", "https"} or publisher.hostname not in {"reuters.com", "www.reuters.com"}:
            continue
        title = unescape(entry.findtext("title", "")).strip()
        title = title.removesuffix("- Reuters").strip()
        link = entry.findtext("link", "").strip()
        parsed_link = urlparse(link)
        if not title or parsed_link.scheme != "https" or parsed_link.netloc != "news.google.com":
            continue
        if not parsed_link.path.startswith("/rss/articles/"):
            continue
        try:
            published = parsedate_to_datetime(entry.findtext("pubDate", ""))
            if published.tzinfo is None or not cutoff <= published <= now:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        articles.append((published, title, link))

    items = []
    seen_urls = set()
    seen_titles = set()
    for published, title, link in sorted(articles, key=lambda article: article[0], reverse=True):
        if link in seen_urls or title in seen_titles:
            continue
        seen_urls.add(link)
        seen_titles.add(title)
        items.append({"title": title, "url": link, "mobileUrl": link})
        if len(items) == MAX_ITEMS:
            break
    if not items:
        raise ValueError("Reuters/Google News 未返回最近 24 小时内可验证的路透社报道")
    return {"status": "success", "items": items}
