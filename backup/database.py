"""
Database module for storing and tracking articles
"""
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
from config import DATABASE_CONFIG, AGGREGATION_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ArticleDatabase:
    """Database for storing articles and tracking posted items"""
    
    def __init__(self):
        self.db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Articles table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT UNIQUE,
                published TEXT,
                summary TEXT,
                content TEXT,
                source TEXT,
                source_type TEXT,
                category TEXT,
                image_url TEXT,
                post_id TEXT,
                ingested_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add category column if it doesn't exist
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN category TEXT')
        except:
            pass  # Column already exists
        
        # Add relevance_score column if it doesn't exist
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN relevance_score REAL')
        except:
            pass  # Column already exists
        
        # Add local_score column if it doesn't exist
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN local_score REAL')
        except:
            pass  # Column already exists
        
        # Add zip_code column if it doesn't exist
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN zip_code TEXT')
        except:
            pass  # Column already exists
        
        # Add category classification columns if they don't exist
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN primary_category TEXT')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN secondary_category TEXT')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN category_confidence REAL')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN category_override INTEGER DEFAULT 0')
        except:
            pass
        
        # Create index on zip_code for performance
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_zip_code ON articles(zip_code)')
        except:
            pass
        
        # Migrate existing Fall River articles to zip_code = '02720'
        # Only do this once - check if any articles have NULL zip_code
        cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code IS NULL')
        null_count = cursor.fetchone()[0]
        if null_count > 0:
            # Set default zip_code for existing articles (assuming they're Fall River)
            cursor.execute("UPDATE articles SET zip_code = '02720' WHERE zip_code IS NULL")
            logger.info(f"Migrated {null_count} existing articles to zip_code '02720'")
        
        conn.commit()
        
        # Posted articles tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS posted_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                platform TEXT,
                posted_at TEXT,
                success INTEGER,
                FOREIGN KEY (article_id) REFERENCES articles (id)
            )
        ''')
        
        # Relevance configuration table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS relevance_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                item TEXT NOT NULL,
                points REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                zip_code TEXT,
                UNIQUE(category, item, zip_code)
            )
        ''')
        
        # Category keywords table (for fast keyword-based categorization)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS category_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zip_code TEXT NOT NULL,
                category TEXT NOT NULL,
                keyword TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(zip_code, category, keyword)
            )
        ''')
        
        # Create index for fast keyword lookups
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_category_keywords_lookup ON category_keywords(zip_code, category)')
        except:
            pass
        
        # Add zip_code column if it doesn't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE relevance_config ADD COLUMN zip_code TEXT')
        except:
            pass
        
        # Create index on category for faster lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_relevance_category ON relevance_config(category)
        ''')
        
        # Create index on zip_code for performance
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_relevance_zip_code ON relevance_config(zip_code)')
        except:
            pass
        
        # Migrate initial data if table is empty
        cursor.execute('SELECT COUNT(*) FROM relevance_config')
        if cursor.fetchone()[0] == 0:
            from datetime import datetime
            # High relevance keywords (10 points each)
            high_relevance = ["fall river", "fallriver", "fall river ma", "fall river, ma", 
                             "fall river massachusetts", "fall river, massachusetts"]
            for keyword in high_relevance:
                cursor.execute('''
                    INSERT OR IGNORE INTO relevance_config (category, item, points)
                    VALUES (?, ?, ?)
                ''', ('high_relevance', keyword, 10.0))
            
            # Medium relevance keywords (5 points each)
            medium_relevance = ["somerset", "swansea", "westport", "freetown", "taunton", "new bedford", 
                               "bristol county", "massachusetts state police", "bristol county sheriff",
                               "dighton", "rehoboth", "seekonk", "warren ri", "tiverton ri"]
            for keyword in medium_relevance:
                cursor.execute('''
                    INSERT OR IGNORE INTO relevance_config (category, item, points)
                    VALUES (?, ?, ?)
                ''', ('medium_relevance', keyword, 5.0))
            
            # Local places (3 points each)
            local_places = [
                "watuppa", "wattupa", "quequechan", "taunton river", "mount hope bay",
                "battleship cove", "lizzie borden", "lizzie borden house", "fall river heritage state park",
                "marine museum", "narrows center", "gates of the city",
                "durfee", "bmc durfee", "b.m.c. durfee", "durfee high", "durfee high school",
                "saint anne's", "saint anne", "st. anne's", "st. anne", "bishop connolly",
                "diman", "diman regional", "diman vocational", "bristol community college", "bcc",
                "fall river public schools", "f.r.p.s.",
                "saint anne's hospital", "st. anne's hospital", "charlton memorial", "southcoast health",
                "north end", "south end", "highlands", "flint village", "maplewood",
                "lower highlands", "upper highlands", "downtown fall river", "the hill",
                "pleasant street", "south main street", "north main street", "eastern avenue",
                "highland avenue", "bedford street", "davol street", "government center",
                "city hall", "fall river city hall", "government center", "city council",
                "mayor paul coogan", "mayor coogan", "school committee", "school board",
                "fall river chamber", "fall river economic development", "fall river housing authority",
                "fall river water department", "fall river gas company",
                "kennedy park", "lafayette park", "riker park", "bicentennial park",
                "fall river little league", "fall river youth soccer"
            ]
            for place in local_places:
                cursor.execute('''
                    INSERT OR IGNORE INTO relevance_config (category, item, points)
                    VALUES (?, ?, ?)
                ''', ('local_places', place, 3.0))
            
            # Topic keywords (variable points)
            topic_keywords = {
                "city council": 8.0, "mayor": 8.0, "school committee": 8.0, "school board": 8.0,
                "city budget": 8.0, "tax rate": 8.0, "zoning": 8.0, "planning board": 8.0,
                "police": 7.0, "arrest": 7.0, "fire department": 7.0, "emergency": 7.0,
                "crime": 7.0, "investigation": 7.0, "suspected": 7.0,
                "school": 6.0, "student": 6.0, "teacher": 6.0, "education": 6.0,
                "graduation": 6.0, "principal": 6.0,
                "business": 5.0, "restaurant": 5.0, "opening": 5.0, "closing": 5.0,
                "new business": 5.0, "local business": 5.0,
                "event": 4.0, "festival": 4.0, "concert": 4.0, "community": 4.0,
                "fundraiser": 4.0, "charity": 4.0
            }
            for keyword, points in topic_keywords.items():
                cursor.execute('''
                    INSERT OR IGNORE INTO relevance_config (category, item, points)
                    VALUES (?, ?, ?)
                ''', ('topic_keywords', keyword, points))
            
            # Source credibility (variable points)
            source_credibility = {
                "herald news": 25.0,
                "fall river reporter": 25.0,
                "wpri": 8.0,
                "abc6": 8.0,
                "nbc10": 8.0,
                "fun107": 5.0,
                "masslive": 5.0,
                "taunton gazette": 4.0,
                "southcoast today": 4.0
            }
            for source_name, points in source_credibility.items():
                cursor.execute('''
                    INSERT OR IGNORE INTO relevance_config (category, item, points)
                    VALUES (?, ?, ?)
                ''', ('source_credibility', source_name, points))
            
            # Clickbait patterns (no points, just for matching - penalty applied in code)
            clickbait_patterns = [
                "you won't believe", "this one trick", "number 7 will shock you",
                "doctors hate", "one weird trick", "click here", "find out more"
            ]
            for pattern in clickbait_patterns:
                cursor.execute('''
                    INSERT OR IGNORE INTO relevance_config (category, item, points)
                    VALUES (?, ?, ?)
                ''', ('clickbait_patterns', pattern, None))
            
            conn.commit()
            logger.info("Populated relevance_config table with initial data")
        
        # Create indexes for performance
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_url ON articles(url)
        ''')
        # Index for sorting by publication date (DESC for newest first)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_published_desc ON articles(published DESC)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_source ON articles(source)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_category ON articles(category)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_created_at ON articles(created_at DESC)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_posted_platform ON posted_articles(platform, posted_at)
        ''')
        # Index for article management lookups
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_article_mgmt_id ON article_management(article_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_article_mgmt_enabled ON article_management(enabled, display_order)
        ''')
        
        # Create admin settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT
            )
        ''')
        
        # Create website generation tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS website_generation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                last_article_id INTEGER,
                last_generation_time TEXT,
                pages_generated TEXT
            )
        ''')
        
        # Create source fetch tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS source_fetch_tracking (
                source_key TEXT PRIMARY KEY,
                last_fetch_time TEXT,
                last_article_count INTEGER
            )
        ''')
        
        # Create article_management table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS article_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                enabled INTEGER DEFAULT 1,
                display_order INTEGER DEFAULT 0,
                is_top_article INTEGER DEFAULT 0,
                is_top_story INTEGER DEFAULT 0,
                is_stellar INTEGER DEFAULT 0,
                FOREIGN KEY (article_id) REFERENCES articles (id)
            )
        ''')
        
        # Add is_stellar column if it doesn't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_stellar INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            # Column already exists
            pass
        
        # Add columns if they don't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_top_article INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_top_story INTEGER DEFAULT 0')
        except:
            pass
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
        
        # Initialize default settings
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('show_images', '1')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('auto_regenerate', '1')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('regenerate_interval', '10')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('regenerate_on_load', '0')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('last_regeneration_time', '')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('admin_version', '0')
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")
    
    def save_articles(self, articles: List[Dict], zip_code: Optional[str] = None) -> List[int]:
        """Save articles to database with zip-specific filtering, return list of new article IDs
        
        Args:
            articles: List of article dicts to save
            zip_code: Optional zip code for zip-specific filtering and relevance calculation
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            new_ids = []
            
            for article in articles:
                try:
                    url = article.get("url", "") or ""
                    title = article.get("title", "").strip()
                    source = article.get("source", "")
                    published = article.get("published", "")
                    
                    # Check if article already exists by URL (if URL exists)
                    existing_id = None
                    is_rejected = False
                    
                    if url:
                        cursor.execute('''
                            SELECT a.id, COALESCE(am.is_rejected, 0) as is_rejected
                            FROM articles a
                            LEFT JOIN (
                                SELECT article_id, is_rejected
                                FROM article_management
                                WHERE ROWID IN (
                                    SELECT MAX(ROWID) 
                                    FROM article_management 
                                    GROUP BY article_id
                                )
                            ) am ON a.id = am.article_id
                            WHERE a.url = ?
                            LIMIT 1
                        ''', (url,))
                        result = cursor.fetchone()
                        if result:
                            existing_id = result[0]
                            is_rejected = bool(result[1])
                    
                    # If no URL or URL not found, check by title + source + published date
                    if not existing_id:
                        cursor.execute('''
                            SELECT a.id, COALESCE(am.is_rejected, 0) as is_rejected
                            FROM articles a
                            LEFT JOIN (
                                SELECT article_id, is_rejected
                                FROM article_management
                                WHERE ROWID IN (
                                    SELECT MAX(ROWID) 
                                    FROM article_management 
                                    GROUP BY article_id
                                )
                            ) am ON a.id = am.article_id
                            WHERE a.title = ? AND a.source = ? AND a.published = ?
                            LIMIT 1
                        ''', (title, source, published))
                        result = cursor.fetchone()
                        if result:
                            existing_id = result[0]
                            is_rejected = bool(result[1])
                    
                    # Also check by normalized title + source (more lenient matching)
                    if not existing_id and title:
                        # Normalize title for comparison (lowercase, strip whitespace)
                        title_normalized = title.lower().strip()
                        cursor.execute('''
                            SELECT a.id, COALESCE(am.is_rejected, 0) as is_rejected
                            FROM articles a
                            LEFT JOIN (
                                SELECT article_id, is_rejected
                                FROM article_management
                                WHERE ROWID IN (
                                    SELECT MAX(ROWID) 
                                    FROM article_management 
                                    GROUP BY article_id
                                )
                            ) am ON a.id = am.article_id
                            WHERE LOWER(TRIM(a.title)) = ? AND a.source = ?
                            LIMIT 1
                        ''', (title_normalized, source))
                        result = cursor.fetchone()
                        if result:
                            existing_id = result[0]
                            is_rejected = bool(result[1])

                    if existing_id:
                        # If article exists and is rejected, skip it completely
                        if is_rejected:
                            logger.info(f"Skipping rejected article: {title[:50]} (ID: {existing_id})")
                            # Don't add to new_ids - we want to skip it completely
                            continue
                        # Article already exists but not rejected, skip adding duplicate
                        logger.debug(f"Article already exists (ID: {existing_id}): {title[:50]}")
                        new_ids.append(existing_id)
                        continue
                    
                    # Also check if this article matches a rejected article by normalized URL
                    # (in case URL has query params or trailing slashes)
                    if url:
                        url_normalized = url.split('?')[0].rstrip('/')
                        cursor.execute('''
                            SELECT a.id, COALESCE(am.is_rejected, 0) as is_rejected
                            FROM articles a
                            LEFT JOIN (
                                SELECT article_id, is_rejected
                                FROM article_management
                                WHERE ROWID IN (
                                    SELECT MAX(ROWID) 
                                    FROM article_management 
                                    GROUP BY article_id
                                )
                            ) am ON a.id = am.article_id
                            WHERE a.url LIKE ? OR a.url = ?
                            LIMIT 1
                        ''', (f"{url_normalized}%", url_normalized))
                        result = cursor.fetchone()
                        if result and bool(result[1]):  # If rejected
                            logger.info(f"Skipping rejected article by normalized URL: {title[:50]}")
                            continue
                    
                    # Calculate relevance score if not already present (using zip-specific config)
                    relevance_score = article.get('relevance_score') or article.get('_relevance_score')
                    if relevance_score is None:
                        from utils.relevance_calculator import calculate_relevance_score
                        # Use zip_code from article or parameter
                        article_zip = article.get("zip_code") or zip_code
                        relevance_score = calculate_relevance_score(article, zip_code=article_zip)
                    
                    # Get relevance threshold for zip-specific filtering
                    article_zip = article.get("zip_code") or zip_code
                    relevance_threshold = None
                    if article_zip:
                        cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', 
                                     (article_zip, 'relevance_threshold'))
                        threshold_row = cursor.fetchone()
                        if threshold_row:
                            try:
                                relevance_threshold = float(threshold_row[0])
                            except (ValueError, TypeError):
                                pass
                    
                    # Auto-filter: Articles below threshold will be marked as disabled
                    is_auto_filtered = (relevance_threshold is not None and relevance_score < relevance_threshold)
                    if is_auto_filtered:
                        logger.info(f"Auto-filtered article (score {relevance_score:.1f} < threshold {relevance_threshold:.1f}): {title[:50]}")
                    
                    # Set zip_code on article if not already set
                    if not article.get("zip_code") and zip_code:
                        article["zip_code"] = zip_code
                    
                    # Predict categories using category classifier
                    article_zip = article.get("zip_code") or zip_code
                    primary_category = article.get("primary_category")
                    secondary_category = article.get("secondary_category")
                    category_confidence = article.get("category_confidence")
                    category_override = article.get("category_override", 0)
                    
                    if not primary_category and article_zip:
                        try:
                            from utils.category_classifier import CategoryClassifier
                            classifier = CategoryClassifier(article_zip)
                            primary_category, category_confidence, secondary_category, _ = classifier.predict_category(article)
                            logger.debug(f"Predicted categories for article: {primary_category} ({category_confidence:.1%}), {secondary_category}")
                        except Exception as e:
                            logger.warning(f"Error predicting category: {e}, defaulting to News")
                            primary_category = "News"
                            secondary_category = "News"
                            category_confidence = 0.5
                    
                    # Insert new article
                    cursor.execute('''
                        INSERT INTO articles 
                        (title, url, published, summary, content, source, source_type, 
                         image_url, post_id, ingested_at, relevance_score, zip_code,
                         primary_category, secondary_category, category_confidence, category_override)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        title,
                        url,
                        published,
                        article.get("summary", ""),
                        article.get("content", ""),
                        source,
                        article.get("source_type", ""),
                        article.get("image_url"),
                        article.get("post_id"),
                        article.get("ingested_at", datetime.now().isoformat()),
                        relevance_score,
                        article.get("zip_code") or zip_code,
                        primary_category or "News",
                        secondary_category or "News",
                        category_confidence or 0.5,
                        category_override
                    ))
                    
                    article_id = cursor.lastrowid
                    new_ids.append(article_id)
                    
                    # Create article_management entry with zip_code
                    # If below threshold, mark as disabled (auto-filtered)
                    cursor.execute('''
                        INSERT INTO article_management 
                        (article_id, enabled, display_order, is_rejected, zip_code)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        article_id,
                        0 if is_auto_filtered else 1,  # Disabled if auto-filtered
                        article_id,
                        0,
                        article.get("zip_code") or zip_code
                    ))
                
                except sqlite3.IntegrityError as e:
                    # URL already exists (UNIQUE constraint violation), try to get existing ID
                    if url:
                        cursor.execute('SELECT id FROM articles WHERE url = ?', (url,))
                        result = cursor.fetchone()
                        if result:
                            existing_id = result[0]
                            logger.debug(f"Article already exists (URL duplicate, ID: {existing_id}): {title[:50]}")
                            new_ids.append(existing_id)
                        else:
                            logger.warning(f"IntegrityError but couldn't find article by URL: {url[:50]}")
                    else:
                        logger.warning(f"IntegrityError for article without URL: {title[:50]}")
                except Exception as e:
                    logger.error(f"Error saving article: {e}")
            
            conn.commit()
            conn.close()
            return new_ids
        except Exception as e:
            logger.error(f"Error in save_articles: {e}")
            return []
    
    def remove_duplicates(self):
        """Remove duplicate articles from database - aggressive version"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        removed = 0
        
        # First, remove duplicates by URL (most reliable)
        cursor.execute('''
            SELECT url, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
            FROM articles
            WHERE url IS NOT NULL AND url != '' AND url != '#'
            GROUP BY url
            HAVING cnt > 1
        ''')
        
        url_duplicates = cursor.fetchall()
        for dup in url_duplicates:
            ids = [int(x) for x in dup[2].split(',')]
            # Keep the one with the lowest ID (oldest)
            keep_id = min(ids)
            delete_ids = [id for id in ids if id != keep_id]
            
            for delete_id in delete_ids:
                cursor.execute('DELETE FROM article_management WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM articles WHERE id = ?', (delete_id,))
                removed += 1
        
        # Remove duplicates by normalized title + source + published date
        cursor.execute('''
            SELECT LOWER(TRIM(title)) as norm_title, source, published, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
            FROM articles
            WHERE title IS NOT NULL AND title != ''
            GROUP BY norm_title, source, published
            HAVING cnt > 1
        ''')
        
        title_duplicates = cursor.fetchall()
        for dup in title_duplicates:
            ids = [int(x) for x in dup[4].split(',')]
            keep_id = min(ids)
            delete_ids = [id for id in ids if id != keep_id]
            
            for delete_id in delete_ids:
                cursor.execute('DELETE FROM article_management WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (delete_id,))
                cursor.execute('DELETE FROM articles WHERE id = ?', (delete_id,))
                removed += 1
        
        # Also check for very similar titles (fuzzy match - same first 50 chars)
        cursor.execute('''
            SELECT SUBSTR(LOWER(TRIM(title)), 1, 50) as title_start, source, COUNT(*) as cnt, GROUP_CONCAT(id) as ids
            FROM articles
            WHERE title IS NOT NULL AND title != '' AND LENGTH(title) > 20
            GROUP BY title_start, source
            HAVING cnt > 1
        ''')
        
        similar_duplicates = cursor.fetchall()
        for dup in similar_duplicates:
            ids = [int(x) for x in dup[3].split(',')]
            if len(ids) > 1:
                keep_id = min(ids)
                delete_ids = [id for id in ids if id != keep_id]
                
                for delete_id in delete_ids:
                    cursor.execute('DELETE FROM article_management WHERE article_id = ?', (delete_id,))
                    cursor.execute('DELETE FROM posted_articles WHERE article_id = ?', (delete_id,))
                    cursor.execute('DELETE FROM articles WHERE id = ?', (delete_id,))
                    removed += 1
        
        conn.commit()
        conn.close()
        logger.info(f"Removed {removed} duplicate articles")
        return removed
    
    def get_recent_articles(self, hours: int = 24, limit: int = 100, zip_code: Optional[str] = None) -> List[Dict]:
        """Get articles from the last N hours, sorted by publication date (newest first)
        
        Args:
            hours: Number of hours to look back
            limit: Maximum number of articles to return
            zip_code: Optional zip code to filter by
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cutoff_time = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        # Build query with optional zip_code filter
        if zip_code:
            cursor.execute('''
                SELECT * FROM articles 
                WHERE zip_code = ? AND (published >= ? OR ingested_at >= ? OR published IS NULL)
                ORDER BY 
                    CASE WHEN published IS NOT NULL AND published != '' THEN published ELSE '1970-01-01' END DESC,
                    ingested_at DESC
                LIMIT ?
            ''', (zip_code, cutoff_time, cutoff_time, limit))
        else:
            # Get all articles, sorted by published date (newest first) - publication date is primary
            # This ensures newest articles appear first regardless of when they were ingested
            cursor.execute('''
                SELECT * FROM articles 
                WHERE published >= ? OR ingested_at >= ? OR published IS NULL
                ORDER BY 
                    CASE WHEN published IS NOT NULL AND published != '' THEN published ELSE '1970-01-01' END DESC,
                    ingested_at DESC
                LIMIT ?
            ''', (cutoff_time, cutoff_time, limit))
        
        rows = cursor.fetchall()
        articles = [dict(row) for row in rows]
        
        conn.close()
        return articles
    
    def get_all_articles(self, limit: int = 500, zip_code: Optional[str] = None) -> List[Dict]:
        """Get all articles sorted by publication date (newest first), excluding auto-rejected articles
        
        Args:
            limit: Maximum number of articles to return
            zip_code: Optional zip code to filter by
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Build zip_code filter condition
        zip_filter = "AND a.zip_code = ?" if zip_code else ""
        zip_params = [zip_code] if zip_code else []
        
        # Exclude auto-rejected articles (is_auto_rejected = 1) but keep manually rejected ones
        # Get articles with published date, excluding auto-rejected
        cursor.execute(f'''
            SELECT a.* FROM articles a
            LEFT JOIN (
                SELECT article_id, is_auto_rejected, is_rejected
                FROM article_management
                WHERE ROWID IN (
                    SELECT MAX(ROWID) 
                    FROM article_management 
                    GROUP BY article_id
                )
            ) am ON a.id = am.article_id
            WHERE a.published IS NOT NULL AND a.published != ''
            AND (am.is_auto_rejected IS NULL OR am.is_auto_rejected = 0)
            {zip_filter}
            ORDER BY a.published DESC
            LIMIT ?
        ''', zip_params + [limit])
        
        rows_with_published = cursor.fetchall()
        
        # Get articles without published date separately, excluding auto-rejected
        cursor.execute(f'''
            SELECT a.* FROM articles a
            LEFT JOIN (
                SELECT article_id, is_auto_rejected, is_rejected
                FROM article_management
                WHERE ROWID IN (
                    SELECT MAX(ROWID) 
                    FROM article_management 
                    GROUP BY article_id
                )
            ) am ON a.id = am.article_id
            WHERE (a.published IS NULL OR a.published = '')
            AND (am.is_auto_rejected IS NULL OR am.is_auto_rejected = 0)
            {zip_filter}
            ORDER BY a.created_at DESC
            LIMIT ?
        ''', zip_params + [limit])
        
        rows_without_published = cursor.fetchall()
        
        # Combine: published articles first, then unpublished
        articles = [dict(row) for row in rows_with_published]
        articles.extend([dict(row) for row in rows_without_published])
        
        # Limit total
        articles = articles[:limit]
        
        conn.close()
        return articles
    
    def mark_as_posted(self, article_id: int, platform: str, success: bool = True):
        """Mark an article as posted to a platform"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO posted_articles (article_id, platform, posted_at, success)
            VALUES (?, ?, ?, ?)
        ''', (article_id, platform, datetime.now().isoformat(), 1 if success else 0))
        
        conn.commit()
        conn.close()
    
    def is_posted(self, article_url: str, platform: str) -> bool:
        """Check if an article has been posted to a platform"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM posted_articles pa
            JOIN articles a ON pa.article_id = a.id
            WHERE a.url = ? AND pa.platform = ? AND pa.success = 1
        ''', (article_url, platform))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    
    def get_unposted_articles(self, platform: str, limit: int = 10) -> List[Dict]:
        """Get articles that haven't been posted to a specific platform"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get articles from last 7 days that haven't been posted
        cutoff_time = (datetime.now() - timedelta(days=7)).isoformat()
        
        cursor.execute('''
            SELECT a.* FROM articles a
            LEFT JOIN posted_articles pa ON a.id = pa.article_id AND pa.platform = ? AND pa.success = 1
            WHERE (a.published >= ? OR a.ingested_at >= ?)
            AND pa.id IS NULL
            ORDER BY a.published DESC, a.ingested_at DESC
            LIMIT ?
        ''', (platform, cutoff_time, cutoff_time, limit))
        
        rows = cursor.fetchall()
        articles = [dict(row) for row in rows]
        
        conn.close()
        return articles
    
    def cleanup_old_articles(self, days: int = 30):
        """Remove articles older than specified days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff_time = (datetime.now() - timedelta(days=days)).isoformat()
        
        # Delete posted tracking first (foreign key constraint)
        cursor.execute('''
            DELETE FROM posted_articles 
            WHERE article_id IN (
                SELECT id FROM articles 
                WHERE published < ? AND ingested_at < ?
            )
        ''', (cutoff_time, cutoff_time))
        
        # Delete old articles
        cursor.execute('''
            DELETE FROM articles 
            WHERE published < ? AND ingested_at < ?
        ''', (cutoff_time, cutoff_time))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        logger.info(f"Cleaned up {deleted_count} old articles")
        return deleted_count

