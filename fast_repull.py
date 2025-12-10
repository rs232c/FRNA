"""Fast repull with strict Fall River filtering"""
import sqlite3
from config import DATABASE_CONFIG
from aggregator import NewsAggregator
from website_generator import WebsiteGenerator
from ingestors.weather_ingestor import WeatherIngestor

print("Clearing database...")
conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
cursor = conn.cursor()
cursor.execute('DELETE FROM articles')
cursor.execute('DELETE FROM article_management')
conn.commit()
conn.close()
print("✓ Cleared")

print("Aggregating (Fall River only)...")
agg = NewsAggregator()
articles = agg.aggregate()
print(f"✓ Got {len(articles)} Fall River articles")

print("Saving...")
from database import ArticleDatabase
db = ArticleDatabase()
db.save_articles(articles)
print("✓ Saved")

print("Generating website...")
weather = WeatherIngestor().fetch_weather()
gen = WebsiteGenerator()
gen.generate(articles)
print("✓ Done!")


