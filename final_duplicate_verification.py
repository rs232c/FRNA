#!/usr/bin/env python3
"""
Final Database Duplicate Verification
FallRiver.live - Post-Cleanup Verification

This script verifies that all duplicates have been successfully removed
and provides a final status report.
"""

import sqlite3
from config import DATABASE_CONFIG
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def final_duplicate_check():
    """Final comprehensive duplicate check"""
    logger.info("Running final duplicate verification...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Get current article count
    cursor.execute('SELECT COUNT(*) FROM articles')
    total_articles = cursor.fetchone()[0]
    logger.info(f"Current total articles: {total_articles}")

    # Check for any remaining identical content
    cursor.execute('''
        SELECT content, COUNT(*) as cnt
        FROM articles
        WHERE content IS NOT NULL AND content != '' AND LENGTH(content) > 100
        GROUP BY content
        HAVING cnt > 1
    ''')
    remaining_identical = cursor.fetchall()
    logger.info(f"Remaining identical content groups: {len(remaining_identical)}")

    # Check for any remaining identical summaries
    cursor.execute('''
        SELECT summary, COUNT(*) as cnt
        FROM articles
        WHERE summary IS NOT NULL AND summary != '' AND LENGTH(summary) > 50
        GROUP BY summary
        HAVING cnt > 1
    ''')
    remaining_summaries = cursor.fetchall()
    logger.info(f"Remaining identical summary groups: {len(remaining_summaries)}")

    # Check for exact title+source+date duplicates
    cursor.execute('''
        SELECT LOWER(TRIM(title)) as norm_title, source, published, COUNT(*) as cnt
        FROM articles
        WHERE title IS NOT NULL AND title != '' AND source IS NOT NULL AND published IS NOT NULL
        GROUP BY LOWER(TRIM(title)), source, published
        HAVING cnt > 1
    ''')
    exact_dupes = cursor.fetchall()
    logger.info(f"Exact title+source+date duplicates: {len(exact_dupes)}")

    # Check URL duplicates
    cursor.execute('''
        SELECT url, COUNT(*) as cnt
        FROM articles
        WHERE url IS NOT NULL AND url != '' AND url != '#'
        GROUP BY url
        HAVING cnt > 1
    ''')
    url_dupes = cursor.fetchall()
    logger.info(f"URL duplicates: {len(url_dupes)}")

    conn.close()

    return {
        'total_articles': total_articles,
        'identical_content': len(remaining_identical),
        'identical_summaries': len(remaining_summaries),
        'exact_duplicates': len(exact_dupes),
        'url_duplicates': len(url_dupes)
    }

def create_final_backup():
    """Create final backup after all cleanup"""
    import shutil
    from datetime import datetime

    backup_path = f"fallriver_final_clean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DATABASE_CONFIG["path"], backup_path)
    logger.info(f"Final clean backup created: {backup_path}")
    return backup_path

def main():
    logger.info("🎯 FINAL DATABASE DUPLICATE VERIFICATION")
    logger.info("=" * 60)

    # Run final checks
    results = final_duplicate_check()

    logger.info("\nFINAL DATABASE STATUS:")
    logger.info(f"  Total articles: {results['total_articles']}")
    logger.info(f"  Identical content groups: {results['identical_content']}")
    logger.info(f"  Identical summary groups: {results['identical_summaries']}")
    logger.info(f"  Exact duplicates: {results['exact_duplicates']}")
    logger.info(f"  URL duplicates: {results['url_duplicates']}")

    # Create final backup
    backup_path = create_final_backup()

    # Determine final status
    all_clean = all(count == 0 for count in [
        results['identical_content'],
        results['identical_summaries'],
        results['exact_duplicates'],
        results['url_duplicates']
    ])

    logger.info("\nFINAL VERDICT:")
    if all_clean:
        logger.info("  DATABASE IS COMPLETELY DUPLICATE-FREE!")
        logger.info(f"  Final backup: {backup_path}")
        logger.info("  Ready for Christmas Eve launch!")
    else:
        logger.info("  Some duplicates remain - needs further cleanup")
        logger.info(f"  Backup created: {backup_path}")

    logger.info("\n" + "="*60)
    logger.info("Database cleanup verification completed!")

if __name__ == "__main__":
    main()