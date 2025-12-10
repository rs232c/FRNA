"""Basic tests for aggregator functionality"""
import unittest
from unittest.mock import Mock, patch
from datetime import datetime
from aggregator import NewsAggregator
from config import ARTICLE_CATEGORIES


class TestAggregator(unittest.TestCase):
    """Test aggregator basic functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.aggregator = NewsAggregator()
    
    def test_aggregator_initialization(self):
        """Test that aggregator initializes correctly"""
        self.assertIsNotNone(self.aggregator)
        self.assertIsNotNone(self.aggregator.news_ingestors)
    
    def test_enrich_articles_adds_category_info(self):
        """Test that enrich_articles adds category information"""
        article = {
            "title": "Test Article",
            "url": "https://example.com/test",
            "published": datetime.now().isoformat(),
            "source": "Test Source",
            "category": "news"
        }
        
        enriched = self.aggregator.enrich_articles([article])
        
        self.assertEqual(len(enriched), 1)
        enriched_article = enriched[0]
        self.assertIn("category_name", enriched_article)
        self.assertIn("category_icon", enriched_article)
        self.assertIn("category_color", enriched_article)
        self.assertEqual(enriched_article["category_name"], "News")
        self.assertEqual(enriched_article["category_icon"], "📰")
    
    def test_enrich_articles_formats_date(self):
        """Test that enrich_articles formats dates correctly"""
        article = {
            "title": "Test Article",
            "url": "https://example.com/test",
            "published": "2024-01-15T10:30:00",
            "source": "Test Source",
            "category": "news"
        }
        
        enriched = self.aggregator.enrich_articles([article])
        
        self.assertEqual(len(enriched), 1)
        enriched_article = enriched[0]
        self.assertIn("formatted_date", enriched_article)
        self.assertIn("date_sort", enriched_article)
        # Should not be "Recently" if published date exists
        self.assertNotEqual(enriched_article["formatted_date"], "Recently")
    
    def test_enrich_articles_handles_missing_published_date(self):
        """Test that enrich_articles handles missing published date"""
        article = {
            "title": "Test Article",
            "url": "https://example.com/test",
            "source": "Test Source",
            "category": "news"
        }
        
        enriched = self.aggregator.enrich_articles([article])
        
        self.assertEqual(len(enriched), 1)
        enriched_article = enriched[0]
        # Should have formatted_date even if published is missing
        self.assertIn("formatted_date", enriched_article)
    
    def test_detect_category(self):
        """Test category detection"""
        # Test news category
        news_article = {
            "title": "Breaking news about Fall River",
            "content": "This is a news article",
            "source": "Herald News"
        }
        category = self.aggregator._detect_category(news_article)
        self.assertIn(category, ARTICLE_CATEGORIES.keys())
    
    def test_deduplicate_articles_removes_duplicates(self):
        """Test that deduplicate_articles removes duplicate URLs"""
        articles = [
            {
                "title": "Article 1",
                "url": "https://example.com/article1",
                "source": "Source 1"
            },
            {
                "title": "Article 1 Duplicate",
                "url": "https://example.com/article1",  # Same URL
                "source": "Source 2"
            },
            {
                "title": "Article 2",
                "url": "https://example.com/article2",
                "source": "Source 1"
            }
        ]
        
        deduplicated = self.aggregator.deduplicate_articles(articles)
        
        # Should have 2 unique articles
        self.assertEqual(len(deduplicated), 2)
        urls = [a["url"] for a in deduplicated]
        self.assertEqual(len(set(urls)), 2)


if __name__ == "__main__":
    unittest.main()

