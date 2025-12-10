"""Check why admin panel shows duplicates"""
import sqlite3
from config import DATABASE_CONFIG

conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Check for duplicate management entries
cursor.execute('''
    SELECT article_id, COUNT(*) as cnt, GROUP_CONCAT(ROWID) as rowids
    FROM article_management
    GROUP BY article_id
    HAVING cnt > 1
''')
dups = cursor.fetchall()
print(f"Articles with multiple management entries: {len(dups)}")
for dup in dups:
    print(f"  Article {dup[0]}: {dup[1]} entries (ROWIDs: {dup[2]})")

# Test the admin query
print("\nTesting admin query:")
cursor.execute('''
    SELECT a.*, 
           COALESCE(am.enabled, 1) as enabled,
           COALESCE(am.display_order, a.id) as display_order
    FROM articles a
    LEFT JOIN (
        SELECT article_id, enabled, display_order
        FROM article_management
        WHERE ROWID IN (
            SELECT MIN(ROWID) 
            FROM article_management 
            GROUP BY article_id
        )
    ) am ON a.id = am.article_id
    ORDER BY 
        CASE WHEN a.published IS NOT NULL AND a.published != '' THEN a.published ELSE '1970-01-01' END DESC,
        COALESCE(am.display_order, a.id) ASC
''')

rows = cursor.fetchall()
print(f"Query returns {len(rows)} rows")
print(f"Unique article IDs: {len(set(r['id'] for r in rows))}")

# Check for duplicates
seen_ids = {}
for row in rows:
    aid = row['id']
    if aid in seen_ids:
        print(f"\nDUPLICATE FOUND: Article ID {aid}")
        print(f"  First: {seen_ids[aid]['title'][:50]}")
        print(f"  Second: {row['title'][:50]}")
    else:
        seen_ids[aid] = row

conn.close()


