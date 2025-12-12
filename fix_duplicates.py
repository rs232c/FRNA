#!/usr/bin/env python3
"""
Fix Database Duplicates - Safe Removal Operation
FallRiver.live - Christmas Eve 2025 Launch

This script safely removes actual duplicate articles from the database,
keeping the oldest version of each duplicate set and properly cleaning
up related tables.
"""

import sqlite3
from database import ArticleDatabase
from config import DATABASE_CONFIG
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def analyze_duplicates_before_cleanup():
    """Analyze current duplicate situation before cleanup"""
    logger.info("Analyzing duplicates before cleanup...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Check total articles
    cursor.execute('SELECT COUNT(*) FROM articles')
    total_articles = cursor.fetchone()[0]
    logger.info(f"Total articles: {total_articles}")

    # Check auto-trashed duplicates
    cursor.execute("SELECT COUNT(*) FROM articles WHERE auto_trashed = 1")
    trashed_count = cursor.fetchone()[0]
    logger.info(f"Auto-trashed articles: {trashed_count}")

    # Check actual duplicates by URL
    cursor.execute('''
        SELECT url, COUNT(*) as cnt
        FROM articles
        WHERE url IS NOT NULL AND url != '' AND url != '#'
        GROUP BY url
        HAVING cnt > 1
        ORDER BY cnt DESC
    ''')
    url_dupes = cursor.fetchall()
    logger.info(f"Actual URL duplicates: {len(url_dupes)} sets")

    # Check duplicates by title+source+date
    cursor.execute('''
        SELECT LOWER(TRIM(title)) as norm_title, source, published, COUNT(*) as cnt
        FROM articles
        WHERE title IS NOT NULL AND title != ''
        GROUP BY norm_title, source, published
        HAVING cnt > 1
        ORDER BY cnt DESC
    ''')
    title_dupes = cursor.fetchall()
    logger.info(f"Title+source+date duplicates: {len(title_dupes)} sets")

    conn.close()
    return total_articles, trashed_count, len(url_dupes), len(title_dupes)

def run_safe_duplicate_removal():
    """Run the safe duplicate removal using the database class method"""
    logger.info("Running safe duplicate removal...")

    db = ArticleDatabase()
    removed_count = db.remove_duplicates()

    logger.info(f"Duplicate removal completed: {removed_count} articles removed")
    return removed_count

def analyze_duplicates_after_cleanup():
    """Analyze the situation after cleanup"""
    logger.info("Analyzing duplicates after cleanup...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Check new totals
    cursor.execute('SELECT COUNT(*) FROM articles')
    new_total = cursor.fetchone()[0]
    logger.info(f"Articles after cleanup: {new_total}")

    # Verify no more duplicates remain
    cursor.execute('''
        SELECT COUNT(*) as dupe_count FROM (
            SELECT url, COUNT(*) as cnt
            FROM articles
            WHERE url IS NOT NULL AND url != '' AND url != '#'
            GROUP BY url
            HAVING cnt > 1
        )
    ''')
    remaining_url_dupes = cursor.fetchone()[0]

    cursor.execute('''
        SELECT COUNT(*) as dupe_count FROM (
            SELECT LOWER(TRIM(title)) as norm_title, source, published, COUNT(*) as cnt
            FROM articles
            WHERE title IS NOT NULL AND title != ''
            GROUP BY norm_title, source, published
            HAVING cnt > 1
        )
    ''')
    remaining_title_dupes = cursor.fetchone()[0]

    logger.info(f"Remaining URL duplicates: {remaining_url_dupes}")
    logger.info(f"Remaining title+source+date duplicates: {remaining_title_dupes}")

    # Check article_management cleanup
    cursor.execute('SELECT COUNT(*) FROM article_management')
    mgmt_count = cursor.fetchone()[0]
    logger.info(f"Article management entries: {mgmt_count}")

    conn.close()
    return new_total, remaining_url_dupes, remaining_title_dupes

def create_post_cleanup_backup():
    """Create a backup after cleanup"""
    import shutil
    from datetime import datetime

    backup_path = f"fallriver_post_duplicate_cleanup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DATABASE_CONFIG["path"], backup_path)
    logger.info(f"Post-cleanup backup created: {backup_path}")
    return backup_path

def main():
    logger.info("🔧 Starting Database Duplicate Fix Operation")
    logger.info("=" * 60)

    # Pre-cleanup analysis
    logger.info("📊 PRE-CLEANUP ANALYSIS:")
    total_before, trashed_before, url_dupes_before, title_dupes_before = analyze_duplicates_before_cleanup()

    # Run the cleanup
    logger.info("\n🧹 RUNNING DUPLICATE REMOVAL:")
    removed = run_safe_duplicate_removal()

    # Post-cleanup analysis
    logger.info("\n📊 POST-CLEANUP ANALYSIS:")
    total_after, url_dupes_after, title_dupes_after = analyze_duplicates_after_cleanup()

    # Create backup
    backup_path = create_post_cleanup_backup()

    # Final report
    logger.info("\n" + "="*60)
    logger.info("✅ DATABASE DUPLICATE FIX COMPLETED")
    logger.info("="*60)

    print("\nDUPLICATE CLEANUP RESULTS:")
    print(f"  Articles before: {total_before}")
    print(f"  Articles after: {total_after}")
    print(f"  Articles removed: {removed}")
    print(f"  Reduction: {((total_before - total_after) / total_before * 100):.1f}%")
    print()
    print(f"  URL duplicate sets before: {url_dupes_before}")
    print(f"  URL duplicate sets after: {url_dupes_after}")
    print(f"  Title duplicate sets before: {title_dupes_before}")
    print(f"  Title duplicate sets after: {title_dupes_after}")
    print()
    print(f"  Backup created: {backup_path}")

    if url_dupes_after == 0 and title_dupes_after == 0:
        print("\nSUCCESS: All duplicates removed!")
    else:
        print(f"\nWARNING: {url_dupes_after + title_dupes_after} duplicate sets remain")

    logger.info("Database duplicate fix operation completed successfully!")

if __name__ == "__main__":
    main()