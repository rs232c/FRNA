#!/usr/bin/env python3
"""
Check for duplicates visible in admin interface
FallRiver.live Admin Duplicate Analysis
"""

import sqlite3
from config import DATABASE_CONFIG
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_admin_articles_query():
    """Check what the admin articles page actually returns"""
    logger.info("Checking admin articles query results...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Simulate the exact admin articles query for zip 02720
    query = '''
        SELECT
            a.*,
            COALESCE(am.is_rejected, 0) as is_rejected,
            COALESCE(am.is_auto_filtered, 0) as is_auto_filtered,
            COALESCE(am.is_featured, 0) as is_featured,
            COALESCE(am.is_top_article, 0) as is_top,
            COALESCE(am.is_top_story, 0) as is_top_story,
            COALESCE(am.is_alert, 0) as is_alert,
            COALESCE(am.is_stellar, 0) as is_good_fit,
            COALESCE(am.is_on_target, NULL) as is_on_target,
            COALESCE(am.user_notes, '') as user_notes,
            am.created_at as management_created_at,
            am.updated_at as management_updated_at
        FROM articles a
        LEFT JOIN article_management am ON a.id = am.article_id
        WHERE a.zip_code = '02720'
        ORDER BY a.published DESC LIMIT 50
    '''

    cursor.execute(query)
    results = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]

    # Convert to dict format like the admin interface
    articles = [dict(zip(columns, row)) for row in results]

    logger.info(f"Admin query returned {len(articles)} articles")

    # Check for duplicate IDs in results
    ids = [article['id'] for article in articles]
    duplicate_ids = set([x for x in ids if ids.count(x) > 1])

    if duplicate_ids:
        logger.info(f"FOUND DUPLICATE IDs IN ADMIN RESULTS: {duplicate_ids}")
        for dup_id in duplicate_ids:
            dup_articles = [a for a in articles if a['id'] == dup_id]
            for article in dup_articles:
                logger.info(f"  ID {dup_id}: '{article['title'][:50]}...' - Source: {article['source']}")
    else:
        logger.info("No duplicate IDs in admin results")

    # Check for very similar titles
    titles = [(article['id'], article['title'].lower().strip()) for article in articles]

    similar_pairs = []
    for i, (id1, title1) in enumerate(titles):
        for j, (id2, title2) in enumerate(titles[i+1:], i+1):
            if id1 != id2:  # Different articles
                # Check if titles are very similar (90%+)
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, title1, title2).ratio()
                if similarity > 0.9 and len(title1) > 10:
                    similar_pairs.append((id1, id2, title1, title2, similarity))

    logger.info(f"Found {len(similar_pairs)} very similar title pairs (90%+ similarity)")

    if similar_pairs:
        logger.info("TOP SIMILAR PAIRS (what user might see as duplicates):")
        # Sort by similarity
        similar_pairs.sort(key=lambda x: x[4], reverse=True)
        for id1, id2, title1, title2, sim in similar_pairs[:10]:
            logger.info(f"  {sim:.1%} similar:")
            logger.info(f"    ID {id1}: '{title1[:60]}'")
            logger.info(f"    ID {id2}: '{title2[:60]}'")

    conn.close()
    return len(duplicate_ids), len(similar_pairs)

def check_for_query_duplicates():
    """Check if the LEFT JOIN is causing duplicate results"""
    logger.info("Checking if LEFT JOIN causes duplicate results...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Check article_management table for multiple entries per article
    cursor.execute('''
        SELECT article_id, COUNT(*) as cnt
        FROM article_management
        GROUP BY article_id
        HAVING cnt > 1
        ORDER BY cnt DESC
    ''')

    multi_mgmt = cursor.fetchall()
    logger.info(f"Articles with multiple management entries: {len(multi_mgmt)}")

    if multi_mgmt:
        logger.info("Articles with multiple management entries (could cause admin display issues):")
        for article_id, cnt in multi_mgmt[:10]:
            logger.info(f"  Article ID {article_id}: {cnt} management entries")

            # Get the titles for these articles
            cursor.execute('SELECT title FROM articles WHERE id = ?', (article_id,))
            title_result = cursor.fetchone()
            if title_result:
                logger.info(f"    Title: '{title_result[0][:50]}...'")

    conn.close()
    return len(multi_mgmt)

def clean_duplicate_management_entries():
    """Clean up any duplicate management entries that could cause display issues"""
    logger.info("Cleaning up duplicate management entries...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Find articles with multiple management entries
    cursor.execute('''
        SELECT article_id, COUNT(*) as cnt, GROUP_CONCAT(id) as mgmt_ids
        FROM article_management
        GROUP BY article_id
        HAVING cnt > 1
        ORDER BY cnt DESC
    ''')

    dupes = cursor.fetchall()
    removed = 0

    for article_id, cnt, mgmt_ids_str in dupes:
        mgmt_ids = [int(x) for x in mgmt_ids_str.split(',')]

        # Keep the most recent management entry (highest ID)
        keep_id = max(mgmt_ids)
        delete_ids = [id for id in mgmt_ids if id != keep_id]

        logger.info(f"Article {article_id}: keeping management entry {keep_id}, removing {delete_ids}")

        for delete_id in delete_ids:
            cursor.execute('DELETE FROM article_management WHERE id = ?', (delete_id,))
            removed += 1

    conn.commit()
    conn.close()

    logger.info(f"Removed {removed} duplicate management entries")
    return removed

def main():
    logger.info("🔍 ADMIN INTERFACE DUPLICATE ANALYSIS")
    logger.info("=" * 60)

    # Check admin query results
    logger.info("\n1. ADMIN QUERY ANALYSIS:")
    duplicate_ids, similar_titles = check_admin_articles_query()

    # Check for query structure issues
    logger.info("\n2. QUERY STRUCTURE CHECK:")
    multi_mgmt = check_for_query_duplicates()

    # Clean up if needed
    if multi_mgmt > 0:
        logger.info("\n3. CLEANUP:")
        removed = clean_duplicate_management_entries()

        # Re-run checks
        logger.info("\n4. POST-CLEANUP VERIFICATION:")
        duplicate_ids2, similar_titles2 = check_admin_articles_query()

        logger.info("\nCLEANUP RESULTS:")
        logger.info(f"  Duplicate IDs before: {duplicate_ids} -> after: {duplicate_ids2}")
        logger.info(f"  Similar titles: {similar_titles} (unchanged - these are legitimate)")
        logger.info(f"  Management entries removed: {removed}")
    else:
        logger.info("\n✅ No cleanup needed - admin interface should display correctly")

    # Summary
    logger.info("\nSUMMARY:")
    if duplicate_ids == 0 and multi_mgmt == 0:
        logger.info("  Admin interface should display articles correctly")
        logger.info("  No duplicate IDs or management entries found")
        if similar_titles > 0:
            logger.info(f"  {similar_titles} articles have similar titles (normal for news)")
    else:
        logger.info("  Issues found that could cause duplicate display")

    logger.info("\n" + "="*60)
    logger.info("Admin duplicate check completed!")

if __name__ == "__main__":
    main()