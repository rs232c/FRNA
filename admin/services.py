"""
Admin services - business logic for admin operations
"""
import sqlite3
import json
import os
import logging
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import List, Dict, Optional, Tuple

from config import DATABASE_CONFIG, NEWS_SOURCES, WEBSITE_CONFIG
from utils.bayesian_relevance import BayesianRelevanceLearner

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    except ImportError:
        raise ImportError("bcrypt not installed. Install with: pip install bcrypt")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash"""
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except ImportError:
        # Fallback to plain text comparison if bcrypt not available
        return password == hashed
    except Exception:
        return False


def validate_zip_code(zip_code: str) -> bool:
    """Validate zip code format"""
    if not zip_code:
        return False
    return zip_code.isdigit() and len(zip_code) == 5


def validate_article_id(article_id) -> bool:
    """Validate article ID"""
    try:
        aid = int(article_id)
        return 0 < aid <= 2**31 - 1
    except (ValueError, TypeError):
        return False


def safe_path(base_path: Path, user_path: str) -> Path:
    """Safely join paths to prevent directory traversal"""
    try:
        result = (base_path / user_path).resolve()
        if base_path in result.parents or result == base_path:
            return result
        else:
            raise ValueError("Path traversal detected")
    except Exception as e:
        logger.error(f"Path validation error: {e}")
        raise ValueError("Invalid path")


@contextmanager
def get_db():
    """Database connection context manager"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_legacy():
    """Legacy database connection (kept for compatibility)"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    try:
        yield conn
    finally:
        conn.close()


def ensure_single_management_entry(cursor, article_id):
    """Ensure only one management entry exists per article"""
    # Remove any existing entries for this article
    cursor.execute('DELETE FROM article_management WHERE article_id = ?', (article_id,))

    # Insert new entry with default values
    cursor.execute('''
        INSERT INTO article_management (article_id, is_rejected, is_featured, user_notes, created_at, updated_at)
        VALUES (?, 0, 0, '', ?, ?)
    ''', (article_id, datetime.now(), datetime.now()))


def init_admin_db():
    """Initialize admin database tables"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Create admin_settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create article_management table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS article_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER UNIQUE NOT NULL,
                is_rejected BOOLEAN DEFAULT 0,
                is_featured BOOLEAN DEFAULT 0,
                user_notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
            )
        ''')

        # Create admin_users table for future multi-user support
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'admin',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')

        # Create default admin user if it doesn't exist
        admin_username = os.getenv('ADMIN_USERNAME')
        admin_password = os.getenv('ADMIN_PASSWORD')

        if admin_username and admin_password:
            cursor.execute('SELECT id FROM admin_users WHERE username = ?', (admin_username,))
            if not cursor.fetchone():
                password_hash = hash_password(admin_password)
                cursor.execute('''
                    INSERT INTO admin_users (username, password_hash, role)
                    VALUES (?, ?, 'admin')
                ''', (admin_username, password_hash))

        conn.commit()


# Article management services
def get_articles(zip_code=None, limit=50, offset=0, category=None, search=None):
    """Get articles with management data"""
    with get_db() as conn:
        cursor = conn.cursor()

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
            WHERE 1=1
        '''
        params = []

        if zip_code:
            query += ' AND a.zip_code = ?'
            params.append(zip_code)

        if category and category != 'all':
            query += ' AND a.category = ?'
            params.append(category)

        if search:
            query += ' AND (a.title LIKE ? OR a.summary LIKE ? OR a.content LIKE ?)'
            search_param = f'%{search}%'
            params.extend([search_param, search_param, search_param])

        query += ' ORDER BY a.published DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])

        cursor.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        articles = [dict(zip(columns, row)) for row in cursor.fetchall()]

        # Get total count for pagination
        count_query = '''
            SELECT COUNT(*) FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id
            WHERE 1=1
        '''
        count_params = []

        if zip_code:
            count_query += ' AND a.zip_code = ?'
            count_params.append(zip_code)

        if category and category != 'all':
            count_query += ' AND a.category = ?'
            count_params.append(category)

        if search:
            count_query += ' AND (a.title LIKE ? OR a.summary LIKE ? OR a.content LIKE ?)'
            search_param = f'%{search}%'
            count_params.extend([search_param, search_param, search_param])

        cursor.execute(count_query, count_params)
        total_count = cursor.fetchone()[0]

        return articles, total_count


def get_rejected_articles(zip_code=None):
    """Get rejected articles"""
    with get_db() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT a.*, am.user_notes, am.created_at as rejected_at,
                   CASE WHEN am.is_rejected = 1 THEN 'manual' ELSE 'auto' END as rejection_type
            FROM articles a
            JOIN article_management am ON a.id = am.article_id
            WHERE am.is_rejected = 1 OR am.is_auto_filtered = 1
        '''
        params = []

        if zip_code:
            query += ' AND a.zip_code = ?'
            params.append(zip_code)

        query += ' ORDER BY am.created_at DESC'

        cursor.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def toggle_article(article_id, action, zip_code=None):
    """Toggle article status (reject/restore/feature/unfeature)"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Ensure management entry exists
        ensure_single_management_entry(cursor, article_id)

        if action == 'reject':
            cursor.execute('UPDATE article_management SET is_rejected = 1, updated_at = ? WHERE article_id = ?',
                         (datetime.now(), article_id))
        elif action == 'restore':
            cursor.execute('UPDATE article_management SET is_rejected = 0, is_auto_filtered = 0, updated_at = ? WHERE article_id = ?',
                         (datetime.now(), article_id))
        elif action == 'feature':
            cursor.execute('UPDATE article_management SET is_featured = 1, updated_at = ? WHERE article_id = ?',
                         (datetime.now(), article_id))
        elif action == 'unfeature':
            cursor.execute('UPDATE article_management SET is_featured = 0, updated_at = ? WHERE article_id = ?',
                         (datetime.now(), article_id))

        conn.commit()

        # Get updated article data
        cursor.execute('''
            SELECT a.*, COALESCE(am.is_rejected, 0) as is_rejected, COALESCE(am.is_featured, 0) as is_featured
            FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id
            WHERE a.id = ?
        ''', (article_id,))

        columns = [desc[0] for desc in cursor.description]
        article = dict(zip(columns, cursor.fetchone()))

        return article


def get_sources():
    """Get news sources configuration"""
    return NEWS_SOURCES


def get_stats(zip_code=None):
    """Get admin statistics"""
    with get_db() as conn:
        cursor = conn.cursor()

        stats = {}

        # Total articles
        if zip_code:
            cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code = ?', (zip_code,))
        else:
            cursor.execute('SELECT COUNT(*) FROM articles')
        stats['total_articles'] = cursor.fetchone()[0]
        print(f"[DEBUG] Stats for zip_code={zip_code}: total_articles={stats['total_articles']}")

        # Active articles (not rejected) - avoid duplicates by using DISTINCT or proper grouping
        if zip_code:
            cursor.execute('''
                SELECT COUNT(DISTINCT a.id) FROM articles a
                LEFT JOIN article_management am ON a.id = am.article_id AND am.zip_code = a.zip_code
                WHERE a.zip_code = ? AND (am.is_rejected IS NULL OR am.is_rejected = 0)
            ''', (zip_code,))
        else:
            cursor.execute('''
                SELECT COUNT(DISTINCT a.id) FROM articles a
                LEFT JOIN article_management am ON a.id = am.article_id AND am.zip_code = a.zip_code
                WHERE am.is_rejected IS NULL OR am.is_rejected = 0
            ''')
        stats['active_articles'] = cursor.fetchone()[0]
        print(f"[DEBUG] active_articles={stats['active_articles']}")

        # Rejected articles (manually rejected only, not auto-filtered) - use DISTINCT to avoid duplicates
        if zip_code:
            cursor.execute('''
                SELECT COUNT(DISTINCT am.article_id) FROM article_management am
                JOIN articles a ON am.article_id = a.id
                WHERE am.is_rejected = 1 AND am.is_auto_filtered = 0 AND a.zip_code = ? AND am.zip_code = ?
            ''', (zip_code, zip_code))
        else:
            cursor.execute('''
                SELECT COUNT(DISTINCT am.article_id) FROM article_management am
                WHERE am.is_rejected = 1 AND am.is_auto_filtered = 0
            ''')
        stats['rejected_articles'] = cursor.fetchone()[0]
        print(f"[DEBUG] rejected_articles={stats['rejected_articles']}")

        # Top stories (is_top_story = 1) - use DISTINCT to avoid duplicates
        if zip_code:
            cursor.execute('''
                SELECT COUNT(DISTINCT am.article_id) FROM article_management am
                JOIN articles a ON am.article_id = a.id
                WHERE am.is_top_story = 1 AND a.zip_code = ? AND am.zip_code = ?
            ''', (zip_code, zip_code))
        else:
            cursor.execute('SELECT COUNT(DISTINCT am.article_id) FROM article_management WHERE is_top_story = 1')
        stats['top_stories'] = cursor.fetchone()[0]
        print(f"[DEBUG] top_stories={stats['top_stories']}")

        # Featured articles (is_featured = 1)
        if zip_code:
            cursor.execute('''
                SELECT COUNT(DISTINCT am.article_id) FROM article_management am
                JOIN articles a ON am.article_id = a.id
                WHERE am.is_featured = 1 AND a.zip_code = ? AND am.zip_code = ?
            ''', (zip_code, zip_code))
        else:
            cursor.execute('SELECT COUNT(DISTINCT am.article_id) FROM article_management WHERE is_featured = 1')
        stats['featured_articles'] = cursor.fetchone()[0]
        print(f"[DEBUG] featured_articles={stats['featured_articles']}")

        # Articles last 7 days
        if zip_code:
            cursor.execute('SELECT COUNT(*) FROM articles WHERE published >= date(\'now\', \'-7 days\') AND zip_code = ?', (zip_code,))
        else:
            cursor.execute('SELECT COUNT(*) FROM articles WHERE published >= date(\'now\', \'-7 days\')')
        stats['articles_last_7_days'] = cursor.fetchone()[0]
        print(f"[DEBUG] articles_last_7_days={stats['articles_last_7_days']}")

        # Articles by source
        if zip_code:
            cursor.execute('''
                SELECT source, COUNT(*) as count
                FROM articles
                WHERE zip_code = ?
                GROUP BY source
                ORDER BY count DESC
                LIMIT 10
            ''', (zip_code,))
        else:
            cursor.execute('''
                SELECT source, COUNT(*) as count
                FROM articles
                GROUP BY source
                ORDER BY count DESC
                LIMIT 10
            ''')
        stats['articles_by_source'] = [{'source': row[0], 'count': row[1]} for row in cursor.fetchall()]

        # Articles by category
        if zip_code:
            cursor.execute('''
                SELECT category, COUNT(*) as count
                FROM articles
                WHERE zip_code = ? AND category IS NOT NULL AND category != ''
                GROUP BY category
                ORDER BY count DESC
                LIMIT 10
            ''', (zip_code,))
        else:
            cursor.execute('''
                SELECT category, COUNT(*) as count
                FROM articles
                WHERE category IS NOT NULL AND category != ''
                GROUP BY category
                ORDER BY count DESC
                LIMIT 10
            ''')
        stats['articles_by_category'] = [{'category': row[0], 'count': row[1]} for row in cursor.fetchall()]

        # Source fetch stats (if available)
        try:
            if zip_code:
                cursor.execute('''
                    SELECT source, COUNT(*) as count, MAX(published) as last_fetch
                    FROM articles
                    WHERE zip_code = ?
                    GROUP BY source
                    ORDER BY last_fetch DESC
                ''', (zip_code,))
            else:
                cursor.execute('''
                    SELECT source, COUNT(*) as count, MAX(published) as last_fetch
                    FROM articles
                    GROUP BY source
                    ORDER BY last_fetch DESC
                ''')
            source_stats = cursor.fetchall()
            stats['source_fetch_stats'] = [
                {'source': row[0], 'count': row[1], 'last_fetch': row[2][:16] if row[2] else 'Never'}
                for row in source_stats
            ]
        except:
            stats['source_fetch_stats'] = []

        return stats


def get_database_stats():
    """Get comprehensive database statistics for admin dashboard"""
    import os
    from datetime import datetime, timedelta

    with get_db() as conn:
        cursor = conn.cursor()

        stats = {
            'database_info': {},
            'article_stats': {},
            'source_stats': {},
            'category_stats': {},
            'management_stats': {},
            'ai_ml_stats': {},
            'performance_stats': {},
            'health_stats': {}
        }

        # Database info
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        stats['database_info'] = {
            'path': db_path,
            'size_mb': round(db_size / (1024 * 1024), 2),
            'size_bytes': db_size
        }

        # Get table counts
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        stats['database_info']['tables'] = len(tables)

        # Article stats
        cursor.execute('SELECT COUNT(*) FROM articles')
        total_articles = cursor.fetchone()[0]

        # Date ranges
        cursor.execute('SELECT MIN(created_at), MAX(created_at), MIN(published), MAX(published) FROM articles')
        min_created, max_created, min_published, max_published = cursor.fetchone()

        # Recent articles
        seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
        cursor.execute('SELECT COUNT(*) FROM articles WHERE created_at >= ?', (seven_days_ago,))
        recent_count = cursor.fetchone()[0]

        # Source breakdown (top 10)
        cursor.execute('SELECT source, COUNT(*) FROM articles GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10')
        sources = cursor.fetchall()

        # Category breakdown
        cursor.execute('SELECT category, COUNT(*) FROM articles WHERE category IS NOT NULL GROUP BY category ORDER BY COUNT(*) DESC')
        categories = cursor.fetchall()

        # Zip code breakdown
        cursor.execute('SELECT zip_code, COUNT(*) FROM articles WHERE zip_code IS NOT NULL GROUP BY zip_code ORDER BY COUNT(*) DESC')
        zip_codes = cursor.fetchall()

        # Relevance scores
        cursor.execute('SELECT AVG(relevance_score), MIN(relevance_score), MAX(relevance_score) FROM articles WHERE relevance_score IS NOT NULL')
        relevance_result = cursor.fetchone()
        if relevance_result and relevance_result[0] is not None:
            avg_score, min_score, max_score = relevance_result
            relevance_stats = {
                'avg': round(avg_score, 1),
                'min': round(min_score, 1),
                'max': round(max_score, 1)
            }
        else:
            relevance_stats = {'avg': 0, 'min': 0, 'max': 0}

        # Articles with images
        cursor.execute('SELECT COUNT(*) FROM articles WHERE image_url IS NOT NULL AND image_url != ""')
        with_images = cursor.fetchone()[0]

        stats['article_stats'] = {
            'total': total_articles,
            'with_images': with_images,
            'image_percentage': round((with_images/total_articles)*100, 1) if total_articles > 0 else 0,
            'recent_7_days': recent_count,
            'date_range': {
                'created_start': min_created,
                'created_end': max_created,
                'published_start': min_published,
                'published_end': max_published
            },
            'relevance_scores': relevance_stats
        }

        stats['source_stats'] = {
            'total_sources': len(sources),
            'top_sources': [{'source': row[0], 'count': row[1], 'percentage': round((row[1]/total_articles)*100, 1)} for row in sources]
        }

        stats['category_stats'] = {
            'total_categories': len(categories),
            'breakdown': [{'category': row[0], 'count': row[1], 'percentage': round((row[1]/total_articles)*100, 1)} for row in categories]
        }

        stats['zip_stats'] = {
            'total_zips': len(zip_codes),
            'breakdown': [{'zip': row[0], 'count': row[1], 'percentage': round((row[1]/total_articles)*100, 1)} for row in zip_codes]
        }

        # Article management stats
        cursor.execute('SELECT COUNT(*) FROM article_management')
        total_mgmt = cursor.fetchone()[0]

        cursor.execute('SELECT enabled, COUNT(*) FROM article_management GROUP BY enabled')
        enabled_stats = cursor.fetchall()
        enabled_count = sum(count for enabled, count in enabled_stats if enabled)
        disabled_count = sum(count for enabled, count in enabled_stats if not enabled)

        stats['management_stats'] = {
            'total_entries': total_mgmt,
            'enabled': enabled_count,
            'disabled': disabled_count,
            'enabled_percentage': round((enabled_count/total_mgmt)*100, 1) if total_mgmt > 0 else 0
        }

        # AI/ML stats
        cursor.execute('SELECT COUNT(*) FROM relevance_config')
        relevance_rules = cursor.fetchone()[0]

        cursor.execute('SELECT category, COUNT(*) FROM relevance_config GROUP BY category ORDER BY COUNT(*) DESC')
        rule_categories = cursor.fetchall()

        cursor.execute('SELECT COUNT(*) FROM training_data')
        training_count = cursor.fetchone()[0]

        if training_count > 0:
            cursor.execute('SELECT good_fit, COUNT(*) FROM training_data GROUP BY good_fit')
            fit_stats = cursor.fetchall()
            good_fit = sum(count for fit, count in fit_stats if fit)
            bad_fit = sum(count for fit, count in fit_stats if not fit)
        else:
            good_fit = bad_fit = 0

        stats['ai_ml_stats'] = {
            'relevance_rules': relevance_rules,
            'rule_categories': [{'category': row[0], 'count': row[1]} for row in rule_categories],
            'training_samples': training_count,
            'good_fit_samples': good_fit,
            'bad_fit_samples': bad_fit
        }

        # Posted articles stats
        cursor.execute('SELECT COUNT(*) FROM posted_articles')
        total_posted = cursor.fetchone()[0]

        cursor.execute('SELECT platform, COUNT(*) FROM posted_articles GROUP BY platform ORDER BY COUNT(*) DESC')
        platforms = cursor.fetchall()

        stats['performance_stats'] = {
            'posted_articles': total_posted,
            'platforms': [{'platform': row[0], 'count': row[1]} for row in platforms]
        }

        # Health stats
        cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code IS NULL')
        null_zip = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM articles WHERE category IS NULL')
        null_category = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM articles WHERE relevance_score IS NULL')
        null_relevance = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(*) FROM (
                SELECT url, COUNT(*) as cnt FROM articles
                WHERE url IS NOT NULL AND url != '' AND url != '#'
                GROUP BY url HAVING cnt > 1
            )
        ''')
        duplicate_urls = cursor.fetchone()[0]

        stats['health_stats'] = {
            'articles_without_zip': null_zip,
            'articles_without_category': null_category,
            'articles_without_relevance': null_relevance,
            'duplicate_urls': duplicate_urls,
            'data_completeness': round(((total_articles - null_zip - null_category - null_relevance) / total_articles) * 100, 1) if total_articles > 0 else 0
        }

        return stats


def get_settings():
    """Get admin settings"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT key, value FROM admin_settings')
        settings = {row[0]: row[1] for row in cursor.fetchall()}
        return settings




def trash_article(article_id, zip_code=None):
    """Mark article as trashed"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO article_management (article_id, is_rejected, updated_at)
            VALUES (?, 1, ?)
        ''', (article_id, datetime.now().isoformat()))
        conn.commit()


def restore_article(article_id, zip_code=None):
    """Restore article (either trashed or auto-filtered)"""
    with get_db() as conn:
        cursor = conn.cursor()
        # Clear both is_rejected and is_auto_filtered when restoring
        cursor.execute('''
            INSERT OR REPLACE INTO article_management (article_id, is_rejected, is_auto_filtered, updated_at)
            VALUES (?, 0, 0, ?)
        ''', (article_id, datetime.now().isoformat()))
        conn.commit()


def toggle_top_story(article_id, is_top_story):
    """Toggle top story status"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE articles SET is_top_story = ? WHERE id = ?', (1 if is_top_story else 0, article_id))
        conn.commit()


def toggle_top_article(article_id, is_top):
    """Toggle top article status"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE articles SET is_top = ? WHERE id = ?', (1 if is_top else 0, article_id))
        conn.commit()


def toggle_alert(article_id, is_alert):
    """Toggle alert status"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE articles SET is_alert = ? WHERE id = ?', (1 if is_alert else 0, article_id))
        conn.commit()


def toggle_good_fit(article_id, is_good_fit):
    """Toggle good fit status"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO article_management (article_id, is_good_fit, updated_at)
            VALUES (?, ?, ?)
        ''', (article_id, 1 if is_good_fit else 0, datetime.now().isoformat()))
        conn.commit()


def set_on_target(article_id, is_on_target):
    """Set on-target status for article"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO article_management (article_id, is_on_target, updated_at)
            VALUES (?, ?, ?)
        ''', (article_id, 1 if is_on_target else 0, datetime.now().isoformat()))
        conn.commit()


def train_relevance(article_id, zip_code, click_type):
    """Train relevance model from admin feedback"""
    try:
        # Get article data
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Article {article_id} not found")

            # Convert to dict
            columns = [desc[0] for desc in cursor.description]
            article = dict(zip(columns, row))

        # Train the model
        trainer = BayesianRelevanceLearner()
        good_fit = 1 if click_type == 'thumbs_up' else 0
        trainer.train_from_click(article, zip_code, click_type, good_fit)

        return True, "Training successful"

    except Exception as e:
        logger.error(f"Error training relevance model: {e}")
        return False, str(e)