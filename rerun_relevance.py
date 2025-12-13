#!/usr/bin/env python3
"""
Rerun relevance scoring for all articles (standalone script)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.relevance_calculator import calculate_relevance_score_with_tags
from utils.bayesian_learner import BayesianLearner
import sqlite3
from config import DATABASE_CONFIG
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    try:
        print('Starting relevance scoring rerun...')
        print(f'Database path: {DATABASE_CONFIG.get("path", "fallriver_news.db")}')

        # Connect to database and get relevance threshold
        conn = sqlite3.connect(DATABASE_CONFIG.get('path', 'fallriver_news.db'))
        cursor = conn.cursor()
        print('Database connection successful')

        # Get relevance threshold from admin_settings
        cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('relevance_threshold',))
        threshold_row = cursor.fetchone()
        relevance_threshold = float(threshold_row[0]) if threshold_row else 10.0
        print(f'Using relevance threshold: {relevance_threshold}')

        # Clear existing auto-filtered status for re-evaluation
        cursor.execute('UPDATE article_management SET is_auto_filtered = 0, auto_reject_reason = NULL WHERE is_auto_filtered = 1')
        print('Cleared existing auto-filtered status')

        # Get all articles (including previously auto-filtered ones for re-evaluation)
        cursor.execute('SELECT id, title, content, source FROM articles')
        articles = cursor.fetchall()
        total_articles = len(articles)
        print(f'Found {total_articles} articles to process')

        processed_count = 0
        filtered_count = 0
        start_time = time.time()

        learner = BayesianLearner()

        for article_row in articles:
            article_id, title, content, source = article_row
            article = {
                'title': title,
                'content': content or '',
                'source': source
            }

            # Calculate relevance score
            try:
                relevance_score, tag_info = calculate_relevance_score_with_tags(article, zip_code='02720')
            except Exception as e:
                logger.warning(f'Error calculating relevance for article {article_id}: {e}')
                continue

            # Update relevance score in database
            cursor.execute('UPDATE articles SET relevance_score = ? WHERE id = ?', (relevance_score, article_id))

            # Check if it should be auto-filtered
            should_filter = False
            reason = ''

            # Check relevance threshold (exclude obituaries)
            article_category = (article.get('category', '') or '').lower()
            is_obituary = 'obituar' in article_category

            if relevance_score < relevance_threshold and not is_obituary:
                should_filter = True
                reason = f'Relevance score {relevance_score:.1f} below threshold {relevance_threshold}'
                print(f'FILTERING article {article_id}: {reason}')

            # Check Bayesian filtering
            if not should_filter:
                try:
                    bayesian_should_filter, probability, reasons = learner.should_filter(article, threshold=0.7)
                    if bayesian_should_filter:
                        should_filter = True
                        reason_str = '; '.join(reasons[:3]) if reasons else 'High similarity to previously rejected articles'
                        reason = f'Bayesian filter: {reason_str}'
                        print(f'BAYESIAN filtering article {article_id}: {reason}')
                except Exception as e:
                    logger.warning(f'Error in Bayesian filtering for article {article_id}: {e}')

            # Auto-filter if needed
            if should_filter:
                cursor.execute('''
                    INSERT OR REPLACE INTO article_management
                    (article_id, enabled, is_auto_filtered, auto_reject_reason, zip_code)
                    VALUES (?, 0, 1, ?, ?)
                ''', (article_id, reason, '02720'))
                filtered_count += 1

            processed_count += 1

            # Progress update every 50 articles
            if processed_count % 50 == 0:
                elapsed = time.time() - start_time
                rate = processed_count / elapsed if elapsed > 0 else 0
                remaining = total_articles - processed_count
                eta = remaining / rate if rate > 0 else 0
                print(f'Progress: {processed_count}/{total_articles} ({processed_count/total_articles*100:.1f}%) - Filtered: {filtered_count} - ETA: {eta:.0f}s')

        conn.commit()
        conn.close()

        elapsed_time = time.time() - start_time
        kept_count = processed_count - filtered_count

        print(f'\nCOMPLETED!')
        print(f'Total time: {elapsed_time:.1f} seconds')
        print(f'Articles processed: {processed_count}')
        print(f'Articles auto-filtered: {filtered_count}')
        print(f'Articles kept: {kept_count}')
        if processed_count > 0:
            print(f'Filter rate: {filtered_count/processed_count*100:.1f}%')

    except Exception as e:
        import traceback
        print(f'ERROR: {e}')
        print('Traceback:')
        traceback.print_exc()

if __name__ == '__main__':
    main()
