"""
Database Migration Script: Move all data to zip code 02720
This script will:
1. Set all articles to zip_code = '02720' (or NULL if they don't have location data)
2. Set all article_management entries to zip_code = '02720'
3. Move all admin_settings_zip entries to zip_code = '02720'
4. Set all relevance_config entries to zip_code = '02720'
5. Clear any data for other zip codes
"""

import sqlite3
import logging
from config import DATABASE_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TARGET_ZIP = '02720'

def scrub_database():
    """Move all data to zip code 02720 and clear other zips"""
    db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
    
    logger.info(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 1. Update articles table - set all to 02720
        logger.info("Updating articles table...")
        cursor.execute('''
            UPDATE articles 
            SET zip_code = ?
            WHERE zip_code IS NOT NULL AND zip_code != ?
        ''', (TARGET_ZIP, TARGET_ZIP))
        articles_updated = cursor.rowcount
        logger.info(f"  Updated {articles_updated} articles to zip {TARGET_ZIP}")
        
        # 2. Update article_management table - set all to 02720
        logger.info("Updating article_management table...")
        cursor.execute('''
            UPDATE article_management 
            SET zip_code = ?
            WHERE zip_code IS NOT NULL AND zip_code != ?
        ''', (TARGET_ZIP, TARGET_ZIP))
        management_updated = cursor.rowcount
        logger.info(f"  Updated {management_updated} article_management entries to zip {TARGET_ZIP}")
        
        # 3. Update admin_settings_zip table - move all to 02720
        logger.info("Updating admin_settings_zip table...")
        # First, get all unique keys for each zip
        cursor.execute('''
            SELECT DISTINCT key FROM admin_settings_zip 
            WHERE zip_code != ?
        ''', (TARGET_ZIP,))
        keys_to_move = [row[0] for row in cursor.fetchall()]
        
        # For each key, move the value to 02720 (or update if it exists)
        moved_count = 0
        for key in keys_to_move:
            # Get the value from the first non-02720 zip (prioritize keeping data)
            cursor.execute('''
                SELECT value FROM admin_settings_zip 
                WHERE zip_code != ? AND key = ?
                LIMIT 1
            ''', (TARGET_ZIP, key))
            row = cursor.fetchone()
            if row:
                # Insert or replace in 02720
                cursor.execute('''
                    INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
                    VALUES (?, ?, ?)
                ''', (TARGET_ZIP, key, row[0]))
                moved_count += 1
        
        # Delete all entries for other zips
        cursor.execute('''
            DELETE FROM admin_settings_zip 
            WHERE zip_code != ?
        ''', (TARGET_ZIP,))
        deleted_count = cursor.rowcount
        logger.info(f"  Moved {moved_count} settings to zip {TARGET_ZIP}, deleted {deleted_count} entries from other zips")
        
        # 4. Update relevance_config table - set all to 02720
        logger.info("Updating relevance_config table...")
        cursor.execute('''
            UPDATE relevance_config 
            SET zip_code = ?
            WHERE zip_code IS NOT NULL AND zip_code != ?
        ''', (TARGET_ZIP, TARGET_ZIP))
        relevance_updated = cursor.rowcount
        logger.info(f"  Updated {relevance_updated} relevance_config entries to zip {TARGET_ZIP}")
        
        # 5. Delete any article_management entries for other zips (safety check)
        logger.info("Cleaning up article_management for other zips...")
        cursor.execute('''
            DELETE FROM article_management 
            WHERE zip_code IS NOT NULL AND zip_code != ?
        ''', (TARGET_ZIP,))
        deleted_management = cursor.rowcount
        logger.info(f"  Deleted {deleted_management} article_management entries for other zips")
        
        # 6. Delete any relevance_config entries for other zips (safety check)
        logger.info("Cleaning up relevance_config for other zips...")
        cursor.execute('''
            DELETE FROM relevance_config 
            WHERE zip_code IS NOT NULL AND zip_code != ?
        ''', (TARGET_ZIP,))
        deleted_relevance = cursor.rowcount
        logger.info(f"  Deleted {deleted_relevance} relevance_config entries for other zips")
        
        # Commit all changes
        conn.commit()
        logger.info("✓ Database migration completed successfully!")
        logger.info(f"  All data is now associated with zip code {TARGET_ZIP}")
        logger.info(f"  Other zip codes have been cleared")
        
    except Exception as e:
        logger.error(f"Error during database migration: {e}", exc_info=True)
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("DATABASE MIGRATION: Moving all data to zip code 02720")
    print("=" * 60)
    print()
    print("This will:")
    print("  1. Set all articles to zip_code = '02720'")
    print("  2. Set all article_management entries to zip_code = '02720'")
    print("  3. Move all admin_settings_zip entries to zip_code = '02720'")
    print("  4. Set all relevance_config entries to zip_code = '02720'")
    print("  5. Clear any data for other zip codes")
    print()
    response = input("Are you sure you want to continue? (yes/no): ")
    
    if response.lower() == 'yes':
        scrub_database()
        print()
        print("Migration complete! Restart your Flask server.")
    else:
        print("Migration cancelled.")

