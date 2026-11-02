from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import Mock, call

import pytz

from trendradar.storage.remote import RemoteStorageBackend


class RemoteRetentionTests(TestCase):
    def setUp(self):
        # Bypass client initialization so tests never access a real bucket.
        self.backend = RemoteStorageBackend.__new__(RemoteStorageBackend)
        self.backend.bucket_name = "test-bucket"
        self.backend.s3_client = Mock()
        self.backend._get_configured_time = Mock(
            return_value=pytz.timezone("Asia/Shanghai").localize(
                datetime(2026, 11, 2, 0, 15)
            )
        )
        self.pages = {"news/": [], "rss/": []}
        self.paginator = self.backend.s3_client.get_paginator.return_value
        self.paginator.paginate.side_effect = lambda **kwargs: self.pages[kwargs["Prefix"]]
        self.backend.s3_client.delete_objects.side_effect = (
            lambda **kwargs: {"Deleted": kwargs["Delete"]["Objects"]}
        )

    def test_keeps_recent_30_dates_and_cleans_both_database_types(self):
        for prefix in self.pages:
            self.pages[prefix] = [{}, {"Contents": [
                {"Key": prefix + date + ".db"}
                for date in ("2026-10-02", "2026-10-03", "2026-10-04", "2026-11-02")
            ]}]

        self.assertEqual(self.backend.cleanup_old_data(30), 4)
        self.paginator.paginate.assert_has_calls([
            call(Bucket="test-bucket", Prefix="news/"),
            call(Bucket="test-bucket", Prefix="rss/"),
        ])
        deleted = self.backend.s3_client.delete_objects.call_args.kwargs["Delete"]["Objects"]
        self.assertEqual({obj["Key"] for obj in deleted}, {
            "news/2026-10-02.db", "news/2026-10-03.db",
            "rss/2026-10-02.db", "rss/2026-10-03.db",
        })

    def test_preserves_unrelated_files_and_invalid_dates(self):
        self.pages["news/"] = [{"Contents": [{"Key": key} for key in (
            "news/notes.txt", "news/2020-01-01.db.backup",
            "news/archive/2020-01-01.db", "news/2020-02-30.db",
            "news/2020-01-01Xdb", "news/2020-01-01.db\n",
        )]}]
        self.assertEqual(self.backend.cleanup_old_data(30), 0)
        self.backend.s3_client.delete_objects.assert_not_called()

    def test_disabled_retention_does_not_access_bucket(self):
        for days in (0, -1):
            self.assertEqual(self.backend.cleanup_old_data(days), 0)
        self.backend.s3_client.get_paginator.assert_not_called()
        self.backend.s3_client.delete_objects.assert_not_called()

    def _add_many_old_databases(self):
        objects = [
            {"Key": f"news/{(datetime(2020, 1, 1) + timedelta(days=i)):%Y-%m-%d}.db"}
            for i in range(1001)
        ]
        self.pages["news/"] = [{"Contents": objects[:750]}, {"Contents": objects[750:]}]

    def test_paginates_and_batches_at_most_1000_deletions(self):
        self._add_many_old_databases()
        self.assertEqual(self.backend.cleanup_old_data(30), 1001)
        self.assertEqual([
            len(args.kwargs["Delete"]["Objects"])
            for args in self.backend.s3_client.delete_objects.call_args_list
        ], [1000, 1])

    def test_failed_objects_are_not_counted_as_deleted(self):
        self.pages["news/"] = [{"Contents": [
            {"Key": "news/2020-01-01.db"}, {"Key": "news/2020-01-02.db"},
        ]}]
        self.backend.s3_client.delete_objects.side_effect = None
        self.backend.s3_client.delete_objects.return_value = {
            "Deleted": [{"Key": "news/2020-01-01.db"}],
            "Errors": [{"Key": "news/2020-01-02.db", "Code": "AccessDenied"}],
        }
        self.assertEqual(self.backend.cleanup_old_data(30), 1)

    def test_batch_failure_does_not_count_failed_batch_or_stop_next_batch(self):
        self._add_many_old_databases()
        self.backend.s3_client.delete_objects.side_effect = [
            RuntimeError("temporary failure"), {"Deleted": [{"Key": "last-object"}]},
        ]
        self.assertEqual(self.backend.cleanup_old_data(30), 1)
        self.assertEqual(self.backend.s3_client.delete_objects.call_count, 2)
