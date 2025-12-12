"""Quick fetch from RSS feeds only - much faster"""
import feedparser
from database import ArticleDatabase
from datetime import datetime
from config import NEWS_SOURCES

db = ArticleDatabase()

all_articles = []

# Fetch from RSS feeds
for source_key, source_config in NEWS_SOURCES.items():
    if not source_config.get("enabled"):
        continue
    
    rss_url = source_config.get("rss")
    if rss_url:
        print(f"Fetching from {source_config['name']} RSS...")
        try:
            feed = feedparser.parse(rss_url)
            print(f"  Found {len(feed.entries)} entries")
            
            for entry in feed.entries[:50]:  # Get up to 50 from each feed
                article = {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "published": entry.get("published", datetime.now().isoformat()),
                    "summary": entry.get("summary", "")[:500],
                    "content": entry.get("content", [{}])[0].get("value", "") if entry.get("content") else entry.get("summary", ""),
                    "source": source_config["name"],
                    "source_type": "news",
                    "ingested_at": datetime.now().isoformat()
                }
                all_articles.append(article)
        except Exception as e:
            print(f"  Error: {e}")

print(f"\nTotal articles fetched: {len(all_articles)}")

# Save to database
if all_articles:
    db.save_articles(all_articles)
    print(f"Saved {len(all_articles)} articles to database")

# Check what we have
articles = db.get_recent_articles(hours=24*30, limit=100)  # Past 30 days
print(f"\nArticles in database (past month): {len(articles)}")



