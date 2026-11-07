"""Reuters provenance, recency, normalization, and direct-source routing."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

with patch.dict(os.environ, {"LITELLM_LOCAL_MODEL_COST_MAP": "True"}):
    from trendradar.crawler.fetcher import DataFetcher
    from trendradar.crawler.reuters import FEED_URL, MAX_ITEMS, parse_reuters_feed
    from trendradar.context import AppContext
    from trendradar.report.generator import prepare_report_data

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def article(title="AI news - Reuters", hours=1, **overrides):
    return dict(title=title, link="https://news.google.com/rss/articles/test?oc=5",
                date=format_datetime(NOW - timedelta(hours=hours)),
                source="Reuters", publisher="https://www.reuters.com", **overrides)


def feed(articles):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    for data in articles:
        item = ET.SubElement(channel, "item")
        for tag, key in (("title", "title"), ("link", "link"), ("pubDate", "date")):
            ET.SubElement(item, tag).text = data[key]
        ET.SubElement(item, "source", url=data["publisher"]).text = data["source"]
    return ET.tostring(root, encoding="unicode")


class ReutersSourceTests(unittest.TestCase):
    def test_cleans_titles_sorts_deduplicates_and_limits_results(self):
        articles = []
        for index in range(40):
            item = article(f"Story {index} - Reuters", hours=index / 2)
            item["link"] = f"https://news.google.com/rss/articles/story{index}"
            articles.append(item)
        articles += [dict(articles[0]), dict(articles[1], link=articles[1]["link"] + "?oc=5")]
        items = parse_reuters_feed(feed(list(reversed(articles))), now=NOW)["items"]
        self.assertEqual(len(items), MAX_ITEMS)
        self.assertEqual([item["title"] for item in items], [f"Story {i}" for i in range(30)])
        self.assertTrue(all(item["url"] == item["mobileUrl"] for item in items))
        self.assertEqual(parse_reuters_feed(feed([article("AI &amp; markets - Reuters")]), now=NOW)["items"][0]["title"], "AI & markets")

    def test_rejects_unverified_publishers_unsafe_links_and_stale_articles(self):
        invalid = [
            {"source": "Other News"}, {"publisher": "https://reuters.com.evil.example"},
            {"publisher": "https://reuters.com@evil.example"},
            {"link": "https://news.google.com.evil.example/rss/articles/test"},
            {"link": "http://news.google.com/rss/articles/test"},
            {"link": "https://news.google.com/search?q=Reuters"},
            {"title": " - Reuters"}, {"date": "invalid"},
            {"date": format_datetime(NOW - timedelta(days=2))},
            {"date": format_datetime(NOW + timedelta(hours=1))},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                result = parse_reuters_feed(feed([dict(article(), **changes), article("Valid - Reuters")]), now=NOW)
                self.assertEqual([item["title"] for item in result["items"]], ["Valid"])

    def test_invalid_or_empty_feeds_fail_explicitly(self):
        for xml in ("not xml", "<html/>", "<rss/>", feed([]), feed([article(hours=25)])):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                parse_reuters_feed(xml, now=NOW)

    @patch("trendradar.crawler.fetcher.requests.get")
    def test_routing_reuses_proxy_and_crawl_format(self, get):
        get.return_value = Mock(text=feed([article()]))
        proxy = "http://127.0.0.1:7890"
        fetcher = DataFetcher(proxy_url=proxy, api_url="https://example.com/api/s")
        with patch("trendradar.crawler.fetcher.parse_reuters_feed", side_effect=lambda text: parse_reuters_feed(text, now=NOW)):
            results, names, failed = fetcher.crawl_websites(
                [("reuters", "路透社（Google News）")], domain_rules={"reuters": "news.google.com"},
            )
        self.assertEqual(failed, [])
        self.assertEqual(results["reuters"]["AI news"]["ranks"], [1])
        self.assertEqual(names["reuters"], "路透社（Google News）")
        get.assert_called_once_with(FEED_URL, proxies={"http": proxy, "https": proxy},
                                    headers=fetcher.DEFAULT_HEADERS, timeout=10)

    @patch("trendradar.crawler.fetcher.requests.get")
    def test_malformed_response_is_reported_as_failure(self, get):
        get.return_value = Mock(text="<html>Unavailable</html>")
        raw, source, _ = DataFetcher().fetch_data("reuters", max_retries=0)
        self.assertIsNone(raw)
        self.assertEqual(source, "reuters")

    def test_translated_reuters_items_join_existing_keyword_groups(self):
        ctx = AppContext({
            "PLATFORMS": [{"id": "reuters", "translate_before_filter": True}],
            "AI_TRANSLATION": {"ENABLED": True, "LANGUAGE": "中文"},
            "WEIGHT_CONFIG": {"RANK_WEIGHT": 0.6, "FREQUENCY_WEIGHT": 0.3, "HOTNESS_WEIGHT": 0.1},
        })
        ctx.is_first_crawl = lambda: True
        ctx._filter_translator = Mock()
        ctx._filter_translator.translate_batch.return_value = SimpleNamespace(results=[
            SimpleNamespace(success=True, translated_text="人工智能市场增长"),
        ])
        results = {"reuters": {"AI market grows": {"ranks": [1]}}, "baidu": {"国内人工智能新闻": {"ranks": [2]}}}
        groups = [{"group_key": "AI 相关", "normal": ["人工智能"], "required": []}]
        stats, _ = ctx.count_frequency(results, groups, [], {"reuters": "路透社（Google News）", "baidu": "百度"})
        self.assertEqual(stats[0]["count"], 2)
        report = prepare_report_data(stats)
        self.assertEqual({t["title"] for t in report["stats"][0]["titles"]}, {"人工智能市场增长", "国内人工智能新闻"})
        ctx._filter_translator.translate_batch.assert_called_once_with(["AI market grows"])


if __name__ == "__main__":
    unittest.main()
