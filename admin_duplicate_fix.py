#!/usr/bin/env python3
"""
Fix Admin Interface Duplicate Display Issues
FallRiver.live Admin Duplicate Resolution
"""

import sqlite3
from config import DATABASE_CONFIG
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fix_admin_display_duplicates():
    """Fix any issues causing duplicate display in admin interface"""
    logger.info("Fixing admin interface duplicate display issues...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Check for articles with multiple management entries
    cursor.execute('''
        SELECT article_id, COUNT(*) as cnt, GROUP_CONCAT(id) as mgmt_ids
        FROM article_management
        GROUP BY article_id
        HAVING cnt > 1
        ORDER BY cnt DESC
    ''')

    multi_mgmt = cursor.fetchall()
    logger.info(f"Found {len(multi_mgmt)} articles with multiple management entries")

    removed = 0
    for article_id, cnt, mgmt_ids_str in multi_mgmt:
        mgmt_ids = [int(x) for x in mgmt_ids_str.split(',')]

        # Keep the most recent (highest ID)
        keep_id = max(mgmt_ids)
        delete_ids = [id for id in mgmt_ids if id != keep_id]

        logger.info(f"Article {article_id}: keeping management entry {keep_id}, removing {len(delete_ids)} duplicates")

        for delete_id in delete_ids:
            cursor.execute('DELETE FROM article_management WHERE id = ?', (delete_id,))
            removed += 1

    # Check for any articles appearing multiple times in admin query
    admin_query = '''
        SELECT a.id, COUNT(*) as appearances
        FROM articles a
        LEFT JOIN article_management am ON a.id = am.article_id
        WHERE a.zip_code = '02720'
        GROUP BY a.id
        HAVING appearances > 1
    '''

    cursor.execute(admin_query)
    dupes_in_query = cursor.fetchall()
    logger.info(f"Found {len(dupes_in_query)} articles appearing multiple times in admin query")

    if dupes_in_query:
        logger.warning("Articles appearing multiple times in admin query - this shouldn't happen!")
        for article_id, appearances in dupes_in_query:
            cursor.execute('SELECT title FROM articles WHERE id = ?', (article_id,))
            title = cursor.fetchone()[0]
            logger.warning(f"  Article {article_id}: '{title[:50]}...' appears {appearances} times")

    conn.commit()
    conn.close()

    logger.info(f"Admin duplicate fix completed: {removed} duplicate management entries removed")
    return removed, len(dupes_in_query)

def verify_admin_display():
    """Verify admin display is now correct"""
    logger.info("Verifying admin display fix...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Get article count from admin query
    admin_query = '''
        SELECT COUNT(DISTINCT a.id) as unique_articles,
               COUNT(*) as total_rows
        FROM articles a
        LEFT JOIN article_management am ON a.id = am.article_id
        WHERE a.zip_code = '02720'
    '''

    cursor.execute(admin_query)
    unique_articles, total_rows = cursor.fetchone()

    logger.info(f"Admin query results: {unique_articles} unique articles, {total_rows} total rows")

    if unique_articles == total_rows:
        logger.info("✅ Admin display should now show each article only once")
        return True
    else:
        logger.warning(f"⚠️  Still {total_rows - unique_articles} duplicate displays possible")
        return False

    conn.close()

def main():
    logger.info("🔧 ADMIN INTERFACE DUPLICATE FIX")
    logger.info("=" * 50)

    # Fix the issues
    removed, query_dupes = fix_admin_display_duplicates()

    # Verify the fix
    fixed = verify_admin_display()

    # Summary
    logger.info("\n" + "="*50)
    logger.info("ADMIN DUPLICATE FIX RESULTS:")
    logger.info(f"  Duplicate management entries removed: {removed}")
    logger.info(f"  Query duplicates found: {query_dupes}")
    logger.info(f"  Admin display fixed: {'Yes' if fixed else 'No'}")

    if fixed and removed > 0:
        logger.info("\n✅ Admin interface duplicate display issues resolved!")
        logger.info("   Each article should now appear only once in the admin articles page.")
    elif query_dupes == 0:
        logger.info("\n✅ No duplicate display issues found.")
        logger.info("   Admin interface was already working correctly.")

    logger.info("\n" + "="*50)

if __name__ == "__main__":
    main()