#!/usr/bin/env python3
"""
Find Content-Based Duplicates
FallRiver.live Database Analysis

This script looks for articles that are essentially the same content
but might have slight variations in titles, dates, or other metadata.
"""

import sqlite3
from config import DATABASE_CONFIG
from difflib import SequenceMatcher
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def find_similar_content_by_source():
    """Find articles with very similar content from the same source"""
    logger.info("Finding articles with similar content from same source...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Get all articles by source
    cursor.execute('''
        SELECT id, title, content, summary, url, published, source
        FROM articles
        WHERE content IS NOT NULL AND content != '' AND source IS NOT NULL
        ORDER BY source, published DESC
    ''')

    articles = cursor.fetchall()
    logger.info(f"Analyzing {len(articles)} articles with content")

    # Group by source
    by_source = {}
    for article in articles:
        source = article[6]
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(article)

    potential_dupes = []

    # For each source, compare content similarity
    for source, source_articles in by_source.items():
        if len(source_articles) < 2:
            continue

        logger.info(f"Checking {len(source_articles)} articles from {source}")

        # Compare each pair of articles from same source
        for i, art1 in enumerate(source_articles):
            for j, art2 in enumerate(source_articles[i+1:], i+1):
                id1, title1, content1, summary1, url1, pub1, src1 = art1
                id2, title2, content2, summary2, url2, pub2, src2 = art2

                # Skip if same URL (already caught)
                if url1 and url2 and url1 == url2:
                    continue

                # Compare content similarity
                content_sim = SequenceMatcher(None, (content1 or "").lower(), (content2 or "").lower()).ratio()

                # Compare summary similarity
                summary_sim = SequenceMatcher(None, (summary1 or "").lower(), (summary2 or "").lower()).ratio()

                # High similarity in content or summary
                if content_sim > 0.85 or (summary_sim > 0.9 and content_sim > 0.7):
                    potential_dupes.append({
                        'source': source,
                        'similarity': max(content_sim, summary_sim),
                        'id1': id1, 'id2': id2,
                        'title1': title1[:60], 'title2': title2[:60],
                        'url1': url1[:50] if url1 else None,
                        'url2': url2[:50] if url2 else None,
                        'date1': pub1, 'date2': pub2
                    })

    logger.info(f"Found {len(potential_dupes)} potential content duplicates")

    # Sort by similarity and show top ones
    if potential_dupes:
        potential_dupes.sort(key=lambda x: x['similarity'], reverse=True)

        logger.info("\nTOP CONTENT DUPLICATES:")
        for i, dupe in enumerate(potential_dupes[:15]):
            logger.info(f"\n{i+1}. {dupe['source']} - Similarity: {dupe['similarity']:.1%}")
            logger.info(f"   Article 1 (ID {dupe['id1']}): '{dupe['title1']}'")
            logger.info(f"   Article 2 (ID {dupe['id2']}): '{dupe['title2']}'")
            logger.info(f"   URL1: {dupe['url1']}")
            logger.info(f"   URL2: {dupe['url2']}")

    conn.close()
    return potential_dupes

def find_articles_with_identical_content():
    """Find articles with completely identical content"""
    logger.info("Finding articles with identical content...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    # Find articles with identical content
    cursor.execute('''
        SELECT content, COUNT(*) as cnt, GROUP_CONCAT(id) as ids,
               GROUP_CONCAT(title) as titles, GROUP_CONCAT(source) as sources
        FROM articles
        WHERE content IS NOT NULL AND content != '' AND LENGTH(content) > 100
        GROUP BY content
        HAVING cnt > 1
        ORDER BY cnt DESC
    ''')

    identical_content = cursor.fetchall()
    logger.info(f"Found {len(identical_content)} sets of articles with identical content")

    if identical_content:
        logger.info("\nARTICLES WITH IDENTICAL CONTENT:")
        for i, (content, cnt, ids_str, titles_str, sources_str) in enumerate(identical_content):
            ids = ids_str.split(',')
            titles = titles_str.split(',')
            sources = sources_str.split(',')

            logger.info(f"\n{i+1}. Identical content found in {cnt} articles:")
            for j, (id, title, source) in enumerate(zip(ids, titles, sources)):
                logger.info(f"   {j+1}. ID {id}: '{title[:50]}...' ({source})")

    conn.close()
    return identical_content

def find_articles_with_identical_summaries():
    """Find articles with identical summaries (often indicates duplication)"""
    logger.info("Finding articles with identical summaries...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    cursor.execute('''
        SELECT summary, COUNT(*) as cnt, GROUP_CONCAT(id) as ids,
               GROUP_CONCAT(title) as titles, GROUP_CONCAT(source) as sources
        FROM articles
        WHERE summary IS NOT NULL AND summary != '' AND LENGTH(summary) > 50
        GROUP BY summary
        HAVING cnt > 1
        ORDER BY cnt DESC
    ''')

    identical_summaries = cursor.fetchall()
    logger.info(f"Found {len(identical_summaries)} sets of articles with identical summaries")

    if identical_summaries:
        logger.info("\nARTICLES WITH IDENTICAL SUMMARIES:")
        for i, (summary, cnt, ids_str, titles_str, sources_str) in enumerate(identical_summaries[:10]):
            ids = ids_str.split(',')
            titles = titles_str.split(',')
            sources = sources_str.split(',')

            logger.info(f"\n{i+1}. Identical summary in {cnt} articles:")
            logger.info(f"   Summary: '{summary[:100]}...'")
            for j, (id, title, source) in enumerate(zip(ids, titles, sources)):
                logger.info(f"   {j+1}. ID {id}: '{title[:50]}...' ({source})")

    conn.close()
    return identical_summaries

def remove_content_duplicates():
    """Remove articles with identical content, keeping the newest one"""
    logger.info("Removing articles with identical content...")

    conn = sqlite3.connect(DATABASE_CONFIG["path"])
    cursor = conn.cursor()

    removed = 0

    # Find identical content groups
    cursor.execute('''
        SELECT content, GROUP_CONCAT(id) as ids
        FROM articles
        WHERE content IS NOT NULL AND content != '' AND LENGTH(content) > 100
        GROUP BY content
        HAVING COUNT(*) > 1
    ''')

    identical_groups = cursor.fetchall()

    for content, ids_str in identical_groups:
        ids = [int(x) for x in ids_str.split(',')]
        if len(ids) > 1:
            # Keep the one with the highest ID (newest)
            keep_id = max(ids)
            delete_ids = [id for id in ids if id != keep_id]

            logger.info(f"Removing {len(delete_ids)} duplicates of content, keeping ID {keep_id}")

            for delete_id in delete_ids:
                # Remove from related tables
                cursor.execute('DELETE FROM article_management WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM training_data WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM articles WHERE id = ?', (delete_id,))
                removed += 1

    conn.commit()
    conn.close()

    logger.info(f"Removed {removed} articles with identical content")
    return removed

def main():
    logger.info("🔍 Deep Content Duplicate Analysis")
    logger.info("=" * 60)

    logger.info("\n1. IDENTICAL CONTENT:")
    identical_content = find_articles_with_identical_content()

    logger.info("\n2. IDENTICAL SUMMARIES:")
    identical_summaries = find_articles_with_identical_summaries()

    logger.info("\n3. SIMILAR CONTENT BY SOURCE:")
    similar_content = find_similar_content_by_source()

    # Summary
    total_issues = len(identical_content) + len(identical_summaries) + len(similar_content)

    logger.info(f"\n📊 SUMMARY:")
    logger.info(f"  Identical content groups: {len(identical_content)}")
    logger.info(f"  Identical summary groups: {len(identical_summaries)}")
    logger.info(f"  Similar content pairs: {len(similar_content)}")
    logger.info(f"  Total potential issues: {total_issues}")

    if total_issues > 0:
        logger.info(f"\n🧹 Found {total_issues} content duplicate issues!")

        # Ask if we should remove identical content duplicates
        if len(identical_content) > 0:
            logger.info("Removing articles with identical content...")
            removed = remove_content_duplicates()
            logger.info(f"✅ Removed {removed} articles with identical content")
        else:
            logger.info("No identical content duplicates to remove.")
    else:
        logger.info("\n✅ No content duplicates found!")

    logger.info("\n" + "="*60)
    logger.info("Content duplicate analysis completed!")

if __name__ == "__main__":
    main()