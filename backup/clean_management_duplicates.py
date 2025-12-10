"""Clean duplicate article_management entries"""
import sqlite3
from config import DATABASE_CONFIG

conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
cursor = conn.cursor()

# Find articles with multiple management entries
cursor.execute('''
    SELECT article_id, COUNT(*) as cnt, GROUP_CONCAT(ROWID) as rowids
    FROM article_management
    GROUP BY article_id
    HAVING cnt > 1
''')

duplicates = cursor.fetchall()
print(f"Found {len(duplicates)} articles with duplicate management entries")

removed = 0
for dup in duplicates:
    article_id = dup[0]
    rowids = [int(x) for x in dup[2].split(',')]
    # Keep the first one (lowest ROWID), delete the rest
    keep_rowid = min(rowids)
    delete_rowids = [r for r in rowids if r != keep_rowid]
    
    for rowid in delete_rowids:
        cursor.execute('DELETE FROM article_management WHERE ROWID = ?', (rowid,))
        removed += 1
    print(f"  Article {article_id}: Kept 1, removed {len(delete_rowids)} duplicate entries")

conn.commit()
print(f"\nRemoved {removed} duplicate management entries")
conn.close()

