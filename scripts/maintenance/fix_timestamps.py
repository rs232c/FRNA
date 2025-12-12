#!/usr/bin/env python3
import sqlite3
from datetime import datetime

conn = sqlite3.connect('fallriver_news.db')
cursor = conn.cursor()

# Update existing top stories with current timestamp
cursor.execute('UPDATE article_management SET updated_at = ? WHERE is_top_story = 1 AND (updated_at IS NULL OR updated_at = "")', (datetime.now().isoformat(),))
print(f'Updated {cursor.rowcount} rows with current timestamp')

conn.commit()
conn.close()
print('Database updated successfully')
