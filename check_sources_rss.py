#!/usr/bin/env python3
"""Check actual RSS feeds stored in database for zip 02720"""
import sqlite3
import json
from config import DATABASE_CONFIG, NEWS_SOURCES

zip_code = "02720"
db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Expected RSS feeds from user
expected = {
    "Herald News": "https://www.heraldnews.com/news/rss",
    "Fall River Reporter": "https://fallriverreporter.com/feed/",
    "Fun107": "https://fun107.com/tag/fall-river/feed/",
    "WPRI 12 Fall River": "https://www.wpri.com/feed/",
    "Taunton Gazette": "https://www.tauntongazette.com/news/rss",
    "MassLive Fall River": "https://www.masslive.com/topic/fall-river/feed/",
    "ABC6 (WLNE) Fall River": "https://www.abc6.com/news/fall-river/feed/",
    "NBC10/WJAR Fall River": "https://turnto10.com/topic/Fall%20River/feed/",
    "Southcoast Today": "https://www.southcoasttoday.com/rss/",
    "Patch Fall River": "https://patch.com/massachusetts/fallriver/rss",
}

print("Checking RSS feeds in database vs expected:")
print("=" * 80)

cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_override_%"', (zip_code,))
rows = cursor.fetchall()

mismatches = []
for row in rows:
    source_key = row[0].replace('source_override_', '')
    data = json.loads(row[1])
    name = data.get('name', '')
    rss_db = data.get('rss', None)
    
    # Find expected RSS by matching name
    expected_rss = None
    for exp_name, exp_rss in expected.items():
        if exp_name.lower() in name.lower() or name.lower() in exp_name.lower():
            expected_rss = exp_rss
            break
    
    if expected_rss and rss_db != expected_rss:
        mismatches.append((source_key, name, rss_db, expected_rss))
        print(f"MISMATCH: {name}")
        print(f"  Database: {rss_db}")
        print(f"  Expected:  {expected_rss}")
        print()
    elif not expected_rss:
        print(f"Not in expected list: {name} -> {rss_db}")

if not mismatches:
    print("All checked sources match!")
else:
    print(f"\nFound {len(mismatches)} mismatches")

# Also check config.py
print("\n" + "=" * 80)
print("Checking config.py RSS feeds:")
for source_key, source_config in NEWS_SOURCES.items():
    name = source_config.get('name', '')
    rss_config = source_config.get('rss', None)
    
    # Find expected RSS
    expected_rss = None
    for exp_name, exp_rss in expected.items():
        if exp_name.lower() in name.lower() or name.lower() in exp_name.lower():
            expected_rss = exp_rss
            break
    
    if expected_rss and rss_config != expected_rss:
        print(f"MISMATCH in config.py: {name}")
        print(f"  Config:    {rss_config}")
        print(f"  Expected:  {expected_rss}")
        print()

conn.close()

