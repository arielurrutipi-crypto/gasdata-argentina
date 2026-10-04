import unittest
from news_reader import metadata, published, feed_items

class NewsReaderTests(unittest.TestCase):
    def test_invalid_and_day_only_dates_do_not_become_new(self):
        self.assertIsNone(published("not a date"))
        self.assertIsNone(published("2026-10-04"))
        self.assertIsNone(published(""))

    def test_publication_not_modification(self):
        item = metadata('<meta property="article:modified_time" content="2026-10-04T12:00:00Z"><script type="application/ld+json">{"headline":"Gas", "datePublished":"2026-10-02T09:00:00-03:00", "image":{"url":"/gas.jpg"}, "description":"Resumen"}</script>', "https://example.com/news")
        self.assertEqual(item["publishedAt"], "2026-10-02T09:00:00-03:00")
        self.assertEqual(item["imageUrl"], "https://example.com/gas.jpg")

    def test_feed_image_and_date(self):
        rows = feed_items(b'<rss><channel><item><title>News</title><link>https://example.com/a</link><pubDate>Sun, 04 Oct 2026 11:00:00 GMT</pubDate><description>&lt;img src="/photo.jpg"&gt;Short summary</description></item></channel></rss>', "Source")
        self.assertEqual(rows[0]["imageUrl"], "https://example.com/photo.jpg")
        self.assertEqual(rows[0]["desc"], "Short summary")
        self.assertEqual(rows[0]["dateType"], "published")
