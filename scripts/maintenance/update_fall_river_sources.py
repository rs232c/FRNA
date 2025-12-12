#!/usr/bin/env python3
"""
Update Fall River (02720) sources in database with new RSS feeds from config.py
"""
import sqlite3
import json
from config import NEWS_SOURCES, DATABASE_CONFIG

def update_sources_in_db():
    """Update source overrides in database for zip 02720"""
    zip_code = "02720"
    db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print(f"Updating sources for zip {zip_code}...")
    print(f"Database: {db_path}")
    print("=" * 60)
    
    updated_count = 0
    
    for source_key, source_config in NEWS_SOURCES.items():
        # Create override with updated RSS feed
        override_data = {
            'name': source_config.get('name'),
            'url': source_config.get('url'),
            'rss': source_config.get('rss'),
            'category': source_config.get('category', 'news'),
            'enabled': source_config.get('enabled', True),
            'require_fall_river': source_config.get('require_fall_river', True)
        }
        
        # Save as source override for this zip
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
            VALUES (?, ?, ?)
        ''', (zip_code, f'source_override_{source_key}', json.dumps(override_data)))
        
        updated_count += 1
        rss_status = override_data['rss'] if override_data['rss'] else 'None (web scraping)'
        print(f"[OK] {source_key}: {override_data['name']}")
        print(f"  RSS: {rss_status}")
    
    conn.commit()
    conn.close()
    
    print("=" * 60)
    print(f"[OK] Updated {updated_count} sources for zip {zip_code}")
    print("\nNext steps:")
    print("1. Run: python main.py --once --zip 02720")
    print("2. Or regenerate website from admin panel")
    print("3. New articles will use the updated RSS feeds")

if __name__ == "__main__":
    update_sources_in_db()

