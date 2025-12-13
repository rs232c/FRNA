#!/usr/bin/env python3
"""
Clean up incorrect/stale rejection reasons in the database
"""

import sqlite3
from config import DATABASE_CONFIG

def clean_rejection_reasons():
    """Clean up incorrect rejection reasons"""

    db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check current rejection reasons
        cursor.execute('SELECT DISTINCT auto_reject_reason, COUNT(*) as count FROM article_management WHERE auto_reject_reason IS NOT NULL GROUP BY auto_reject_reason ORDER BY count DESC')
        reasons = cursor.fetchall()

        print('Current rejection reasons:')
        for reason, count in reasons:
            print(f'  {count:4d}: {reason}')

        # Remove incorrect "national_politics_no_local_tie" reasons
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE auto_reject_reason LIKE ?', ('%national_politics_no_local_tie%',))
        national_politics_count = cursor.fetchone()[0]

        if national_politics_count > 0:
            print(f'\nRemoving {national_politics_count} incorrect "national_politics_no_local_tie" rejections...')

            # For articles with this incorrect reason, check if they should actually be enabled
            cursor.execute('''
                SELECT am.article_id, a.relevance_score, a.source, a.title
                FROM article_management am
                JOIN articles a ON am.article_id = a.id
                WHERE am.auto_reject_reason LIKE '%national_politics_no_local_tie%'
                AND am.enabled = 0
                ORDER BY a.relevance_score DESC
            ''')

            potentially_valid_articles = cursor.fetchall()

            # Clear the incorrect rejection reasons
            cursor.execute('UPDATE article_management SET auto_reject_reason = NULL WHERE auto_reject_reason LIKE ?', ('%national_politics_no_local_tie%',))

            print(f'Cleared incorrect rejection reasons for {len(potentially_valid_articles)} articles')

            # Show some examples of what was incorrectly rejected
            print('\nExamples of incorrectly rejected articles (now cleared):')
            for article_id, score, source, title in potentially_valid_articles[:5]:
                print(f'  {score:.1f}: {title[:50]}... ({source})')

        # Clean up other stale reasons that don't match current logic
        stale_patterns = [
            'national_politics_no_local_tie',
            'relevance score below threshold',  # Old format
            'Relevance score below threshold (<30)',  # Old format
        ]

        for pattern in stale_patterns:
            cursor.execute('UPDATE article_management SET auto_reject_reason = NULL WHERE auto_reject_reason LIKE ?', (f'%{pattern}%',))

        conn.commit()

        # Final count
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE auto_reject_reason IS NOT NULL AND auto_reject_reason != ""')
        remaining_reasons = cursor.fetchone()[0]

        print(f'\nCleanup complete. {remaining_reasons} valid rejection reasons remain.')

        conn.close()

    except Exception as e:
        print(f'Error cleaning rejection reasons: {e}')

if __name__ == "__main__":
    clean_rejection_reasons()