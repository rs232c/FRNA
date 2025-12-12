#!/usr/bin/env python3
"""
Clean Up Remaining Identical Summaries
FallRiver.live Database Final Cleanup

Remove the remaining 3 groups of articles with identical summaries.
"""

import sqlite3
from config import DATABASE_CONFIG
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def remove_identical_summaries():
    """Remove articles with identical summaries, keeping the newest"""
    logger.info("Removing articles with identical summaries...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    removed = 0

    # Find identical summary groups
    cursor.execute('''
        SELECT summary, GROUP_CONCAT(id) as ids
        FROM articles
        WHERE summary IS NOT NULL AND summary != '' AND LENGTH(summary) > 50
        GROUP BY summary
        HAVING COUNT(*) > 1
    ''')

    identical_summary_groups = cursor.fetchall()
    logger.info(f"Found {len(identical_summary_groups)} groups with identical summaries")

    for summary, ids_str in identical_summary_groups:
        ids = [int(x) for x in ids_str.split(',')]
        if len(ids) > 1:
            # Keep the one with the highest ID (newest)
            keep_id = max(ids)
            delete_ids = [id for id in ids if id != keep_id]

            logger.info(f"Removing {len(delete_ids)} duplicates with identical summary, keeping ID {keep_id}")
            logger.info(f"  Summary: '{summary[:100]}...'")

            for delete_id in delete_ids:
                # Remove from related tables
                cursor.execute('DELETE FROM article_management WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM training_data WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM articles WHERE id = ?', (delete_id,))
                removed += 1

    conn.commit()
    conn.close()

    logger.info(f"Removed {removed} articles with identical summaries")
    return removed

def final_status_check():
    """Final status check"""
    logger.info("Running final status check...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Get final counts
    cursor.execute('SELECT COUNT(*) FROM articles')
    total_articles = cursor.fetchone()[0]

    cursor.execute('''
        SELECT COUNT(*) FROM (
            SELECT summary FROM articles
            WHERE summary IS NOT NULL AND summary != '' AND LENGTH(summary) > 50
            GROUP BY summary
            HAVING COUNT(*) > 1
        )
    ''')
    remaining_summaries = cursor.fetchone()[0]

    cursor.execute('''
        SELECT COUNT(*) FROM (
            SELECT content FROM articles
            WHERE content IS NOT NULL AND content != '' AND LENGTH(content) > 100
            GROUP BY content
            HAVING COUNT(*) > 1
        )
    ''')
    remaining_content = cursor.fetchone()[0]

    conn.close()

    return {
        'total_articles': total_articles,
        'remaining_summaries': remaining_summaries,
        'remaining_content': remaining_content
    }

def main():
    logger.info("🧹 Final Summary Cleanup")
    logger.info("=" * 50)

    # Remove remaining identical summaries
    removed = remove_identical_summaries()

    # Final status check
    status = final_status_check()

    logger.info("\nFINAL CLEANUP RESULTS:")
    logger.info(f"  Articles removed: {removed}")
    logger.info(f"  Total articles now: {status['total_articles']}")
    logger.info(f"  Remaining identical summaries: {status['remaining_summaries']}")
    logger.info(f"  Remaining identical content: {status['remaining_content']}")

    if status['remaining_summaries'] == 0 and status['remaining_content'] == 0:
        logger.info("\nDATABASE IS NOW COMPLETELY DUPLICATE-FREE!")
        logger.info("Ready for Christmas Eve launch!")
    else:
        logger.info(f"\nStill {status['remaining_summaries'] + status['remaining_content']} duplicate groups remain")

    logger.info("\n" + "="*50)
    logger.info("Summary cleanup completed!")

if __name__ == "__main__":
    main()