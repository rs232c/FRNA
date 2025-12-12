"""Aggressive duplicate removal script"""
import sqlite3
from database import ArticleDatabase

db = ArticleDatabase()
conn = sqlite3.connect('fallriver_news.db')
cursor = conn.cursor()

print("=" * 60)
print("Aggressive Duplicate Removal")
print("=" * 60)

# Find duplicates by exact title match
print("\n1. Finding duplicates by exact title...")
cursor.execute('''
    SELECT LOWER(TRIM(title)) as norm_title, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
    FROM articles
    WHERE title IS NOT NULL AND title != ''
    GROUP BY norm_title
    HAVING cnt > 1
    ORDER BY cnt DESC
''')

title_dups = cursor.fetchall()
print(f"Found {len(title_dups)} sets of duplicate titles")

removed = 0
for dup in title_dups:
    ids = [int(x) for x in dup[2].split(',')]
    if len(ids) > 1:
        keep_id = min(ids)  # Keep oldest
        delete_ids = [id for id in ids if id != keep_id]
        print(f"  Title: {dup[0][:50]}... ({len(ids)} copies, keeping ID {keep_id})")
        
        for delete_id in delete_ids:
            cursor.execute('DELETE FROM article_management WHERE article_id = ?', (delete_id,))
            cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (delete_id,))
            cursor.execute('DELETE FROM articles WHERE id = ?', (delete_id,))
            removed += 1

# Find duplicates by URL
print("\n2. Finding duplicates by URL...")
cursor.execute('''
    SELECT url, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
    FROM articles
    WHERE url IS NOT NULL AND url != '' AND url != '#'
    GROUP BY url
    HAVING cnt > 1
''')

url_dups = cursor.fetchall()
print(f"Found {len(url_dups)} sets of duplicate URLs")

for dup in url_dups:
    ids = [int(x) for x in dup[2].split(',')]
    if len(ids) > 1:
        keep_id = min(ids)
        delete_ids = [id for id in ids if id != keep_id]
        
        for delete_id in delete_ids:
            cursor.execute('DELETE FROM article_management WHERE article_id = ?', (delete_id,))
            cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (delete_id,))
            cursor.execute('DELETE FROM articles WHERE id = ?', (delete_id,))
            removed += 1

conn.commit()
conn.close()

print(f"\n{'=' * 60}")
print(f"Total removed: {removed} duplicate articles")
print(f"{'=' * 60}")

# Run the standard duplicate removal too
print("\n3. Running standard duplicate removal...")
db_removed = db.remove_duplicates()
print(f"Standard removal found: {db_removed} duplicates")

print(f"\n✓ Duplicate cleanup complete!")


