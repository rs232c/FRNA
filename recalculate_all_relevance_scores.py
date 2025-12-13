#!/usr/bin/env python3
"""
Recalculate relevance scores for all existing articles to fix trending section
"""

import sqlite3
from utils.relevance_calculator_v2 import calculate_relevance_score
from config import DATABASE_CONFIG
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def recalculate_all_relevance_scores():
    """Recalculate relevance scores for all articles in database"""

    db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get all articles
        cursor.execute('''
            SELECT id, title, content, summary, source, published, zip_code
            FROM articles
            WHERE zip_code = '02720'
            ORDER BY id
        ''')

        articles = cursor.fetchall()
        total_articles = len(articles)

        logger.info(f"Recalculating relevance scores for {total_articles} articles...")

        updated_count = 0
        for i, (article_id, title, content, summary, source, published, zip_code) in enumerate(articles):
            if i % 100 == 0:
                logger.info(f"Processing {i}/{total_articles} articles...")

            # Create article dict for relevance calculation
            article_dict = {
                'id': article_id,
                'title': title or '',
                'content': content or '',
                'summary': summary or '',
                'source': source or '',
                'published': published or '',
                'zip_code': zip_code or '02720'
            }

            try:
                # Calculate new relevance score
                new_score = calculate_relevance_score(article_dict, zip_code=zip_code)

                # Update the database
                cursor.execute('''
                    UPDATE articles
                    SET relevance_score = ?
                    WHERE id = ?
                ''', (new_score, article_id))

                updated_count += 1

            except Exception as e:
                logger.warning(f"Error calculating score for article {article_id}: {e}")
                continue

        conn.commit()
        conn.close()

        logger.info(f"Successfully updated relevance scores for {updated_count}/{total_articles} articles")

        # Verify the update worked
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT COUNT(*), AVG(relevance_score), MIN(relevance_score), MAX(relevance_score)
            FROM articles
            WHERE zip_code = '02720' AND relevance_score IS NOT NULL
        ''')

        count, avg_score, min_score, max_score = cursor.fetchone()
        logger.info(f"Verification - Articles with scores: {count}")
        logger.info(f"Average relevance score: {avg_score:.1f}")
        logger.info(f"Score range: {min_score:.1f} - {max_score:.1f}")

        # Check recent articles specifically
        cursor.execute('''
            SELECT COUNT(*), AVG(relevance_score)
            FROM articles
            WHERE zip_code = '02720' AND published > datetime('now', '-3 days')
            AND relevance_score IS NOT NULL
        ''')

        recent_count, recent_avg = cursor.fetchone()
        logger.info(f"Recent articles (3 days): {recent_count} with avg score {recent_avg:.1f}")

        conn.close()

    except Exception as e:
        logger.error(f"Error recalculating relevance scores: {e}")

if __name__ == "__main__":
    recalculate_all_relevance_scores()