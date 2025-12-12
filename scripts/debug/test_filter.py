"""Test if disabled articles are being filtered correctly"""
from database import ArticleDatabase
from aggregator import NewsAggregator
from website_generator import WebsiteGenerator
import sqlite3

db = ArticleDatabase()
agg = NewsAggregator()
wg = WebsiteGenerator()

# Get all articles
articles = db.get_all_articles(limit=500)
print(f"Total articles in DB: {len(articles)}")

# Enrich them
enriched = agg.enrich_articles(articles)
print(f"Enriched articles: {len(enriched)}")

# Check disabled articles
conn = sqlite3.connect('fallriver_news.db')
cursor = conn.cursor()
cursor.execute('SELECT DISTINCT article_id FROM article_management WHERE enabled = 0')
disabled_ids = {row[0] for row in cursor.fetchall()}
print(f"\nDisabled article IDs: {disabled_ids}")

# Test the filter
enabled_articles = wg._get_enabled_articles(enriched, {})
print(f"\nArticles after filter: {len(enabled_articles)}")

# Check if any disabled articles are still in the list
disabled_found = [a for a in enabled_articles if a.get('id') in disabled_ids]
print(f"Disabled articles still showing: {len(disabled_found)}")
if disabled_found:
    print("\nDisabled articles that are still showing:")
    for a in disabled_found[:5]:
        print(f"  - ID {a.get('id')}: {a.get('title', 'No title')[:60]}")

# Check management data
print("\nChecking management data for disabled articles:")
for article_id in list(disabled_ids)[:5]:
    cursor.execute('SELECT article_id, enabled, COUNT(*) as cnt FROM article_management WHERE article_id = ?', (article_id,))
    rows = cursor.fetchall()
    print(f"  Article {article_id}: {len(rows)} management entries")
    for row in rows:
        print(f"    - enabled={row[1]} (type: {type(row[1])}), count={row[2]}")

conn.close()

