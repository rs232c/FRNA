"""
Admin utility functions for database operations
"""
import sqlite3
import logging
from contextlib import contextmanager
from config import DATABASE_CONFIG
from flask import session

logger = logging.getLogger(__name__)


@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_db_legacy():
    """Legacy database connection (use get_db context manager instead)"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    return conn


def validate_zip_code(zip_code: str) -> bool:
    """Validate zip code format"""
    if not zip_code:
        return False
    return zip_code.isdigit() and len(zip_code) == 5


def trash_article(article_id: int, zip_code: str) -> dict:
    """Move article to trash (reject it)"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure is_rejected column exists
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass
    
    # Get article data for Bayesian training
    cursor.execute('SELECT title, content, summary, source FROM articles WHERE id = ?', (article_id,))
    article_row = cursor.fetchone()
    article_data = None
    if article_row:
        article_data = {
            'title': article_row[0] or '',
            'content': article_row[1] or article_row[2] or '',
            'summary': article_row[2] or '',
            'source': article_row[3] or ''
        }
    
    # Get current display_order
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Check if entry exists
    cursor.execute('SELECT id FROM article_management WHERE article_id = ? AND zip_code = ?', (article_id, zip_code))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute('''
            UPDATE article_management 
            SET enabled = ?, display_order = ?, is_rejected = ?
            WHERE article_id = ? AND zip_code = ?
        ''', (0, display_order, 1, article_id, zip_code))
    else:
        cursor.execute('''
            INSERT INTO article_management (article_id, enabled, display_order, is_rejected, zip_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (article_id, 0, display_order, 1, zip_code))
    
    conn.commit()
    conn.close()
    
    # Train Bayesian model
    if article_data:
        try:
            from utils.bayesian_learner import BayesianLearner
            learner = BayesianLearner()
            learner.train_from_rejection(article_data)
            logger.info(f"Bayesian model trained from rejected article: '{article_data.get('title', '')[:50]}...'")
        except Exception as e:
            logger.warning(f"Could not train Bayesian model: {e}")
    
    return {'success': True, 'message': 'Article moved to trash'}


def restore_article(article_id: int, zip_code: str, rejection_type: str = 'manual') -> dict:
    """Restore article from trash"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
    except:
        pass
    
    if rejection_type == 'auto':
        cursor.execute('''
            UPDATE article_management 
            SET is_auto_rejected = 0, is_rejected = 0, enabled = 1, auto_reject_reason = NULL
            WHERE article_id = ? AND zip_code = ?
        ''', (article_id, zip_code))
    else:
        cursor.execute('''
            UPDATE article_management 
            SET is_rejected = 0, enabled = 1
            WHERE article_id = ? AND zip_code = ?
        ''', (article_id, zip_code))
    
    # If no rows were updated, create a new entry
    if cursor.rowcount == 0:
        cursor.execute('''
            INSERT INTO article_management (article_id, zip_code, enabled, is_rejected, is_auto_rejected, auto_reject_reason)
            VALUES (?, ?, 1, 0, 0, NULL)
        ''', (article_id, zip_code))
    
    conn.commit()
    conn.close()
    
    return {'success': True, 'message': 'Article restored'}


def toggle_top_story(article_id: int, zip_code: str, is_top_story: bool) -> dict:
    """Toggle top story status for an article"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Get current display_order
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_top_story INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass
    
    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, is_top_article, is_top_story, zip_code)
        VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ? AND zip_code = ?), 1), 
                COALESCE((SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ?), ?),
                COALESCE((SELECT is_top_article FROM article_management WHERE article_id = ? AND zip_code = ?), 0), ?, ?)
    ''', (article_id, article_id, zip_code, article_id, zip_code, article_id, article_id, zip_code, 1 if is_top_story else 0, zip_code))
    
    conn.commit()
    conn.close()
    
    return {'success': True}


def toggle_good_fit(article_id: int, zip_code: str, is_good_fit: bool) -> dict:
    """Toggle good fit status for an article"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure is_good_fit column exists
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_good_fit INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass
    
    # Get current display_order
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Check if entry exists
    cursor.execute('SELECT id FROM article_management WHERE article_id = ? AND zip_code = ?', (article_id, zip_code))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute('''
            UPDATE article_management 
            SET is_good_fit = ?, display_order = ?
            WHERE article_id = ? AND zip_code = ?
        ''', (1 if is_good_fit else 0, display_order, article_id, zip_code))
    else:
        cursor.execute('''
            INSERT INTO article_management (article_id, enabled, display_order, is_good_fit, zip_code)
            VALUES (?, 1, ?, ?, ?)
        ''', (article_id, display_order, 1 if is_good_fit else 0, zip_code))
    
    conn.commit()
    
    # Recalculate relevance scores when good fit is enabled
    if is_good_fit:
        try:
            from aggregator import NewsAggregator
            from utils.relevance_calculator import calculate_relevance_score
            
            # Get article data
            cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
            article_row = cursor.fetchone()
            
            if article_row:
                article = {key: article_row[key] for key in article_row.keys()}
                
                # Recalculate relevance score
                relevance_score = calculate_relevance_score(article, zip_code=zip_code)
                
                # Calculate local focus score (0-10)
                local_focus_score = calculate_local_focus_score(article, zip_code=zip_code)
                
                # Update article with new scores
                cursor.execute('''
                    UPDATE articles 
                    SET relevance_score = ?, local_score = ?
                    WHERE id = ?
                ''', (relevance_score, local_focus_score, article_id))
                
                conn.commit()
                logger.info(f"Recalculated relevance for article {article_id}: relevance={relevance_score:.1f}, local_focus={local_focus_score:.1f}/10")
                
                # Train the category classifier if article has a primary_category
                try:
                    primary_category = article.get('primary_category')
                    if primary_category:
                        from utils.category_classifier import CategoryClassifier
                        classifier = CategoryClassifier(zip_code)
                        article_for_training = {
                            'title': article.get('title', ''),
                            'content': article.get('content', ''),
                            'summary': article.get('summary', ''),
                            'source': article.get('source', '')
                        }
                        classifier.train_from_feedback(article_for_training, primary_category, is_positive=True)
                        logger.info(f"Trained classifier from good fit: article {article_id}, category {primary_category}")
                except Exception as e:
                    logger.warning(f"Could not train classifier from good fit: {e}")
                    # Don't fail if training fails
        except Exception as e:
            logger.warning(f"Could not recalculate relevance for article {article_id}: {e}")
            # Don't fail the good fit toggle if relevance calc fails
    
    conn.close()
    
    logger.info(f"Article {article_id} good fit set to {is_good_fit} for zip {zip_code}")
    return {'success': True, 'message': f'Good fit {"enabled" if is_good_fit else "disabled"}'}


def map_category_to_classifier(category_slug: str) -> str:
    """Map new category slugs to classifier category names"""
    mapping = {
        "local-news": "News",
        "crime": "Crime",
        "sports": "Sports",
        "events": "Entertainment",  # Classifier uses "Entertainment" not "Events"
        "weather": "News",
        "business": "Business",
        "schools": "Schools",
        "food": "News",
        "obituaries": "News"
    }
    # Also handle old category names
    old_to_new = {
        "news": "News",
        "entertainment": "Entertainment",
        "sports": "Sports",
        "local": "News",
        "custom": "News",
        "media": "Entertainment"
    }
    # First check if it's already a classifier category name
    if category_slug in ["News", "Crime", "Sports", "Entertainment", "Events", "Politics", "Schools", "Business", "Health", "Traffic", "Fire"]:
        return category_slug
    # Check new category slugs
    if category_slug in mapping:
        return mapping[category_slug]
    # Check old category names
    if category_slug in old_to_new:
        return old_to_new[category_slug]
    # Default fallback
    return "News"


def map_classifier_to_category(classifier_category: str) -> str:
    """Map classifier category names back to new category slugs"""
    mapping = {
        "News": "local-news",
        "Crime": "crime",
        "Sports": "sports",
        "Entertainment": "events",
        "Events": "events",
        "Business": "business",
        "Schools": "schools",
        "Politics": "local-news",
        "Health": "local-news",
        "Traffic": "local-news",
        "Fire": "local-news"
    }
    return mapping.get(classifier_category, "local-news")


def calculate_local_focus_score(article: dict, zip_code: str = None) -> float:
    """Calculate local focus score (0-10) based on Fall River mentions
    Weighted by location: byline > title > content
    Excludes source names like "Fall River Reporter"
    
    Args:
        article: Article dict with title, content, source, byline, author, etc.
        zip_code: Optional zip code for zip-specific config
    
    Returns:
        Local focus score between 0.0 and 10.0
    """
    try:
        content = article.get("content", article.get("summary", "")).lower()
        title = article.get("title", "").lower()
        source = article.get("source", "").lower()
        byline = article.get("byline", article.get("author", "")).lower()
        
        # Fall River variations to check
        fall_river_variations = [
            "fall river",
            "fallriver",
            "fall-river"
        ]
        
        score = 0.0
        max_score = 10.0
        
        # Check byline (highest weight - 4 points per mention, max 4 points)
        if byline:
            byline_mentions = sum(1 for variant in fall_river_variations if variant in byline)
            if byline_mentions > 0:
                score += min(4.0, byline_mentions * 4.0)
        
        # Check title (medium weight - 2 points per mention, max 4 points)
        # But exclude if it's just the source name
        if title:
            # Check if title contains source name patterns (like "Fall River Reporter")
            source_name_patterns = ["fall river reporter", "fall river news", "herald news"]
            is_source_name = any(pattern in title for pattern in source_name_patterns)
            
            if not is_source_name:
                title_mentions = sum(1 for variant in fall_river_variations if variant in title)
                if title_mentions > 0:
                    score += min(4.0, title_mentions * 2.0)
        
        # Check content (lower weight - 0.2 points per mention, max 2 points)
        if content:
            content_mentions = sum(1 for variant in fall_river_variations if variant in content)
            if content_mentions > 0:
                # Count unique mentions (approximate by checking first 10)
                unique_mentions = min(10, content_mentions)
                score += min(2.0, unique_mentions * 0.2)
        
        return min(max_score, score)
    except Exception as e:
        logger.warning(f"Error calculating local focus score: {e}")
        return 0.0


def get_articles(zip_code: str, show_trash: bool = False) -> list:
    """Get articles for a zip code"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Build WHERE clause
    where_clauses = ['a.zip_code = ?']
    where_params = [zip_code]
    
    # Rejection filter
    where_clauses.append('((am.is_rejected IS NULL AND ? = 0) OR (am.is_rejected = ?))')
    where_params.extend([1 if show_trash else 0, 1 if show_trash else 0])
    
    where_sql = ' AND '.join(where_clauses)
    query_params = ([zip_code] * 2) + where_params
    
    cursor.execute(f'''
        SELECT a.*, 
               COALESCE(am.enabled, 1) as enabled,
               COALESCE(am.display_order, a.id) as display_order,
               COALESCE(am.is_rejected, 0) as is_rejected,
               COALESCE(am.is_top_story, 0) as is_top_story,
               COALESCE(am.is_stellar, 0) as is_stellar,
               COALESCE(am.is_good_fit, 0) as is_good_fit
        FROM articles a
        LEFT JOIN (
            SELECT article_id, enabled, display_order, is_rejected, is_top_story, is_stellar, is_good_fit
            FROM article_management
            WHERE zip_code = ?
            AND ROWID IN (
                SELECT MAX(ROWID) 
                FROM article_management 
                WHERE zip_code = ?
                GROUP BY article_id
            )
        ) am ON a.id = am.article_id
        WHERE {where_sql}
        ORDER BY 
            CASE WHEN a.published IS NOT NULL AND a.published != '' THEN a.published ELSE '1970-01-01' END DESC,
            COALESCE(am.display_order, a.id) ASC
    ''', query_params)
    
    articles = [dict(row) for row in cursor.fetchall()]
    
    # Remove duplicates
    seen_ids = set()
    unique_articles = []
    for article in articles:
        article_id = article.get('id')
        if article_id and article_id not in seen_ids:
            seen_ids.add(article_id)
            unique_articles.append(article)
    
    # Calculate relevance scores for articles that don't have them
    from utils.relevance_calculator import calculate_relevance_score
    for article in unique_articles:
        if article.get('relevance_score') is None:
            article['relevance_score'] = calculate_relevance_score(article)
    
    conn.close()
    return unique_articles


def get_rejected_articles(zip_code: str) -> list:
    """Get rejected articles for trash tab"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure columns exist
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
        cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        conn.commit()
    except:
        pass
    
    cursor.execute('''
        SELECT a.*, 
               a.relevance_score,
               COALESCE(am.is_rejected, 0) as is_rejected,
               COALESCE(am.is_auto_rejected, 0) as is_auto_rejected,
               am.auto_reject_reason,
               CASE 
                   WHEN am.is_auto_rejected = 1 THEN 'auto'
                   WHEN am.is_rejected = 1 THEN 'manual'
                   ELSE 'unknown'
               END as rejection_type,
               am.ROWID as rejection_rowid
        FROM articles a
        INNER JOIN article_management am ON a.id = am.article_id
        WHERE am.zip_code = ?
        AND am.is_rejected = 1
        AND am.ROWID = (
            SELECT MAX(ROWID)
            FROM article_management
            WHERE article_id = a.id
            AND zip_code = ?
            AND is_rejected = 1
        )
        ORDER BY am.ROWID DESC
        LIMIT 100
    ''', (zip_code, zip_code))
    
    articles = []
    for row in cursor.fetchall():
        article = {key: row[key] for key in row.keys()}
        articles.append(article)
    
    conn.close()
    return articles


def get_sources(zip_code: str) -> dict:
    """Get sources configuration for a zip code"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    sources_config = {}
    
    if zip_code:
        # Get zip-specific source settings
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_%"', (zip_code,))
        source_settings = {}
        for row in cursor.fetchall():
            key = row['key']
            if key.startswith('source_'):
                parts = key.replace('source_', '').split('_', 1)
                if len(parts) == 2:
                    source_key = parts[0]
                    setting = parts[1]
                    if source_key not in source_settings:
                        source_settings[source_key] = {}
                    source_settings[source_key][setting] = row['value']
        
        # Get custom sources
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "custom_source_%"', (zip_code,))
        for row in cursor.fetchall():
            import json
            source_key = row['key'].replace('custom_source_', '')
            try:
                custom_data = json.loads(row['value'])
                custom_data['key'] = source_key
                sources_config[source_key] = custom_data
            except:
                pass
        
        # Get source overrides
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_override_%"', (zip_code,))
        for row in cursor.fetchall():
            import json
            source_key = row['key'].replace('source_override_', '')
            try:
                override_data = json.loads(row['value'])
                if source_key in sources_config:
                    sources_config[source_key].update(override_data)
                else:
                    from config import NEWS_SOURCES
                    if source_key in NEWS_SOURCES:
                        sources_config[source_key] = dict(NEWS_SOURCES[source_key])
                        sources_config[source_key].update(override_data)
                    else:
                        sources_config[source_key] = override_data
                    sources_config[source_key]['key'] = source_key
            except:
                pass
        
        # Apply settings
        for source_key in sources_config:
            if source_key in source_settings:
                if 'enabled' in source_settings[source_key]:
                    sources_config[source_key]['enabled'] = source_settings[source_key]['enabled'] == '1'
                if 'require_fall_river' in source_settings[source_key]:
                    sources_config[source_key]['require_fall_river'] = source_settings[source_key]['require_fall_river'] == '1'
    
    conn.close()
    return sources_config


def get_stats(zip_code: str) -> dict:
    """Get statistics for a zip code"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    stats = {}
    
    # Total articles
    if zip_code:
        cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code = ?', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM articles')
    stats['total_articles'] = cursor.fetchone()[0]
    
    # Active articles
    if zip_code:
        cursor.execute('''
            SELECT COUNT(DISTINCT a.id) FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id AND am.zip_code = ?
            WHERE (a.zip_code = ? OR a.zip_code IS NULL)
            AND COALESCE(am.is_rejected, 0) = 0
        ''', (zip_code, zip_code))
    else:
        cursor.execute('''
            SELECT COUNT(DISTINCT a.id) FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id
            WHERE COALESCE(am.is_rejected, 0) = 0
        ''')
    stats['active_articles'] = cursor.fetchone()[0]
    
    # Rejected articles
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE is_rejected = 1 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE is_rejected = 1')
    stats['rejected_articles'] = cursor.fetchone()[0]
    
    # Top stories
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE is_top_story = 1 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE is_top_story = 1')
    stats['top_stories'] = cursor.fetchone()[0]
    
    # Disabled articles
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE enabled = 0 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE enabled = 0')
    stats['disabled_articles'] = cursor.fetchone()[0]
    
    # Articles by source
    if zip_code:
        cursor.execute('''
            SELECT source, COUNT(*) as count 
            FROM articles 
            WHERE zip_code = ? OR zip_code IS NULL
            GROUP BY source 
            ORDER BY count DESC
        ''', (zip_code,))
    else:
        cursor.execute('''
            SELECT source, COUNT(*) as count 
            FROM articles 
            GROUP BY source 
            ORDER BY count DESC
        ''')
    stats['articles_by_source'] = [{'source': row[0], 'count': row[1]} for row in cursor.fetchall()]
    
    # Articles by category
    if zip_code:
        cursor.execute('''
            SELECT COALESCE(category, 'uncategorized') as cat, COUNT(*) as count 
            FROM articles 
            WHERE zip_code = ? OR zip_code IS NULL
            GROUP BY cat 
            ORDER BY count DESC
        ''', (zip_code,))
    else:
        cursor.execute('''
            SELECT COALESCE(category, 'uncategorized') as cat, COUNT(*) as count 
            FROM articles 
            GROUP BY cat 
            ORDER BY count DESC
        ''')
    stats['articles_by_category'] = [{'category': row[0], 'count': row[1]} for row in cursor.fetchall()]
    
    # Category keywords and counts
    # Get category keywords from website_generator
    category_keywords = {
        "local-news": ["news", "update", "report", "announcement", "city", "town", "community"],
        "crime": ["crime", "police", "arrest", "suspect", "investigation", "charges", "court", "trial", "criminal"],
        "sports": ["sport", "football", "basketball", "baseball", "hockey", "athlete", "game", "team", "player"],
        "events": ["event", "concert", "show", "festival", "entertainment", "performance", "celebration"],
        "weather": ["weather", "forecast", "temperature", "rain", "snow", "storm", "climate"],
        "business": ["business", "company", "development", "economic", "commerce", "retail", "store", "shop"],
        "schools": ["school", "student", "teacher", "education", "academic", "college", "university", "graduation"],
        "food": ["food", "restaurant", "dining", "cafe", "menu", "chef", "cuisine", "meal"],
        "obituaries": ["obituary", "death", "passed away", "memorial", "funeral", "died", "remembered"]
    }
    
    # Get category article counts and keyword counts
    stats['categories_detail'] = []
    for category_slug, keywords in category_keywords.items():
        # Get article count for this category using keyword matching
        category_name = category_slug.replace('-', ' ').title()
        
        # Build SQL query to count articles matching any keyword in this category
        keyword_conditions = []
        params = []
        for keyword in keywords:
            keyword_conditions.append("(LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(summary) LIKE ?)")
            keyword_pattern = f'%{keyword}%'
            params.extend([keyword_pattern, keyword_pattern, keyword_pattern])
        
        where_clause = " OR ".join(keyword_conditions)
        if zip_code:
            query = f'''
                SELECT COUNT(DISTINCT id) FROM articles 
                WHERE (zip_code = ? OR zip_code IS NULL)
                AND ({where_clause})
            '''
            params = [zip_code] + params
        else:
            query = f'''
                SELECT COUNT(DISTINCT id) FROM articles 
                WHERE {where_clause}
            '''
        
        cursor.execute(query, params)
        article_count = cursor.fetchone()[0]
        
        stats['categories_detail'].append({
            'category': category_name,
            'slug': category_slug,
            'article_count': article_count,
            'keyword_count': len(keywords),
            'keywords': keywords
        })
    
    # Recent articles (last 7 days)
    from datetime import datetime, timedelta
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM articles 
            WHERE ((published IS NOT NULL AND published > ?) 
               OR (published IS NULL AND created_at > ?))
            AND (zip_code = ? OR zip_code IS NULL)
        ''', (week_ago, week_ago, zip_code))
    else:
        cursor.execute('''
            SELECT COUNT(*) FROM articles 
            WHERE ((published IS NOT NULL AND published > ?) 
               OR (published IS NULL AND created_at > ?))
        ''', (week_ago, week_ago))
    stats['articles_last_7_days'] = cursor.fetchone()[0]
    
    # Source fetch stats
    cursor.execute('SELECT source_key, last_fetch_time, last_article_count FROM source_fetch_tracking')
    stats['source_fetch_stats'] = [{'source': row[0], 'last_fetch': row[1], 'count': row[2]} for row in cursor.fetchall()]
    
    conn.close()
    return stats


def get_settings(zip_code: str) -> dict:
    """Get settings (merge global and zip-specific)"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    settings = {}
    
    # Get global settings
    cursor.execute('SELECT key, value FROM admin_settings')
    for row in cursor.fetchall():
        settings[row['key']] = row['value']
    
    # Get zip-specific settings (override global)
    if zip_code:
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ?', (zip_code,))
        for row in cursor.fetchall():
            settings[row['key']] = row['value']
    
    conn.close()
    return settings


def init_admin_db():
    """Initialize admin settings table"""
    from database import ArticleDatabase
    db = ArticleDatabase()
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Create admin_settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT
            )
        ''')
        
        # Create article_management table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS article_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                enabled INTEGER DEFAULT 1,
                display_order INTEGER DEFAULT 0,
                FOREIGN KEY (article_id) REFERENCES articles (id)
            )
        ''')
        
        # Add columns if they don't exist
        for col in ['is_rejected', 'is_top_story', 'is_auto_rejected', 'auto_reject_reason', 'zip_code', 'is_stellar', 'is_good_fit']:
            try:
                cursor.execute(f'ALTER TABLE article_management ADD COLUMN {col} INTEGER DEFAULT 0')
            except:
                pass
        
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        except:
            pass
        
        # Create admin_settings_zip table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings_zip (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zip_code TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                UNIQUE(zip_code, key)
            )
        ''')
        
        # Create index
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_admin_settings_zip_code ON admin_settings_zip(zip_code)')
        except:
            pass
        
        # Create categories table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                zip_code TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name, zip_code)
            )
        ''')
        
        # Create index on categories
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_categories_zip_code ON categories(zip_code)')
        except:
            pass
        
        # Initialize default categories for all zip codes
        from config import CATEGORY_SLUGS
        
        # Old categories to remove
        old_categories = ['news', 'entertainment', 'sports', 'local', 'custom', 'media']
        
        # Get all zip codes from articles
        cursor.execute('SELECT DISTINCT zip_code FROM articles WHERE zip_code IS NOT NULL')
        zip_codes = [row[0] for row in cursor.fetchall()]
        # Also check admin_settings_zip for zip codes
        cursor.execute('SELECT DISTINCT zip_code FROM admin_settings_zip WHERE zip_code IS NOT NULL')
        zip_codes.extend([row[0] for row in cursor.fetchall()])
        zip_codes = list(set(zip_codes))  # Remove duplicates
        
        # If no zip codes found, use a default (02720 for Fall River)
        if not zip_codes:
            zip_codes = ['02720']
        
        # Update categories for each zip code
        for zip_code in zip_codes:
            # Remove old categories
            for old_cat in old_categories:
                try:
                    cursor.execute('''
                        DELETE FROM categories WHERE name = ? AND zip_code = ?
                    ''', (old_cat, zip_code))
                except:
                    pass
            
            # Insert new categories (using slugs as names)
            for slug, name in CATEGORY_SLUGS.items():
                try:
                    # Use REPLACE to update if exists, insert if not
                    cursor.execute('''
                        INSERT OR REPLACE INTO categories (name, zip_code)
                        VALUES (?, ?)
                    ''', (slug, zip_code))
                except:
                    pass
        
        # Special handling for 02720 - ensure it has all new categories
        zip_code_02720 = '02720'
        # Remove all old categories for 02720
        for old_cat in old_categories:
            try:
                cursor.execute('''
                    DELETE FROM categories WHERE name = ? AND zip_code = ?
                ''', (old_cat, zip_code_02720))
            except:
                pass
        
        # Insert all new categories for 02720
        for slug, name in CATEGORY_SLUGS.items():
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO categories (name, zip_code)
                    VALUES (?, ?)
                ''', (slug, zip_code_02720))
            except:
                pass
        
        # Initialize default settings
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('show_images', '1')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('relevance_threshold', '10')
        ''')
        
        conn.commit()

