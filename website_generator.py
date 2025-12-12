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
import contextlib
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
                self.output_dir = os.path.join(original_output_dir, "zips", f"zip_{zip_code.zfill(5)}")
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
                self.output_dir = os.path.join(original_output_dir, "zips", f"zip_{zip_code.zfill(5)}")
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
        categories_to_generate = ['business', 'crime', 'events', 'food', 'local-news', 'meetings', 'obituaries', 'schools', 'sports', 'weather']
        for category_slug in categories_to_generate:
            try:
                self._generate_category_page(category_slug, enabled_articles, weather, admin_settings, zip_code)
                logger.info(f"  ✓ Generated {category_slug} category page")
            except Exception as e:
                logger.error(f"Failed to generate {category_slug} category page: {e}")

        # Generate scanner page separately
        logger.info("About to generate scanner page...")
        try:
            self._generate_scanner_page(weather, admin_settings, zip_code, city_state)
            logger.info("  ✓ Generated scanner page")
        except Exception as e:
            logger.error(f"Failed to generate scanner page: {e}")
            import traceback
            logger.error(f"Scanner generation traceback: {traceback.format_exc()}")

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
        """
        admin_settings = self._get_admin_settings()
        enabled_articles = self._get_enabled_articles(all_articles, admin_settings, zip_code=zip_code)
        weather = self.weather_ingestor.fetch_weather()
        
        # Always regenerate index (it shows all articles)
        logger.info("About to call _generate_index")
        try:
            result = self._generate_index(enabled_articles, weather, admin_settings, zip_code)
            logger.info(f"_generate_index returned: {result}")
            logger.info("  ✓ Index page generated")
        except Exception as e:
            logger.error(f"Failed to generate index page: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        
        # CSS and JS only if they don't exist or are old
        css_path = Path(self.output_dir) / "css" / "style.css"
        js_path = Path(self.output_dir) / "js" / "main.js"
        
        if not css_path.exists():
            self._generate_css()
            logger.info("  ✓ CSS generated")

        if not js_path.exists():
            self._generate_js()
            logger.info("  ✓ JS generated")
        
        # Always copy static JS files in incremental updates to ensure weather.js is current
        self._copy_static_js_files()

        # Generate scanner page
        logger.info("About to generate scanner page...")
        try:
            self._generate_scanner_page(weather, admin_settings, zip_code)
            logger.info("  ✓ Generated scanner page")
        except Exception as e:
            logger.error(f"Failed to generate scanner page: {e}")
            import traceback
            logger.error(f"Scanner generation traceback: {traceback.format_exc()}")

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

    @contextlib.contextmanager
    def get_db_cursor(self):
        """Context manager for database cursor"""
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
        """
        try:
            # Method body removed during cleanup - needs restoration
            return articles  # Placeholder return
        except Exception as e:
            logger.warning(f"Could not process articles: {e}")
            return articles
    
    def _get_article_management_for_zip(self, cursor, article_ids: List[int], zip_code: str) -> Dict:
        """Get article management data from database for a specific zip code"""
        if not article_ids:
            return {}

        placeholders = ','.join('?' * len(article_ids))
        cursor.execute(f'''
        ''', tuple(article_ids) + (zip_code,) + tuple(article_ids) + (zip_code,))
        
        rows = cursor.fetchall()

        management_data = {}
        for row in rows:
            article_id = row['article_id']
            management_data[article_id] = {
                'enabled': row['enabled'],
                'display_order': row['display_order'],
                'is_top_article': row['is_top_article']
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
        ''', article_ids + article_ids)
        
        return {
        }
    
    def _filter_and_sort_articles(self, articles: List[Dict], management: Dict) -> List[Dict]:
        """Filter enabled articles and apply sorting - only show articles that are enabled"""
        enabled = []
        for article in articles:
            article_id = article.get('id', 0)
            article_management = management.get(article_id, {})
            if article_management.get('enabled', 1):  # Default to enabled
                enabled.append(article)

        # Sort by: 1) is_top_story, 2) created_at (ingestion date - newest first), 3) display_order
        # Use created_at (when article came in) to show newest articles first
        def get_ingestion_timestamp(article):
            return article.get('created_at', '1970-01-01')

        # Sort: 1) is_top_story (top stories first), 2) created_at DESC (newest first), 3) display_order
        enabled.sort(key=lambda x: (
            -management.get(x.get('id', 0), {}).get('is_top_article', 0),  # Top stories first
            -get_ingestion_timestamp(x),  # Newest first (negative for descending)
            management.get(x.get('id', 0), {}).get('display_order', 999)  # Display order
        ))
        return enabled
    
    def _filter_articles_by_category(self, articles: List[Dict], category_slug: str) -> List[Dict]:
        """Filter articles by category slug using mapping and keyword fallback
        
        Args:
        
        Returns:
        """
        if category_slug not in CATEGORY_SLUGS:
            return []

        filtered = []
        
        # Keywords for each category (for fallback matching)
        category_keywords = {
        }
        
        keywords = category_keywords.get(category_slug, [])
        
        # Get list of funeral home sources for obituaries filtering
        funeral_home_sources = set()
        if category_slug == "obituaries":
            # Add funeral home sources for obituaries filtering
            funeral_home_sources.update(["Legacy.com", "Funeral Home", "Memorial"])

        for article in articles:
            # Basic filtering logic - add articles that match category
            article_category = article.get('category', '').lower()
            article_title = article.get('title', '').lower()
            article_source = article.get('source', '').lower()

            # Category matching logic
            if category_slug in article_category or any(keyword in article_title for keyword in keywords):
                filtered.append(article)

        # Deduplicate by article ID to prevent showing the same article multiple times
        seen_ids = set()
        deduplicated = []
        for article in filtered:
            article_id = article.get('id')
            if article_id and article_id not in seen_ids:
                seen_ids.add(article_id)
                deduplicated.append(article)

        return deduplicated
    
    def _generate_index(self, articles: List[Dict], weather: Dict, settings: Dict, zip_code: Optional[str] = None, city_state: Optional[str] = None):
        """Generate main index page
        Phase 6: Now supports city_state for dynamic city names

        Args:
        """
        logger.info(f"_generate_index called with {len(articles)} articles")
        logger.info(f"_generate_index called with {len(articles)} articles")
        logger.error(f"settings is: {type(settings)}")
        show_images_val = settings.get('show_images', '1')
        logger.error("show_images_val processed")
        if isinstance(show_images_val, bool):
            show_images = show_images_val
        elif isinstance(show_images_val, str):
            show_images = show_images_val.strip().lower() in ('1', 'true', 'yes', 'on')
        else:
            show_images = bool(show_images_val)

        # Process articles normally with proper timestamps

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
        def sort_key(article):
            published = article.get('published')
            if published:
                return published
            # Fallback to other date fields
            return article.get('created_at', article.get('date_sort', '1970-01-01'))

        all_articles.sort(key=sort_key, reverse=True)
        
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
            x.get('_top_story_display_order', 999)  # Display order
        ))
        if not top_stories:
            top_stories = all_articles[:5]  # Fallback to top 5 articles if no top stories

        # Get trending articles (recent articles with high relevance scores)
        # Excludes obituaries and returns top 10 (client-side will filter to top 5 based on user preferences)
        try:
            trending_articles = self._get_trending_articles(all_articles, limit=10)
        except ImportError:
            trending_articles = all_articles[:10]  # Fallback if method doesn't exist
        
        # Add category slug and format trending date (no year) to each trending article
        for article in trending_articles:
            # Add category for trending articles
            article['_category'] = 'trending'
            # Format date without year
            if article.get('formatted_date'):
                formatted_date = article['formatted_date']
                if ', ' in formatted_date:
                    date_part = formatted_date.split(', ')[0]
                    article['_trending_date'] = date_part
                else:
                    article['_trending_date'] = formatted_date[:10] if len(formatted_date) >= 10 else formatted_date
            else:
                article['_trending_date'] = 'Recently'

        # Get latest stories (5 most recent by publication date, excluding top stories)
        latest_stories = [a for a in articles if not a.get('_is_top_story', 0)]
        # Sort by published date (newest first)
        latest_stories.sort(key=lambda x: (
        ), reverse=True)
        latest_stories = latest_stories[:5]
        
        # Get newest articles (simple chronological order, newest first, no algorithm)
        newest_articles = list(articles)  # Copy the list
        # Sort by publication date (newest first) - pure chronological order
        newest_articles.sort(key=lambda x: (
        ), reverse=True)
        newest_articles = newest_articles[:10]  # Take top 10 newest articles
        
        # Add related articles to each article
        try:
            from aggregator import NewsAggregator
            aggregator = NewsAggregator()
            for article in all_articles:
                # Add related articles logic here
                pass
        except ImportError:
            pass  # Skip if aggregator not available

        # Enrich articles with source initials, gradients, and glow colors
        for article in all_articles:
            article['_source_initials'] = article.get('source', '')[:2].upper()
        for article in top_stories:
            article['_source_initials'] = article.get('source', '')[:2].upper()
        for article in trending_articles:
            article['_source_initials'] = article.get('source', '')[:2].upper()
        for article in latest_stories:
            article['_source_initials'] = article.get('source', '')[:2].upper()
        for article in newest_articles:
            article['_source_initials'] = article.get('source', '')[:2].upper()
        for article in entertainment_articles:
            article['_source_initials'] = article.get('source', '')[:2].upper()
        
        # Optimize images for articles (only when hotlinking is disabled)
        # When hotlinking is enabled (show_images=True), preserve external URLs
        if not show_images:
            # Image optimization logic would go here
            pass

        # Get hero articles (top 3 stories for carousel)
        hero_articles = top_stories[:3] if len(top_stories) >= 3 else (top_stories if top_stories else [])
        

        # Get top article (single featured article)
        top_article = None
        for article in all_articles:
            if article.get('_is_featured', 0) or article.get('_is_top_story', 0):
                top_article = article
                break

        # Get alert articles (urgent notifications)
        alert_articles = [a for a in all_articles if a.get('_is_alert', 0)]
        # Sort alerts by updated_at DESC (newest first)
        alert_articles.sort(key=lambda x: (
        ))
        
        # DEBUG: Log hero articles for troubleshooting slider
        logger.info(f"HERO ARTICLES COUNT: {len(hero_articles)}")
        for i, article in enumerate(hero_articles):
            logger.info(f"  Hero [{i}]: {article.get('title', 'No title')[:50]}")

        # Get IDs of featured articles to exclude from main grid
        featured_ids = set()
        for hero_article in hero_articles:
            if hero_article and hero_article.get('id'):
                featured_ids.add(hero_article.get('id'))
        
        # Filter out featured articles from main grid
        grid_articles = [a for a in all_articles if a.get('id') not in featured_ids]
        
        # Add video detection to articles
        for hero_article in hero_articles:
            hero_article['_is_video'] = self._is_video_article(hero_article) if hasattr(self, '_is_video_article') else False
        for article in grid_articles:
            article['_is_video'] = self._is_video_article(article) if hasattr(self, '_is_video_article') else False
        for article in trending_articles:
            article['_is_video'] = self._is_video_article(article) if hasattr(self, '_is_video_article') else False
        
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
            weather_condition = 'cloudy'
        elif 'sun' in weather_condition or 'clear' in weather_condition:
            weather_condition = 'sunny'
        
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
            with self.get_db_cursor() as cursor:
                cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('zip_pin_editable',))
                row = cursor.fetchone()
                zip_pin_editable = row[0] == '1' if row else False
        except Exception as e:
            logger.warning(f"Could not determine zip pin editability: {e}")

        # Phase 6: Resolve city name for dynamic title
        locale_name = LOCALE  # Default to "Fall River, MA"
        if city_state:
            locale_name = city_state
        elif zip_code:
            from zip_resolver import resolve_zip
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "")
                state = zip_data.get("state_abbrev", "")
                locale_name = f"{city}, {state}" if city and state else f"Zip {zip_code}"
            else:
                locale_name = f"Zip {zip_code}"

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
                with self.get_db_cursor() as cursor:
                    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('weather_station_url',))
                    row = cursor.fetchone()
                    weather_station_url = row[0] if row else ""
            except Exception as e:
                logger.warning(f"Could not get weather station URL from database: {e}")

        # Fall back to weather_ingestor method if not in database
        if not weather_station_url:
            try:
                weather_station_url = self.weather_ingestor.get_station_url(lookup_zip or '02720')
            except Exception as e:
                logger.warning(f"Could not get weather station URL from ingestor: {e}")

        # Get weather icon based on condition
        weather_icon = self._get_weather_icon(weather.get('current', {}).get('condition', ''))
        weather_api_key = ""

        # Get last database update time for enabled articles
        last_db_update = None
        try:
            with self.get_db_cursor() as cursor:
                cursor.execute('SELECT MAX(created_at) FROM articles')
                row = cursor.fetchone()
                if row and row[0]:
                    dt = datetime.fromisoformat(row[0])
                    last_db_update = dt.strftime("%B %d, %Y at %I:%M %p")
                else:
                    last_db_update = "No articles yet"
        except Exception as e:
            logger.warning(f"Could not get last DB update time: {e}")
            last_db_update = "Recently"

        # Format articles and enrich with source data
        formatted_articles = []
        if articles:
            for article in articles:
                formatted = self._format_article_for_display(article, show_images) if hasattr(self, '_format_article_for_display') else article.copy()
                formatted_articles.append(formatted)

        # CRITICAL FIX: Sort formatted articles by publication date (newest first)
        formatted_articles.sort(key=lambda x: (
            -parse_timestamp(x.get('_top_story_updated_at', '1970-01-01T00:00:00')),  # Newest clicked first (negative for descending)
            x.get('_display_order', 999),  # Then by display order
            -parse_timestamp(x.get('published', x.get('created_at', '1970-01-01')))  # Then by publication date
        ), reverse=True)

        # Get hero articles for index page
        hero_articles = formatted_articles[:3] if formatted_articles else []  # Top 3 articles as heroes

        # Get trending articles
        try:
            trending_articles = self._get_trending_articles(formatted_articles, limit=5)
        except (AttributeError, ImportError):
            trending_articles = formatted_articles[:5]  # Fallback

        # Latest stories (different from trending)
        latest_stories = formatted_articles[:5]

        # Newest articles
        newest_articles = formatted_articles[:10]

        # Entertainment articles
        entertainment_articles = [a for a in formatted_articles if 'entertainment' in (a.get('category') or '')][:5]

        # Top article
        top_article = formatted_articles[0] if formatted_articles else None

        # Current time and generation timestamp
        current_time = datetime.now().strftime("%I:%M %p")
        generation_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

        # Get template
        template = self._get_index_template(zip_code, city_state, formatted_articles, {'show_images': show_images})

        logger.error("TEMPLATE CONTEXT CREATION STARTING")
        # Create template context
        template_context = {
            'title': title,
            'description': description,
            'articles': formatted_articles,
            'hero_articles': hero_articles,
            'trending_articles': trending_articles,
            'latest_stories': latest_stories,
            'newest_articles': newest_articles,
            'entertainment_articles': entertainment_articles,
            'top_article': top_article,
            'weather': weather,
            'current_year': datetime.now().year,
            'current_time': current_time,
            'generation_timestamp': generation_timestamp,
            'last_db_update': last_db_update,
            'nav_tabs': nav_tabs,
            'unique_sources': unique_sources,
            'location_badge_text': location_badge_text,
            'zip_code': zip_code or "02720",
            'weather_station_url': weather_station_url,
            'weather_api_key': weather_api_key,
            'weather_icon': weather_icon,
            'zip_pin_editable': zip_pin_editable,
            'show_images': show_images
        }

        # Render template
        try:
            html = template.render(**template_context)
            logger.info(f"Template rendered successfully, HTML length: {len(html)}")
        except Exception as e:
            logger.error(f"TEMPLATE RENDERING FAILED: {e}")
            import traceback
            logger.error(f"TRACEBACK: {traceback.format_exc()}")
            logger.error(f"Template type: {type(template)}")
            logger.error(f"Template context keys: {list(template_context.keys())[:10]}")
            # Fallback to simple HTML
            html = f"<html><body><h1>{title}</h1><p>Template error: {e}</p><p>Generated at {datetime.now()}</p></body></html>"

        with open(os.path.join(self.output_dir, "index.html"), "w", encoding="utf-8", errors='replace') as f:
            f.write(html)


    def _get_nav_tabs(self, active_page: str = "home", zip_code: Optional[str] = None, is_category_page: bool = False) -> str:
        """Generate two-row navigation structure for top local news site
        
        Top row (big, bold): Home • Local • Police & Fire • Sports • Obituaries • Food & Drink
        Second row (smaller, lighter): Media • Scanner • Weather • Submit Tip • Lost & Found • Events
        
        Args:
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
            ("Local", f"{home_href}", "home", "home"),
            ("Police & Fire", f"{category_prefix}crime.html", "crime", "category-crime"),
            ("Sports", f"{category_prefix}sports.html", "sports", "category-sports"),
            ("Obituaries", f"{category_prefix}obituaries.html", "obituaries", "category-obituaries"),
            ("Food & Drink", f"{category_prefix}food.html", "food", "category-food"),
        ]

        # Second row: Secondary navigation (slightly smaller, lighter)
        second_row_tabs = [
            ("Media", f"{category_prefix}entertainment.html", "entertainment", "category-entertainment"),
            ("Scanner", f"{category_prefix}scanner.html", "scanner", "category-scanner"),
            ("Meetings", f"{category_prefix}meetings.html", "meetings", "category-meetings"),
            ("Submit Tip", f"{home_href}#submit", "submit-tip", "home"),
            ("Lost & Found", f"{home_href}#lost-found", "lost-found", "home"),
            ("Events", f"{category_prefix}events.html", "events", "category-events"),
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
            else:
                active_class = 'text-gray-300 hover:text-white font-bold border border-transparent hover:border-gray-700 hover:bg-gray-900/30'
            nav_html += f'''            <a href="{href}" class="px-3 py-2 rounded-lg transition-all duration-200 {active_class}" data-tab="{data_tab}">{label}</a>
'''

        nav_html += '''        </div>
        
        <!-- Second Row: Secondary Navigation (Smaller, Lighter) - Centered under first row -->
        <div class="flex flex-wrap items-center justify-center gap-2 lg:gap-3">
'''
        
        # Second row links
        for i, (label, href, data_tab, page_key) in enumerate(second_row_tabs):
            # Check if this is the active page
            if data_tab in ["submit-tip", "lost-found"]:
                # Submit Tip and Lost & Found are section links on home page - never highlight them as active
                # They're not separate pages, just anchors on the home page
                is_active = False
            else:
                # Default logic for other links
                is_active = (active_page == page_key) or (page_key == "home" and (active_page == "home" or active_page == "all"))

            if is_active:
                active_class = 'text-white font-semibold bg-blue-500/20 border border-blue-500/40'
            else:
                active_class = 'text-gray-400 hover:text-white font-semibold border border-transparent hover:border-gray-600 hover:bg-gray-900/30'
            nav_html += f'''            <a href="{href}" class="px-2 py-1 rounded-md transition-all duration-200 text-sm {active_class}" data-tab="{data_tab}">{label}</a>
'''

        nav_html += '''        </div>
    </div>
    
    <!-- Custom Hamburger Menu - Side Drawer Overlay -->
    <div id="mobileNavMenu" class="hidden fixed inset-0 z-[1000] transition-opacity duration-300" style="opacity: 0;">
        <!-- Backdrop -->
        <div class="fixed inset-0 bg-black/70 backdrop-blur-sm z-[999]" onclick="closeHamburgerMenu()"></div>
        <!-- Side Drawer -->
        <div id="hamburgerDrawer" class="fixed top-0 right-0 h-full w-80 bg-[#161616] shadow-2xl overflow-y-auto transform transition-transform duration-300 ease-out z-[1000]" style="transform: translateX(100%);" onclick="event.stopPropagation()">
'''
        
        # Primary categories with toggle switches
        for label, href, data_tab, page_key in top_row_tabs:
            nav_html += f'''                    <a href="{href}" class="block px-6 py-3 text-lg text-gray-300 hover:text-white hover:bg-gray-800 transition-colors duration-200 border-b border-gray-700" data-tab="{data_tab}" onclick="closeHamburgerMenu()">{label}</a>
'''

        nav_html += '''                    </div>
'''

        # Secondary categories with toggle switches
        for label, href, data_tab, page_key in second_row_tabs:
            nav_html += f'''                    <a href="{href}" class="block px-6 py-2 text-base text-gray-400 hover:text-white hover:bg-gray-800 transition-colors duration-200" data-tab="{data_tab}" onclick="closeHamburgerMenu()">{label}</a>
'''
        
        nav_html += '''                    </div>
        </div>
    </div>
    
    <script>
        // Custom Hamburger Menu with Smooth Animations
        function openHamburgerMenu() {
        }
        
        function closeHamburgerMenu() {
        }
        
        function updateToggleSwitches() {
        }
        
        // Initialize menu - wait for DOM and CategoryPreferences
        function initHamburgerMenu() {
        }
        
        // Start initialization
        if (document.readyState === 'loading') {
        } else {
        }
        
        // Make functions globally available for onclick handlers
        window.openHamburgerMenu = openHamburgerMenu;
        window.closeHamburgerMenu = closeHamburgerMenu;
        
        // Update mobile toggle icons based on preferences
        function updateMobileToggleIcons() {
        }
        
        // Make function globally available
        window.updateMobileToggleIcons = updateMobileToggleIcons;
        
        // Handle toggle button clicks
        document.addEventListener('click', function(e) {
        });
        
        // Toggle admin submenu
        function toggleAdminSubmenu(e) {
        }
        window.toggleAdminSubmenu = toggleAdminSubmenu;
        
        // Update admin link with current zip code and initialize icons
        document.addEventListener('DOMContentLoaded', function() {
        });
    </script>
'''
        
        return nav_html
    
    def _get_index_template(self, zip_code: Optional[str] = None, city_state: Optional[str] = None, articles: Optional[List[Dict]] = None, settings: Optional[Dict] = None) -> Template:
        """Get index page template"""
        # Use FileSystemLoader if available
        if self.use_file_templates and self.jinja_env:
            try:
                template = self.jinja_env.get_template("index.html.j2")
                logger.info("Loaded index.html.j2 template from file system")
                return template
            except Exception as e:
                logger.warning(f"Failed to load index.html.j2 template: {e}")
                # Fallback to basic template
                from jinja2 import Template
                return Template('<html><body><h1>{{title}}</h1><p>Template load failed: {{e}}</p><p>Generated at {{generation_timestamp}}</p></body></html>')
        else:
            logger.info("Using fallback template (file templates not available)")
            # Fallback to basic template
            from jinja2 import Template
            return Template('<html><body><h1>{{title}}</h1><p>Generated at {{generation_timestamp}}</p></body></html>')
        
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
                formatted = self._format_article_for_display(article, show_images) if hasattr(self, '_format_article_for_display') else article.copy()
                formatted_articles.append(formatted)

        # CRITICAL FIX: Sort formatted articles by publication date (newest first)
        formatted_articles.sort(key=lambda x: (
        ), reverse=True)
        
        # Get hero articles for index page
        hero_articles = formatted_articles[:3] if formatted_articles else []  # Top 3 articles as heroes
        
        # DEBUG: Log hero articles for category page
        logger.info(f"CATEGORY PAGE HERO ARTICLES ({category_slug}): {len(hero_articles)}")
        for i, article in enumerate(hero_articles):
            logger.info(f"  Hero [{i}]: {article.get('title', 'No title')[:50]}")

        # Get IDs of featured articles to exclude from main grid
        featured_ids = set()
        for hero_article in hero_articles:
            if hero_article and hero_article.get('id'):
                featured_ids.add(hero_article.get('id'))
        
        # Filter out featured articles from main grid (only show category articles)
        grid_articles = [a for a in formatted_articles if a.get('id') not in featured_ids]
        
        # Add video detection to hero articles
        for hero_article in hero_articles:
            hero_article['_is_video'] = self._is_video_article(hero_article) if hasattr(self, '_is_video_article') else False

        # Get trending articles from this category only (already filtered by category)
        # Use limit=5 to match index page consistency
        try:
            trending_articles_raw = self._get_trending_articles(filtered_articles, limit=5)
        except (AttributeError, ImportError):
            trending_articles_raw = filtered_articles[:5]  # Fallback

        trending_articles = []
        for article in trending_articles_raw:
            formatted = self._format_article_for_display(article, show_images) if hasattr(self, '_format_article_for_display') else article.copy()
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
            with self.get_db_cursor() as cursor:
                cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('zip_pin_editable',))
                row = cursor.fetchone()
                zip_pin_editable = row[0] == '1' if row else False
        except Exception as e:
            logger.warning(f"Could not determine zip pin editability: {e}")
        
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
                with self.get_db_cursor() as cursor:
                    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('weather_station_url',))
                    row = cursor.fetchone()
                    weather_station_url = row[0] if row else ""
            except Exception as e:
                logger.warning(f"Could not get weather station URL from database: {e}")

        # Fall back to weather_ingestor method if not in database
        if not weather_station_url:
            try:
                weather_station_url = self.weather_ingestor.get_primary_weather_station_url()
            except Exception as e:
                logger.warning(f"Could not get weather station URL from ingestor: {e}")

        # Adjust URL for category page context (if it's a relative path, make it relative to category/)
        if weather_station_url.startswith("category/"):
            weather_station_url = "../" + weather_station_url[9:]  # Remove "category/" and add "../"
        elif not weather_station_url.startswith("http"):
            weather_station_url = "../" + weather_station_url  # Make relative to category/
        # If it's an absolute URL (http/https), use as-is
        
        # Get weather icon based on condition
        weather_icon = self._get_weather_icon(weather.get('current', {}).get('condition', ''))
        
        # Extract funeral home names for obituaries filter
        funeral_homes = set()
        if category_slug == "obituaries":
            # Add common funeral home names for filtering
            funeral_homes.update(["Legacy.com", "Funeral Home", "Memorial", "Cremation"])

        current_time = datetime.now().strftime("%I:%M %p")
        generation_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        
        # Get last database update time for enabled articles
        last_db_update = None
        try:
            with self.get_db_cursor() as cursor:
                cursor.execute('SELECT MAX(created_at) FROM articles')
                row = cursor.fetchone()
                if row and row[0]:
                    dt = datetime.fromisoformat(row[0])
                    last_db_update = dt.strftime("%B %d, %Y at %I:%M %p")
                else:
                    last_db_update = "No articles yet"
        except Exception as e:
            logger.warning(f"Could not get last DB update time: {e}")
            last_db_update = "Recently"

        # Format articles and enrich with source data
        formatted_articles = []
        if articles:
            for article in articles:
                formatted = self._format_article_for_display(article, show_images) if hasattr(self, '_format_article_for_display') else article.copy()
                formatted_articles.append(formatted)

        # CRITICAL FIX: Sort formatted articles by publication date (newest first)
        formatted_articles.sort(key=lambda x: (
            -parse_timestamp(x.get('_top_story_updated_at', '1970-01-01T00:00:00')),  # Newest clicked first (negative for descending)
            x.get('_display_order', 999),  # Then by display order
            -parse_timestamp(x.get('published', x.get('created_at', '1970-01-01')))  # Then by publication date
        ), reverse=True)

        # Get hero articles for index page
        hero_articles = formatted_articles[:3] if formatted_articles else []  # Top 3 articles as heroes

        # Get trending articles
        try:
            trending_articles = self._get_trending_articles(formatted_articles, limit=5)
        except (AttributeError, ImportError):
            trending_articles = formatted_articles[:5]  # Fallback

        # Latest stories (different from trending)
        latest_stories = formatted_articles[:5]

        # Newest articles
        newest_articles = formatted_articles[:10]

        # Entertainment articles
        entertainment_articles = [a for a in formatted_articles if 'entertainment' in (a.get('category') or '')][:5]

        # Top article
        top_article = formatted_articles[0] if formatted_articles else None

        # Current time and generation timestamp
        current_time = datetime.now().strftime("%I:%M %p")
        generation_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

        # Get template
        template = self._get_index_template(zip_code, city_state, formatted_articles, {'show_images': show_images})

        logger.error("TEMPLATE CONTEXT CREATION STARTING")
        # Create template context
        template_context = {
            'title': title,
            'description': description,
            'articles': formatted_articles,
            'hero_articles': hero_articles,
            'trending_articles': trending_articles,
            'latest_stories': latest_stories,
            'newest_articles': newest_articles,
            'entertainment_articles': entertainment_articles,
            'top_article': top_article,
            'weather': weather,
            'current_year': datetime.now().year,
            'current_time': current_time,
            'generation_timestamp': generation_timestamp,
            'last_db_update': last_db_update,
            'nav_tabs': nav_tabs,
            'unique_sources': unique_sources,
            'location_badge_text': location_badge_text,
            'zip_code': zip_code or "02720",
            'weather_station_url': weather_station_url,
            'weather_api_key': weather_api_key,
            'weather_icon': weather_icon,
            'zip_pin_editable': zip_pin_editable,
            'show_images': show_images
        }

        # Render template
        logger.error("About to get template")
        template = self._get_index_template(zip_code, city_state, formatted_articles, settings)
        logger.error(f"Got template: {type(template)}")
        logger.error("About to render template")
        logger.error("ABOUT TO CALL template.render()")
        logger.error(f"template_context generation_timestamp: {template_context.get('generation_timestamp', 'NOT_SET')}")
        logger.error(f"template_context last_db_update: {template_context.get('last_db_update', 'NOT_SET')}")
        try:
            html = template.render(**template_context)
            logger.info(f"Template rendered successfully, HTML length: {len(html)}")
        except Exception as e:
            logger.error(f"TEMPLATE RENDERING FAILED: {e}")
            import traceback
            logger.error(f"TRACEBACK: {traceback.format_exc()}")
            logger.error(f"Template type: {type(template)}")
            logger.error(f"Template context keys: {list(template_context.keys())[:10]}")
            # Fallback to simple HTML
            html = f"<html><body><h1>{title}</h1><p>Template error: {e}</p><p>Generated at {datetime.now()}</p></body></html>"

        with open(os.path.join(self.output_dir, "index.html"), "w", encoding="utf-8", errors='replace') as f:
            f.write(html)

        # Prepare template variables
        template_vars = {
        }
        
        # Add funeral homes for obituaries template
        if category_slug == "obituaries":
            template_vars['funeral_homes'] = list(funeral_homes)

        html = template.render(**template_vars)
        
        output_file = os.path.join(output_path, f"{category_slug}.html")
        with open(output_file, "w", encoding="utf-8", errors='replace') as f:
            f.write(html)

        logger.info(f"Generated category page: {output_file} ({len(formatted_articles)} articles)")
    
    def _generate_category_page(self, category_slug: str, articles: List[Dict], weather: Dict, settings: Dict, zip_code: Optional[str] = None):
        """Generate category page using template system"""
        # Determine paths
        if zip_code:
            output_path = os.path.join(self.output_dir, "category")
            home_path = "../"
            css_path = "../css/"
            locale = f"{zip_code} area"  # Will be resolved properly by template
        else:
            output_path = os.path.join(self.output_dir, "category")
            home_path = "../"
            css_path = "../css/"
            locale = self.locale

        os.makedirs(output_path, exist_ok=True)

        # Filter articles by category
        category_articles = [a for a in articles if a.get('category') == category_slug]

        # Get template
        if self.use_file_templates and self.jinja_env:
            try:
                template = self.jinja_env.get_template("category.html.j2")
                logger.info(f"Using category.html.j2 template for {category_slug}")
            except Exception as e:
                logger.warning(f"Failed to load category.html.j2 template: {e}")
                return
        else:
            logger.warning("File templates not available for category generation")
            return

        # Prepare template context
        current_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        generation_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

        # Get category display name
        category_names = {
            'business': 'Business',
            'crime': 'Police & Fire',
            'events': 'Events',
            'food': 'Food & Drink',
            'local-news': 'Local News',
            'meetings': 'Meetings',
            'obituaries': 'Obituaries',
            'scanner': 'Scanner',
            'schools': 'Schools',
            'sports': 'Sports',
            'weather': 'Weather'
        }
        category_name = category_names.get(category_slug, category_slug.title())

        template_context = {
            'category_slug': category_slug,
            'category_name': category_name,
            'title': self.title,
            'locale': locale,
            'articles': category_articles[:50],  # Limit to 50 articles per category
            'hero_articles': category_articles[:5] if len(category_articles) >= 5 else category_articles,
            'trending_articles': category_articles[:10] if len(category_articles) >= 10 else category_articles,
            'weather': weather,
            'settings': settings,
            'home_path': home_path,
            'css_path': css_path,
            'current_time': current_time,
            'generation_timestamp': generation_timestamp,
            'current_year': datetime.now().year,
            'location_badge_text': f"{locale.split(',')[0] if ',' in locale else locale} · {zip_code or '02720'}",
            'show_images': settings.get('show_images', '1') == '1',
            'weather_station_url': weather.get('station_url', '#'),
            'weather_icon': '☀️',  # Default icon
            'nav_tabs': self._get_nav_tabs(f"category-{category_slug}", zip_code, is_category_page=True),
            'last_db_update': getattr(self, 'last_db_update', None)
        }

        # Render template
        try:
            logger.info(f"Rendering category template for {category_slug} with context keys: {list(template_context.keys())}")
            html = template.render(**template_context)
            output_file = os.path.join(output_path, f"{category_slug}.html")
            with open(output_file, "w", encoding="utf-8", errors='replace') as f:
                f.write(html)
            logger.info(f"Generated category page: {output_file}")
        except Exception as e:
            logger.error(f"Failed to render category template for {category_slug}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def _generate_scanner_page(self, weather: Dict, settings: Dict, zip_code: Optional[str] = None, city_state: Optional[str] = None):
        """Generate scanner page with embedded Broadcastify feed

        Args:
        """
        logger.info(f"_generate_scanner_page called with zip_code={zip_code}, city_state={city_state}")

        # DEBUG: Write a test file to see if this function is called
        with open("C:\\FRNA\\scanner_debug.txt", "w") as f:
            f.write(f"Scanner generation called at {datetime.now()} for zip_code={zip_code}")

        # Phase 6: Resolve city name for dynamic title
        locale_name = LOCALE  # Default to "Fall River, MA"
        if city_state:
            locale_name = city_state
        elif zip_code:
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
        
        # Build scanner page HTML with proper navigation
        scanner_html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Police & Fire Scanner</title>
    <meta name="description" content="Live police and fire scanner audio and call transcripts for Fall River, MA — Real-time emergency communications">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background: #0a0a0a; color: #e0e0e0; }
        .broadcastify-iframe {
            background: #1a1a1a;
            border-radius: 8px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
        }
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
</head>
<body class="bg-[#0a0a0a] text-gray-100 min-h-screen">
    <!-- Navigation -->
    <nav class="bg-[#0f0f0f]/80 backdrop-blur-md border-b border-gray-900/20 py-2 sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
''' + nav_tabs + '''
        </div>
    </nav>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div class="max-w-4xl mx-auto">
            <!-- Scanner Header -->
            <div class="text-center mb-8">
                <h1 class="text-4xl font-bold text-gray-100 mb-4">Live Police & Fire Scanner</h1>
                <p class="text-gray-400 text-lg">Real-time audio feed from Fall River emergency services</p>
            </div>

            <!-- Broadcastify Audio Player -->
            <div class="bg-gray-900/80 rounded-lg p-6 mb-6 border border-gray-700/30">
                <h2 class="text-2xl font-bold text-white mb-4 flex items-center">
                    <span class="text-2xl mr-3">🔊</span>
                    Live Audio Feed
                </h2>
                <div style="background: rgba(26, 26, 26, 0.8); border-radius: 8px; padding: 8px;">
                    <iframe
                        src="https://www.broadcastify.com/listen/feed/856/web"
                        style="width: 100%; height: 400px; border: none; border-radius: 8px;"
                        class="broadcastify-iframe"
                        allowfullscreen>
                    </iframe>
                </div>
                <p class="text-xs text-gray-500 mt-3 text-center">
                    Audio player powered by Broadcastify.com • Click to enable autoplay
                </p>
            </div>

            <!-- Call Transcript Feed -->
            <div class="bg-gray-900/80 rounded-lg p-6 border border-gray-700/30">
                <h2 class="text-2xl font-bold text-white mb-4 flex items-center">
                    <span class="text-2xl mr-3">📋</span>
                    Live Call Transcripts
                </h2>
                <div style="background: rgba(26, 26, 26, 0.8); border-radius: 8px; padding: 8px;">
                    <iframe
                        src="https://www.broadcastify.com/listen/ctfeed/856/web"
                        style="width: 100%; height: 500px; border: none; border-radius: 8px;"
                        class="broadcastify-iframe"
                        allowfullscreen>
                    </iframe>
                </div>
                <p class="text-xs text-gray-500 mt-3 text-center">
                    Real-time text transcripts • Updated live as calls come in
                </p>
            </div>
        </div>
    </main>
</body>
</html>'''
        
        output_file = os.path.join(output_path, "scanner.html")
        logger.info(f"About to write scanner page to: {output_file}")
        logger.info(f"HTML length: {len(scanner_html)}")
        with open(output_file, "w", encoding="utf-8", errors='replace') as f:
            f.write(scanner_html)
        logger.info(f"Successfully wrote scanner page: {output_file}")

    def _get_source_gradient(self, source: str) -> str:
        """Get gradient classes for a source"""
        gradients = {
            'herald news': 'from-orange-500 to-red-600',
            'fall river herald news': 'from-orange-500 to-red-600',
            'fall river reporter': 'from-blue-500 to-cyan-600',
            'taunton gazette': 'from-green-500 to-teal-600',
            'taunton daily gazette': 'from-green-500 to-teal-600',
            'new bedford light': 'from-purple-500 to-pink-600',
            'southcoasttoday': 'from-cyan-500 to-blue-600',
            'providence journal': 'from-indigo-500 to-blue-600',
            'boston globe': 'from-red-500 to-pink-600',
            'google news': 'from-blue-600 to-indigo-600',
            'fun107': 'from-pink-500 to-purple-600',
            'anchor news': 'from-emerald-500 to-teal-600',
            'hathaway funeral homes': 'from-slate-500 to-slate-700',
            'washington post': 'from-blue-600 to-indigo-600',
            'new york times': 'from-gray-600 to-gray-800',
            'cnn': 'from-red-500 to-orange-500',
            'bbc': 'from-blue-600 to-purple-600',
            'fox news': 'from-blue-700 to-blue-900',
            'nbc': 'from-blue-500 to-purple-600',
            'abc': 'from-green-500 to-blue-600',
            'cbs': 'from-blue-600 to-cyan-600',
            'reuters': 'from-blue-500 to-indigo-500',
            'ap': 'from-blue-600 to-blue-800',
            'associated press': 'from-blue-600 to-blue-800',
        }
        return gradients.get(source.lower(), 'from-gray-500 to-gray-600')

    def _get_source_glow_color(self, source: str) -> str:
        """Get glow color for a source"""
        glow_colors = {
            'herald news': '#ff6b35',
            'fall river herald news': '#ff6b35',
            'fall river reporter': '#06b6d4',
            'taunton gazette': '#10b981',
            'taunton daily gazette': '#10b981',
            'new bedford light': '#a855f7',
            'southcoasttoday': '#0891b2',
            'providence journal': '#3b82f6',
            'boston globe': '#ef4444',
            'google news': '#2563eb',
            'fun107': '#ec4899',
            'anchor news': '#10b981',
            'hathaway funeral homes': '#64748b',
            'washington post': '#2563eb',
            'new york times': '#374151',
            'cnn': '#dc2626',
            'bbc': '#7c3aed',
            'fox news': '#1e40af',
            'nbc': '#8b5cf6',
            'abc': '#059669',
            'cbs': '#0891b2',
            'reuters': '#3b82f6',
            'ap': '#1e40af',
            'associated press': '#1e40af',
        }
        return glow_colors.get(source.lower(), '#6b7280')

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
            src_file = public_js_dir / filename
            dst_file = output_js_dir / filename
            if src_file.exists():
                import shutil
                shutil.copy2(src_file, dst_file)
                logger.info(f"Copied static JS file: {filename}")

    def _get_trending_articles(self, articles: List[Dict], limit: int = 10) -> List[Dict]:
        """Get trending articles (for now, just return recent articles)"""
        # Sort by publication date and return top N, handling None values
        def sort_key(article):
            published = article.get('published')
            if published:
                return published
            # Fallback to other date fields or default
            return article.get('created_at', article.get('date_sort', '1970-01-01'))

        sorted_articles = sorted(articles, key=sort_key, reverse=True)
        return sorted_articles[:limit]

    def _get_weather_icon(self, condition: str) -> str:
        """Get weather icon emoji based on condition"""
        if not condition:
            return "☀️"

        condition = condition.lower()
        if 'clear' in condition or 'sun' in condition:
            return "☀️"
        elif 'cloud' in condition:
            return "☁️"
        elif 'rain' in condition or 'shower' in condition:
            return "🌧️"
        elif 'snow' in condition:
            return "❄️"
        elif 'storm' in condition or 'thunder' in condition:
            return "⛈️"
        elif 'fog' in condition or 'mist' in condition:
            return "🌫️"
        else:
            return "☀️"

    def _optimize_article_images(self, articles: List[Dict]) -> List[Dict]:
        """Optimize images for a list of articles"""
        optimized_articles = []
        for article in articles:
            # Basic image optimization logic would go here
            # For now, just copy the article
            optimized_articles.append(article)
        return optimized_articles





