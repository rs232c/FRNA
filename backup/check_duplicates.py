"""Check for duplicate articles in database"""
import sqlite3
from config import DATABASE_CONFIG

conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
cursor = conn.cursor()

# Check total articles
cursor.execute('SELECT COUNT(*) FROM articles')
total = cursor.fetchone()[0]
print(f"Total articles: {total}")

# Check for duplicate URLs
cursor.execute('''
    SELECT url, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
    FROM articles
    WHERE url IS NOT NULL AND url != '' AND url != '#'
    GROUP BY url
    HAVING cnt > 1
''')
url_dups = cursor.fetchall()
print(f"\nDuplicate URLs: {len(url_dups)}")
for dup in url_dups[:5]:
    print(f"  URL: {dup[0][:60]}... ({dup[1]} copies, IDs: {dup[2]})")

# Check for duplicate titles + source
cursor.execute('''
    SELECT LOWER(TRIM(title)) as norm_title, source, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
    FROM articles
    WHERE title IS NOT NULL AND title != ''
    GROUP BY norm_title, source
    HAVING cnt > 1
''')
title_dups = cursor.fetchall()
print(f"\nDuplicate titles+source: {len(title_dups)}")
for dup in title_dups[:5]:
    print(f"  Title: {dup[0][:50]}... ({dup[1]}) - {dup[2]} copies, IDs: {dup[3]}")

conn.close()

