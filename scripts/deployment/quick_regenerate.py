#!/usr/bin/env python3
"""Quick website regeneration script - Fast regeneration without fetching new articles"""
import sys
import sqlite3
import os
from datetime import datetime, timezone
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from website_generator import WebsiteGenerator
from database import ArticleDatabase
from aggregator import NewsAggregator
from config import DATABASE_CONFIG

def main(zip_code=None, city_state=None):
    """Quick regenerate website with existing articles
    
    Args:
        zip_code: Optional zip code for zip-specific generation
        city_state: Optional city_state for city-based generation
    """
    print("=" * 60)
    print("Quick Regeneration: Using existing articles from database")
    print("(No fetching - fast regeneration for page-load triggers)")
    print("=" * 60)
    
    # Get articles from database
    db = ArticleDatabase()
    articles = db.get_all_articles(limit=500, zip_code=zip_code, city_state=city_state)
    print(f"Found {len(articles)} articles in database")
    
    if not articles:
        print("No articles found. Run main.py --once first to fetch articles.")
        return
    
    # Enrich articles
    print("Enriching articles with metadata...")
    aggregator = NewsAggregator()
    enriched = aggregator.enrich_articles(articles)
    print(f"Enriched {len(enriched)} articles")
    
    # Generate website
    print("Generating website...")
    generator = WebsiteGenerator()
    generator.generate(enriched, zip_code=zip_code, city_state=city_state)
    print("[OK] Website regenerated successfully!")
    
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
        print("[OK] Updated last regeneration timestamp")
    except Exception as e:
        print(f"Warning: Could not update last regeneration time: {e}")
    
    print("=" * 60)

if __name__ == "__main__":
    # Support zip_code from command line or environment variable
    zip_code = None
    city_state = None
    
    if len(sys.argv) > 1:
        zip_code = sys.argv[1]
    elif os.environ.get('ZIP_CODE'):
        zip_code = os.environ.get('ZIP_CODE')
    
    # Resolve city_state if zip_code provided
    if zip_code and not city_state:
        try:
            from zip_resolver import get_city_state_for_zip
            city_state = get_city_state_for_zip(zip_code)
            if city_state:
                print(f"Resolved zip {zip_code} to city_state: {city_state}")
        except Exception as e:
            print(f"Warning: Could not resolve city_state for zip {zip_code}: {e}")
    
    main(zip_code=zip_code, city_state=city_state)
