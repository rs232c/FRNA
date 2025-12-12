"""Check articles in database"""
import sqlite3
from config import DATABASE_CONFIG

conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
cursor = conn.cursor()

# Get total count
cursor.execute('SELECT COUNT(*) FROM articles')
total = cursor.fetchone()[0]

print(f"\n{'='*60}")
print(f"Total Articles in Database: {total}")
print(f"{'='*60}")

# Get latest articles
cursor.execute('''
    SELECT title, published, source, created_at 
    FROM articles 
    ORDER BY COALESCE(published, created_at) DESC 
    LIMIT 10
''')
print("\nLatest 10 articles (by publication date):")
for i, row in enumerate(cursor.fetchall(), 1):
    date = row[1] or row[3] or "No date"
    print(f"{i}. {row[0][:60]}...")
    print(f"   Date: {date} | Source: {row[2]}")

# Get count by source
cursor.execute('SELECT source, COUNT(*) FROM articles GROUP BY source ORDER BY COUNT(*) DESC')
by_source = cursor.fetchall()

if by_source:
    print("\nArticles by Source:")
    for source, count in by_source:
        print(f"  {source}: {count}")

conn.close()
