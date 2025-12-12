"""Test script to verify feedparser date parsing"""
import feedparser
from datetime import datetime
from config import NEWS_SOURCES

print("Testing feedparser date extraction from RSS feeds...\n")

for source_key, source_config in NEWS_SOURCES.items():
    if not source_config.get("enabled") or not source_config.get("rss"):
        continue
    
    rss_url = source_config["rss"]
    print(f"Testing: {source_config['name']}")
    print(f"RSS URL: {rss_url}")
    
    try:
        feed = feedparser.parse(rss_url)
        print(f"  Entries found: {len(feed.entries)}")
        
        if feed.entries:
            entry = feed.entries[0]
            print(f"  First entry title: {entry.get('title', 'N/A')[:60]}")
            
            # Check for published_parsed
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    dt = datetime(*entry.published_parsed[:6])
                    print(f"  ✓ published_parsed available: {dt.isoformat()}")
                except Exception as e:
                    print(f"  ✗ Error converting published_parsed: {e}")
            else:
                print(f"  ✗ No published_parsed available")
            
            # Check for updated_parsed
            if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    dt = datetime(*entry.updated_parsed[:6])
                    print(f"  ✓ updated_parsed available: {dt.isoformat()}")
                except Exception as e:
                    print(f"  ✗ Error converting updated_parsed: {e}")
            
            # Check string fields
            print(f"  published (string): {entry.get('published', 'N/A')}")
            print(f"  updated (string): {entry.get('updated', 'N/A')}")
        else:
            print(f"  ✗ No entries in feed")
    except Exception as e:
        print(f"  ✗ Error: {e}")
    
    print()

