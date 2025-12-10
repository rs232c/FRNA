"""Update article dates in database by re-fetching from RSS feeds"""
import asyncio
import logging
import sqlite3
from datetime import datetime
from aggregator import NewsAggregator
from database import ArticleDatabase
from config import DATABASE_CONFIG, NEWS_SOURCES
import feedparser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def update_dates_from_feeds():
    """Update article dates by matching URLs with RSS feeds"""
    logger.info("Updating article dates from RSS feeds...")
    
    db = ArticleDatabase()
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    cursor = conn.cursor()
    
    # Get all articles
    cursor.execute('SELECT id, url, source, published FROM articles')
    articles = cursor.fetchall()
    
    logger.info(f"Found {len(articles)} articles in database")
    
    # Build URL to date mapping from RSS feeds
    url_to_date = {}
    
    for source_key, source_config in NEWS_SOURCES.items():
        if not source_config.get("enabled") or not source_config.get("rss"):
            continue
        
        rss_url = source_config["rss"]
        logger.info(f"Fetching dates from {source_config['name']}...")
        
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                url = entry.get("link", "")
                if url:
                    # Use published_parsed if available
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        try:
                            date_str = datetime(*entry.published_parsed[:6]).isoformat()
                            url_to_date[url] = date_str
                        except:
                            pass
        except Exception as e:
            logger.warning(f"Error fetching from {source_config['name']}: {e}")
    
    logger.info(f"Found {len(url_to_date)} URLs with dates from feeds")
    
    # Update articles with matching URLs
    updated = 0
    for article_id, url, source, old_published in articles:
        if url and url in url_to_date:
            new_date = url_to_date[url]
            if new_date != old_published:
                cursor.execute('UPDATE articles SET published = ? WHERE id = ?', (new_date, article_id))
                updated += 1
                logger.debug(f"Updated article {article_id}: {old_published} -> {new_date}")
    
    conn.commit()
    conn.close()
    
    logger.info(f"Updated {updated} article dates")
    return updated

if __name__ == '__main__':
    asyncio.run(update_dates_from_feeds())

