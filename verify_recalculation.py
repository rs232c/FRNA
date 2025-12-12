#!/usr/bin/env python3
"""
Verify the results of article recalculation
"""
import sqlite3
from config import DATABASE_CONFIG

def main():
    """Check recalculation results"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    cursor = conn.cursor()

    print("=== RECALCULATION VERIFICATION ===\n")

    # Check total articles
    cursor.execute('SELECT COUNT(*) FROM articles')
    total = cursor.fetchone()[0]
    print(f"Total articles: {total}")

    # Check articles with relevance scores
    cursor.execute('SELECT COUNT(*) FROM articles WHERE relevance_score IS NOT NULL')
    with_scores = cursor.fetchone()[0]
    print(f"Articles with relevance scores: {with_scores} ({with_scores/total*100:.1f}%)")

    # Check articles with positive relevance scores
    cursor.execute('SELECT COUNT(*) FROM articles WHERE relevance_score > 0')
    with_positive_scores = cursor.fetchone()[0]
    print(f"Articles with positive relevance scores: {with_positive_scores} ({with_positive_scores/total*100:.1f}%)")

    # Check articles with categories
    cursor.execute('SELECT COUNT(*) FROM articles WHERE category IS NOT NULL AND category != ""')
    with_categories = cursor.fetchone()[0]
    print(f"Articles with categories: {with_categories} ({with_categories/total*100:.1f}%)")

    # Check articles with primary categories
    cursor.execute('SELECT COUNT(*) FROM articles WHERE primary_category IS NOT NULL AND primary_category != ""')
    with_primary = cursor.fetchone()[0]
    print(f"Articles with primary categories: {with_primary} ({with_primary/total*100:.1f}%)")

    # Relevance score distribution
    print("\n=== RELEVANCE SCORE DISTRIBUTION ===")
    cursor.execute('''
        SELECT
            CASE
                WHEN relevance_score < 10 THEN '0-9'
                WHEN relevance_score < 20 THEN '10-19'
                WHEN relevance_score < 30 THEN '20-29'
                WHEN relevance_score < 40 THEN '30-39'
                WHEN relevance_score < 50 THEN '40-49'
                WHEN relevance_score >= 50 THEN '50+'
                ELSE 'No Score'
            END as range,
            COUNT(*) as count
        FROM articles
        GROUP BY range
        ORDER BY
            CASE range
                WHEN '0-9' THEN 1
                WHEN '10-19' THEN 2
                WHEN '20-29' THEN 3
                WHEN '30-39' THEN 4
                WHEN '40-49' THEN 5
                WHEN '50+' THEN 6
                ELSE 7
            END
    ''')

    for row in cursor.fetchall():
        range_name, count = row
        percentage = count / total * 100 if total > 0 else 0
        print(f"  {range_name}: {count} articles ({percentage:.1f}%)")

    # Category distribution
    print("\n=== CATEGORY DISTRIBUTION ===")
    cursor.execute('''
        SELECT category, COUNT(*) as count
        FROM articles
        WHERE category IS NOT NULL AND category != ""
        GROUP BY category
        ORDER BY count DESC
        LIMIT 10
    ''')

    for row in cursor.fetchall():
        category, count = row
        percentage = count / total * 100 if total > 0 else 0
        print(f"  {category}: {count} articles ({percentage:.1f}%)")

    # Check enabled articles after recalculation
    cursor.execute('''
        SELECT COUNT(*) FROM article_management am
        JOIN articles a ON am.article_id = a.id
        WHERE am.enabled = 1 AND am.zip_code = '02720'
    ''')
    enabled = cursor.fetchone()[0]
    print(f"\nEnabled articles (02720): {enabled}")

    # Average relevance of enabled articles
    cursor.execute('''
        SELECT AVG(a.relevance_score) FROM article_management am
        JOIN articles a ON am.article_id = a.id
        WHERE am.enabled = 1 AND am.zip_code = '02720' AND a.relevance_score IS NOT NULL
    ''')
    avg_enabled = cursor.fetchone()[0]
    if avg_enabled:
        print(f"Average relevance of enabled articles: {avg_enabled:.1f}")

    conn.close()

    print("\n=== SUMMARY ===")
    print("SUCCESS: Recalculation verification complete!")
    print(f"DATA: {with_scores}/{total} articles have relevance scores")
    print(f"LABELS: {with_categories}/{total} articles have categories")
    print(f"TARGET: {enabled} articles are currently enabled")

if __name__ == "__main__":
    main()
