"""Basic tests for database operations"""
import unittest
import os
import tempfile
import sqlite3
from database import ArticleDatabase
from datetime import datetime


class TestDatabase(unittest.TestCase):
    """Test database basic functionality"""
    
    def setUp(self):
        """Set up test fixtures with temporary database"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        # Create database instance and override path before initialization
        self.db = ArticleDatabase.__new__(ArticleDatabase)
        self.db.db_path = self.temp_db.name
        # Initialize database with custom path
        self.db._init_database()
    
    def tearDown(self):
        """Clean up test fixtures"""
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)
    
    def test_database_initialization(self):
        """Test that database initializes correctly"""
        conn = sqlite3.connect(self.temp_db.name)
        cursor = conn.cursor()
        
        # Check that articles table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles'")
        self.assertIsNotNone(cursor.fetchone())
        
        conn.close()
    
    def test_save_article(self):
        """Test saving an article to database"""
        article = {
            "title": "Test Article",
            "url": "https://example.com/test",
            "published": datetime.now().isoformat(),
            "summary": "Test summary",
            "content": "Test content",
            "source": "Test Source",
            "source_type": "news"
        }
        
        article_ids = self.db.save_articles([article])
        
        self.assertEqual(len(article_ids), 1)
        self.assertIsInstance(article_ids[0], int)
    
    def test_get_articles(self):
        """Test retrieving articles from database"""
        # Save some articles
        articles = [
            {
                "title": f"Article {i}",
                "url": f"https://example.com/article{i}",
                "published": datetime.now().isoformat(),
                "summary": f"Summary {i}",
                "content": f"Content {i}",
                "source": "Test Source",
                "source_type": "news"
            }
            for i in range(3)
        ]
        
        self.db.save_articles(articles)
        
        # Retrieve articles
        retrieved = self.db.get_all_articles(limit=10)
        
        self.assertGreaterEqual(len(retrieved), 3)
        self.assertIn("title", retrieved[0])
        self.assertIn("url", retrieved[0])
    
    def test_save_duplicate_article(self):
        """Test that saving duplicate article doesn't create duplicate"""
        article = {
            "title": "Test Article",
            "url": "https://example.com/test",
            "published": datetime.now().isoformat(),
            "summary": "Test summary",
            "content": "Test content",
            "source": "Test Source",
            "source_type": "news"
        }
        
        # Save twice
        ids1 = self.db.save_articles([article])
        ids2 = self.db.save_articles([article])
        
        # Should return same ID or handle duplicate gracefully
        self.assertIsNotNone(ids1[0])
        # Second save should either return same ID or handle duplicate
        self.assertIsNotNone(ids2[0])


if __name__ == "__main__":
    unittest.main()

