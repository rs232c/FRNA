#!/usr/bin/env python3
"""Verify all RSS feeds match user's list exactly"""
import sqlite3
import json
from config import DATABASE_CONFIG

# User's exact list
user_sources = {
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
    "FRCMedia (Fall River Community Media)": "https://frmedia.org/feed/",
    "WSAR Radio": "https://rss.app/feeds/wsar-news.xml",
    "FREDTV": "https://rss.app/feeds/fredtv.xml",
    "FRGTV": "https://rss.app/feeds/frgtv.xml",
    "New Bedford Light": "https://newbedfordlight.org/feed/",
    "Anchor News (Diocese)": "https://www.anchornews.org/feed/",
    "Fall River Development News FB Page": "https://rss.app/feeds/facebook-fall-river-development-news.xml",
    "Legacy.com Fall River": "https://rss.app/feeds/legacy-fall-river-obits.xml",
    "Herald News Obituaries": "https://www.heraldnews.com/obituaries/rss",
    "Hathaway Funeral Homes": "https://www.hathawayfunerals.com/rss/obituaries",
    "South Coast Funeral Service": "https://www.southcoastchapel.com/rss/obituaries",
    "Waring-Sullivan (Dignity Memorial)": "https://www.dignitymemorial.com/rss/funeral-homes/massachusetts/fall-river-ma",
    "Oliveira Funeral Homes": "https://www.oliveirafuneralhomes.com/rss/obituaries",
}

zip_code = "02720"
db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Checking all sources in database:")
print("=" * 80)

cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_override_%"', (zip_code,))
rows = cursor.fetchall()

db_sources = {}
for row in rows:
    source_key = row[0].replace('source_override_', '')
    data = json.loads(row[1])
    name = data.get('name', '')
    rss = data.get('rss', None)
    db_sources[name] = {'key': source_key, 'rss': rss}

# Check each user source
mismatches = []
missing = []
for user_name, expected_rss in user_sources.items():
    if user_name in db_sources:
        actual_rss = db_sources[user_name]['rss']
        if actual_rss != expected_rss:
            mismatches.append((user_name, actual_rss, expected_rss))
            print(f"MISMATCH: {user_name}")
            print(f"  Database: {actual_rss}")
            print(f"  Expected:  {expected_rss}")
            print()
    else:
        missing.append(user_name)
        print(f"MISSING: {user_name} (Expected RSS: {expected_rss})")
        print()

if not mismatches and not missing:
    print("All sources match!")
else:
    print(f"\nSummary: {len(mismatches)} mismatches, {len(missing)} missing")

conn.close()

