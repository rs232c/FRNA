import sqlite3
import os
from pathlib import Path

# Connect to database
db_path = Path('fallriver_news.db')
if not db_path.exists():
    print('Database not found')
    exit(1)

conn = sqlite3.connect('fallriver_news.db')
cursor = conn.cursor()

# Check for duplicate titles in 02720
cursor.execute('SELECT title, COUNT(*) as count FROM articles WHERE zip_code="02720" GROUP BY title HAVING count > 1 ORDER BY count DESC LIMIT 10')
duplicates = cursor.fetchall()

print(f'Found {len(duplicates)} duplicate title groups in 02720:')
for title, count in duplicates[:5]:
    print(f'  {count}x: {title[:60]}...')

# Check total articles in 02720
cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code="02720"')
total = cursor.fetchone()[0]
print(f'\nTotal articles in 02720: {total}')

# Check recent articles to see if they look like duplicates
cursor.execute('SELECT title, source, published FROM articles WHERE zip_code="02720" ORDER BY published DESC LIMIT 10')
recent = cursor.fetchall()

print('\nRecent articles (last 10):')
for title, source, published in recent:
    print(f'  {published}: {title[:50]}... ({source})')

conn.close()