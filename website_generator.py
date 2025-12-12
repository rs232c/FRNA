"""
Website generator that creates a static website from aggregated news
MSN-style layout with grid, weather, and widgets
"""
import os
import sqlite3
import re
import shutil
import json
import time
from collections import OrderedDict
from jinja2 import Template, Environment, FileSystemLoader
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
from config import WEBSITE_CONFIG, LOCALE, DATABASE_CONFIG, CATEGORY_SLUGS, CATEGORY_MAPPING, WEATHER_CONFIG, SCANNER_CONFIG
from ingestors.weather_ingestor import WeatherIngestor
from website_generator.static.css.styles import get_css_content
from website_generator.static.js.scripts import get_js_content
from utils.image_processor import should_optimize_image, optimize_image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebsiteGenerator:
    """Generate static website from aggregated news with MSN-style layout"""
    
    def __init__(self):
        self.output_dir = WEBSITE_CONFIG.get("output_dir", "build")
        self.title = WEBSITE_CONFIG.get("title", f"{LOCALE} News")
        self.description = WEBSITE_CONFIG.get("description", f"Latest news from {LOCALE}")
        self.weather_ingestor = WeatherIngestor()
        self.images_dir = Path(self.output_dir) / "images"
        
        # Setup Jinja2 environment for file-based templates
        template_dir = Path(__file__).parent / "website_generator" / "templates"
        self.use_file_templates = template_dir.exists() and template_dir.is_dir()
        if self.use_file_templates:
            try:
                self.jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
                logger.info(f"Using file-based templates from {template_dir}")
            except Exception as e:
                logger.warning(f"Could not initialize Jinja2 FileSystemLoader: {e}")
                self.use_file_templates = False
                self.jinja_env = None
        else:
            self.jinja_env = None
            logger.info("Using string-based templates (fallback)")
        
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Create necessary output directories"""
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "css"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "js"), exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "category"), exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, articles: List[Dict], zip_code: Optional[str] = None, city_state: Optional[str] = None):
        """Generate complete website with incremental updates
        Phase 6: Now supports city_state for city-based generation

        Args:
            articles: List of articles to generate
            zip_code: Optional zip code for zip-specific generation
            city_state: Optional city_state (e.g., "Fall River, MA") for city-based generation
        """
        try:
            # Phase 6: Default to Fall River (02720) if no zip_code or city_state provided
            if not zip_code and not city_state:
                zip_code = '02720'  # Default to Fall River, MA
                logger.info(f"No location specified, defaulting to zip code: {zip_code}")

            # Phase 6: Resolve city_state if not provided
            if not city_state and zip_code:
                try:
                    from zip_resolver import get_city_state_for_zip
                    city_state = get_city_state_for_zip(zip_code)
                except Exception as e:
                    logger.warning(f"Error resolving city_state for zip {zip_code}: {e}")

            # Phase 6: Set output directory based on clean zip structure
            original_output_dir = self.output_dir
            if zip_code:
                # Clean zip-based structure: build/zips/zip_XXXXX/
                self.output_dir = os.path.join("build", "zips", f"zip_{zip_code.zfill(5)}")
                os.makedirs(self.output_dir, exist_ok=True)
                # Create subdirectories
                os.makedirs(os.path.join(self.output_dir, "css"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "js"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "images"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "category"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "meetings"), exist_ok=True)
                logger.info(f"Generating website for zip {zip_code} in {self.output_dir} with {len(articles)} articles...")
            else:
                # Default to Fall River if no zip code provided
                zip_code = '02720'
                self.output_dir = os.path.join("build", "zips", f"zip_{zip_code.zfill(5)}")
                os.makedirs(self.output_dir, exist_ok=True)
                # Create subdirectories
                os.makedirs(os.path.join(self.output_dir, "css"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "js"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "images"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "category"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "meetings"), exist_ok=True)
                logger.info(f"Generating website for default zip {zip_code} in {self.output_dir} with {len(articles)} articles...")
            
            # Check if we can do incremental update
            last_article_id = self._get_last_generated_article_id()
            new_articles = self._get_new_articles(articles, last_article_id)
            
            # Auto-expire old flags before generation
            if zip_code:
                try:
                    from admin.utils import expire_old_flags
                    expire_result = expire_old_flags(zip_code)
                    if expire_result.get('expired_count', 0) > 0:
                        logger.info(f"Auto-expired {expire_result['expired_count']} flags for zip {zip_code}")
                except Exception as e:
                    logger.warning(f"Could not expire old flags: {e}")
            
            # Use incremental generation which includes index.html generation
            logger.info("Incremental regeneration: generating index and category pages")
            self._generate_incremental(articles, new_articles, last_article_id, zip_code)
            
            # Update last article ID
            if articles:
                article_ids = [a.get('id', 0) for a in articles if a.get('id')]
                if article_ids:
                    max_id = max(article_ids)
                    self._update_last_generated_article_id(max_id)
            
            # Restore original output directory
            self.output_dir = original_output_dir
        except Exception as e:
            logger.error(f"Error generating website: {e}", exc_info=True)
            # Fallback to full generation on error
            try:
                self._generate_full(articles, zip_code, city_state)
            except Exception as e2:
                logger.error(f"Full generation also failed: {e2}", exc_info=True)
                raise
            finally:
                # Always restore original output directory
                self.output_dir = original_output_dir
    
    def _generate_full(self, articles: List[Dict], zip_code: Optional[str] = None, city_state: Optional[str] = None):
        """Generate complete website from scratch
        Phase 6: Now supports city_state for city-based generation
        
        Args:
            articles: List of articles
            zip_code: Optional zip code for zip-specific generation
            city_state: Optional city_state (e.g., "Fall River, MA") for city-based generation
        """
        logger.info("=" * 60)
        logger.info(f"Starting full website generation (zip: {zip_code}, city_state: {city_state})")
        logger.info(f"Processing {len(articles)} articles")
        logger.info("=" * 60)
        
        logger.info("Step 1/6: Loading admin settings...")
        admin_settings = self._get_admin_settings()
        logger.info("✓ Admin settings loaded")
        
        logger.info("Step 2/6: Filtering enabled articles...")
        enabled_articles = self._get_enabled_articles(articles, admin_settings, zip_code=zip_code, city_state=city_state)
        logger.info(f"✓ Filtered to {len(enabled_articles)} enabled articles (from {len(articles)} total)")
        
        logger.info("Step 3/6: Fetching weather data...")
        # CACHING DISABLED - Always fetch fresh weather data
        logger.info("[CACHE] ⚠️ Weather caching DISABLED - fetching fresh data")
        weather = self.weather_ingestor.fetch_weather()
        logger.info("✓ Weather data fetched (fresh)")

        logger.info("Step 4/6: Generating index page...")
        self._generate_index(enabled_articles, weather, admin_settings, zip_code)
        logger.info("  ✓ Index page generated")

        logger.info("Step 5/6: Generating category pages...")
        # Generate category pages for all categories
        categories_to_generate = ['business', 'crime', 'events', 'food', 'local-news', 'meetings', 'obituaries', 'scanner', 'schools', 'sports', 'weather']
        for category_slug in categories_to_generate:
            try:
                self._generate_category_page(category_slug, enabled_articles, weather, admin_settings, zip_code)
                logger.info(f"  ✓ Generated {category_slug} category page")
            except Exception as e:
                logger.warning(f"Failed to generate {category_slug} category page: {e}")

        logger.info("Step 6/6: Generating CSS and JS files...")
        self._generate_css()
        logger.info("  ✓ CSS generated")
        self._generate_js()
        logger.info("  ✓ JS generated")
        self._copy_static_js_files()
        logger.info("  ✓ Static JS files copied")
        
        logger.info("=" * 60)
        logger.info(f"✓ Website fully regenerated in {self.output_dir}")
        logger.info("=" * 60)
    
    def _generate_incremental(self, all_articles: List[Dict], new_articles: List[Dict], last_article_id: int, zip_code: Optional[str] = None):
        """Generate website incrementally - only update changed pages
        
        Args:
            all_articles: All articles
            new_articles: New articles since last generation
            last_article_id: Last article ID from previous generation
            zip_code: Optional zip code for zip-specific generation
        """
        admin_settings = self._get_admin_settings()
        enabled_articles = self._get_enabled_articles(all_articles, admin_settings, zip_code=zip_code)
        weather = self.weather_ingestor.fetch_weather()
        
        # Always regenerate index (it shows all articles)
        try:
            self._generate_index(enabled_articles, weather, admin_settings, zip_code)
            logger.info("Regenerated index.html")
        except Exception as e:
            logger.error(f"Failed to generate index: {e}")
            raise
        except Exception as e:
            print(f"DEBUG: _generate_index failed: {e}")
            logger.error(f"Failed to generate index: {e}")
            raise
        
        # CSS and JS only if they don't exist or are old
        css_path = Path(self.output_dir) / "css" / "style.css"
        js_path = Path(self.output_dir) / "js" / "main.js"
        
        if not css_path.exists():
            self._generate_css()
            logger.info("Regenerated CSS")
        
        if not js_path.exists():
            self._generate_js()
            logger.info("Regenerated JS")
        
        # Always copy static JS files in incremental updates to ensure weather.js is current
        self._copy_static_js_files()
        
        logger.info(f"Incremental update complete in {self.output_dir}")
    
    def _get_last_generated_article_id(self) -> int:
        """Get the last article ID that was included in website generation"""
        try:
            with self.get_db_cursor() as cursor:
                cursor.execute('SELECT last_article_id FROM website_generation ORDER BY id DESC LIMIT 1')
                row = cursor.fetchone()
                return row[0] if row and row[0] else 0
        except Exception as e:
            logger.warning(f"Could not get last generated article ID: {e}")
            return 0
    
    def _update_last_generated_article_id(self, article_id: int):
        """Update the last article ID that was included in website generation"""
        try:
            with self.get_db_cursor() as cursor:
                cursor.execute('''
                    INSERT OR REPLACE INTO website_generation (id, last_article_id, last_generation_time)
                    VALUES (1, ?, ?)
                ''', (article_id, datetime.now().isoformat()))
        except Exception as e:
            logger.warning(f"Could not update last article ID: {e}")
    
    def _get_new_articles(self, articles: List[Dict], last_article_id: int) -> List[Dict]:
        """Get articles that are newer than last generated article ID"""
        return [a for a in articles if a.get('id', 0) > last_article_id]
    
    def _get_db_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(DATABASE_CONFIG["path"])
        conn.row_factory = sqlite3.Row
        return conn

    def get_db_cursor(self):
        """Context manager for database cursor"""
        from contextlib import contextmanager

        @contextmanager
        def _cursor_manager():
            conn = self._get_db_connection()
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        return _cursor_manager()

    def _get_admin_settings(self) -> Dict:
        """Get admin settings from database"""
        try:
            with self.get_db_cursor() as cursor:
                cursor.execute('SELECT key, value FROM admin_settings')
                settings = {row['key']: row['value'] for row in cursor.fetchall()}
                return settings
        except Exception as e:
            logger.warning(f"Could not load admin settings: {e}")
            return {'show_images': '1'}
    
    def _get_enabled_articles(self, articles: List[Dict], settings: Dict, zip_code: Optional[str] = None, city_state: Optional[str] = None) -> List[Dict]:
        """Filter and order articles based on admin settings and zip-specific threshold
        Phase 2: Now supports city_state for city-based filtering
        
        Args:
            articles: List of article dicts
            settings: Admin settings dict
            zip_code: Optional zip code for zip-specific filtering
            city_state: Optional city_state for city-based filtering
        """
        try:
            with self.get_db_cursor() as cursor:
                # Get relevance threshold for zip if provided
                relevance_threshold = None
                if zip_code:
                    cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?',
                                 (zip_code, 'relevance_threshold'))
                    threshold_row = cursor.fetchone()
                    if threshold_row:
                        try:
                            relevance_threshold = float(threshold_row[0])
                        except (ValueError, TypeError):
                            pass

                article_ids = [a.get('id') for a in articles if a.get('id')]

                # Get article management filtered by zip_code if provided
                if zip_code:
                    management = self._get_article_management_for_zip(cursor, article_ids, zip_code)
                else:
                    management = self._get_article_management(cursor, article_ids)
            
            # Filter articles
            enabled = self._filter_and_sort_articles(articles, management)

            # Apply relevance threshold filter if zip_code provided
            # BUT exclude obituaries - they should always show on obit page regardless of relevance
            if zip_code and relevance_threshold is not None:
                enabled_before_filter = len(enabled)
                enabled = [
                    a for a in enabled 
                    if (a.get('relevance_score') or 0) >= relevance_threshold 
                    or (a.get('category', '').lower() in ['obituaries', 'obituary', 'obits'])
                    or ((a.get('primary_category', '') or '').lower() in ['obituaries', 'obituary', 'obits'])
                ]
                logger.info(f"Filtered to {len(enabled)} articles above threshold {relevance_threshold} for zip {zip_code}")
            
            return enabled
        except Exception as e:
            logger.warning(f"Could not load article management: {e}")
            return articles
    
    def _get_article_management_for_zip(self, cursor, article_ids: List[int], zip_code: str) -> Dict:
        """Get article management data from database for a specific zip code"""
        if not article_ids:
            return {}
        
        placeholders = ','.join('?' * len(article_ids))
        cursor.execute(f'''
            SELECT article_id, enabled, display_order,
                   COALESCE(is_top_article, 0) as is_top_article,
                   COALESCE(is_top_story, 0) as is_top_story,
                   COALESCE(is_alert, 0) as is_alert,
                   COALESCE(is_rejected, 0) as is_rejected,
                   ROWID as management_rowid,
                   COALESCE(updated_at, '1970-01-01T00:00:00') as updated_at
            FROM article_management
            WHERE article_id IN ({placeholders}) AND zip_code = ?
            AND ROWID IN (
                SELECT MAX(ROWID)
                FROM article_management
                WHERE article_id IN ({placeholders}) AND zip_code = ?
                GROUP BY article_id
            )
        ''', tuple(article_ids) + (zip_code,) + tuple(article_ids) + (zip_code,))
        
        rows = cursor.fetchall()

        management_data = {}
        for row in rows:
            article_id = row[0]  # article_id
            management_data[article_id] = {
                'enabled': bool(row[1]),  # enabled
                'order': row[2],  # display_order
                'is_top': row[3],  # is_top_article
                'is_top_story': row[4],  # is_top_story
                'is_alert': row[5],  # is_alert
                'is_rejected': bool(row[6]),  # is_rejected
                'management_rowid': row[7],  # management_rowid
                'updated_at': row[8]  # updated_at
            }

        return management_data
    
    def _get_article_management(self, cursor, article_ids: List[int]) -> Dict:
        """Get article management data from database - get only one entry per article"""
        if not article_ids:
            return {}
        
        placeholders = ','.join('?' * len(article_ids))
        # Get only one management entry per article - use the MOST RECENT one (MAX ROWID)
        # This ensures we get the latest enabled/disabled state
        cursor.execute(f'''
            SELECT article_id, enabled, display_order,
                   COALESCE(is_top_article, 0) as is_top_article,
                   COALESCE(is_top_story, 0) as is_top_story,
                   COALESCE(is_alert, 0) as is_alert,
                   COALESCE(is_rejected, 0) as is_rejected,
                   ROWID as management_rowid,
                   COALESCE(updated_at, '1970-01-01T00:00:00') as updated_at
            FROM article_management
            WHERE article_id IN ({placeholders})
            AND ROWID IN (
                SELECT MAX(ROWID)
                FROM article_management
                WHERE article_id IN ({placeholders})
                GROUP BY article_id
            )
        ''', article_ids + article_ids)
        
        return {
            row['article_id']: {
                'enabled': bool(row['enabled']),  # Ensure boolean
                'order': row['display_order'],
                'is_top': row['is_top_article'],
                'is_top_story': row['is_top_story'],
                'is_alert': row['is_alert'],
                'is_rejected': bool(row['is_rejected']),
                'management_rowid': row['management_rowid'],
                'updated_at': row['updated_at']
            }
            for row in cursor.fetchall()
        }
    
    def _filter_and_sort_articles(self, articles: List[Dict], management: Dict) -> List[Dict]:
        """Filter enabled articles and apply sorting - only show articles that are enabled"""
        enabled = []
        for article in articles:
            article_id = article.get('id')
            if article_id and article_id in management:
                # Skip rejected articles
                if management[article_id].get('is_rejected', 0):
                    continue
                # Article has management entry - only include if enabled
                if management[article_id]['enabled']:
                    article['_display_order'] = management[article_id]['order']
                    article['_is_top'] = management[article_id].get('is_top', 0)
                    article['_is_top_story'] = management[article_id].get('is_top_story', 0)
                    article['_is_alert'] = management[article_id].get('is_alert', 0)
                    article['_management_rowid'] = management[article_id].get('management_rowid', 0)
                    article['_top_story_updated_at'] = management[article_id].get('updated_at', '1970-01-01T00:00:00')
                    enabled.append(article)
                # If disabled, skip it (don't add to enabled list)
            else:
                # No management entry - default to enabled (new articles are enabled by default)
                article['_display_order'] = article_id or 0
                article['_is_top'] = 0
                article['_is_top_story'] = 0
                article['_is_alert'] = 0
                article['_management_rowid'] = 0
                enabled.append(article)
        
        # Sort by: 1) is_top_story, 2) created_at (ingestion date - newest first), 3) display_order
        # Use created_at (when article came in) to show newest articles first
        def get_ingestion_timestamp(article):
            # Use created_at (ingestion date) - when the article came in
            created = article.get('created_at', '')
            if created:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created.replace('Z', '+00:00').split('+')[0].split('.')[0])
                    return dt.timestamp()  # Return timestamp for proper numeric sorting
                except Exception as e:
                    logger.warning(f"Could not parse datetime with timezone: {e}")
                    try:
                        # Try parsing as datetime string without timezone
                        dt = datetime.fromisoformat(created.split('T')[0])
                        return dt.timestamp()
                    except Exception as e:
                        pass
            # Fallback to article ID (newer articles have higher IDs)
            article_id = article.get('id', 0)
            if article_id:
                return float(article_id)  # Use ID as timestamp proxy
            return 0  # No date found, put at end
        
        # Sort: 1) is_top_story (top stories first), 2) created_at DESC (newest first), 3) display_order
        enabled.sort(key=lambda x: (
            -x.get('_is_top_story', 0),  # Top stories first (negative for descending)
            -get_ingestion_timestamp(x),  # Newest first by ingestion time (negative for descending)
            x.get('_display_order', 0)  # Then by display order
        ))
        return enabled
    
    def _filter_articles_by_category(self, articles: List[Dict], category_slug: str) -> List[Dict]:
        """Filter articles by category slug using mapping and keyword fallback
        
        Args:
            articles: List of article dicts
            category_slug: Category slug to filter by (e.g., 'local-news', 'crime')
        
        Returns:
            Filtered list of articles matching the category
        """
        if category_slug not in CATEGORY_SLUGS:
            return []
        
        filtered = []
        
        # Keywords for each category (for fallback matching)
        category_keywords = {
            "local-news": ["news", "update", "report", "announcement", "city", "town", "community", "local"],
            "crime": ["crime", "police", "arrest", "suspect", "investigation", "charges", "court", "trial", "criminal", "officer", "detective", "murder", "robbery", "theft", "assault"],
            "sports": ["sport", "football", "basketball", "baseball", "hockey", "athlete", "game", "team", "player", "coach", "championship", "score"],
            "events": ["event", "concert", "show", "festival", "entertainment", "performance", "celebration", "music", "theater"],
            "weather": ["weather", "forecast", "temperature", "rain", "snow", "storm", "climate"],
            "business": ["business", "company", "development", "economic", "commerce", "retail", "store", "shop", "restaurant", "opening", "closing"],
            "schools": ["school", "student", "teacher", "education", "academic", "college", "university", "graduation", "principal", "classroom"],
            "food": ["food", "restaurant", "dining", "cafe", "menu", "chef", "cuisine", "meal", "recipe", "kitchen"],
            "obituaries": ["obituary", "death", "passed away", "memorial", "funeral", "died", "remembered", "services", "survived by", "predeceased"]
        }
        
        keywords = category_keywords.get(category_slug, [])
        
        # Get list of funeral home sources for obituaries filtering
        funeral_home_sources = set()
        if category_slug == "obituaries":
            from config import NEWS_SOURCES
            for source_key, source_config in NEWS_SOURCES.items():
                if source_config.get("category", "").lower() == "obituaries":
                    funeral_home_sources.add(source_config.get("name", "").lower())
                    funeral_home_sources.add(source_key.lower())
        
        for article in articles:
            article_category = article.get('category', '').lower() if article.get('category') else ''
            article_primary_category = (article.get('primary_category', '') or '').lower()
            article_source = (article.get('source', '') or '').lower()
            article_source_display = (article.get('source_display', '') or '').lower()
            already_added = False

            # For obituaries: STRICT filtering - exclude news/crime/articles and informational content
            if category_slug == "obituaries":
                # Check primary_category FIRST - if it's obits/obituaries, skip exclusion checks and add immediately
                is_obit_by_primary = article_primary_category in ["obituaries", "obituary", "obits"]
                is_obit_by_category = article_category in ["obituaries", "obituary", "obits"]
                
                # If already identified as obituary by primary_category or category, add it immediately
                if is_obit_by_primary:
                    filtered.append(article)
                    already_added = True
                elif is_obit_by_category:
                    
                    filtered.append(article)
                    already_added = True
                
                # Only run exclusion checks if NOT already identified as obituary
                if not already_added:
                    # EXCLUDE informational/educational articles about obituaries FIRST
                    title_lower = (article.get('title', '') or '').lower()
                    informational_patterns = [
                        "how to write", "how to", "coping with", "guide to", "tips for",
                        "what is", "understanding", "explaining", "about obituaries",
                        "writing an obituary", "obituary writing", "obituary guide",
                        "learn about", "everything you need to know"
                    ]
                    if any(pattern in title_lower for pattern in informational_patterns):
                        continue  # Skip informational articles
                    
                    # EXCLUDE suicide/murder/homicide articles - these are crime, not obituaries
                    combined = f"{(article.get('title', '') or '').lower()} {(article.get('content', '') or article.get('summary', '') or '').lower()}"
                    exclusion_keywords = [
                        "suicide", "murder", "homicide", "killed", "shot", "stabbed", 
                        "died in crash", "died in accident", "died in fire", "fatal",
                        "police investigation", "arrest", "charges", "suspect"
                    ]
                    matched_exclusion = [kw for kw in exclusion_keywords if kw in combined]
                    if matched_exclusion:
                        
                        continue  # Skip crime/suicide articles - not obituaries
                    
                    # Check if source is a funeral home (most reliable) - these are ALWAYS obituaries
                    for funeral_source in funeral_home_sources:
                        if funeral_source and (funeral_source in article_source or funeral_source in article_source_display):
                            # For funeral home sources, still check it's an actual obituary (not a general page)
                            # But be more lenient - if it's from a funeral home, it's likely an obituary
                            combined_check = f"{(article.get('title', '') or '').lower()} {(article.get('content', '') or article.get('summary', '') or '').lower()}"
                            if any(keyword in combined_check for keyword in ["obituary", "passed away", "died", "survived by", "memorial", "funeral"]):
                                filtered.append(article)
                                already_added = True
                                break
                    
                    # EXCLUDE articles that are explicitly categorized as news, crime, sports, or other non-obituary categories
                    # BUT only if primary_category is NOT obituaries/obits (primary_category takes precedence)
                    if not already_added and article_category and article_category not in ["obituaries", "obituary", "obits", "", None]:
                        if article_category in ["news", "crime", "sports", "entertainment", "business", "schools", "food", "local-news"]:
                            
                            continue  # Explicitly categorized as non-obituary - skip it
            
            # First, try direct category mapping
            mapped_slug = CATEGORY_MAPPING.get(article_category, '')
            if mapped_slug == category_slug:
                filtered.append(article)
                already_added = True
                continue
            
            # Also check if article_category directly matches category_slug (for cases like "sports" -> "sports", "crime" -> "crime")
            if article_category == category_slug:
                filtered.append(article)
                already_added = True
                continue
            
            # Only use keyword matching if no exact category match AND article has no category assigned
            # This prevents false positives (e.g., "funeral home" matching non-obituary articles)
            # Only match if article has no category OR category doesn't match any known category
            if not already_added and keywords and (not article_category or article_category not in CATEGORY_MAPPING and article_category not in CATEGORY_SLUGS.values()):
                title = (article.get('title', '') or '').lower()
                content = (article.get('content', '') or article.get('summary', '') or '').lower()
                combined = f"{title} {content}"
                
                # For obituaries, require STRONG obituary indicators
                if category_slug == "obituaries" and not already_added:
                    # EXCLUDE articles that are clearly news/accidents
                    news_exclusion_patterns = [
                        "fire", "accident", "crash", "injured", "killed in", "died in", "dead in", 
                        "fatal crash", "fatal accident", "fatal fire", "police", "arrest", "investigation",
                        "condo fire", "house fire", "car crash", "motor vehicle"
                    ]
                    has_news_keywords = any(keyword in combined for keyword in news_exclusion_patterns)
                    has_obituary_context = any(keyword in combined for keyword in ["obituary", "survived by", "memorial service", "funeral service", "visitation", "wake", "calling hours", "funeral home"])
                    
                    if has_news_keywords and not has_obituary_context:
                        continue  # News article, not obituary
                    
                    # Require STRONG obituary indicators - not just mentioning "obituary" in passing
                    strong_keywords = ["passed away", "survived by", "predeceased", "memorial service", "funeral service", "visitation", "wake", "calling hours", "funeral home", "memorial visitation"]
                    
                    # Check if title is just a name (common obituary format: "John Smith" or "John Smith, 85")
                    title_words = title.split()
                    is_name_only = len(title_words) <= 4 and not has_news_keywords
                    
                    # Only include if it has strong obituary keywords OR is just a name
                    if any(keyword in combined for keyword in strong_keywords):
                        filtered.append(article)
                    elif is_name_only:
                        # Short title with just a name - likely an obituary
                        filtered.append(article)
                    elif ("died" in combined or "passed" in combined) and (has_obituary_context or is_name_only or (len(title_words) <= 5 and "died" in title.lower())):
                        # Include if it has obituary context OR if it's just a name + "died"
                        filtered.append(article)
                    # Don't include articles that just mention "obituary" without strong indicators
                elif category_slug == "crime":
                    # For crime, require crime-specific keywords (not just "police" which could be in many contexts)
                    crime_keywords = ["arrest", "crime", "charges", "suspect", "investigation", "court", "trial", "criminal", "murder", "robbery", "theft", "assault"]
                    if any(keyword in combined for keyword in crime_keywords):
                        filtered.append(article)
                elif category_slug == "sports":
                    # For sports, require sport-specific keywords
                    sport_keywords = ["sport", "football", "basketball", "baseball", "hockey", "athlete", "game", "team", "player", "coach", "championship", "score"]
                    if any(keyword in combined for keyword in sport_keywords):
                        filtered.append(article)
                else:
                    # For other categories, check if any keywords match
                    for keyword in keywords:
                        if keyword in combined:
                            filtered.append(article)
                            break
        
        # Deduplicate by article ID to prevent showing the same article multiple times
        seen_ids = set()
        deduplicated = []
        for article in filtered:
            article_id = article.get('id')
            if article_id and article_id not in seen_ids:
                seen_ids.add(article_id)
                deduplicated.append(article)
            elif not article_id:
                # Articles without IDs - include them but check by URL
                url = article.get('url', '')
                if url and url not in seen_ids:
                    seen_ids.add(url)
                    deduplicated.append(article)
                elif not url:
                    # No ID and no URL - include it (shouldn't happen but be safe)
                    deduplicated.append(article)
        
        return deduplicated
    
    def _generate_index(self, articles: List[Dict], weather: Dict, settings: Dict, zip_code: Optional[str] = None, city_state: Optional[str] = None):
        """Generate main index page
        Phase 6: Now supports city_state for dynamic city names
        
        Args:
            articles: List of articles
            weather: Weather data
            settings: Admin settings
            zip_code: Optional zip code for zip-specific generation
            city_state: Optional city_state (e.g., "Fall River, MA") for dynamic titles
        """
        show_images_val = settings.get('show_images', '1')
        if isinstance(show_images_val, bool):
            show_images = show_images_val
        elif isinstance(show_images_val, str):
            show_images = show_images_val.strip().lower() in ('1', 'true', 'yes', 'on')
        else:
            show_images = bool(show_images_val)
        
        # Skip template rendering for safety - use simple HTML
        html = f"<html><body><h1>{self.title}</h1><p>Generated at {datetime.now()}</p></body></html>"

        # Write the HTML to file
        with open(os.path.join(self.output_dir, "index.html"), "w", encoding="utf-8", errors='replace') as f:
            f.write(html)
            # Resolve zip code to city/state if city_state not provided
            from zip_resolver import resolve_zip
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "")
                state = zip_data.get("state_abbrev", "")
                locale_name = f"{city}, {state}" if city and state else f"Zip {zip_code}"
            else:
                locale_name = f"Zip {zip_code}"
        
        # Always lead with latest news on home page
        # Separate articles by category
        news_articles = [a for a in articles if a.get('category') == 'news'][:50]
        entertainment_articles = [a for a in articles if a.get('category') == 'entertainment'][:20]
        sports_articles = [a for a in articles if a.get('category') == 'sports'][:20]
        
        # For home page, prioritize news articles first
        all_articles = news_articles + [a for a in articles if a.get('category') != 'news'][:30]
        
        # If no articles, show message
        if not all_articles:
            all_articles = articles  # Fallback to all if filtered list is empty
        
        # Sort all articles by publication date (newest first) - CRITICAL FIX
        all_articles.sort(key=lambda x: (
            x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
        ), reverse=True)
        
        # Get top stories (articles marked as top stories)
        top_stories = [a for a in articles if a.get('_is_top_story', 0)]
        # Sort by updated_at DESC (newest top hat clicks first), then by display_order
        # This ensures articles marked most recently by admin appear first
        def parse_timestamp(ts_str):
            try:
                from datetime import datetime
                return datetime.fromisoformat(ts_str.replace('Z', '+00:00').split('+')[0]).timestamp()
            except Exception as e:
                logger.warning(f"Could not parse timestamp: {e}")
                return 0  # Default to oldest if parsing fails

        top_stories.sort(key=lambda x: (
            -parse_timestamp(x.get('_top_story_updated_at', '1970-01-01T00:00:00')),  # Newest clicked first (negative for descending)
            x.get('_display_order', 0)  # Then by display_order
        ))
        if not top_stories:
            # Fallback to first 5 news articles if no top stories marked
            top_stories = news_articles[:5] if news_articles else articles[:5]
        
        # Get trending articles (recent articles with high relevance scores)
        # Excludes obituaries and returns top 10 (client-side will filter to top 5 based on user preferences)
        try:
            from website_generator.utils import get_trending_articles
            trending_articles = get_trending_articles(articles)
        except ImportError:
            # Fallback to old method - get more articles to account for client-side filtering
            trending_articles = self._get_trending_articles(articles, limit=10)
        
        # Add category slug and format trending date (no year) to each trending article
        for article in trending_articles:
            article_category = article.get('category', '').lower() if article.get('category') else ''
            
            # Map category to slug using CATEGORY_MAPPING
            # First check direct mapping
            if article_category in CATEGORY_SLUGS:
                category_slug = article_category
            elif article_category in CATEGORY_MAPPING:
                category_slug = CATEGORY_MAPPING[article_category]
            else:
                # Default to local-news for unknown categories
                category_slug = 'local-news'
            
            article['_category_slug'] = category_slug
            
            # Format trending date: remove year, keep time
            if article.get('formatted_date'):
                formatted_date = article['formatted_date']
                # Remove year from "January 15, 2024 at 3:45 PM" -> "January 15 at 3:45 PM"
                if ', ' in formatted_date and ' at ' in formatted_date:
                    parts = formatted_date.split(', ')
                    if len(parts) == 2:
                        date_part = parts[0]  # "January 15"
                        time_part = parts[1]  # "2024 at 3:45 PM"
                        if ' at ' in time_part:
                            time_only = time_part.split(' at ', 1)[1]  # "3:45 PM"
                            article['_trending_date'] = f"{date_part} at {time_only}"
                        else:
                            article['_trending_date'] = date_part
                    else:
                        article['_trending_date'] = formatted_date
                else:
                    article['_trending_date'] = formatted_date
            else:
                article['_trending_date'] = 'Recently'
        
        # Get latest stories (5 most recent by publication date, excluding top stories)
        latest_stories = [a for a in articles if not a.get('_is_top_story', 0)]
        # Sort by published date (newest first)
        latest_stories.sort(key=lambda x: (
            x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
        ), reverse=True)
        latest_stories = latest_stories[:5]
        
        # Get newest articles (simple chronological order, newest first, no algorithm)
        newest_articles = list(articles)  # Copy the list
        # Sort by publication date (newest first) - pure chronological order
        newest_articles.sort(key=lambda x: (
            x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
        ), reverse=True)
        newest_articles = newest_articles[:10]  # Take top 10 newest articles
        
        # Add related articles to each article
        from aggregator import NewsAggregator
        aggregator = NewsAggregator()
        for article in all_articles:
            related = aggregator._find_related_articles(article, all_articles, limit=3)
            article['_related_articles'] = related[:3]  # Limit to 3 related articles
        
        # Enrich articles with source initials, gradients, and glow colors
        for article in all_articles:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
            if 'source_glow_color' not in article:
                article['source_glow_color'] = self._get_source_glow_color(article.get('source_display', article.get('source', '')))
        for article in top_stories:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
            if 'source_glow_color' not in article:
                article['source_glow_color'] = self._get_source_glow_color(article.get('source_display', article.get('source', '')))
        for article in trending_articles:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
            if 'source_glow_color' not in article:
                article['source_glow_color'] = self._get_source_glow_color(article.get('source_display', article.get('source', '')))
        for article in latest_stories:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
            if 'source_glow_color' not in article:
                article['source_glow_color'] = self._get_source_glow_color(article.get('source_display', article.get('source', '')))
        for article in newest_articles:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
            if 'source_glow_color' not in article:
                article['source_glow_color'] = self._get_source_glow_color(article.get('source_display', article.get('source', '')))
        for article in entertainment_articles:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
            if 'source_glow_color' not in article:
                article['source_glow_color'] = self._get_source_glow_color(article.get('source_display', article.get('source', '')))
        
        # Optimize images for articles (only when hotlinking is disabled)
        # When hotlinking is enabled (show_images=True), preserve external URLs
        if not show_images:
            # Remove external image URLs when images are disabled
            for article in all_articles:
                article['image_url'] = None
            for article in top_stories:
                article['image_url'] = None
            for article in entertainment_articles:
                article['image_url'] = None
        
        # Get hero articles (top 3 stories for carousel)
        hero_articles = top_stories[:3] if len(top_stories) >= 3 else (top_stories if top_stories else [])
        

        # Get top article (single featured article)
        top_article = None
        for article in all_articles:
            if article.get('_is_top', 0):
                top_article = article
                break
        
        # Get alert articles (urgent notifications)
        alert_articles = [a for a in all_articles if a.get('_is_alert', 0)]
        # Sort alerts by updated_at DESC (newest first)
        alert_articles.sort(key=lambda x: (
            -parse_timestamp(x.get('_top_story_updated_at', '1970-01-01T00:00:00')),
            x.get('_display_order', 0)
        ))
        
        # DEBUG: Log hero articles for troubleshooting slider
        logger.info(f"HERO ARTICLES COUNT: {len(hero_articles)}")
        for i, article in enumerate(hero_articles):
            logger.info(f"  Hero [{i}]: title='{article.get('title', 'NO TITLE')[:50]}' | "
                       f"image_url={bool(article.get('image_url'))} | "
                       f"top_story={article.get('_is_top_story', 0)} | "
                       f"category={article.get('category', 'N/A')} | "
                       f"id={article.get('id', 'N/A')}")
        
        # Get IDs of featured articles to exclude from main grid
        featured_ids = set()
        for hero_article in hero_articles:
            if hero_article and hero_article.get('id'):
                featured_ids.add(hero_article.get('id'))
        
        # Filter out featured articles from main grid
        grid_articles = [a for a in all_articles if a.get('id') not in featured_ids]
        
        # Add video detection to articles
        for hero_article in hero_articles:
            if hero_article:
                hero_article['_is_video'] = self._is_video_article(hero_article)
        for article in grid_articles:
            article['_is_video'] = self._is_video_article(article)
        for article in trending_articles:
            article['_is_video'] = self._is_video_article(article)
        
        # Get weather condition for body class
        weather_condition = weather.get('current', {}).get('condition', 'clear').lower().replace(' ', '-')
        # Normalize common weather terms
        if 'rain' in weather_condition or 'shower' in weather_condition:
            weather_condition = 'rain'
        elif 'snow' in weather_condition:
            weather_condition = 'snow'
        elif 'storm' in weather_condition or 'thunder' in weather_condition or "nor'easter" in weather_condition.lower():
            weather_condition = 'storm'
        elif 'cloud' in weather_condition:
            weather_condition = 'cloud'
        elif 'sun' in weather_condition or 'clear' in weather_condition:
            weather_condition = 'sun'
        
        # Get unique sources for filtering
        unique_sources = sorted(set(a.get('source', '') for a in articles if a.get('source')))
        
        nav_tabs = self._get_nav_tabs("home", zip_code)
        
        # Prepare location badge data
        location_badge_text = "Fall River · 02720"
        if zip_code:
            from zip_resolver import resolve_zip
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "Fall River")
                location_badge_text = f"{city} · {zip_code}"
            else:
                location_badge_text = f"Fall River · {zip_code}"

        # Phase 9: Zip pin editability flag (from admin_settings)
        zip_pin_editable = False
        try:
            # Prefer settings dict if present
            if 'zip_pin_editable' in settings:
                zip_pin_editable = str(settings.get('zip_pin_editable')) == '1'
            else:
                conn = self._get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('zip_pin_editable',))
                row = cursor.fetchone()
                conn.close()
                zip_pin_editable = row[0] == '1' if row else False
        except Exception as e:
            logger.warning(f"Could not determine zip pin editability: {e}")
            zip_pin_editable = False
        
        # Phase 6: Update title and description with dynamic city name
        title = f"{locale_name} News Aggregator" if (zip_code or city_state) else self.title
        description = f"Latest news from {locale_name}" if (zip_code or city_state) else self.description
        
        # Get weather API key - check database first, then fall back to config
        # Default to "02720" (Fall River) if zip_code is not provided
        lookup_zip = zip_code or "02720"
        
        # Get weather station URL - check database first, then fall back to weather_ingestor
        weather_station_url = ""
        if lookup_zip:
            try:
                conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
                cursor = conn.cursor()
                cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', (lookup_zip, 'weather_station_url'))
                row = cursor.fetchone()
                if row and row[0]:
                    weather_station_url = row[0]
                conn.close()
            except Exception as e:
                logger.warning(f"Could not load weather station URL from database: {e}")
        
        # Fall back to weather_ingestor method if not in database
        if not weather_station_url:
            weather_station_url = self.weather_ingestor.get_primary_weather_station_url()
        
        # Get weather icon based on condition
        weather_icon = self._get_weather_icon(weather.get('current', {}).get('condition', ''))
        weather_api_key = ""
        
        
        with open(os.path.join(self.output_dir, "index.html"), "w", encoding="utf-8", errors='replace') as f:
            f.write(html)
    
    def _get_nav_tabs(self, active_page: str = "home", zip_code: Optional[str] = None, is_category_page: bool = False) -> str:
        """Generate two-row navigation structure for top local news site
        
        Top row (big, bold): Home • Local • Police & Fire • Sports • Obituaries • Food & Drink
        Second row (smaller, lighter): Media • Scanner • Weather • Submit Tip • Lost & Found • Events
        
        Args:
            active_page: Current page identifier
            zip_code: Optional zip code for zip-specific pages
            is_category_page: If True, paths are relative from category/ subdirectory
        """
        # Use relative paths for navigation
        if is_category_page:
            home_href = "../index.html"
            category_prefix = ""
        else:
            home_href = "index.html"
            category_prefix = "category/"
        
        # Top row: Primary navigation (big, bold)
        # Note: "Local" replaces "Home" and shows mixed articles (all enabled articles)
        top_row_tabs = [
            ("Local", home_href, "all", "home"),
            ("Police & Fire", f"{category_prefix}crime.html" if category_prefix else "crime.html", None, "category-crime"),
            ("Sports", f"{category_prefix}sports.html" if category_prefix else "sports.html", None, "category-sports"),
            ("Obituaries", f"{category_prefix}obituaries.html" if category_prefix else "obituaries.html", None, "category-obituaries"),
            ("Food & Drink", f"{category_prefix}food.html" if category_prefix else "food.html", None, "category-food"),
        ]
        
        # Second row: Secondary navigation (slightly smaller, lighter)
        second_row_tabs = [
            ("Media", f"{category_prefix}media.html" if category_prefix else "media.html", None, "category-media"),
            ("Scanner", f"{category_prefix}scanner.html" if category_prefix else "scanner.html", None, "category-scanner"),
            ("Submit Tip", "#", None, "submit-tip"),  # Placeholder - implement later
            ("Lost & Found", "#", None, "lost-found"),  # Placeholder - implement later
            ("Events", f"{category_prefix}events.html" if category_prefix else "events.html", None, "category-events"),
        ]
        
        # Build navigation HTML with two-row structure
        nav_html = '''
    <!-- Desktop Navigation: Two Rows - Centered -->
    <div class="hidden lg:flex flex-col items-center gap-3 w-full">
        <!-- Top Row: Primary Navigation (Big, Bold) -->
        <div class="flex flex-wrap items-center justify-center gap-2 lg:gap-3">
'''
        
        # Top row links
        for i, (label, href, data_tab, page_key) in enumerate(top_row_tabs):
            # Check if this is the active page
            is_active = (active_page == page_key) or (page_key == "home" and (active_page == "home" or active_page == "all"))
            if is_active:
                active_class = 'text-white font-bold bg-blue-500/20 border border-blue-500/40'
                active_style = ''
            else:
                active_class = 'text-gray-300 hover:text-white font-bold border border-transparent hover:border-gray-700 hover:bg-gray-900/30'
                active_style = ''
            
            # Add category slug data attribute for category links (not Home)
            category_slug = None
            if page_key and page_key.startswith('category-'):
                category_slug = page_key.replace('category-', '')
            elif page_key in ['submit-tip', 'lost-found']:
                category_slug = page_key
            
            data_attr = f' data-tab="{data_tab}"' if data_tab else ''
            category_attr = f' data-category-slug="{category_slug}"' if category_slug else ''
            separator = ' <span class="text-gray-700 mx-2 text-sm">•</span> ' if i < len(top_row_tabs) - 1 else ''
            nav_html += f'            <a href="{href}" class="nav-category-link px-4 py-2.5 rounded-md text-base lg:text-lg font-bold transition-all duration-200 {active_class}"{active_style}{data_attr}{category_attr}>{label}</a>{separator}\n'
        
        nav_html += '''        </div>
        
        <!-- Second Row: Secondary Navigation (Smaller, Lighter) - Centered under first row -->
        <div class="flex flex-wrap items-center justify-center gap-2 lg:gap-3">
'''
        
        # Second row links
        for i, (label, href, data_tab, page_key) in enumerate(second_row_tabs):
            is_active = active_page == page_key
            if is_active:
                active_class = 'text-blue-300 font-semibold bg-blue-500/15 border border-blue-500/30'
                active_style = ''
            else:
                active_class = 'text-gray-500 hover:text-gray-300 font-medium border border-transparent hover:border-gray-800 hover:bg-gray-900/20'
                active_style = ''
            
            # Add category slug data attribute for category links
            category_slug = None
            if page_key and page_key.startswith('category-'):
                category_slug = page_key.replace('category-', '')
            elif page_key in ['submit-tip', 'lost-found']:
                category_slug = page_key
            
            data_attr = f' data-tab="{data_tab}"' if data_tab else ''
            category_attr = f' data-category-slug="{category_slug}"' if category_slug else ''
            separator = ' <span class="text-gray-800 mx-1.5 text-xs">•</span> ' if i < len(second_row_tabs) - 1 else ''
            nav_html += f'            <a href="{href}" class="nav-category-link px-3 py-1.5 rounded-md text-sm lg:text-base transition-all duration-200 {active_class}"{active_style}{data_attr}{category_attr}>{label}</a>{separator}\n'
        
        nav_html += '''        </div>
    </div>
    
    <!-- Custom Hamburger Menu - Side Drawer Overlay -->
    <div id="mobileNavMenu" class="hidden fixed inset-0 z-[1000] transition-opacity duration-300" style="opacity: 0;">
        <!-- Backdrop -->
        <div class="fixed inset-0 bg-black/70 backdrop-blur-sm z-[999]" onclick="closeHamburgerMenu()"></div>
        <!-- Side Drawer -->
        <div id="hamburgerDrawer" class="fixed top-0 right-0 h-full w-80 bg-[#161616] shadow-2xl overflow-y-auto transform transition-transform duration-300 ease-out z-[1000]" style="transform: translateX(100%);" onclick="event.stopPropagation()">
            <!-- Header -->
            <div class="sticky top-0 bg-gradient-to-r from-[#161616] to-[#1a1a1a] border-b border-gray-800/50 p-5 flex items-center justify-between z-10 shadow-lg">
                <div class="flex items-center gap-3">
                    <div class="text-2xl font-bold text-blue-400">FRNA</div>
                    <span class="text-xs text-gray-500 uppercase tracking-wider">Menu</span>
                </div>
                <button id="closeMobileNav" class="text-gray-400 hover:text-white transition-colors p-2 rounded-lg hover:bg-gray-800/50" aria-label="Close menu" onclick="closeHamburgerMenu()">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
            
            <!-- Menu Content -->
            <div class="p-5 space-y-6">
                <!-- Admin Section (Top) - Collapsible Submenu -->
                <div class="pb-4 border-b border-gray-800/50">
                    <button id="adminMenuToggle" class="w-full flex items-center justify-between px-4 py-3 rounded-lg bg-gradient-to-r from-blue-600/20 to-blue-500/10 border border-blue-500/30 hover:border-blue-500/50 transition-all group" onclick="toggleAdminSubmenu(event)">
                        <div class="flex items-center gap-3">
                            <div class="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center group-hover:bg-blue-500/30 transition-colors">
                                <svg class="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                                </svg>
                            </div>
                            <div>
                                <div class="text-white font-semibold">Admin Panel</div>
                                <div class="text-xs text-gray-400">Manage articles & settings</div>
                            </div>
                        </div>
                        <svg id="adminMenuArrow" class="w-5 h-5 text-gray-400 group-hover:text-white transition-transform duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                        </svg>
                    </button>
                    <!-- Admin Submenu (Hidden by default) -->
                    <div id="adminSubmenu" class="hidden mt-2 pl-4 space-y-2">
                        <a href="#" id="adminLink" class="block px-4 py-2 rounded-lg text-gray-300 hover:text-white hover:bg-[#1a1a1a]/50 transition-colors text-sm">Current Zip Admin</a>
                        <a href="/admin" class="block px-4 py-2 rounded-lg text-gray-300 hover:text-white hover:bg-[#1a1a1a]/50 transition-colors text-sm">Main Admin Dashboard</a>
                    </div>
                </div>
                
                <!-- Navigation Links Section -->
                <div class="space-y-4">
                    <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Navigation</div>
                    
                    <!-- Home Link (No Toggle) -->
                    <a href="''' + home_href + '''" class="flex items-center px-4 py-3 rounded-lg text-gray-200 hover:text-white hover:bg-[#1a1a1a] transition-colors border border-transparent hover:border-gray-800" data-tab="all">
                        <svg class="w-5 h-5 mr-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"></path>
                        </svg>
                        <span class="font-semibold">Home</span>
                    </a>
                </div>
                
                <!-- Category Controls Section -->
                <div class="space-y-4">
                    <div class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Category Controls</div>
                    <p class="text-xs text-gray-400 mb-4 px-2">Toggle categories on/off to customize your navigation</p>
                    
                    <!-- Primary Categories -->
                    <div class="space-y-2">
                        <div class="text-xs font-medium text-gray-500 px-2 mb-2">Primary Navigation</div>
'''
        
        # Primary categories with toggle switches
        for label, href, data_tab, page_key in top_row_tabs:
            # Skip Home - already added above
            if page_key == "home":
                continue
                
            # Get category slug
            category_slug = None
            if page_key and page_key.startswith('category-'):
                category_slug = page_key.replace('category-', '')
            elif page_key in ['submit-tip', 'lost-found']:
                category_slug = page_key
            
            if not category_slug:
                continue
            
            category_attr = f' data-category-slug="{category_slug}"'
            nav_html += f'''                        <div class="flex items-center justify-between px-4 py-3 rounded-lg bg-[#1a1a1a]/50 border border-gray-800/30 hover:border-gray-700 transition-colors" data-category-slug="{category_slug}">
                            <div class="flex items-center gap-3 flex-1">
                                <a href="{href}" class="nav-category-link text-gray-200 hover:text-white font-medium transition-colors flex-1"{category_attr}>{label}</a>
                            </div>
                            <label class="relative inline-flex items-center cursor-pointer ml-4">
                                <input type="checkbox" class="category-toggle-switch sr-only peer" data-category-slug="{category_slug}" checked>
                                <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-500/50 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                            </label>
                        </div>
'''
        
        nav_html += '''                    </div>
                    
                    <!-- Secondary Categories -->
                    <div class="space-y-2 pt-2">
                        <div class="text-xs font-medium text-gray-500 px-2 mb-2">Secondary Navigation</div>
'''
        
        # Secondary categories with toggle switches
        for label, href, data_tab, page_key in second_row_tabs:
            # Get category slug
            category_slug = None
            if page_key and page_key.startswith('category-'):
                category_slug = page_key.replace('category-', '')
            elif page_key in ['submit-tip', 'lost-found']:
                category_slug = page_key
            
            if not category_slug:
                continue
            
            category_attr = f' data-category-slug="{category_slug}"'
            nav_html += f'''                        <div class="flex items-center justify-between px-4 py-3 rounded-lg bg-[#1a1a1a]/50 border border-gray-800/30 hover:border-gray-700 transition-colors" data-category-slug="{category_slug}">
                            <div class="flex items-center gap-3 flex-1">
                                <a href="{href}" class="nav-category-link text-gray-200 hover:text-white font-medium transition-colors flex-1"{category_attr}>{label}</a>
                            </div>
                            <label class="relative inline-flex items-center cursor-pointer ml-4">
                                <input type="checkbox" class="category-toggle-switch sr-only peer" data-category-slug="{category_slug}" checked>
                                <div class="w-11 h-6 bg-gray-700 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-500/50 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                            </label>
                        </div>
'''
        
        nav_html += '''                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // Custom Hamburger Menu with Smooth Animations
        function openHamburgerMenu() {
            const menu = document.getElementById('mobileNavMenu');
            const drawer = document.getElementById('hamburgerDrawer');
            if (!menu || !drawer) {
                console.error('Hamburger menu elements not found:', { menu: !!menu, drawer: !!drawer });
                return;
            }
            
            menu.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
            
            // Trigger animation
            requestAnimationFrame(() => {
                menu.style.opacity = '1';
                drawer.style.transform = 'translateX(0)';
            });
            
            // Update toggle switch states
            updateToggleSwitches();
        }
        
        function closeHamburgerMenu() {
            const menu = document.getElementById('mobileNavMenu');
            const drawer = document.getElementById('hamburgerDrawer');
            if (!menu || !drawer) return;
            
            // Animate out
            menu.style.opacity = '0';
            drawer.style.transform = 'translateX(100%)';
            
            setTimeout(() => {
                menu.classList.add('hidden');
                document.body.style.overflow = '';
            }, 300);
        }
        
        function updateToggleSwitches() {
            // Wait for CategoryPreferences to be available
            if (!window.CategoryPreferences) {
                setTimeout(updateToggleSwitches, 100);
                return;
            }
            
            document.querySelectorAll('.category-toggle-switch').forEach(switchEl => {
                const categorySlug = switchEl.dataset.categorySlug;
                if (categorySlug) {
                    const isEnabled = window.CategoryPreferences.isCategoryEnabled(categorySlug);
                    switchEl.checked = isEnabled;
                }
            });
        }
        
        // Initialize menu - wait for DOM and CategoryPreferences
        function initHamburgerMenu() {
            const toggle = document.getElementById('mobileNavToggle');
            const menu = document.getElementById('mobileNavMenu');
            const closeBtn = document.getElementById('closeMobileNav');
            
            if (!toggle || !menu) {
                // Retry if elements not found yet
                setTimeout(initHamburgerMenu, 100);
                return;
            }
            
            // Hamburger button click handler
            toggle.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                openHamburgerMenu();
            });
            
            // Close button handler
            if (closeBtn) {
                closeBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    closeHamburgerMenu();
                });
            }
            
            // Close on backdrop click
            const backdrop = menu.querySelector('div.bg-black\\/70.backdrop-blur-sm');
            if (backdrop) {
                backdrop.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    closeHamburgerMenu();
                });
            }
            
            // Close on Escape key
            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape' && !menu.classList.contains('hidden')) {
                    closeHamburgerMenu();
                }
            });
            
            // Handle toggle switch changes
            menu.addEventListener('change', function(e) {
                if (e.target.classList.contains('category-toggle-switch')) {
                    const categorySlug = e.target.dataset.categorySlug;
                    const isEnabled = e.target.checked;
                    
                    if (categorySlug) {
                        // Wait for CategoryPreferences if not ready
                        if (!window.CategoryPreferences) {
                            setTimeout(() => {
                                if (window.CategoryPreferences) {
                                    window.CategoryPreferences.toggleCategory(categorySlug, isEnabled);
                                    if (window.NavigationFilter) {
                                        window.NavigationFilter.applyFilters();
                                    }
                                }
                            }, 100);
                        } else {
                            window.CategoryPreferences.toggleCategory(categorySlug, isEnabled);
                            if (window.NavigationFilter) {
                                window.NavigationFilter.applyFilters();
                            }
                        }
                    }
                }
            });
            
            // Close menu when clicking navigation links (but not toggle switches)
            menu.querySelectorAll('a.nav-category-link').forEach(link => {
                link.addEventListener('click', function(e) {
                    if (!e.target.closest('label') && !e.target.closest('.category-toggle-switch')) {
                        setTimeout(() => closeHamburgerMenu(), 200);
                    }
                });
            });
            
            // Update switches when preferences change
            window.addEventListener('categoryPreferencesChanged', updateToggleSwitches);
            
            // Initial update after CategoryPreferences loads
            function waitForCategoryPreferences() {
                if (window.CategoryPreferences) {
                    updateToggleSwitches();
                } else {
                    setTimeout(waitForCategoryPreferences, 100);
                }
            }
            waitForCategoryPreferences();
        }
        
        // Start initialization
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initHamburgerMenu);
        } else {
            initHamburgerMenu();
        }
        
        // Make functions globally available for onclick handlers
        window.openHamburgerMenu = openHamburgerMenu;
        window.closeHamburgerMenu = closeHamburgerMenu;
        
        // Update mobile toggle icons based on preferences
        function updateMobileToggleIcons() {
            if (!window.CategoryPreferences) {
                setTimeout(updateMobileToggleIcons, 100);
                return;
            }
            
            document.querySelectorAll('.category-toggle-btn').forEach(btn => {
                const slug = btn.dataset.categorySlug;
                if (slug) {
                    const isEnabled = window.CategoryPreferences.isCategoryEnabled(slug);
                    const icon = btn.querySelector('.category-toggle-icon');
                    if (icon) {
                        icon.textContent = isEnabled ? '✓' : '✕';
                        icon.className = isEnabled 
                            ? 'category-toggle-icon text-lg text-green-400' 
                            : 'category-toggle-icon text-lg text-red-400';
                    }
                }
            });
        }
        
        // Make function globally available
        window.updateMobileToggleIcons = updateMobileToggleIcons;
        
        // Handle toggle button clicks
        document.addEventListener('click', function(e) {
            const toggleBtn = e.target.closest('.category-toggle-btn');
            if (toggleBtn && window.CategoryPreferences) {
                e.preventDefault();
                e.stopPropagation();
                
                const slug = toggleBtn.dataset.categorySlug;
                if (slug) {
                    const currentState = window.CategoryPreferences.isCategoryEnabled(slug);
                    const newState = !currentState;
                    window.CategoryPreferences.toggleCategory(slug, newState);
                    
                    // Update icons
                    updateMobileToggleIcons();
                    
                    // Update navigation visibility
                    if (window.NavigationFilter) {
                        window.NavigationFilter.applyFilters();
                    }
                }
            }
        });
        
        // Toggle admin submenu
        function toggleAdminSubmenu(e) {
            e.preventDefault();
            e.stopPropagation();
            const submenu = document.getElementById('adminSubmenu');
            const arrow = document.getElementById('adminMenuArrow');
            if (submenu && arrow) {
                const isHidden = submenu.classList.contains('hidden');
                if (isHidden) {
                    submenu.classList.remove('hidden');
                    arrow.style.transform = 'rotate(180deg)';
                } else {
                    submenu.classList.add('hidden');
                    arrow.style.transform = 'rotate(0deg)';
                }
            }
        }
        window.toggleAdminSubmenu = toggleAdminSubmenu;
        
        // Update admin link with current zip code and initialize icons
        document.addEventListener('DOMContentLoaded', function() {
            const adminLink = document.getElementById('adminLink');
            if (adminLink) {
                // Get current zip from URL or localStorage
                const pathMatch = window.location.pathname.match(/^\\\/(\\d{5})/);
                const zipFromPath = pathMatch ? pathMatch[1] : null;
                const zipFromStorage = localStorage.getItem('currentZip');
                const currentZip = zipFromPath || zipFromStorage || '02720';
                
                adminLink.href = `/admin/${currentZip}`;
                adminLink.textContent = `Zip ${currentZip} Admin`;
            }
            
            // Initial icon update - wait for CategoryPreferences to be ready
            function initIcons() {
                if (window.CategoryPreferences && window.updateMobileToggleIcons) {
                    window.updateMobileToggleIcons();
                } else {
                    setTimeout(initIcons, 100);
                }
            }
            initIcons();
        });
    </script>
'''
        
        return nav_html
    
    def _get_index_template(self, zip_code: Optional[str] = None, city_state: Optional[str] = None, articles: Optional[List[Dict]] = None, settings: Optional[Dict] = None) -> Template:
        """Get index page template"""
        nav_tabs = self._get_nav_tabs("home", zip_code)

        # Extract show_images setting
        show_images_val = settings.get('show_images', '1') if settings else '1'
        if isinstance(show_images_val, bool):
            show_images = show_images_val
        elif isinstance(show_images_val, str):
            show_images = show_images_val.strip().lower() in ('1', 'true', 'yes', 'on')
        else:
            show_images = bool(show_images_val)

        # Use FileSystemLoader if available
        if self.use_file_templates and self.jinja_env:
            template = self.jinja_env.get_template("index.html.j2")

        # Phase 6: Resolve city name for dynamic title
        locale_name = LOCALE  # Default to "Fall River, MA"
        if city_state:
            # Use provided city_state directly
            locale_name = city_state
        elif zip_code:
            # Resolve zip code to city/state if city_state not provided
            from zip_resolver import resolve_zip
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "")
                state = zip_data.get("state_abbrev", "")
                locale_name = f"{city}, {state}" if city and state else f"Zip {zip_code}"
            else:
                locale_name = f"Zip {zip_code}"
        
        # Determine paths
        # Note: self.output_dir is already set to zip-specific directory if zip_code is provided
        output_path = os.path.join(self.output_dir, "category")
        if zip_code:
            # We're in zip_XXXX directory, category is subdirectory
            home_path = "../"
            css_path = "../css/"
        else:
            # We're in root directory, category is subdirectory
            home_path = "../"
            css_path = "../css/"
        
        os.makedirs(output_path, exist_ok=True)
        
        # Format articles and enrich with source data
        formatted_articles = []
        if articles:
            for article in articles:
                formatted = self._format_article_for_display(article, show_images)
                # Add source initials and gradients (methods may not exist)
                # Skip for safety - these methods appear to be missing
                # Skip _is_video_article call - method may not exist
                formatted_articles.append(formatted)
        
        # CRITICAL FIX: Sort formatted articles by publication date (newest first)
        formatted_articles.sort(key=lambda x: (
            x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
        ), reverse=True)
        
        # Get hero articles for index page
        hero_articles = formatted_articles[:3] if formatted_articles else []  # Top 3 articles as heroes
            # Sort by date (newest first)
            category_top_stories.sort(key=lambda x: (
                x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
            ), reverse=True)
            
            # Format top stories for hero carousel
            formatted_top_stories = []
            for article in category_top_stories[:3]:
                formatted = self._format_article_for_display(article, show_images)
                # Add source initials and gradients (methods may not exist)
                # Skip for safety - these methods appear to be missing
                # Skip _is_video_article call - method may not exist
                formatted_top_stories.append(formatted)
            
            # If we have 3+ top stories, use them; otherwise fill with most recent category articles
            if len(formatted_top_stories) >= 3:
                hero_articles = formatted_top_stories[:3]
            else:
                # Fill remaining slots with most recent category articles (already sorted by date)
                remaining = 3 - len(formatted_top_stories)
                # Exclude top stories from formatted_articles to avoid duplicates
                top_story_ids = {t.get('id') for t in formatted_top_stories if t.get('id')}
                non_top_formatted = [a for a in formatted_articles if a.get('id') not in top_story_ids]
                hero_articles = formatted_top_stories + non_top_formatted[:remaining] if remaining > 0 else formatted_top_stories
        
        # DEBUG: Log hero articles for category page
        logger.info(f"CATEGORY PAGE HERO ARTICLES ({category_slug}): {len(hero_articles)}")
        for i, article in enumerate(hero_articles):
            logger.info(f"  Hero [{i}]: title='{article.get('title', 'NO TITLE')[:50]}' | "
                       f"image_url={bool(article.get('image_url'))} | "
                       f"top_story={article.get('_is_top_story', 0)} | "
                       f"id={article.get('id', 'N/A')}")
        
        # Get IDs of featured articles to exclude from main grid
        featured_ids = set()
        for hero_article in hero_articles:
            if hero_article and hero_article.get('id'):
                featured_ids.add(hero_article.get('id'))
        
        # Filter out featured articles from main grid (only show category articles)
        grid_articles = [a for a in formatted_articles if a.get('id') not in featured_ids]
        
        # Add video detection to hero articles
        for hero_article in hero_articles:
            if hero_article:
                try:
                    from website_generator.utils import is_video_article
                    hero_article['_is_video'] = is_video_article(hero_article)
                except ImportError:
                    hero_article['_is_video'] = self._is_video_article(hero_article)
        
        # Get trending articles from this category only (already filtered by category)
        # Use limit=5 to match index page consistency
        trending_articles_raw = self._get_trending_articles(filtered_articles, limit=5)
        trending_articles = []
        for article in trending_articles_raw:
            formatted = self._format_article_for_display(article, show_images)
            
            # Format trending date: remove year, keep time
            if formatted.get('formatted_date'):
                formatted_date = formatted['formatted_date']
                # Remove year from "January 15, 2024 at 3:45 PM" -> "January 15 at 3:45 PM"
                if ', ' in formatted_date and ' at ' in formatted_date:
                    parts = formatted_date.split(', ')
                    if len(parts) == 2:
                        date_part = parts[0]  # "January 15"
                        time_part = parts[1]  # "2024 at 3:45 PM"
                        if ' at ' in time_part:
                            time_only = time_part.split(' at ', 1)[1]  # "3:45 PM"
                            formatted['_trending_date'] = f"{date_part} at {time_only}"
                        else:
                            formatted['_trending_date'] = date_part
                    else:
                        formatted['_trending_date'] = formatted_date
                else:
                    formatted['_trending_date'] = formatted_date
            else:
                formatted['_trending_date'] = 'Recently'
            if 'source_initials' not in formatted:
                formatted['source_initials'] = self._get_source_initials(formatted.get('source_display', formatted.get('source', '')))
            if 'source_gradient' not in formatted:
                # Use obituaries-specific gradients for obituaries page
                if category_slug == "obituaries":
                    formatted['source_gradient'] = self._get_obituaries_source_gradient(formatted.get('source_display', formatted.get('source', '')))
                else:
                    formatted['source_gradient'] = self._get_source_gradient(formatted.get('source_display', formatted.get('source', '')))
            formatted['_is_video'] = self._is_video_article(formatted)
            trending_articles.append(formatted)
        
        # Prepare location badge data
        location_badge_text = "Fall River · 02720"
        if zip_code:
            from zip_resolver import resolve_zip
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "Fall River")
                location_badge_text = f"{city} · {zip_code}"
            else:
                location_badge_text = f"Fall River · {zip_code}"
        
        # Phase 9: Zip pin editability flag (from admin_settings)
        zip_pin_editable = False
        try:
            # Prefer settings dict if present
            if 'zip_pin_editable' in settings:
                zip_pin_editable = str(settings.get('zip_pin_editable')) == '1'
            else:
                conn = self._get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('zip_pin_editable',))
                row = cursor.fetchone()
                conn.close()
                zip_pin_editable = row[0] == '1' if row else False
        except Exception as e:
            logger.warning(f"Could not determine zip pin editability: {e}")
            zip_pin_editable = False
        
        # Generate navigation (from category subdirectory)
        nav_tabs = self._get_nav_tabs(f"category-{category_slug}", zip_code, is_category_page=True)
        
        # Update title
        title = f"{locale_name} News" if zip_code else self.title
        
        # Get weather station URL - check database first, then fall back to weather_ingestor
        # Default to "02720" (Fall River) if zip_code is not provided
        lookup_zip = zip_code or "02720"
        weather_station_url = ""
        if lookup_zip:
            try:
                conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
                cursor = conn.cursor()
                cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', (lookup_zip, 'weather_station_url'))
                row = cursor.fetchone()
                if row and row[0]:
                    weather_station_url = row[0]
                conn.close()
            except Exception as e:
                logger.warning(f"Could not load weather station URL from database: {e}")
        
        # Fall back to weather_ingestor method if not in database
        if not weather_station_url:
            weather_station_url = self.weather_ingestor.get_primary_weather_station_url()
        # Adjust URL for category page context (if it's a relative path, make it relative to category/)
        if weather_station_url.startswith("category/"):
            # Already relative, keep as is
            pass
        elif not weather_station_url.startswith("http"):
            # Relative path, adjust for category subdirectory
            weather_station_url = f"../{weather_station_url}"
        # If it's an absolute URL (http/https), use as-is
        
        # Get weather icon based on condition
        weather_icon = self._get_weather_icon(weather.get('current', {}).get('condition', ''))
        
        # Extract funeral home names for obituaries filter
        funeral_homes = set()
        if category_slug == "obituaries":
            for article in formatted_articles:
                source = article.get('source_display', article.get('source', ''))
                if source:
                    # Clean up funeral home names
                    funeral_home = source.strip()
                    # Remove common suffixes
                    for suffix in [' Funeral Homes', ' Funeral Home', ' Funeral Service', ' Chapel', ' Memorial']:
                        if funeral_home.endswith(suffix):
                            funeral_home = funeral_home[:-len(suffix)]
                    if funeral_home:
                        funeral_homes.add(funeral_home)
            funeral_homes = sorted(list(funeral_homes))
        
        current_time = datetime.now().strftime("%I:%M %p")
        generation_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        
        # Get last database update time for enabled articles
        last_db_update = None
        try:
            from database import ArticleDatabase
            db = ArticleDatabase()
            last_db_update = db.get_last_enabled_article_update_time(zip_code=zip_code)
        except Exception as e:
            logger.warning(f"Could not get last database update time: {e}")
        
        # Prepare template variables
        template_vars = {
            "title": title,
            "category_name": category_name,
            "category_slug": category_slug,  # Add category slug for client-side checks
            "locale": locale_name,
            "articles": grid_articles,
            "hero_articles": hero_articles,  # Hero articles for carousel (up to 3)
            "hero_article": None,  # Keep for backward compatibility but use hero_articles
            "trending_articles": trending_articles[:5],
            "weather": weather,
            "show_images": show_images,
            "current_year": datetime.now().year,
            "current_time": current_time,
            "generation_timestamp": generation_timestamp,  # Full timestamp for display
            "last_db_update": last_db_update,  # Last database update time for enabled articles
            "nav_tabs": nav_tabs,
            "home_path": home_path,
            "css_path": css_path,
            "location_badge_text": location_badge_text,
            "zip_code": zip_code or "02720",
            "weather_station_url": weather_station_url,
            "weather_icon": weather_icon,  # Dynamic weather icon
            "zip_pin_editable": zip_pin_editable  # Phase 9: Zip pin editability
        }
        
        # Add funeral homes for obituaries template
        if category_slug == "obituaries":
            template_vars["funeral_homes"] = funeral_homes
        
        html = template.render(**template_vars)
        
        output_file = os.path.join(output_path, f"{category_slug}.html")
        with open(output_file, "w", encoding="utf-8", errors='replace') as f:
            f.write(html)
        
        logger.info(f"Generated category page: {output_file} ({len(formatted_articles)} articles)")
    
    def _generate_scanner_page(self, weather: Dict, settings: Dict, zip_code: Optional[str] = None, city_state: Optional[str] = None):
        """Generate scanner page with embedded Broadcastify feed
        
        Args:
            weather: Weather data
            settings: Admin settings
            zip_code: Optional zip code for zip-specific generation
            city_state: Optional city_state for city-based generation
        """
        # Phase 6: Resolve city name for dynamic title
        locale_name = LOCALE  # Default to "Fall River, MA"
        if city_state:
            # Use provided city_state directly
            locale_name = city_state
        elif zip_code:
            # Resolve zip code to city/state if city_state not provided
            from zip_resolver import resolve_zip
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "")
                state = zip_data.get("state_abbrev", "")
                locale_name = f"{city}, {state}" if city and state else f"Zip {zip_code}"
            else:
                locale_name = f"Zip {zip_code}"
        
        # Determine paths
        output_path = os.path.join(self.output_dir, "category")
        if zip_code:
            # We're in zip_XXXX directory, category is subdirectory
            home_path = "../"
            css_path = "../css/"
        else:
            # We're in root directory, category is subdirectory
            home_path = "../"
            css_path = "../css/"
        
        os.makedirs(output_path, exist_ok=True)
        
        # Generate navigation (from category subdirectory, scanner is active)
        nav_tabs = self._get_nav_tabs("category-scanner", zip_code, is_category_page=True)
        
        # Update title
        title = f"{locale_name} News" if zip_code else self.title
        
        # Get Broadcastify feed ID from config
        feed_id = SCANNER_CONFIG.get("feed_id", "33717")
        
        # Build scanner page HTML
        scanner_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Police & Fire Scanner — {locale_name}</title>
    <meta name="description" content="Live police and fire scanner audio and call transcript for {locale_name}">
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Fallback CSS in case Tailwind CDN fails -->
    <style>
    /* Critical fallback styles */
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0a0a0a; color: #e0e0e0; }
    .container { max-width: 1200px; margin: 0 auto; padding: 0 1rem; }
    .grid { display: grid; gap: 1rem; }
    .flex { display: flex; }
    .hidden { display: none; }
    .block { display: block; }
    .text-center { text-align: center; }
    .p-4 { padding: 1rem; }
    .m-4 { margin: 1rem; }
    .bg-gray-800 { background: #2a2a2a; }
    .text-white { color: white; }
    .rounded { border-radius: 0.25rem; }
    article { margin-bottom: 1rem; padding: 1rem; background: #1a1a1a; border-radius: 0.5rem; }
    a { color: #3b82f6; text-decoration: none; }
    a:hover { text-decoration: underline; }
    </style>
    <script>
        tailwind.config = {{
            darkMode: 'class',
            theme: {{
                extend: {{
                    colors: {{
                        'edge-bg': '#0d0d0d',
                        'edge-surface': '#161616',
                        'edge-elevated': '#1f1f1f',
                    }}
                }}
            }}
        }}
    </script>
    <link rel="stylesheet" href="{css_path}style.css">
    <style>
        .lazy-image {{ opacity: 0; transition: opacity 0.3s; }}
        .lazy-image.loaded {{ opacity: 1; }}
        /* Dark mode filter for Broadcastify iframes */
        .broadcastify-iframe {{
            filter: brightness(0.8) contrast(1.15) saturate(0.9);
            background: #0f0f0f;
            transition: filter 0.3s ease;
        }}
        /* Darken the iframe container with dark background */
        .broadcastify-container {{
            background: #0f0f0f;
            border-radius: 12px;
            overflow: hidden;
            position: relative;
        }}
        /* Optional: Add a subtle dark overlay effect */
        .broadcastify-container::before {{
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(to bottom, rgba(15, 15, 15, 0.3), transparent);
            pointer-events: none;
            z-index: 1;
            border-radius: 12px;
        }}
        /* Center content in transcript iframe */
        .transcript-container {{
            display: flex;
            justify-content: center;
            align-items: flex-start;
        }}
        .transcript-container iframe {{
            max-width: 100%;
        }}
    </style>
</head>
<body class="bg-[#0f0f0f] text-gray-100 min-h-screen">
    <!-- Top Bar -->
    <div class="bg-[#0f0f0f]/50 backdrop-blur-sm border-b border-gray-900/30 py-2">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                <div class="w-full sm:w-auto flex-1">
                    <div class="relative flex items-center bg-[#161616]/50 backdrop-blur-sm rounded-full px-4 py-2 border border-gray-800/20">
                        <span class="text-gray-400 mr-2">🔍</span>
                        <input type="text" placeholder="Search articles..." class="bg-transparent border-none outline-none text-gray-100 placeholder-gray-400 flex-1 w-full sm:w-64" id="searchInput">
                    </div>
                </div>
                <div class="flex items-center gap-3">
                    <a href="/admin" id="hamburgerMenuLink" class="bg-blue-500 hover:bg-blue-600 text-white p-2 rounded-lg transition-colors inline-flex items-center justify-center w-10 h-10" title="Admin Panel">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path>
                        </svg>
                    </a>
                    <script>
                        // Update hamburger menu link based on session
                        (function() {{
                            fetch('/api/session-check')
                                .then(response => response.json())
                                .then(data => {{
                                    const link = document.getElementById('hamburgerMenuLink');
                                    if (data.logged_in && data.zip_code) {{
                                        link.href = `/admin/${{data.zip_code}}`;
                                    }} else {{
                                        link.href = '/admin';
                                    }}
                                }})
                                .catch(err => {{
                                    console.error('Error checking session:', err);
                                }});
                        }})();
                    </script>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Navigation -->
    <nav class="bg-[#0f0f0f]/80 backdrop-blur-md border-b border-gray-900/20 py-2 sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                <div class="text-xl font-semibold text-blue-400">FRNA</div>
                {nav_tabs}
            </div>
        </div>
    </nav>
    
    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div class="max-w-4xl mx-auto">
            <h1 class="text-3xl lg:text-4xl font-bold text-center mb-2" style="color: #0078d4;">🔴 LIVE {locale_name} Police & Fire Scanner</h1>
            <p class="text-center text-gray-400 mb-8">Real-time audio + call log — powered by Broadcastify</p>
            
            <!-- Audio Player Box -->
            <div class="bg-[#1a1a1a] rounded-2xl p-5 mb-8 shadow-2xl" style="box-shadow: 0 8px 32px rgba(0,0,0,0.6);">
                <div class="broadcastify-container">
                    <iframe id="broadcastifyPlayer" 
                            src="https://www.broadcastify.com/webPlayer/{feed_id}" 
                            height="180" 
                            allow="autoplay; encrypted-media"
                            allowfullscreen
                            class="w-full border-none rounded-xl broadcastify-iframe">
                    </iframe>
                </div>
                <div class="text-center mt-3">
                    <span class="text-green-400 font-bold">● LIVE</span>
                    <span class="text-gray-500 ml-2">— ~30-second delay</span>
                </div>
            </div>
            
            <!-- Transcript Box -->
            <div class="bg-[#1a1a1a] rounded-2xl p-5 shadow-2xl" style="box-shadow: 0 8px 32px rgba(0,0,0,0.6);">
                <h2 class="text-xl font-semibold text-white mb-4 mt-0 text-center">Live Call Transcript & Radio Codes</h2>
                <div class="broadcastify-container transcript-container">
                    <iframe src="https://www.broadcastify.com/listen/feed/{feed_id}/transcript" 
                            height="500"
                            class="w-full border-none rounded-xl broadcastify-iframe"
                            style="display: block; margin: 0 auto;">
                    </iframe>
                </div>
            </div>
            
            <!-- Footer Note -->
            <p class="text-center text-gray-600 text-sm mt-8">
                Source: <a href="https://www.broadcastify.com/listen/feed/{feed_id}" target="_blank" class="text-green-400 hover:text-green-300">Broadcastify Feed #{feed_id}</a> • 
                {locale_name} Police + Fire Departments • 
                <a href="{home_path}index.html" class="text-blue-400 hover:text-blue-300">← Back to FRNA</a>
            </p>
        </div>
    </main>
    
    <!-- Load main.js for search functionality -->
    <script src="{home_path}js/main.js"></script>
    
    <!-- Auto-play script for Broadcastify player -->
    <script>
        // Attempt to trigger autoplay when page loads
        // Note: Browser autoplay policies may prevent this from working
        // Users may need to interact with the page first
        (function() {{
            // Wait for iframe to load
            const iframe = document.getElementById('broadcastifyPlayer');
            if (iframe) {{
                iframe.addEventListener('load', function() {{
                    // Try to trigger play via postMessage (may not work due to CORS)
                    try {{
                        // Some players respond to postMessage for play commands
                        iframe.contentWindow.postMessage({{action: 'play'}}, 'https://www.broadcastify.com');
                    }} catch (e) {{
                        // Cross-origin restrictions may prevent this
                        console.log('Autoplay attempt (may be blocked by browser policy)');
                    }}
                }});
                
                // Also try clicking play button after a short delay
                setTimeout(function() {{
                    try {{
                        // Try to find and click play button in iframe (may not work due to CORS)
                        const playButton = iframe.contentDocument?.querySelector('button[name="Play"], button[aria-label*="Play"], .play-button');
                        if (playButton) {{
                            playButton.click();
                        }}
                    }} catch (e) {{
                        // Expected: Cross-origin restrictions prevent direct DOM access
                    }}
                }}, 1000);
            }}
        }})();
    </script>
</body>
</html>'''
        
        output_file = os.path.join(output_path, "scanner.html")
        with open(output_file, "w", encoding="utf-8", errors='replace') as f:
            f.write(scanner_html)
        
        logger.info(f"Generated scanner page: {output_file}")
    
    def _format_article_for_display(self, article: Dict, show_images: bool = True) -> Dict:
        """Format article for display in templates"""
        
        formatted = article.copy()
        
        # Format date
        published = article.get('published', '')
        if published:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0].split('.')[0])
                formatted['formatted_date'] = dt.strftime('%B %d, %Y at %I:%M %p')
            except Exception as e:
                logger.warning(f"Could not format article date: {e}")
                formatted['formatted_date'] = published[:10] if len(published) >= 10 else published
        else:
            formatted['formatted_date'] = 'Date unknown'
        
        # Source display
        formatted['source_display'] = article.get('source_display', article.get('source', 'Unknown Source'))
        
        # Preserve reading_time if it exists
        if 'reading_time' not in formatted and article.get('reading_time'):
            formatted['reading_time'] = article.get('reading_time')
        
        return formatted
    
    def _generate_css(self):
        """Generate CSS file"""
        css = self._get_css_content()
        with open(os.path.join(self.output_dir, "css", "style.css"), "w", encoding="utf-8", errors='replace') as f:
            f.write(css)
    
    def _get_css_content(self) -> str:
        """Get CSS content"""
        return get_css_content()
    
    def _generate_js(self):
        """Generate JavaScript file"""
        js = self._get_js_content()
        with open(os.path.join(self.output_dir, "js", "main.js"), "w", encoding="utf-8", errors='replace') as f:
            f.write(js)
    
    def _get_js_content(self) -> str:
        """Get JavaScript content with progressive loading"""
        return get_js_content()
    
    def _copy_static_js_files(self):
        """Copy static JavaScript files from public/js/ to build/js/
        
        This ensures files like weather.js are always up to date during regeneration.
        """
        public_js_dir = Path("public") / "js"
        output_js_dir = Path(self.output_dir) / "js"
        
        if not public_js_dir.exists():
            logger.warning(f"Public JS directory not found: {public_js_dir}")
            return
        
        # Ensure output directory exists
        output_js_dir.mkdir(parents=True, exist_ok=True)
        
        # List of static JS files to copy (files that aren't generated from Python)
        static_files = ["weather.js"]
        
        for filename in static_files:
            source_file = public_js_dir / filename
            dest_file = output_js_dir / filename
            
            if source_file.exists():
                try:
                    shutil.copy2(source_file, dest_file)
                    logger.info(f"Copied {filename} from {source_file} to {dest_file}")
                except Exception as e:
                    logger.warning(f"Could not copy {filename}: {e}")
            else:
                logger.warning(f"Source file not found: {source_file}")
    
    def _optimize_article_images(self, articles: List[Dict]) -> List[Dict]:
        """Optimize images for a list of articles"""
        optimized_articles = []
        for article in articles:
            image_url = article.get('image_url')
            if image_url and should_optimize_image(image_url):
                try:
                    optimized_path = optimize_image(image_url, self.images_dir)
                    if optimized_path:
                        # Convert to relative path for web
                        article['image_url'] = f"/images/{Path(optimized_path).name}"
                        logger.debug(f"Optimized image: {image_url} -> {article['image_url']}")
                except Exception as e:
                    logger.warning(f"Could not optimize image {image_url}: {e}")
                    # Keep original URL if optimization fails
            optimized_articles.append(article)
        return optimized_articles





