"""Enable some articles so the site has content"""
import sqlite3
from config import DATABASE_CONFIG

conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
cursor = conn.cursor()

# Enable the first 5 articles
cursor.execute('SELECT id FROM articles ORDER BY id LIMIT 5')
article_ids = [row[0] for row in cursor.fetchall()]

print(f"Enabling {len(article_ids)} articles: {article_ids}")

for article_id in article_ids:
    # Delete any existing entries
    cursor.execute('DELETE FROM article_management WHERE article_id = ?', (article_id,))
    # Insert enabled entry
    cursor.execute('''
        INSERT INTO article_management (article_id, enabled, display_order)
        VALUES (?, 1, ?)
    ''', (article_id, article_id))

conn.commit()
print("Articles enabled!")

# Verify
cursor.execute('SELECT COUNT(*) FROM article_management WHERE enabled = 1')
print(f"Total enabled articles: {cursor.fetchone()[0]}")

conn.close()


