#!/usr/bin/env python3
"""
Recalculate categories and relevance scores for existing articles
"""
import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Optional
import logging

# Add utils to path
sys.path.append('utils')

from config import DATABASE_CONFIG

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ArticleRecalculator:
    """Recalculates categories and relevance for existing articles"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_CONFIG.get("path", "fallriver_news.db")

    def recalculate_batch(self, zip_code: Optional[str] = None, limit: int = 100, offset: int = 0):
        """Recalculate a batch of articles"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get articles to recalculate
            if zip_code:
                cursor.execute('''
                    SELECT id, title, content, summary, source, zip_code
                    FROM articles
                    WHERE zip_code = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                ''', (zip_code, limit, offset))
            else:
                cursor.execute('''
                    SELECT id, title, content, summary, source, zip_code
                    FROM articles
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                ''', (limit, offset))

            articles = cursor.fetchall()

            if not articles:
                logger.info("No articles found to recalculate")
                return 0

            logger.info(f"Recalculating {len(articles)} articles...")

            updated_count = 0

            for article_row in articles:
                article_id = article_row['id']
                article_dict = dict(article_row)

                # Recalculate relevance score (skip dynamic credibility during bulk operations)
                try:
                    from utils.relevance_calculator import calculate_relevance_score
                    # Temporarily disable dynamic credibility to avoid database locks
                    new_relevance = calculate_relevance_score(article_dict, zip_code=article_row['zip_code'])
                    # Note: Dynamic credibility learning is skipped during bulk recalculation

                    # Recalculate category using smart categorizer
                    try:
                        from utils.smart_categorizer import SmartCategorizer
                        categorizer = SmartCategorizer(article_row['zip_code'])
                        primary_category, confidence, _ = categorizer.categorize_article(article_dict)

                        # Convert to database format
                        category = primary_category.replace(' ', '-').lower()  # "Local News" -> "local-news"
                        primary_category_db = primary_category.replace('-', ' ').title()  # "local-news" -> "Local News"

                        # Update article
                        cursor.execute('''
                            UPDATE articles
                            SET relevance_score = ?, category = ?, primary_category = ?,
                                category_confidence = ?
                            WHERE id = ?
                        ''', (new_relevance, category, primary_category_db, confidence/100.0, article_id))

                        updated_count += 1

                        if updated_count % 10 == 0:
                            logger.info(f"Updated {updated_count} articles...")

                    except ImportError:
                        logger.warning("Smart categorizer not available, skipping category update")

                except Exception as e:
                    logger.error(f"Error recalculating article {article_id}: {e}")
                    continue

            conn.commit()
            conn.close()

            logger.info(f"Successfully recalculated {updated_count} articles")
            return updated_count

        except Exception as e:
            logger.error(f"Error in recalculate_batch: {e}")
            return 0

    def recalculate_all(self, zip_code: Optional[str] = None, batch_size: int = 100):
        """Recalculate all articles in batches"""
        total_updated = 0
        offset = 0

        while True:
            batch_updated = self.recalculate_batch(zip_code, batch_size, offset)
            total_updated += batch_updated

            if batch_updated < batch_size:
                # Last batch
                break

            offset += batch_size

        return total_updated

def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description='Recalculate categories and relevance for articles')
    parser.add_argument('--zip', help='Specific zip code to recalculate (optional)')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for processing')
    parser.add_argument('--all', action='store_true', help='Recalculate all articles')

    args = parser.parse_args()

    recalculator = ArticleRecalculator()

    if args.all:
        logger.info("Recalculating ALL articles...")
        total = recalculator.recalculate_all(args.zip, args.batch_size)
        logger.info(f"Completed recalculation of {total} articles")
    else:
        # Recalculate just one batch for testing
        logger.info("Recalculating one batch of articles (use --all for all articles)...")
        count = recalculator.recalculate_batch(args.zip, args.batch_size, 0)
        logger.info(f"Recalculated {count} articles")

if __name__ == "__main__":
    main()
