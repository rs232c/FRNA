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
        self.db_path = DATABASE_CONFIG["path"]
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
        
        # Add city columns for city-based consolidation (Phase 1)
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN city_name TEXT')
        except:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN state_abbrev TEXT')
        except:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN city_state TEXT')
        except:
            pass  # Column already exists
        
        # Create index on city_state for fast lookups
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_city_state ON articles(city_state)')
        except:
            pass
        
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
                city_state TEXT,
                UNIQUE(category, item, zip_code, city_state)
            )
        ''')
        
        # Add city_state column if it doesn't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE relevance_config ADD COLUMN city_state TEXT')
        except:
            pass  # Column already exists
        
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
            
            # Excluded towns (auto-filtered nearby towns)
            excluded_towns = ["somerset", "swansea", "westport", "freetown", "taunton", "new bedford",
                              "bristol county", "massachusetts state police", "bristol county sheriff",
                              "dighton", "rehoboth", "seekonk", "warren ri", "tiverton ri"]
            for town in excluded_towns:
                cursor.execute('''
                    INSERT OR IGNORE INTO relevance_config (category, item, points)
                    VALUES (?, ?, ?)
                ''', ('excluded_towns', town, 0.0))
            
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
        
        # Create training_data table for Bayesian relevance learning
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS training_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                zip_code TEXT NOT NULL,
                good_fit INTEGER DEFAULT 0,
                click_type TEXT,
                clicked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (article_id) REFERENCES articles(id)
            )
        ''')
        
        # Create zip_hard_filters table for zip-specific hard filtering
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS zip_hard_filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zip_code TEXT NOT NULL,
                keyword TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(zip_code, keyword)
            )
        ''')
        
        # Create indexes for training_data
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_training_data_zip_code ON training_data(zip_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_training_data_article_id ON training_data(article_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_training_data_good_fit ON training_data(good_fit)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_training_data_clicked_at ON training_data(clicked_at DESC)')
        except:
            pass
        
        # Create indexes for zip_hard_filters
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_zip_hard_filters_zip_code ON zip_hard_filters(zip_code)')
        except:
            pass
        
        # Seed Fall River (02720) hard filter keywords
        fall_river_keywords = [
            "Fall River", "02720", "02721", "02723", "02724", "02726",
            "Durfee", "BMC", "Battleship Cove", "Quequechan", "Flint",
            "Highlands", "SouthCoast", "Globe", "North End", "South End",
            "Cork", "Lower Highlands"
        ]
        for keyword in fall_river_keywords:
            cursor.execute('''
                INSERT OR IGNORE INTO zip_hard_filters (zip_code, keyword)
                VALUES (?, ?)
            ''', ('02720', keyword.lower()))
        
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
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN updated_at TEXT')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_alert INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_featured INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN user_notes TEXT DEFAULT ""')
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_good_fit INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_on_target INTEGER')
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_filtered INTEGER DEFAULT 0')
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN created_at TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists

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
        
        # Create city_zip_mapping table for city-based consolidation (Phase 1)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS city_zip_mapping (
                zip_code TEXT PRIMARY KEY,
                city_name TEXT NOT NULL,
                state_abbrev TEXT NOT NULL,
                city_state TEXT NOT NULL,
                resolved_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create index on city_state for fast lookups
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_city_zip_mapping_city_state ON city_zip_mapping(city_state)')
        except:
            pass
        
        # Migrate existing NULL zip_code data to 02720 (Fall River)
        # Migrate article_management NULL zip_code
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE zip_code IS NULL')
        null_mgmt_count = cursor.fetchone()[0]
        if null_mgmt_count > 0:
            cursor.execute("UPDATE article_management SET zip_code = '02720' WHERE zip_code IS NULL")
            logger.info(f"Migrated {null_mgmt_count} article_management entries with NULL zip_code to '02720'")
        
        # Migrate articles NULL zip_code and populate city columns
        cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code IS NULL OR city_state IS NULL')
        null_articles_count = cursor.fetchone()[0]
        if null_articles_count > 0:
            # Set default zip_code for existing articles
            cursor.execute("UPDATE articles SET zip_code = '02720' WHERE zip_code IS NULL")
            # Populate city columns for existing articles (default: Fall River, MA)
            cursor.execute("""
                UPDATE articles 
                SET city_name = 'Fall River', 
                    state_abbrev = 'MA', 
                    city_state = 'Fall River, MA'
                WHERE city_state IS NULL OR city_name IS NULL
            """)
            logger.info(f"Migrated {null_articles_count} articles with NULL zip_code/city_state to '02720' (Fall River, MA)")
        
        # Initialize city_zip_mapping for 02720 (Fall River) if not exists
        cursor.execute('SELECT COUNT(*) FROM city_zip_mapping WHERE zip_code = ?', ('02720',))
        if cursor.fetchone()[0] == 0:
            cursor.execute('''
                INSERT INTO city_zip_mapping (zip_code, city_name, state_abbrev, city_state)
                VALUES (?, ?, ?, ?)
            ''', ('02720', 'Fall River', 'MA', 'Fall River, MA'))
            logger.info("Initialized city_zip_mapping for 02720 (Fall River, MA)")
        
        # Add zip_pin_editable setting (Phase 9 - Purple Zip Pin)
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('zip_pin_editable', '0')
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

            # Apply semantic deduplication to the batch
            try:
                from utils.semantic_deduplication import SemanticDeduplicator
                deduplicator = SemanticDeduplicator()
                unique_articles, duplicates = deduplicator.deduplicate_batch(articles, threshold=0.75)

                if duplicates:
                    logger.info(f"Semantic deduplication removed {len(duplicates)} duplicate articles")
                    for dup in duplicates[:5]:  # Log first 5 duplicates
                        logger.debug(f"Duplicate: '{dup['article'].get('title', '')[:50]}...' similar to existing article")

                articles = unique_articles  # Use deduplicated list

            except ImportError:
                logger.warning("Semantic deduplication module not available, skipping")
            except Exception as e:
                logger.warning(f"Error during semantic deduplication: {e}, proceeding without it")
            
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
                        # Article already exists but not rejected - update image_url if provided and missing
                        new_image_url = article.get("image_url")
                        if new_image_url:
                            # Check if existing article has image_url
                            cursor.execute('SELECT image_url FROM articles WHERE id = ?', (existing_id,))
                            result = cursor.fetchone()
                            existing_image_url = result[0] if result else None
                            # Update if missing or empty
                            if not existing_image_url or (isinstance(existing_image_url, str) and existing_image_url.strip() == ''):
                                cursor.execute('UPDATE articles SET image_url = ? WHERE id = ?', (new_image_url, existing_id))
                                logger.debug(f"Updated existing article (ID: {existing_id}) with image_url: {title[:50]}")
                                # #region agent log
                                try:
                                    import json
                                    import time
                                    with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"I","location":"database.py:633","message":"Updated existing article with image_url","data":{"article_id":existing_id,"title":(title or '')[:50],"new_image_url":(new_image_url or '')[:80]},"timestamp":int(time.time()*1000)})+'\n')
                                except: pass
                                # #endregion
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

                    # Track source performance for dynamic credibility learning
                    try:
                        from utils.dynamic_source_credibility import DynamicSourceCredibility
                        from utils.content_quality import ContentQualityAnalyzer

                        credibility_system = DynamicSourceCredibility()
                        quality_analyzer = ContentQualityAnalyzer()

                        # Get quality score
                        quality_analysis = quality_analyzer.calculate_quality_score(article)
                        quality_score = quality_analysis['quality_score']

                        # Determine if article will be enabled (rough approximation)
                        # Check if article should be enabled based on relevance threshold
                        relevance_threshold = 11.0  # Default, can be overridden from admin_settings
                        try:
                            threshold_cursor = conn.cursor()
                            threshold_cursor.execute('SELECT value FROM admin_settings WHERE key = "relevance_threshold"')
                            threshold_result = threshold_cursor.fetchone()
                            if threshold_result and threshold_result[0]:
                                relevance_threshold = float(threshold_result[0])
                        except:
                            pass  # Use default

                        is_enabled = relevance_score >= relevance_threshold

                        # Update source performance
                        credibility_system.update_source_performance(
                            source, relevance_score, quality_score, is_enabled, zip_code
                        )

                    except ImportError:
                        pass  # Optional feature
                    except Exception as e:
                        logger.debug(f"Error tracking source performance: {e}")
                    
                    # Calculate local focus score
                    local_focus_score = None
                    try:
                        from admin.utils import calculate_local_focus_score
                        article_zip = article.get("zip_code") or zip_code
                        local_focus_score = calculate_local_focus_score(article, zip_code=article_zip)
                    except Exception as e:
                        logger.warning(f"Error calculating local focus score: {e}")
                        local_focus_score = 0.0
                    
                    # Auto-reject threshold: score < 40 (hard-coded production threshold)
                    # Auto-candidate hero: score > 85
                    is_auto_rejected = (relevance_score < 40)
                    is_hero_candidate = (relevance_score > 85)
                    auto_reject_reason = None
                    
                    if is_auto_rejected:
                        auto_reject_reason = "Relevance score below threshold (<40)"
                        logger.info(f"Auto-rejected article (score {relevance_score:.1f} < 40): {title[:50]}")
                    elif is_hero_candidate:
                        logger.debug(f"Hero candidate article (score {relevance_score:.1f} > 85): {title[:50]}")
                    
                    # Also check admin-configured relevance threshold (for backward compatibility)
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
                    
                    # Auto-filter: Articles below admin threshold OR below 40 will be marked as disabled
                    is_auto_filtered = is_auto_rejected or (relevance_threshold is not None and relevance_score < relevance_threshold)
                    if is_auto_filtered and not is_auto_rejected:
                        logger.info(f"Auto-filtered article (score {relevance_score:.1f} < threshold {relevance_threshold:.1f}): {title[:50]}")
                    
                    # Set zip_code on article if not already set
                    if not article.get("zip_code") and zip_code:
                        article["zip_code"] = zip_code
                    
                    # Resolve city_state for article (Phase 1 & 3)
                    article_zip = article.get("zip_code") or zip_code
                    city_name = article.get("city_name")
                    state_abbrev = article.get("state_abbrev")
                    city_state = article.get("city_state")
                    
                    if not city_state and article_zip:
                        try:
                            from zip_resolver import get_city_state_for_zip
                            city_state = get_city_state_for_zip(article_zip)
                            if city_state:
                                # Parse city_state to get city_name and state_abbrev
                                parts = city_state.split(", ")
                                if len(parts) == 2:
                                    city_name = parts[0]
                                    state_abbrev = parts[1]
                        except Exception as e:
                            logger.warning(f"Error resolving city_state for zip {article_zip}: {e}")
                            # Default to Fall River, MA if resolution fails
                            if article_zip == "02720" or not city_state:
                                city_name = "Fall River"
                                state_abbrev = "MA"
                                city_state = "Fall River, MA"
                    
                    # Predict categories using smart categorizer (enhanced)
                    primary_category = article.get("primary_category")
                    secondary_category = article.get("secondary_category")
                    category_confidence = article.get("category_confidence")
                    category_override = article.get("category_override", 0)

                    if not primary_category and article_zip:
                        try:
                            # Try smart categorizer first (with learning capabilities)
                            from utils.smart_categorizer import SmartCategorizer
                            categorizer = SmartCategorizer(article_zip)
                            predicted_category, confidence_score, all_scores = categorizer.categorize_article(article)

                            # Convert to format expected by rest of system
                            primary_category = predicted_category.replace('-', ' ').title()  # local-news -> Local News
                            category_confidence = confidence_score / 100.0  # Convert to 0-1 scale
                            secondary_category = primary_category  # Default secondary to primary

                            # Find second best category if confidence is low
                            if confidence_score < 60 and len(all_scores) > 1:
                                sorted_scores = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
                                if len(sorted_scores) > 1:
                                    second_best = sorted_scores[1][0]
                                    secondary_category = second_best.replace('-', ' ').title()

                            logger.debug(f"Smart categorized article: {primary_category} ({category_confidence:.1%}), secondary: {secondary_category}")

                        except ImportError:
                            # Fall back to original classifier
                            try:
                                from utils.category_classifier import CategoryClassifier
                                classifier = CategoryClassifier(article_zip)
                                primary_category, category_confidence, secondary_category, _ = classifier.predict_category(article)
                                logger.debug(f"Fallback categorized article: {primary_category} ({category_confidence:.1%}), {secondary_category}")
                            except Exception as e:
                                logger.warning(f"Error predicting category: {e}, defaulting to News")
                                primary_category = "News"
                                secondary_category = "News"
                                category_confidence = 0.5
                        except Exception as e:
                            logger.warning(f"Error in smart categorization: {e}, falling back to News")
                            primary_category = "News"
                            secondary_category = "News"
                            category_confidence = 0.5
                    
                    # Map primary_category to category (lowercase, match expected values)
                    # primary_category uses capitalized names like "Obituaries", category uses lowercase like "obituaries"
                    category = article.get("category", "").lower() if article.get("category") else ""
                    if not category and primary_category:
                        # Map primary_category to category format
                        category_map = {
                            "Obituaries": "obituaries",
                            "obits": "obituaries",  # Handle short form from classifier
                            "Obits": "obituaries",  # Handle capitalized short form
                            "News": "news",
                            "Sports": "sports",
                            "Entertainment": "entertainment",
                            "Crime": "crime",
                            "Business": "business",
                            "Schools": "schools",
                            "Food": "food",
                            "Events": "events",
                            "Weather": "weather"
                        }
                        category = category_map.get(primary_category, primary_category.lower())
                        # Also map "obits" lowercase if it wasn't caught above
                        if category == "obits":
                            category = "obituaries"
                    
                    # #region agent log
                    try:
                        if (category == "obituaries" or (primary_category or "").lower() in ["obituaries", "obituary", "obits"]):
                            import json
                            import time
                            with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"database.py:755","message":"Saving obituary article","data":{"title":(title or '')[:50],"category":category,"primary_category":primary_category,"source":source},"timestamp":int(time.time()*1000)})+'\n')
                    except: pass
                    # #endregion
                    
                    # Insert new article with city_state (Phase 1)
                    # #region agent log
                    try:
                        import json
                        import time
                        with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"H","location":"database.py:791","message":"Saving article to database","data":{"title":(title or '')[:50],"has_image_url":bool(article.get("image_url")),"image_url":(article.get("image_url") or '')[:80] if article.get("image_url") else None},"timestamp":int(time.time()*1000)})+'\n')
                    except: pass
                    # #endregion
                    cursor.execute('''
                        INSERT INTO articles 
                        (title, url, published, summary, content, source, source_type, 
                         image_url, post_id, ingested_at, relevance_score, local_score, zip_code,
                         city_name, state_abbrev, city_state,
                         category, primary_category, secondary_category, category_confidence, category_override)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        local_focus_score,
                        article.get("zip_code") or zip_code,
                        city_name,
                        state_abbrev,
                        city_state,
                        category or "news",
                        primary_category or "News",
                        secondary_category or "News",
                        category_confidence or 0.5,
                        category_override
                    ))
                    
                    article_id = cursor.lastrowid
                    new_ids.append(article_id)
                    
                    # Create article_management entry with zip_code
                    # If below threshold, mark as disabled (auto-filtered)
                    # Ensure is_auto_rejected column exists
                    try:
                        cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
                        cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
                    except:
                        pass  # Columns already exist
                    
                    cursor.execute('''
                        INSERT INTO article_management 
                        (article_id, enabled, display_order, is_rejected, is_auto_rejected, auto_reject_reason, zip_code)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        article_id,
                        0 if is_auto_filtered else 1,  # Disabled if auto-filtered
                        article_id,
                        0,
                        1 if is_auto_rejected else 0,
                        auto_reject_reason,
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
    
    def get_recent_articles(self, hours: int = 24, limit: int = 100, zip_code: Optional[str] = None, city_state: Optional[str] = None) -> List[Dict]:
        """Get articles from the last N hours, sorted by publication date (newest first)
        Phase 2: Now supports city_state for city-based consolidation
        
        Args:
            hours: Number of hours to look back
            limit: Maximum number of articles to return
            zip_code: Optional zip code to filter by (resolves to city_state)
            city_state: Optional city_state to filter by (e.g., "Fall River, MA")
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cutoff_time = (datetime.now() - timedelta(hours=hours)).isoformat()
        
        # Resolve zip_code to city_state if provided (Phase 2)
        if zip_code and not city_state:
            try:
                from zip_resolver import get_city_state_for_zip
                city_state = get_city_state_for_zip(zip_code)
            except Exception as e:
                logger.warning(f"Error resolving city_state for zip {zip_code}: {e}")
        
        # Build query with city_state filter (Phase 2: city-based consolidation)
        if city_state:
            # Filter by city_state (articles shared across zips in same city)
            cursor.execute('''
                SELECT * FROM articles 
                WHERE city_state = ? AND (published >= ? OR ingested_at >= ? OR published IS NULL)
                ORDER BY 
                    CASE WHEN published IS NOT NULL AND published != '' THEN published ELSE '1970-01-01' END DESC,
                    ingested_at DESC
                LIMIT ?
            ''', (city_state, cutoff_time, cutoff_time, limit))
        elif zip_code:
            # Fallback: filter by zip_code if city_state resolution failed
            cursor.execute('''
                SELECT * FROM articles 
                WHERE (city_state = (SELECT city_state FROM city_zip_mapping WHERE zip_code = ?) OR zip_code = ?)
                AND (published >= ? OR ingested_at >= ? OR published IS NULL)
                ORDER BY 
                    CASE WHEN published IS NOT NULL AND published != '' THEN published ELSE '1970-01-01' END DESC,
                    ingested_at DESC
                LIMIT ?
            ''', (zip_code, zip_code, cutoff_time, cutoff_time, limit))
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
    
    def get_all_articles(self, limit: int = 500, zip_code: Optional[str] = None, city_state: Optional[str] = None) -> List[Dict]:
        """Get all articles sorted by publication date (newest first), excluding auto-rejected articles
        Phase 2: Now supports city_state for city-based consolidation
        
        Args:
            limit: Maximum number of articles to return
            zip_code: Optional zip code to filter by (resolves to city_state)
            city_state: Optional city_state to filter by (e.g., "Fall River, MA")
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Resolve zip_code to city_state if provided (Phase 2)
        if zip_code and not city_state:
            try:
                from zip_resolver import get_city_state_for_zip
                city_state = get_city_state_for_zip(zip_code)
            except Exception as e:
                logger.warning(f"Error resolving city_state for zip {zip_code}: {e}")
        
        # Build city_state filter condition (Phase 2: city-based consolidation)
        if city_state:
            # Filter by city_state (articles shared across zips in same city)
            city_filter = "AND a.city_state = ?"
            filter_params = [city_state]
        elif zip_code:
            # Fallback: filter by zip_code if city_state resolution failed
            city_filter = "AND (a.city_state = (SELECT city_state FROM city_zip_mapping WHERE zip_code = ?) OR a.zip_code = ?)"
            filter_params = [zip_code, zip_code]
        else:
            # No filter - get all articles
            city_filter = ""
            filter_params = []
        
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
            {city_filter}
            ORDER BY a.published DESC
            LIMIT ?
        ''', filter_params + [limit])
        
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
            {city_filter}
            ORDER BY a.created_at DESC
            LIMIT ?
        ''', filter_params + [limit])
        
        rows_without_published = cursor.fetchall()
        
        # Combine: published articles first, then unpublished
        articles = [dict(row) for row in rows_with_published]
        articles.extend([dict(row) for row in rows_without_published])
        
        # Limit total
        articles = articles[:limit]
        
        conn.close()
        return articles

    def get_articles_by_category(self, category: str, limit: int = 50, zip_code: Optional[str] = None, city_state: Optional[str] = None) -> List[Dict]:
        """Get articles filtered by category, sorted by publication date (newest first)

        Args:
            category: Category name (e.g., 'crime', 'sports', 'obituaries')
            limit: Maximum number of articles to return
            zip_code: Optional zip code to filter by (resolves to city_state)
            city_state: Optional city_state to filter by (e.g., "Fall River, MA")
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Resolve zip_code to city_state if provided
        if zip_code and not city_state:
            try:
                from zip_resolver import get_city_state_for_zip
                city_state = get_city_state_for_zip(zip_code)
            except Exception as e:
                logger.warning(f"Error resolving city_state for zip {zip_code}: {e}")

        # Build query with filters
        base_query = '''
            SELECT * FROM articles
            WHERE category = ?
        '''

        params = [category]

        # Add city_state filter if provided
        if city_state:
            base_query += " AND city_state = ?"
            params.append(city_state)
        elif zip_code:
            # Fallback: filter by zip_code if city_state resolution failed
            base_query += " AND (city_state = (SELECT city_state FROM city_zip_mapping WHERE zip_code = ?) OR zip_code = ?)"
            params.extend([zip_code, zip_code])

        # Order by published date first, then by ingested date
        base_query += '''
            ORDER BY
                CASE
                    WHEN published IS NOT NULL THEN published
                    ELSE ingested_at
                END DESC,
                created_at DESC
            LIMIT ?
        '''
        params.append(limit)

        cursor.execute(base_query, params)
        rows = cursor.fetchall()

        articles = [dict(row) for row in rows]
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
    
    def get_last_enabled_article_update_time(self, zip_code: Optional[str] = None) -> Optional[str]:
        """Get the timestamp of the most recently created enabled article
        
        Args:
            zip_code: Optional zip code filter
            
        Returns:
            Formatted timestamp string or None if no enabled articles found
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Query for enabled articles (not rejected, enabled=1 or no management entry)
        # Get the MAX created_at from articles that are enabled
        if zip_code:
            query = '''
                SELECT MAX(a.created_at)
                FROM articles a
                LEFT JOIN (
                    SELECT article_id, 
                           COALESCE(is_rejected, 0) as is_rejected,
                           COALESCE(enabled, 1) as enabled
                    FROM article_management
                    WHERE ROWID IN (
                        SELECT MAX(ROWID)
                        FROM article_management
                        GROUP BY article_id
                    )
                ) am ON a.id = am.article_id
                WHERE (am.article_id IS NULL OR (am.is_rejected = 0 AND am.enabled = 1))
                AND (a.zip_code = ? OR a.zip_code IS NULL)
            '''
            cursor.execute(query, (zip_code,))
        else:
            query = '''
                SELECT MAX(a.created_at)
                FROM articles a
                LEFT JOIN (
                    SELECT article_id, 
                           COALESCE(is_rejected, 0) as is_rejected,
                           COALESCE(enabled, 1) as enabled
                    FROM article_management
                    WHERE ROWID IN (
                        SELECT MAX(ROWID)
                        FROM article_management
                        GROUP BY article_id
                    )
                ) am ON a.id = am.article_id
                WHERE (am.article_id IS NULL OR (am.is_rejected = 0 AND am.enabled = 1))
            '''
            cursor.execute(query)
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0]:
            try:
                # Parse and format the timestamp, converting UTC to local time
                from datetime import datetime, timezone
                import time
                
                # Parse the timestamp (assume UTC if no timezone info)
                timestamp_str = result[0]
                if timestamp_str.endswith('Z'):
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                elif '+' in timestamp_str or (timestamp_str.count('-') > 2 and 'T' in timestamp_str):
                    # Has timezone info
                    dt = datetime.fromisoformat(timestamp_str)
                else:
                    # No timezone info, assume UTC
                    dt = datetime.fromisoformat(timestamp_str)
                    dt = dt.replace(tzinfo=timezone.utc)
                
                # Convert to local time if timezone-aware
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                
                # Convert UTC to local time (system local time)
                local_dt = dt.astimezone()
                
                return local_dt.strftime("%Y-%m-%d %I:%M:%S %p")
            except Exception as e:
                logger.warning(f"Error formatting last update time: {e}")
                return result[0]
        
        return None

