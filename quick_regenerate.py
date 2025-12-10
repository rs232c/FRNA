#!/usr/bin/env python3
"""Quick website regeneration script"""
import sys
import sqlite3
from datetime import datetime, timezone
from website_generator import WebsiteGenerator
from database import ArticleDatabase
from aggregator import NewsAggregator
from ingestors.weather_ingestor import WeatherIngestor
from config import DATABASE_CONFIG

def main():
    print("Regenerating website with existing articles...")
    
    # Get articles from database
    db = ArticleDatabase()
    articles = db.get_all_articles()
    print(f"Found {len(articles)} articles in database")
    
    if not articles:
        print("No articles found. Run main.py --once first to fetch articles.")
        return
    
    # Enrich articles
    aggregator = NewsAggregator()
    enriched = aggregator.enrich_articles(articles)
    print(f"Enriched {len(enriched)} articles")
    
    # Generate website
    generator = WebsiteGenerator()
    generator.generate(enriched)
    print("Website regenerated successfully!")
    
    # Update last regeneration time in database
    try:
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings (key, value)
            VALUES ('last_regeneration_time', ?)
        ''', (datetime.now(timezone.utc).isoformat(),))
        conn.commit()
        conn.close()
        print("Updated last regeneration timestamp")
    except Exception as e:
        print(f"Warning: Could not update last regeneration time: {e}")

if __name__ == "__main__":
    main()
