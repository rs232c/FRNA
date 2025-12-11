#!/usr/bin/env python3
"""Verify sources are updated in database"""
import sqlite3
import json
from config import DATABASE_CONFIG

zip_code = "02720"
db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute('SELECT COUNT(*) FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_override_%"', (zip_code,))
count = cursor.fetchone()[0]

print(f"Found {count} source overrides for zip {zip_code}")

# Show a few examples
cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_override_%" LIMIT 5', (zip_code,))
rows = cursor.fetchall()

print("\nSample overrides:")
for row in rows:
    key = row[0].replace('source_override_', '')
    data = json.loads(row[1])
    rss = data.get('rss', 'None')
    print(f"  {key}: {rss}")

conn.close()

