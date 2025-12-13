import sqlite3
import os
from datetime import datetime, timedelta

def analyze_database():
    # Connect to the main database
    db_path = 'fallriver_news.db'
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found!")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print('=== FALL RIVER NEWS DATABASE STATISTICS ===')
    print(f'Database: {db_path}')
    print(f'Size: {os.path.getsize(db_path):,} bytes ({os.path.getsize(db_path)/1024/1024:.1f} MB)')
    print()

    # Get table info
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print(f'Tables: {len(tables)}')
    for table in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {table[0]}')
        count = cursor.fetchone()[0]
        print(f'  - {table[0]}: {count:,} rows')
    print()

    # Articles table statistics
    print('=== ARTICLES TABLE ===')
    cursor.execute('SELECT COUNT(*) FROM articles')
    total_articles = cursor.fetchone()[0]
    print(f'Total articles: {total_articles:,}')

    # Date range
    cursor.execute('SELECT MIN(created_at), MAX(created_at), MIN(published), MAX(published) FROM articles')
    min_created, max_created, min_published, max_published = cursor.fetchone()
    print(f'Created date range: {min_created} to {max_created}')
    print(f'Published date range: {min_published} to {max_published}')

    # Recent articles (last 7 days)
    seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
    cursor.execute('SELECT COUNT(*) FROM articles WHERE created_at >= ?', (seven_days_ago,))
    recent_count = cursor.fetchone()[0]
    print(f'Articles in last 7 days: {recent_count:,}')

    # Source breakdown
    cursor.execute('SELECT source, COUNT(*) FROM articles GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10')
    sources = cursor.fetchall()
    print(f'Top 10 sources ({len(sources)} total sources):')
    for source, count in sources:
        percentage = (count / total_articles) * 100
        print(f'  - {source}: {count:,} ({percentage:.1f}%)')

    # Category breakdown
    cursor.execute('SELECT category, COUNT(*) FROM articles WHERE category IS NOT NULL GROUP BY category ORDER BY COUNT(*) DESC')
    categories = cursor.fetchall()
    print(f'Categories ({len(categories)} total):')
    for category, count in categories:
        percentage = (count / total_articles) * 100
        print(f'  - {category}: {count:,} ({percentage:.1f}%)')

    # Zip code breakdown
    cursor.execute('SELECT zip_code, COUNT(*) FROM articles WHERE zip_code IS NOT NULL GROUP BY zip_code ORDER BY COUNT(*) DESC')
    zip_codes = cursor.fetchall()
    print(f'Zip codes ({len(zip_codes)} total):')
    for zip_code, count in zip_codes:
        percentage = (count / total_articles) * 100
        print(f'  - {zip_code}: {count:,} ({percentage:.1f}%)')

    # Relevance scores
    cursor.execute('SELECT AVG(relevance_score), MIN(relevance_score), MAX(relevance_score) FROM articles WHERE relevance_score IS NOT NULL')
    result = cursor.fetchone()
    if result and result[0] is not None:
        avg_score, min_score, max_score = result
        print(f'Relevance scores - Avg: {avg_score:.1f}, Min: {min_score:.1f}, Max: {max_score:.1f}')
    else:
        print('Relevance scores: No data available')

    # Articles with images
    cursor.execute('SELECT COUNT(*) FROM articles WHERE image_url IS NOT NULL AND image_url != ""')
    with_images = cursor.fetchone()[0]
    print(f'Articles with images: {with_images:,} ({(with_images/total_articles)*100:.1f}%)')

    print()
    print('=== ARTICLE MANAGEMENT ===')
    cursor.execute('SELECT COUNT(*) FROM article_management')
    total_mgmt = cursor.fetchone()[0]
    print(f'Total management entries: {total_mgmt:,}')

    cursor.execute('SELECT enabled, COUNT(*) FROM article_management GROUP BY enabled')
    enabled_stats = cursor.fetchall()
    for enabled, count in enabled_stats:
        status = 'Enabled' if enabled else 'Disabled'
        print(f'  - {status}: {count:,}')

    print()
    print('=== RELEVANCE CONFIG ===')
    cursor.execute('SELECT COUNT(*) FROM relevance_config')
    relevance_rules = cursor.fetchone()[0]
    print(f'Total relevance rules: {relevance_rules:,}')

    cursor.execute('SELECT category, COUNT(*) FROM relevance_config GROUP BY category ORDER BY COUNT(*) DESC')
    rule_categories = cursor.fetchall()
    print('Rules by category:')
    for category, count in rule_categories:
        print(f'  - {category}: {count:,}')

    print()
    print('=== POSTED ARTICLES ===')
    cursor.execute('SELECT COUNT(*) FROM posted_articles')
    total_posted = cursor.fetchone()[0]
    print(f'Total posted articles: {total_posted:,}')

    cursor.execute('SELECT platform, COUNT(*) FROM posted_articles GROUP BY platform ORDER BY COUNT(*) DESC')
    platforms = cursor.fetchall()
    print('By platform:')
    for platform, count in platforms:
        print(f'  - {platform}: {count:,}')

    print()
    print('=== TRAINING DATA ===')
    cursor.execute('SELECT COUNT(*) FROM training_data')
    training_count = cursor.fetchone()[0]
    print(f'Total training samples: {training_count:,}')

    if training_count > 0:
        cursor.execute('SELECT good_fit, COUNT(*) FROM training_data GROUP BY good_fit')
        fit_stats = cursor.fetchall()
        for fit, count in fit_stats:
            status = 'Good fit' if fit else 'Not good fit'
            print(f'  - {status}: {count:,}')

    # Additional database health checks
    print()
    print('=== DATABASE HEALTH ===')

    # Check for duplicate URLs
    cursor.execute('''
        SELECT COUNT(*) FROM (
            SELECT url, COUNT(*) as cnt FROM articles
            WHERE url IS NOT NULL AND url != '' AND url != '#'
            GROUP BY url HAVING cnt > 1
        )
    ''')
    duplicate_urls = cursor.fetchone()[0]
    print(f'Duplicate URLs: {duplicate_urls:,}')

    # Check for articles without zip_code
    cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code IS NULL')
    null_zip = cursor.fetchone()[0]
    print(f'Articles without zip_code: {null_zip:,} ({(null_zip/total_articles)*100:.1f}%)')

    # Check for articles without category
    cursor.execute('SELECT COUNT(*) FROM articles WHERE category IS NULL')
    null_category = cursor.fetchone()[0]
    print(f'Articles without category: {null_category:,} ({(null_category/total_articles)*100:.1f}%)')

    # Check for articles without relevance_score
    cursor.execute('SELECT COUNT(*) FROM articles WHERE relevance_score IS NULL')
    null_relevance = cursor.fetchone()[0]
    print(f'Articles without relevance_score: {null_relevance:,} ({(null_relevance/total_articles)*100:.1f}%)')

    conn.close()

if __name__ == '__main__':
    analyze_database()
