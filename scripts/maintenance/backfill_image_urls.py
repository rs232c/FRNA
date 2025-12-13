"""
Backfill image_url for existing articles by scraping their pages.

⚠️  IMPORTANT: This script makes HTTP requests to external websites.
   Default settings are conservative to avoid violating terms of service:
   - Max 2 concurrent requests
   - 1-3 second delays between requests
   - 5 second pauses between batches

   Adjust settings carefully and respect robots.txt!
"""
import asyncio
import sqlite3
import argparse
import time
import random
from ingestors.news_ingestor import NewsIngestor
from database import ArticleDatabase
from config import DATABASE_CONFIG
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def process_article(article, ingestor, db_conn, semaphore, stats, request_delay=1.0):
    """Process a single article to extract and save image_url"""
    async with semaphore:
        url = article.get('url')
        article_id = article.get('id')
        title = article.get('title', '')[:50]

        if not url:
            stats['skipped'] += 1
            return

        try:
            # Add random delay between requests to be respectful (0.5-2.5 seconds)
            delay = request_delay + random.uniform(0.5, 1.5)
            await asyncio.sleep(delay)

            scraped = await ingestor._do_scrape_article(url)

            if scraped and scraped.get('image_url'):
                image_url = scraped['image_url']
                cursor = db_conn.cursor()
                cursor.execute('UPDATE articles SET image_url = ? WHERE id = ?', (image_url, article_id))
                db_conn.commit()
                stats['updated'] += 1
                logger.info(f"  ✓ [{stats['processed']}/{stats['total']}] Updated article {article_id}: {title}...")
                # #region agent log
                try:
                    import json
                    with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"backfill","hypothesisId":"J","location":"backfill_image_urls.py:process_article","message":"Backfilled article with image_url","data":{"article_id":article_id,"title":title,"image_url":(image_url or '')[:80]},"timestamp":int(time.time()*1000)})+'\n')
                except: pass
                # #endregion
            else:
                stats['no_image'] += 1
                logger.debug(f"  ✗ [{stats['processed']}/{stats['total']}] No image found for article {article_id}: {title}...")
                # #region agent log
                try:
                    import json
                    with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                        f.write(json.dumps({"sessionId":"debug-session","runId":"backfill","hypothesisId":"J","location":"backfill_image_urls.py:process_article","message":"No image found for article","data":{"article_id":article_id,"title":title,"url":(url or '')[:60]},"timestamp":int(time.time()*1000)})+'\n')
                except: pass
                # #endregion
        except Exception as e:
            stats['errors'] += 1
            logger.warning(f"  ✗ [{stats['processed']}/{stats['total']}] Error scraping article {article_id} ({url[:50]}...): {e}")
        finally:
            stats['processed'] += 1
            # Print progress every 10 articles
            if stats['processed'] % 10 == 0:
                progress = (stats['processed'] / stats['total']) * 100
                logger.info(f"Progress: {progress:.1f}% ({stats['processed']}/{stats['total']}) - Updated: {stats['updated']}, No image: {stats['no_image']}, Errors: {stats['errors']}")

async def backfill_image_urls(limit=50, concurrency=2, offset=0, process_all=False, request_delay=1.0):
    """
    Scrape article pages to get image_url for existing articles.

    ⚠️  RESPECTFUL SCRAPING: This function implements conservative rate limiting
    to avoid overwhelming servers or violating terms of service. Always check
    robots.txt before running at scale.

    Args:
        limit: Maximum number of articles to process per batch (default: 50)
        concurrency: Maximum concurrent requests - keep low! (default: 2)
        offset: Starting offset for pagination
        process_all: If True, process all articles in batches
        request_delay: Base delay between requests (adds random 0.5-1.5s)
    """
    db = ArticleDatabase()
    db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
    
    # Get total count of articles without image_url
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM articles WHERE image_url IS NULL OR image_url = ""')
    total_articles = cursor.fetchone()[0]
    conn.close()
    
    if total_articles == 0:
        logger.info("No articles need image_url backfill")
        return
    
    logger.info(f"Found {total_articles} articles without image_url")
    
    if process_all:
        logger.info(f"Processing all {total_articles} articles in batches of {limit}")
        total_processed = 0
        current_offset = offset
        
        while current_offset < total_articles:
            batch_limit = min(limit, total_articles - current_offset)
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing batch: {current_offset} to {current_offset + batch_limit} (of {total_articles})")
            logger.info(f"{'='*60}")
            
            batch_stats = await process_batch(batch_limit, concurrency, current_offset, db_path, request_delay)
            total_processed += batch_stats['processed']
            current_offset += batch_limit

            if current_offset < total_articles:
                logger.info(f"\nBatch complete. Continuing to next batch...")
                await asyncio.sleep(5)  # Respectful pause between batches (5 seconds)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"All batches complete! Total processed: {total_processed}")
        logger.info(f"{'='*60}")
    else:
        await process_batch(limit, concurrency, offset, db_path, request_delay)

async def process_batch(limit, concurrency, offset, db_path, request_delay=1.0):
    """Process a single batch of articles"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get articles without image_url
    cursor.execute('''
        SELECT id, url, title, source 
        FROM articles 
        WHERE image_url IS NULL OR image_url = ''
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    
    articles = [dict(row) for row in cursor.fetchall()]
    
    if not articles:
        logger.info("No articles found in this batch")
        conn.close()
        return {'processed': 0, 'updated': 0, 'no_image': 0, 'errors': 0, 'skipped': 0}
    
    logger.info(f"Processing {len(articles)} articles with concurrency limit of {concurrency}")
    
    # Create a dummy ingestor just for scraping
    dummy_config = {"name": "Backfill", "url": ""}
    ingestor = NewsIngestor(dummy_config)
    
    # Statistics tracking
    stats = {
        'total': len(articles),
        'processed': 0,
        'updated': 0,
        'no_image': 0,
        'errors': 0,
        'skipped': 0
    }
    
    # Create semaphore for rate limiting
    semaphore = asyncio.Semaphore(concurrency)
    
    # Process articles in parallel
    start_time = time.time()
    tasks = [process_article(article, ingestor, conn, semaphore, stats, request_delay) for article in articles]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Handle any exceptions that weren't caught
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            stats['errors'] += 1
            logger.error(f"Unhandled exception for article {articles[i].get('id')}: {result}")
    
    elapsed_time = time.time() - start_time
    
    conn.close()
    await ingestor._close_session()
    
    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"Batch Summary:")
    logger.info(f"  Total processed: {stats['processed']}")
    logger.info(f"  Successfully updated: {stats['updated']}")
    logger.info(f"  No image found: {stats['no_image']}")
    logger.info(f"  Errors: {stats['errors']}")
    logger.info(f"  Skipped: {stats['skipped']}")
    logger.info(f"  Time elapsed: {elapsed_time:.2f} seconds")
    if stats['processed'] > 0:
        logger.info(f"  Average time per article: {elapsed_time / stats['processed']:.2f} seconds")
    logger.info(f"{'='*60}\n")
    
    return stats

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backfill image_url for articles missing images (with respectful rate limiting)')
    parser.add_argument('limit', type=int, nargs='?', default=50,
                       help='Number of articles to process per batch (default: 50)')
    parser.add_argument('--concurrency', '-c', type=int, default=2,
                       help='Maximum concurrent requests - be respectful! (default: 2)')
    parser.add_argument('--offset', '-o', type=int, default=0,
                       help='Starting offset for pagination (default: 0)')
    parser.add_argument('--all', '-a', action='store_true',
                       help='Process all articles in batches')
    parser.add_argument('--delay', '-d', type=float, default=1.0,
                       help='Base delay between requests in seconds (default: 1.0, adds 0.5-1.5s random)')

    args = parser.parse_args()

    # Safety check for concurrency
    if args.concurrency > 5:
        logger.warning(f"⚠️  High concurrency ({args.concurrency}) may violate terms of service. Consider using 2-3 for safety.")
    if args.concurrency > 10:
        logger.error("🚫 Concurrency too high! Maximum allowed: 10. Use --concurrency 2 for safety.")
        exit(1)

    logger.info(f"🛡️  Starting backfill with safe settings:")
    logger.info(f"   • Concurrency: {args.concurrency} (max simultaneous requests)")
    logger.info(f"   • Request delay: {args.delay:.1f}s + random(0.5-1.5s)")
    logger.info(f"   • Batch size: {args.limit}")
    logger.info(f"   • Process all: {args.all}")

    asyncio.run(backfill_image_urls(
        limit=args.limit,
        concurrency=args.concurrency,
        offset=args.offset,
        process_all=args.all,
        request_delay=args.delay
    ))

