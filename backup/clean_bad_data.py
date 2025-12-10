"""Script to clean bad data from database"""
import sqlite3
import re
from database import ArticleDatabase

db = ArticleDatabase()
conn = sqlite3.connect('fallriver_news.db')
cursor = conn.cursor()

print("=" * 60)
print("Cleaning Bad Data from Database")
print("=" * 60)

# 1. Remove articles with bad characters or encoding issues
print("\n1. Removing articles with bad characters...")
cursor.execute('SELECT id, title, summary FROM articles')
articles = cursor.fetchall()

bad_chars_pattern = re.compile(r'[^\x00-\x7F\u00A0-\uFFFF]')
removed_bad_chars = 0

for article in articles:
    article_id, title, summary = article
    has_bad = False
    
    if title and bad_chars_pattern.search(title):
        has_bad = True
    if summary and bad_chars_pattern.search(summary):
        has_bad = True
    
    if has_bad:
        # Try to clean it first
        clean_title = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', title) if title else ''
        clean_summary = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', summary) if summary else ''
        
        if len(clean_title) < 5:  # If cleaned title is too short, delete
            cursor.execute('DELETE FROM articles WHERE id = ?', (article_id,))
            cursor.execute('DELETE FROM article_management WHERE article_id = ?', (article_id,))
            cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (article_id,))
            removed_bad_chars += 1
            print(f"  Deleted article {article_id}: bad characters")
        else:
            # Update with cleaned version
            cursor.execute('UPDATE articles SET title = ?, summary = ? WHERE id = ?', 
                         (clean_title, clean_summary, article_id))

# 2. Remove articles not related to Fall River
print("\n2. Removing articles not related to Fall River...")
cursor.execute('SELECT id, title, summary, content, source FROM articles')
articles = cursor.fetchall()

fall_river_keywords = ['fall river', 'fallriver', 'fall-river', 'fallriver ma', 'fall river ma', 
                      'fall river massachusetts', 'somerset', 'swansea', 'westport', 'freetown',
                      'taunton', 'new bedford', 'dartmouth', 'seekonk', 'bristol county']

removed_irrelevant = 0

for article in articles:
    article_id, title, summary, content, source = article
    
    # Check if article mentions Fall River or nearby areas
    text_to_check = f"{title or ''} {summary or ''} {content or ''}".lower()
    
    is_relevant = any(keyword in text_to_check for keyword in fall_river_keywords)
    
    # Exception: if source is explicitly Fall River related, keep it
    if 'fall river' in (source or '').lower() or 'fallriver' in (source or '').lower():
        is_relevant = True
    
    if not is_relevant:
        cursor.execute('DELETE FROM articles WHERE id = ?', (article_id,))
        cursor.execute('DELETE FROM article_management WHERE article_id = ?', (article_id,))
        cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (article_id,))
        removed_irrelevant += 1
        print(f"  Removed article {article_id}: {title[:50]}... (not Fall River related)")

# 3. Remove articles with empty or very short titles
print("\n3. Removing articles with empty/short titles...")
cursor.execute('SELECT id, title FROM articles WHERE title IS NULL OR LENGTH(TRIM(title)) < 5')
empty_titles = cursor.fetchall()
removed_empty = 0

for article in empty_titles:
    article_id = article[0]
    cursor.execute('DELETE FROM articles WHERE id = ?', (article_id,))
    cursor.execute('DELETE FROM article_management WHERE article_id = ?', (article_id,))
    cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (article_id,))
    removed_empty += 1

# 4. Clean up duplicate URLs
print("\n4. Removing duplicate URLs...")
cursor.execute('''
    SELECT url, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
    FROM articles
    WHERE url IS NOT NULL AND url != '' AND url != '#'
    GROUP BY url
    HAVING cnt > 1
''')
duplicates = cursor.fetchall()
removed_dups = 0

for dup in duplicates:
    ids = [int(x) for x in dup[2].split(',')]
    keep_id = min(ids)
    delete_ids = [id for id in ids if id != keep_id]
    
    for delete_id in delete_ids:
        cursor.execute('DELETE FROM article_management WHERE article_id = ?', (delete_id,))
        cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (delete_id,))
        cursor.execute('DELETE FROM articles WHERE id = ?', (delete_id,))
        removed_dups += 1

conn.commit()
conn.close()

print(f"\n{'=' * 60}")
print(f"Cleanup Summary:")
print(f"  - Removed {removed_bad_chars} articles with bad characters")
print(f"  - Removed {removed_irrelevant} articles not related to Fall River")
print(f"  - Removed {removed_empty} articles with empty/short titles")
print(f"  - Removed {removed_dups} duplicate articles")
print(f"{'=' * 60}")

# Run standard duplicate removal too
print("\nRunning standard duplicate removal...")
db_removed = db.remove_duplicates()
print(f"Standard removal found: {db_removed} duplicates")

print("\n✓ Database cleanup complete!")


