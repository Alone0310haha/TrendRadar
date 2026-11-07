"""Signal source routing, rank integrity, and compatibility with the news pipeline."""

import json
import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import requests

# Package imports also load LiteLLM; keep this test runnable without network access.
with patch.dict(os.environ, {"LITELLM_LOCAL_MODEL_COST_MAP": "True"}):
    from trendradar.crawler.fetcher import DataFetcher
    from trendradar.crawler.signal import API_URL, SOURCE_ID, parse_signal_response
    from trendradar.storage.base import convert_crawl_results_to_news_data


def response_for(payload):
    response = Mock()
    response.text = json.dumps(payload, ensure_ascii=False)
    return response


class SignalParsingTests(unittest.TestCase):
    def test_sorts_ranks_and_encodes_keywords_without_using_upstream_links(self):
        keyword = "삼성 & AI + #뉴스"
        parsed = parse_signal_response({
            "top10": [
                {"rank": 2, "keyword": "두 번째", "summary": "https://example.com"},
                {"rank": 1, "keyword": "  " + keyword + "  "},
            ],
            "articles": [{"title": "Not a search trend"}],
        })
        self.assertEqual(parsed["status"], "success")
        self.assertEqual([item["title"] for item in parsed["items"]], [keyword, "두 번째"])
        for item in parsed["items"]:
            for field, host, where in (
                ("url", "search.naver.com", "news"),
                ("mobileUrl", "m.search.naver.com", "m_news"),
            ):
                url = urlparse(item[field])
                self.assertEqual(url.scheme, "https")
                self.assertEqual(url.netloc, host)
                self.assertEqual(parse_qs(url.query), {"where": [where], "query": [item["title"]]})
                self.assertEqual(url.fragment, "")
        self.assertIsNone(DataFetcher._check_domain_safety(parsed["items"], "naver.com"))

    def test_rejects_missing_empty_or_malformed_payloads(self):
        for payload in (None, [], {}, {"top10": None}, {"top10": {}}, {"top10": []},
                        {"top10": [None]}, {"top10": ["keyword"]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_signal_response(payload)

    def test_rejects_invalid_rank_or_keyword_instead_of_renumbering(self):
        cases = [
            [{"rank": rank, "keyword": "뉴스"}]
            for rank in (None, True, 0, -1, 1.5, "1", 2)
        ]
        cases += [
            [{"rank": 1, "keyword": keyword}]
            for keyword in (None, "", "  ", 123, [], {})
        ]
        cases += [
            [{"rank": 1, "keyword": "뉴스"}, {"rank": 1, "keyword": "다른 뉴스"}],
            [{"rank": 1, "keyword": "뉴스"}, {"rank": 3, "keyword": "다른 뉴스"}],
            [{"rank": 1, "keyword": "뉴스"}, {"rank": 2, "keyword": " 뉴스 "}],
        ]
        for entries in cases:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                parse_signal_response({"top10": entries})


class SignalFetcherTests(unittest.TestCase):
    @patch("trendradar.crawler.fetcher.requests.get")
    def test_direct_source_ignores_newsnow_url_and_preserves_proxy_timeout(self, get):
        get.return_value = response_for({"top10": [{"rank": 1, "keyword": "뉴스"}]})
        proxy = "http://127.0.0.1:7890"
        fetcher = DataFetcher(proxy_url=proxy, api_url="https://example.com/api/s")
        raw, source, name = fetcher.fetch_data((SOURCE_ID, "Signal 韩国热搜（第三方）"))
        self.assertEqual(source, SOURCE_ID)
        self.assertEqual(name, "Signal 韩国热搜（第三方）")
        self.assertEqual(json.loads(raw)["items"][0]["title"], "뉴스")
        get.assert_called_once_with(
            API_URL, proxies={"http": proxy, "https": proxy},
            headers=fetcher.DEFAULT_HEADERS, timeout=10,
        )
        get.return_value.raise_for_status.assert_called_once_with()

    @patch("trendradar.crawler.fetcher.requests.get")
    def test_newsnow_sources_keep_their_existing_url_and_response(self, get):
        payload = {"status": "cache", "items": [{"title": "Existing news", "url": "https://baidu.com"}]}
        get.return_value = response_for(payload)
        fetcher = DataFetcher(api_url="https://example.com/api/s")
        raw, source, name = fetcher.fetch_data("baidu")
        self.assertEqual(json.loads(raw), payload)
        self.assertEqual((source, name), ("baidu", "baidu"))
        self.assertEqual(get.call_args.args[0], "https://example.com/api/s?id=baidu&latest")

    @patch("trendradar.crawler.fetcher.time.sleep")
    @patch("trendradar.crawler.fetcher.requests.get")
    def test_timeout_is_retried_with_the_same_source(self, get, sleep):
        get.side_effect = [
            requests.Timeout("timeout"),
            response_for({"top10": [{"rank": 1, "keyword": "뉴스"}]}),
        ]
        raw, _, _ = DataFetcher().fetch_data(SOURCE_ID)
        self.assertIsNotNone(raw)
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all(call.args[0] == API_URL for call in get.call_args_list))
        sleep.assert_called_once()

    @patch("trendradar.crawler.fetcher.time.sleep")
    @patch("trendradar.crawler.fetcher.requests.get")
    def test_invalid_data_is_reported_as_failed_without_affecting_other_sources(self, get, sleep):
        get.side_effect = [
            response_for({"top10": []}),
            response_for({"top10": []}),
            response_for({"top10": []}),
            response_for({"status": "success", "items": [{"title": "Existing news"}]}),
        ]
        results, names, failed = DataFetcher().crawl_websites([SOURCE_ID, "baidu"])
        self.assertEqual(failed, [SOURCE_ID])
        self.assertNotIn(SOURCE_ID, results)
        self.assertIn("Existing news", results["baidu"])
        self.assertEqual(names[SOURCE_ID], SOURCE_ID)
        self.assertEqual([call.args[0] for call in get.call_args_list[:3]], [API_URL] * 3)

    @patch("trendradar.crawler.fetcher.requests.get")
    def test_http_error_and_non_json_response_fail_cleanly(self, get):
        http_error = response_for({})
        http_error.raise_for_status.side_effect = requests.HTTPError("503 unavailable")
        not_json = Mock(text="<html>unavailable</html>")
        for response in (http_error, not_json):
            with self.subTest(response=response):
                get.return_value = response
                raw, source, _ = DataFetcher().fetch_data(SOURCE_ID, max_retries=0)
                self.assertIsNone(raw)
                self.assertEqual(source, SOURCE_ID)

    @patch("trendradar.crawler.fetcher.requests.get")
    def test_rank_order_and_links_survive_crawling_and_storage_conversion(self, get):
        get.return_value = response_for({
            "top10": [{"rank": 2, "keyword": "둘"}, {"rank": 1, "keyword": "하나"}],
        })
        results, names, failed = DataFetcher().crawl_websites(
            [(SOURCE_ID, "Signal 韩国热搜（第三方）")],
            domain_rules={SOURCE_ID: "naver.com"},
        )
        self.assertEqual(failed, [])
        self.assertEqual(results[SOURCE_ID]["하나"]["ranks"], [1])
        self.assertEqual(results[SOURCE_ID]["둘"]["ranks"], [2])
        data = convert_crawl_results_to_news_data(results, names, failed, "12:00", "2026-11-07")
        items = data.items[SOURCE_ID]
        self.assertEqual([(item.title, item.rank) for item in items], [("하나", 1), ("둘", 2)])
        self.assertTrue(all(item.source_name == names[SOURCE_ID] for item in items))
        self.assertTrue(all(item.mobile_url.startswith("https://m.search.naver.com/") for item in items))


if __name__ == "__main__":
    unittest.main()
