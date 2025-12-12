"""Quick script to repull all data with Fall River filtering"""
import logging
from database import ArticleDatabase
from aggregator import NewsAggregator
from website_generator import WebsiteGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("=" * 60)
print("Quick Data Repull with Fall River Filtering")
print("=" * 60)

# Clear existing articles first
print("\nClearing existing articles...")
import sqlite3
from config import DATABASE_CONFIG
conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
cursor = conn.cursor()
cursor.execute('DELETE FROM articles')
cursor.execute('DELETE FROM article_management')
cursor.execute('DELETE FROM posted_articles')
conn.commit()
conn.close()
print("✓ Database cleared")

# Aggregate news (with strict Fall River filtering)
print("\nAggregating news with Fall River filtering...")
aggregator = NewsAggregator()
articles = aggregator.aggregate()

print(f"\n✓ Aggregated {len(articles)} articles (all Fall River relevant)")

# Save to database
print("\nSaving to database...")
db.save_articles(articles)
print("✓ Articles saved")

# Generate website
print("\nGenerating website...")
from ingestors.weather_ingestor import WeatherIngestor
weather = WeatherIngestor().fetch_weather()
generator = WebsiteGenerator()
generator.generate(articles)

print("\n" + "=" * 60)
print("✓ Data repull complete!")
print(f"  Articles: {len(articles)}")
print(f"  All articles are Fall River relevant")
print("=" * 60)

