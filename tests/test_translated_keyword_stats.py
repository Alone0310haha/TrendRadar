"""Translate selected sources before keyword grouping without changing article identity."""

import copy
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

with patch.dict(os.environ, {"LITELLM_LOCAL_MODEL_COST_MAP": "True"}):
    from trendradar.context import AppContext
    from trendradar.core.frequency import _parse_word
    from trendradar.notification.dispatcher import NotificationDispatcher
    from trendradar.report.generator import prepare_report_data
    from trendradar.report.html import render_html_content


NAMES = {"signal-hot": "Signal 韩国热搜（第三方）", "baidu": "百度热搜"}
GROUPS = [
    {"group_key": "AI 相关", "required": [], "normal": ["人工智能"]},
    {"group_key": "财经", "required": [], "normal": ["股市"]},
]
TRANSLATIONS = {
    "인공지능 신제품": "人工智能新品发布",
    "증시 상승": "韩国股市上涨",
    "연예 뉴스": "明星新剧上映",
}


def entry(rank):
    return {"ranks": [rank], "url": f"https://search.naver.com/?rank={rank}",
            "mobileUrl": f"https://m.search.naver.com/?rank={rank}"}


class TranslatedKeywordStatsTests(unittest.TestCase):
    def setUp(self):
        self.ctx = AppContext({
            "WEIGHT_CONFIG": {"RANK_WEIGHT": 0.6, "FREQUENCY_WEIGHT": 0.3, "HOTNESS_WEIGHT": 0.1},
            "PLATFORMS": [{"id": "signal-hot", "translate_before_filter": True}, {"id": "baidu"}],
            "AI_TRANSLATION": {"ENABLED": True, "LANGUAGE": "中文", "BATCH_SIZE": 100,
                               "BATCH_INTERVAL": 0, "SCOPE": {"HOTLIST": False}},
        })
        self.ctx.is_first_crawl = Mock(return_value=False)
        self.ctx.convert_time_display = lambda value: value
        self.translator = Mock()
        self.translator.translate_batch.side_effect = lambda titles: SimpleNamespace(results=[
            SimpleNamespace(success=True, translated_text=TRANSLATIONS.get(title, title))
            for title in titles
        ])
        self.factory = patch("trendradar.context.AITranslator", return_value=self.translator).start()
        self.addCleanup(patch.stopall)
        self.results = {
            "signal-hot": {title: entry(i) for i, title in enumerate(TRANSLATIONS, 1)},
            "baidu": {"国内人工智能新闻": entry(1)},
        }

    def count(self, **kwargs):
        return self.ctx.count_frequency(self.results, GROUPS, [], NAMES, quiet=True, **kwargs)

    def test_merges_translated_topics_and_keeps_history_and_new_item_identity(self):
        original = copy.deepcopy(self.results)
        timeline = [{"time": "08:00", "rank": 3}, {"time": "09:00", "rank": 1}]
        history = {source: {title: {"first_time": "08:00", "last_time": "09:00", "count": 2,
                                   "ranks": [3, data["ranks"][0]], "rank_timeline": timeline}
                            for title, data in titles.items()}
                   for source, titles in self.results.items()}
        new = {"signal-hot": {"인공지능 신제품": entry(1)}}
        stats, total = self.count(mode="current", title_info=history, new_titles=new)
        self.assertEqual(total, 4)
        by_group = {stat["word"]: stat for stat in stats}
        self.assertEqual(by_group["AI 相关"]["count"], 2)
        self.assertEqual(by_group["财经"]["count"], 1)
        signal = next(t for t in by_group["AI 相关"]["titles"] if t["source_id"] == "signal-hot")
        self.assertEqual(signal["title"], "인공지능 신제품")
        self.assertEqual(signal["translated_title"], "人工智能新品发布")
        self.assertTrue(signal["is_new"])
        self.assertEqual((signal["count"], signal["ranks"], signal["rank_timeline"]), (2, [3, 1], timeline))
        self.assertEqual(signal["first_time"], "08:00")
        self.assertEqual(self.results, original)
        self.translator.translate_batch.assert_called_once_with(list(TRANSLATIONS))

        report = prepare_report_data(stats, new_titles=new, id_to_name=NAMES, mode="current")
        self.assertEqual(report["total_new_count"], 1)
        self.assertEqual(report["new_titles"][0]["titles"][0]["title"], "人工智能新品发布")
        self.assertEqual(report["new_titles"][0]["titles"][0]["url"], entry(1)["url"])
        html = render_html_content(report, total, mode="current")
        self.assertIn("人工智能新品发布", html)
        self.assertIn(NAMES["signal-hot"], html)
        self.assertIn("国内人工智能新闻", html)
        self.assertNotIn("明星新剧上映", html)
        self.assertNotIn('<div class="standalone-section">', html)

    def test_translated_global_filter_and_regex_are_respected(self):
        stats, _ = self.count(global_filters=[_parse_word("/股市/")])
        self.assertEqual(sum(stat["count"] for stat in stats), 2)
        stats, _ = self.ctx.count_frequency(
            self.results, [{"group_key": "股票", "required": ["韩国"], "normal": [_parse_word("/股市/")]}],
            [], NAMES, quiet=True,
        )
        self.assertEqual(stats[0]["count"], 1)
        self.assertEqual(stats[0]["titles"][0]["translated_title"], "韩国股市上涨")

    def test_incremental_translates_only_new_titles(self):
        stats, _ = self.count(mode="incremental", new_titles={"signal-hot": {"증시 상승": entry(2)}})
        self.translator.translate_batch.assert_called_once_with(["증시 상승"])
        self.assertEqual(sum(stat["count"] for stat in stats), 1)
        self.assertTrue(next(stat for stat in stats if stat["count"])["titles"][0]["is_new"])

    def test_current_translates_only_the_latest_batch(self):
        history = {"signal-hot": {
            "인공지능 신제품": {"last_time": "08:00"},
            "증시 상승": {"last_time": "09:00"},
            "연예 뉴스": {"last_time": "08:00"},
        }}
        stats, _ = self.count(mode="current", title_info=history)
        self.translator.translate_batch.assert_called_once_with(["증시 상승"])
        self.assertEqual(sum(stat["count"] for stat in stats), 1)

    def test_successful_translations_are_cached_and_batched(self):
        self.ctx.config["AI_TRANSLATION"]["BATCH_SIZE"] = 2
        self.count()
        self.count()
        self.assertEqual(self.translator.translate_batch.call_count, 2)
        self.assertEqual([len(call.args[0]) for call in self.translator.translate_batch.call_args_list], [2, 1])

    def test_disabled_translation_or_unselected_source_makes_no_ai_calls(self):
        self.ctx.config["AI_TRANSLATION"]["ENABLED"] = False
        stats, _ = self.count()
        self.assertEqual(sum(stat["count"] for stat in stats), 1)
        self.factory.assert_not_called()
        self.ctx.config["AI_TRANSLATION"]["ENABLED"] = True
        self.ctx.config["PLATFORMS"][0]["translate_before_filter"] = False
        self.count()
        self.factory.assert_not_called()

    def test_failed_translation_falls_back_to_original_and_can_retry(self):
        self.translator.translate_batch.side_effect = RuntimeError("API unavailable")
        stats, _ = self.count()
        self.assertEqual(sum(stat["count"] for stat in stats), 1)
        self.assertEqual(self.ctx._filter_translation_cache, {})
        self.translator.translate_batch.side_effect = lambda titles: SimpleNamespace(results=[
            SimpleNamespace(success=(i == 0), translated_text=TRANSLATIONS[title])
            for i, title in enumerate(titles)
        ])
        stats, _ = self.count()
        self.assertEqual(sum(stat["count"] for stat in stats), 2)
        self.assertEqual(len(self.ctx._filter_translation_cache), 1)

    def test_same_translation_does_not_merge_distinct_original_titles(self):
        self.translator.translate_batch.side_effect = lambda titles: SimpleNamespace(results=[
            SimpleNamespace(success=True, translated_text="人工智能新闻") for _ in titles
        ])
        stats, _ = self.count()
        self.assertEqual(sum(stat["count"] for stat in stats), 4)
        self.assertEqual(len(stats[0]["titles"]), 4)

    def test_report_translation_does_not_translate_signal_twice(self):
        stats, _ = self.count()
        report = prepare_report_data(stats, new_titles={"signal-hot": {"인공지능 신제품": entry(1)}}, id_to_name=NAMES)
        self.translator.enabled = True
        self.translator.scope = {"HOTLIST": True}
        self.translator.target_language = "中文"
        self.translator.translate_batch.side_effect = None
        self.translator.translate_batch.return_value = SimpleNamespace(
            results=[], success_count=0, fail_count=1, total_count=1,
        )
        self.translator.translate_batch.reset_mock()
        dispatcher = NotificationDispatcher({}, Mock(), Mock(), self.translator)
        translated_report, _, _, _ = dispatcher.translate_content(report)
        self.translator.translate_batch.assert_called_once_with(["国内人工智能新闻"])
        self.assertEqual(translated_report["new_titles"][0]["titles"][0]["title"], "人工智能新品发布")


if __name__ == "__main__":
    unittest.main()
