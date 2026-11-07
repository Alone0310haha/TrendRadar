"""Official Bloomberg RSS provenance, recency, and integration checks."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

with patch.dict(os.environ, {"LITELLM_LOCAL_MODEL_COST_MAP": "True"}):
    from trendradar.crawler.fetcher import DataFetcher
    from trendradar.crawler.bloomberg import FEED_URL, MAX_ITEMS, parse_bloomberg_feed

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def article(index=0):
    return {"title": f"Markets story {index}",
            "link": f"https://www.bloomberg.com/news/articles/story-{index}",
            "pubDate": format_datetime(NOW - timedelta(minutes=index))}


def feed(items):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    for data in items:
        item = ET.SubElement(channel, "item")
        for tag, value in data.items():
            ET.SubElement(item, tag).text = value
    return ET.tostring(root, encoding="unicode")


class BloombergSourceTests(unittest.TestCase):
    def test_latest_first_unique_and_capped_with_original_links(self):
        articles = [article(i) for i in range(40)]
        articles += [article(), dict(article(1), link=article(1)["link"] + "?ref=rss")]
        parsed = parse_bloomberg_feed(feed(list(reversed(articles))), now=NOW)
        self.assertEqual(parsed["status"], "success")
        items = parsed["items"]
        self.assertEqual(len(items), MAX_ITEMS)
        self.assertEqual([i["title"] for i in items], [f"Markets story {i}" for i in range(30)])
        self.assertEqual(items[0]["url"], article()["link"])
        self.assertTrue(all(i["url"] == i["mobileUrl"] for i in items))
        self.assertIsNone(DataFetcher._check_domain_safety(items, "bloomberg.com"))

    def test_decodes_entities_and_rejects_bad_links_dates_and_empty_titles(self):
        invalid = [
            {"link": "http://www.bloomberg.com/news/story"},
            {"link": "https://www.bloomberg.com.evil.example/news/story"},
            {"link": "https://www.bloomberg.com@evil.example/news/story"},
            {"link": "https://news.google.com/rss/articles/story"},
            {"link": "https://www.bloomberg.com/"}, {"link": "https://["},
            {"title": " "}, {"pubDate": "invalid"},
            {"pubDate": "Sat, 07 Nov 2026 11:00:00"},
            {"pubDate": format_datetime(NOW + timedelta(hours=1))},
            {"pubDate": format_datetime(NOW - timedelta(days=2))},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                items = parse_bloomberg_feed(feed([
                    dict(article(), **changes), dict(article(1), title="AI &amp; markets"),
                ]), now=NOW)["items"]
                self.assertEqual([i["title"] for i in items], ["AI & markets"])

    def test_empty_stale_or_invalid_responses_fail_explicitly(self):
        for xml in ("not xml", "<html/>", "<rss/>", feed([]),
                    feed([dict(article(), pubDate=format_datetime(NOW - timedelta(days=2)))])):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                parse_bloomberg_feed(xml, now=NOW)

    @patch("trendradar.crawler.fetcher.requests.get")
    def test_direct_routing_preserves_proxy_timeout_and_rank(self, get):
        get.return_value = Mock(text=feed([article()]))
        proxy = "http://127.0.0.1:7890"
        fetcher = DataFetcher(proxy_url=proxy, api_url="https://example.com/api/s")
        with patch("trendradar.crawler.fetcher.parse_bloomberg_feed", side_effect=lambda text: parse_bloomberg_feed(text, now=NOW)):
            results, names, failed = fetcher.crawl_websites(
                [("bloomberg", "彭博社")], domain_rules={"bloomberg": "bloomberg.com"},
            )
        self.assertEqual(failed, [])
        self.assertEqual(names["bloomberg"], "彭博社")
        self.assertEqual(results["bloomberg"]["Markets story 0"]["ranks"], [1])
        get.assert_called_once_with(FEED_URL, proxies={"http": proxy, "https": proxy},
                                    headers=fetcher.DEFAULT_HEADERS, timeout=10)

    @patch("trendradar.crawler.fetcher.requests.get")
    def test_failed_feed_does_not_fall_back_to_another_publisher(self, get):
        get.return_value = Mock(text="<html>Unavailable</html>")
        raw, source, _ = DataFetcher().fetch_data("bloomberg", max_retries=0)
        self.assertIsNone(raw)
        self.assertEqual(source, "bloomberg")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], FEED_URL)


if __name__ == "__main__":
    unittest.main()
