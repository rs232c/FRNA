"""
Website generator that creates a static website from aggregated news
MSN-style layout with grid, weather, and widgets
"""
import os
import sqlite3
import re
from jinja2 import Template, Environment, FileSystemLoader
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import logging
from config import WEBSITE_CONFIG, LOCALE, DATABASE_CONFIG, CATEGORY_SLUGS, CATEGORY_MAPPING
from ingestors.weather_ingestor import WeatherIngestor
# Import from new modular structure
try:
    from website_generator.static.css.styles import get_css_content
    from website_generator.static.js.scripts import get_js_content
except ImportError:
    # Fallback to old location
    from website_generator_styles import get_css_content
    from website_generator_scripts import get_js_content
from utils.image_processor import should_optimize_image, optimize_image

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebsiteGenerator:
    """Generate static website from aggregated news with MSN-style layout"""
    
    def __init__(self):
        self.output_dir = WEBSITE_CONFIG.get("output_dir", "website_output")
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
    
    def generate(self, articles: List[Dict], zip_code: Optional[str] = None):
        """Generate complete website with incremental updates
        
        Args:
            articles: List of articles to generate
            zip_code: Optional zip code for zip-specific generation
        """
        try:
            # Set output directory based on zip_code
            original_output_dir = self.output_dir
            if zip_code:
                self.output_dir = os.path.join(original_output_dir, f"zip_{zip_code}")
                os.makedirs(self.output_dir, exist_ok=True)
                # Also create subdirectories
                os.makedirs(os.path.join(self.output_dir, "css"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "js"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "images"), exist_ok=True)
                os.makedirs(os.path.join(self.output_dir, "category"), exist_ok=True)
                logger.info(f"Generating website for zip {zip_code} with {len(articles)} articles...")
            else:
                logger.info(f"Generating website with {len(articles)} articles...")
            
            # Check if we can do incremental update
            last_article_id = self._get_last_generated_article_id()
            new_articles = self._get_new_articles(articles, last_article_id)
            
            # FORCE FULL REGENERATION - Always do full regen to ensure JS updates
            logger.info("Full regeneration: forcing complete rebuild")
            self._generate_full(articles, zip_code)
            
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
                self._generate_full(articles, zip_code)
            except Exception as e2:
                logger.error(f"Full generation also failed: {e2}", exc_info=True)
                raise
            finally:
                # Always restore original output directory
                self.output_dir = original_output_dir
    
    def _generate_full(self, articles: List[Dict], zip_code: Optional[str] = None):
        """Generate complete website from scratch
        
        Args:
            articles: List of articles
            zip_code: Optional zip code for zip-specific generation
        """
        admin_settings = self._get_admin_settings()
        enabled_articles = self._get_enabled_articles(articles, admin_settings, zip_code=zip_code)
        weather = self.weather_ingestor.fetch_weather()
        
        self._generate_index(enabled_articles, weather, admin_settings, zip_code)
        
        # Generate category pages for all navigation categories (in order)
        # This ensures all nav links have working pages, even if empty
        category_order = ["local-news", "crime", "sports", "events", "business", "schools", "food", "obituaries"]
        for category_slug in category_order:
            if category_slug in CATEGORY_SLUGS:
                self._generate_category_page(category_slug, enabled_articles, weather, admin_settings, zip_code)
        
        self._generate_css()
        self._generate_js()
        
        logger.info(f"Website fully regenerated in {self.output_dir}")
    
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
        self._generate_index(enabled_articles, weather, admin_settings, zip_code)
        logger.info("Regenerated index.html")
        
        # CSS and JS only if they don't exist or are old
        css_path = Path(self.output_dir) / "css" / "style.css"
        js_path = Path(self.output_dir) / "js" / "main.js"
        
        if not css_path.exists():
            self._generate_css()
            logger.info("Regenerated CSS")
        
        if not js_path.exists():
            self._generate_js()
            logger.info("Regenerated JS")
        
        logger.info(f"Incremental update complete in {self.output_dir}")
    
    def _get_last_generated_article_id(self) -> int:
        """Get the last article ID that was included in website generation"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT last_article_id FROM website_generation ORDER BY id DESC LIMIT 1')
            row = cursor.fetchone()
            conn.close()
            return row[0] if row and row[0] else 0
        except:
            return 0
    
    def _update_last_generated_article_id(self, article_id: int):
        """Update the last article ID that was included in website generation"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO website_generation (id, last_article_id, last_generation_time)
                VALUES (1, ?, ?)
            ''', (article_id, datetime.now().isoformat()))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Could not update last article ID: {e}")
    
    def _get_new_articles(self, articles: List[Dict], last_article_id: int) -> List[Dict]:
        """Get articles that are newer than last generated article ID"""
        return [a for a in articles if a.get('id', 0) > last_article_id]
    
    def _get_db_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _get_admin_settings(self) -> Dict:
        """Get admin settings from database"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM admin_settings')
            settings = {row['key']: row['value'] for row in cursor.fetchall()}
            conn.close()
            return settings
        except Exception as e:
            logger.warning(f"Could not load admin settings: {e}")
            return {'show_images': '1'}
    
    def _get_enabled_articles(self, articles: List[Dict], settings: Dict, zip_code: Optional[str] = None) -> List[Dict]:
        """Filter and order articles based on admin settings and zip-specific threshold
        
        Args:
            articles: List of article dicts
            settings: Admin settings dict
            zip_code: Optional zip code for zip-specific filtering
        """
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
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
            
            conn.close()
            
            # Filter articles
            enabled = self._filter_and_sort_articles(articles, management)
            
            # Apply relevance threshold filter if zip_code provided
            if zip_code and relevance_threshold is not None:
                enabled = [a for a in enabled if (a.get('relevance_score') or 0) >= relevance_threshold]
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
                   COALESCE(is_rejected, 0) as is_rejected
            FROM article_management
            WHERE article_id IN ({placeholders}) AND zip_code = ?
            AND ROWID IN (
                SELECT MAX(ROWID) 
                FROM article_management 
                WHERE article_id IN ({placeholders}) AND zip_code = ?
                GROUP BY article_id
            )
        ''', tuple(article_ids) + (zip_code,) + tuple(article_ids) + (zip_code,))
        
        return {
            row['article_id']: {
                'enabled': bool(row['enabled']),
                'order': row['display_order'],
                'is_top': row['is_top_article'],
                'is_top_story': row['is_top_story'],
                'is_rejected': bool(row['is_rejected'])
            }
            for row in cursor.fetchall()
        }
    
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
                   COALESCE(is_rejected, 0) as is_rejected
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
                'is_rejected': bool(row['is_rejected'])
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
                    enabled.append(article)
                # If disabled, skip it (don't add to enabled list)
            else:
                # No management entry - default to enabled (new articles are enabled by default)
                article['_display_order'] = article_id or 0
                article['_is_top'] = 0
                article['_is_top_story'] = 0
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
                except:
                    try:
                        # Try parsing as datetime string without timezone
                        dt = datetime.fromisoformat(created.split('T')[0])
                        return dt.timestamp()
                    except:
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
            article_source = (article.get('source', '') or '').lower()
            article_source_display = (article.get('source_display', '') or '').lower()
            already_added = False
            
            # For obituaries: STRICT filtering - exclude news/crime articles
            if category_slug == "obituaries":
                # Check if source is a funeral home FIRST (most reliable) - these are ALWAYS obituaries
                source_matches = False
                for funeral_source in funeral_home_sources:
                    if funeral_source and (funeral_source in article_source or funeral_source in article_source_display):
                        filtered.append(article)
                        already_added = True
                        break
                if already_added:
                    continue
                
                # If article is explicitly categorized as obituaries, include it
                if article_category in ["obituaries", "obituary"]:
                    filtered.append(article)
                    already_added = True
                    continue
                
                # EXCLUDE articles that are explicitly categorized as news, crime, or other non-obituary categories
                # But allow articles with no category or empty category (they might be obituaries)
                if article_category and article_category not in ["obituaries", "obituary", "", None]:
                    # Only exclude if it's explicitly categorized as something non-obituary
                    # Allow through to keyword matching if category is empty/None
                    if article_category in ["news", "crime", "sports", "entertainment", "business", "schools", "food"]:
                        # This article is explicitly categorized as non-obituary - skip it
                        continue
            
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
                
                # For obituaries, require stronger keyword matches AND exclude news articles
                if category_slug == "obituaries":
                    # EXCLUDE articles that are clearly news/accidents (these should NOT be obituaries)
                    # But be careful - only exclude if it's clearly a news report, not an obituary
                    news_exclusion_patterns = [
                        "fire", "accident", "crash", "injured", "killed in", "died in", "dead in", 
                        "fatal crash", "fatal accident", "fatal fire", "police", "arrest", "investigation",
                        "condo fire", "house fire", "car crash", "motor vehicle", "middleboro", "middleborough"
                    ]
                    # Only exclude if it has news keywords AND lacks obituary context
                    has_news_keywords = any(keyword in combined for keyword in news_exclusion_patterns)
                    has_obituary_context = any(keyword in combined for keyword in ["obituary", "survived by", "memorial service", "funeral service", "visitation", "wake", "calling hours", "funeral home"])
                    
                    if has_news_keywords and not has_obituary_context:
                        # This is a news article, not an obituary - skip it
                        continue
                    
                    # Include articles with obituary-specific keywords
                    # These keywords indicate a formal obituary notice
                    strong_keywords = ["obituary", "passed away", "memorial service", "funeral service", "survived by", "predeceased", "visitation", "wake", "calling hours", "funeral home", "memorial visitation"]
                    
                    # Check if title is just a name (common obituary format: "John Smith" or "John Smith, 85")
                    title_words = title.split()
                    is_name_only = len(title_words) <= 4 and not has_news_keywords
                    
                    # Also allow articles that mention "died" or "passed" if they have obituary context
                    if "died" in combined or "passed" in combined:
                        # Include if it has obituary context OR if it's just a name + "died" (likely an obituary)
                        if has_obituary_context or is_name_only or (len(title_words) <= 5 and "died" in title.lower()):
                            # Likely an obituary (short title with just name + "died")
                            filtered.append(article)
                    elif any(keyword in combined for keyword in strong_keywords):
                        filtered.append(article)
                    # Also allow articles that are just names (common obituary format)
                    elif is_name_only:
                        # Short title with just a name - likely an obituary
                        filtered.append(article)
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
        
        return filtered
    
    def _generate_index(self, articles: List[Dict], weather: Dict, settings: Dict, zip_code: Optional[str] = None):
        """Generate main index page
        
        Args:
            articles: List of articles
            weather: Weather data
            settings: Admin settings
            zip_code: Optional zip code for zip-specific generation
        """
        show_images = settings.get('show_images', '1') == '1'
        template = self._get_index_template(zip_code)
        
        # Resolve zip code to city/state if provided
        locale_name = LOCALE
        if zip_code:
            from zip_resolver import resolve_zip
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "")
                state = zip_data.get("state_abbrev", "")
                locale_name = f"{city}, {state}" if city and state else zip_code
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
        # Sort by publication date (newest first) - CRITICAL FIX for hero slider
        top_stories.sort(key=lambda x: (
            x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
        ), reverse=True)
        if not top_stories:
            # Fallback to first 5 news articles if no top stories marked
            top_stories = news_articles[:5] if news_articles else articles[:5]
        
        # Get trending articles (recent articles with high relevance scores)
        try:
            from website_generator.utils import get_trending_articles
            trending_articles = get_trending_articles(articles)
        except ImportError:
            # Fallback to old method
            trending_articles = self._get_trending_articles(articles)
        
        # Get latest stories (5 most recent by publication date, excluding top stories)
        latest_stories = [a for a in articles if not a.get('_is_top_story', 0)]
        # Sort by published date (newest first)
        latest_stories.sort(key=lambda x: (
            x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
        ), reverse=True)
        latest_stories = latest_stories[:5]
        
        # Add related articles to each article
        from aggregator import NewsAggregator
        aggregator = NewsAggregator()
        for article in all_articles:
            related = aggregator._find_related_articles(article, all_articles, limit=3)
            article['_related_articles'] = related[:3]  # Limit to 3 related articles
        
        # Enrich articles with source initials and gradients
        for article in all_articles:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
        for article in top_stories:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
        for article in trending_articles:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
        for article in latest_stories:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
        for article in entertainment_articles:
            if 'source_initials' not in article:
                article['source_initials'] = self._get_source_initials(article.get('source_display', article.get('source', '')))
            if 'source_gradient' not in article:
                article['source_gradient'] = self._get_source_gradient(article.get('source_display', article.get('source', '')))
        
        # Optimize images for articles
        if show_images:
            all_articles = self._optimize_article_images(all_articles)
            top_stories = self._optimize_article_images(top_stories)
            entertainment_articles = self._optimize_article_images(entertainment_articles)
        
        # Get hero articles (top 3 stories for carousel)
        hero_articles = top_stories[:3] if len(top_stories) >= 3 else (top_stories if top_stories else [])
        
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
        
        # Update title and description for zip-specific pages
        title = f"{locale_name} News" if zip_code else self.title
        description = f"Latest news from {locale_name}" if zip_code else self.description
        
        # Get weather station URL (link to actual weather station page if available)
        weather_station_url = self.weather_ingestor.get_primary_weather_station_url()
        
        current_time = datetime.now().strftime("%I:%M %p")
        html = template.render(
            title=title,
            description=description,
            locale=locale_name,
            articles=grid_articles,  # Articles for main grid (excluding featured)
            all_articles=all_articles,  # All articles for reference
            news_articles=news_articles,  # News articles for filtering
            trending_articles=trending_articles[:8],  # Trending articles (6-8 for sidebar)
            entertainment_articles=entertainment_articles[:10],  # Entertainment in sidebar
            sports_articles=sports_articles,  # Sports articles for filtering
            top_stories=top_stories[:5],
            hero_articles=hero_articles,  # Hero articles for carousel (up to 3)
            latest_stories=latest_stories,  # Latest stories by date
            weather=weather,
            weather_condition=weather_condition,
            show_images=show_images,
            current_year=datetime.now().year,
            current_time=current_time,  # Add timestamp for visible change
            nav_tabs=nav_tabs,
            sources=unique_sources,  # Sources for filter dropdown
            location_badge_text=location_badge_text,  # Location badge text
            zip_code=zip_code or "02720",  # Zip code for badge
            weather_station_url=weather_station_url  # Weather station page URL
        )
        
        with open(os.path.join(self.output_dir, "index.html"), "w", encoding="utf-8", errors='replace') as f:
            f.write(html)
    
    def _get_nav_tabs(self, active_page: str = "home", zip_code: Optional[str] = None, is_category_page: bool = False) -> str:
        """Generate consistent navigation tabs across all pages
        
        Args:
            active_page: Current page identifier
            zip_code: Optional zip code for zip-specific pages
            is_category_page: If True, paths are relative from category/ subdirectory
        """
        # Use relative paths for navigation
        # If we're on a category page, we need to go up one level
        if is_category_page:
            home_href = "../index.html"
            category_prefix = ""  # Same directory
        else:
            home_href = "index.html"
            category_prefix = "category/"
        
        tabs = [
            ("Home", home_href, "all", "home"),
        ]
        
        # Add category tabs
        category_order = ["local-news", "crime", "sports", "events", "business", "schools", "food", "obituaries"]
        for slug in category_order:
            if slug in CATEGORY_SLUGS:
                name = CATEGORY_SLUGS[slug]
                page_key = f"category-{slug}"
                href = f"{category_prefix}{slug}.html" if category_prefix else f"{slug}.html"
                tabs.append((name, href, None, page_key))
        
        nav_html = '<div class="flex flex-wrap gap-2">\n'
        for label, href, data_tab, page_key in tabs:
            active_class = 'bg-[#161616] text-blue-400' if active_page == page_key else 'text-gray-300 hover:bg-[#161616]/50 hover:text-gray-100'
            data_attr = f' data-tab="{data_tab}"' if data_tab else ''
            nav_html += f'                    <a href="{href}" class="px-4 py-2 rounded-lg text-sm font-medium transition-colors {active_class}"{data_attr}>{label}</a>\n'
        nav_html += '                </div>'
        return nav_html
    
    def _get_index_template(self, zip_code: Optional[str] = None) -> Template:
        """Get index page template"""
        nav_tabs = self._get_nav_tabs("home", zip_code)
        
        # Use FileSystemLoader if available
        if self.use_file_templates and self.jinja_env:
            return self.jinja_env.get_template("index.html.j2")
        
        # Fallback to string template
        template_str = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <meta name="description" content="{{ description }}">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        'edge-bg': '#0d0d0d',
                        'edge-surface': '#161616',
                        'edge-elevated': '#1f1f1f',
                    }
                }
            }
        }
    </script>
    <link rel="stylesheet" href="css/style.css">
    <style>
        /* Custom styles for things Tailwind can't handle */
        .lazy-image { opacity: 0; transition: opacity 0.3s; }
        .lazy-image.loaded { opacity: 1; }
    </style>
</head>
<body class="bg-[#0f0f0f] text-gray-100 min-h-screen">
    <!-- Top Bar -->
    <div class="bg-[#0f0f0f]/50 backdrop-blur-sm border-b border-gray-900/30 py-2">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                <div class="w-full sm:w-auto flex-1">
                    <div class="relative flex items-center bg-[#161616]/50 backdrop-blur-sm rounded-full px-4 py-2 border border-gray-800/20 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/20">
                        <span class="text-gray-400 mr-2">🔍</span>
                        <input type="text" placeholder="Search articles..." class="bg-transparent border-none outline-none text-gray-100 placeholder-gray-400 flex-1 w-full sm:w-64" id="searchInput">
                        <button class="text-gray-400 hover:text-blue-400 transition-colors ml-2" onclick="toggleSearchFilters()" title="Advanced Filters">⚙️</button>
                    </div>
                    <div class="hidden mt-3 p-4 bg-[#161616] rounded-lg border border-gray-800/30 shadow-xl" id="searchFilters">
                        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-300 mb-2">Category:</label>
                                <select id="filterCategory" class="w-full bg-[#161616] border border-gray-800/30 text-gray-100 rounded-lg px-3 py-2 text-sm focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20">
                                    <option value="">All Categories</option>
                                    <option value="news">📰 News</option>
                                    <option value="entertainment">🎬 Entertainment</option>
                                    <option value="sports">⚽ Sports</option>
                                    <option value="local">📍 Local</option>
                                    <option value="media">🎥 Media</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-300 mb-2">Neighborhood:</label>
                                <select id="filterNeighborhood" class="w-full bg-[#161616] border border-gray-800/30 text-gray-100 rounded-lg px-3 py-2 text-sm focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20">
                                    <option value="">All Neighborhoods</option>
                                    <option value="north end">North End</option>
                                    <option value="south end">South End</option>
                                    <option value="highlands">Highlands</option>
                                    <option value="flint village">Flint Village</option>
                                    <option value="maplewood">Maplewood</option>
                                    <option value="downtown">Downtown</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-300 mb-2">Source:</label>
                                <select id="filterSource" class="w-full bg-[#161616] border border-gray-800/30 text-gray-100 rounded-lg px-3 py-2 text-sm focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20">
                                    <option value="">All Sources</option>
                                    {% for source in sources %}
                                    <option value="{{ source }}">{{ source }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-300 mb-2">Date Range:</label>
                                <select id="filterDateRange" class="w-full bg-[#161616] border border-gray-800/30 text-gray-100 rounded-lg px-3 py-2 text-sm focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20">
                                    <option value="">All Time</option>
                                    <option value="today">Today</option>
                                    <option value="week">Last 7 Days</option>
                                    <option value="month">Last 30 Days</option>
                                </select>
                            </div>
                            <div class="flex items-end">
                                <button class="w-full bg-[#161616] hover:bg-[#1a1a1a] border border-gray-800/30 text-gray-100 px-4 py-2 rounded-lg text-sm font-medium transition-colors" onclick="clearFilters()">Clear Filters</button>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="flex items-center gap-3">
                    <a href="/admin" class="bg-blue-500 hover:bg-blue-600 text-white p-2 rounded-lg transition-colors inline-flex items-center justify-center w-10 h-10" title="Admin Panel">⚙️</a>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Navigation -->
    <nav class="bg-[#0f0f0f]/80 backdrop-blur-md border-b border-gray-900/20 py-2 sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                <div class="text-xl font-semibold text-blue-400">FRNA</div>
                {{ nav_tabs }}
            </div>
        </div>
    </nav>
    
    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 relative">
        <!-- Fixed Location Badge (Top-Left) -->
        <div class="fixed top-4 left-4 z-50 bg-purple-600 text-white px-4 py-2 rounded-full text-sm font-semibold shadow-lg">
            {{ location_badge_text }}
        </div>
        
        <!-- Fixed Weather Pill (Top-Right) -->
        <a href="{{ weather_station_url }}" target="_blank" rel="noopener" class="fixed top-4 right-4 z-50 flex items-center gap-2 bg-gradient-to-br from-blue-600 to-blue-800 rounded-lg px-4 py-2 shadow-lg hover:shadow-xl transition-all duration-300 hover:scale-105">
            <span class="text-xl">🌤️</span>
            <div class="text-white">
                <div class="font-bold text-sm leading-tight">{{ weather.current.temperature }}{{ weather.current.unit }}</div>
                <div class="text-blue-100 text-xs">{{ weather.current.condition }}</div>
            </div>
        </a>
        
        <!-- Hero + Trending Row (65/35 split) -->
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 mb-10">
            <!-- Massive Hero Carousel (65% - 8 columns) -->
            <div class="lg:col-span-8">
                {% if hero_articles and hero_articles|length > 0 %}
                <div class="relative rounded-xl overflow-hidden shadow-2xl h-[400px] lg:h-[600px]" style="overflow: hidden;">
                    <!-- Carousel Container -->
                    <div class="top-stories-track relative h-full" style="display: flex; transition: transform 0.5s ease-in-out; width: {% if hero_articles %}{{ hero_articles|length * 100 }}{% else %}100{% endif %}%;">
                        {% for hero_article in hero_articles %}
                        <div class="story-slide flex-shrink-0 h-full relative" style="width: calc(100% / {% if hero_articles %}{{ hero_articles|length }}{% else %}1{% endif %});">
                            <a href="{{ hero_article.url }}" target="_blank" rel="noopener" class="group block relative w-full h-full">
                                {% if show_images and hero_article.image_url %}
                                <div class="relative h-full overflow-hidden">
                                    <img data-src="{{ hero_article.image_url }}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="{{ hero_article.title }}" loading="lazy" class="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700 lazy-image">
                                    <!-- Dark gradient overlay bottom 40% -->
                                    <div class="absolute inset-0 bg-gradient-to-t from-black/90 via-black/50 to-transparent" style="background: linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.5) 40%, transparent 100%);"></div>
                                    <!-- Video play icon if video -->
                                    {% if hero_article._is_video %}
                                    <div class="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-20">
                                        <div class="bg-white/90 rounded-full p-4 shadow-2xl">
                                            <svg class="w-16 h-16 text-gray-900" fill="currentColor" viewBox="0 0 24 24">
                                                <path d="M8 5v14l11-7z"/>
                                            </svg>
                                        </div>
                                    </div>
                                    {% endif %}
                                    <!-- Content overlay at bottom -->
                                    <div class="absolute bottom-0 left-0 right-0 p-8 lg:p-10">
                                        <h2 class="text-3xl lg:text-5xl font-bold text-white mb-4 line-clamp-3 group-hover:text-blue-300 transition-colors" style="font-size: 3rem; line-height: 1.2;">
                                            {{ hero_article.title }}
                                        </h2>
                                        <div class="flex items-center gap-3 text-sm text-gray-200">
                                            <span class="font-medium">{{ hero_article.source_display }}</span>
                                            <span>•</span>
                                            <span>{{ hero_article.formatted_date.split(' at ')[0] if ' at ' in hero_article.formatted_date else 'Recently' }}</span>
                                            {% if hero_article.reading_time %}
                                            <span>•</span>
                                            <span>{{ hero_article.reading_time }}</span>
                                            {% endif %}
                                        </div>
                                    </div>
                                </div>
                                {% else %}
                                <div class="relative h-full overflow-hidden bg-gradient-to-br {{ hero_article.source_gradient }}">
                                    <!-- Subtle pattern overlay -->
                                    <div class="absolute inset-0 opacity-5" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 20px, rgba(255,255,255,0.03) 20px, rgba(255,255,255,0.03) 40px);"></div>
                                    <!-- City skyline silhouette -->
                                    <div class="absolute bottom-0 left-0 right-0 h-32 opacity-3">
                                        <svg viewBox="0 0 400 100" class="w-full h-full" preserveAspectRatio="none">
                                            <path d="M0,100 L0,85 L15,82 L30,78 L45,75 L60,72 L75,70 L90,68 L105,66 L120,64 L135,62 L150,60 L165,58 L180,56 L195,54 L210,52 L225,50 L240,52 L255,54 L270,56 L285,58 L300,60 L315,62 L330,64 L345,66 L360,68 L375,70 L385,72 L400,75 L400,100 Z" fill="white"/>
                                        </svg>
                                    </div>
                                    <!-- Video play icon if video -->
                                    {% if hero_article._is_video %}
                                    <div class="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-20">
                                        <div class="bg-white/90 rounded-full p-4 shadow-2xl">
                                            <svg class="w-16 h-16 text-gray-900" fill="currentColor" viewBox="0 0 24 24">
                                                <path d="M8 5v14l11-7z"/>
                                            </svg>
                                        </div>
                                    </div>
                                    {% endif %}
                                    <!-- Content overlay at bottom -->
                                    <div class="absolute bottom-0 left-0 right-0 p-8 lg:p-10 bg-gradient-to-t from-black/95 via-black/70 to-transparent">
                                        <h2 class="text-3xl lg:text-5xl font-bold text-white mb-4 line-clamp-3 group-hover:text-blue-300 transition-colors" style="font-size: 3rem; line-height: 1.2;">
                                            {{ hero_article.title }}
                                        </h2>
                                        <div class="flex items-center gap-3 text-sm text-gray-200">
                                            <span class="font-medium">{{ hero_article.source_display }}</span>
                                            <span>•</span>
                                            <span>{{ hero_article.formatted_date.split(' at ')[0] if ' at ' in hero_article.formatted_date else 'Recently' }}</span>
                                            {% if hero_article.reading_time %}
                                            <span>•</span>
                                            <span>{{ hero_article.reading_time }}</span>
                                            {% endif %}
                                        </div>
                                    </div>
                                </div>
                                {% endif %}
                            </a>
                        </div>
                        {% endfor %}
                    </div>
                    
                    <!-- Navigation Dots -->
                    {% if hero_articles|length > 1 %}
                    <div class="slider-dots absolute bottom-4 left-1/2 transform -translate-x-1/2 flex gap-2 z-30">
                        {% for i in range(hero_articles|length) %}
                        <button onclick="goToTopStory({{ i }})" class="dot w-3 h-3 rounded-full {% if loop.first %}bg-white{% else %}bg-white/40{% endif %} hover:bg-white/60 transition-colors cursor-pointer" data-index="{{ i }}"></button>
                        {% endfor %}
                    </div>
                    {% endif %}
                </div>
                {% endif %}
            </div>
            
            <!-- Narrow Trending Sidebar (35% - 4 columns) -->
            <aside class="lg:col-span-4">
                <div class="bg-[#161616] rounded-xl p-6 border border-gray-800/30">
                    <div class="flex items-center gap-2 mb-6">
                        <span class="text-2xl">🔥</span>
                        <h3 class="text-lg font-bold text-gray-100">Trending in {{ locale.split(',')[0] if ',' in locale else locale }}</h3>
                    </div>
                    <div class="space-y-4">
                        {% if trending_articles %}
                            {% for article in trending_articles[:8] %}
                            <a href="{{ article.url }}" target="_blank" rel="noopener" class="block group">
                                <div class="flex items-center gap-3 pb-4 border-b border-gray-800/30 last:border-0 hover:bg-[#1a1a1a] -mx-2 px-2 rounded-lg transition-colors">
                                    {% if show_images and article.image_url %}
                                    <div class="flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden bg-gradient-to-br from-[#161616] to-[#0f0f0f]">
                                        <img data-src="{{ article.image_url }}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="{{ article.title }}" loading="lazy" class="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300 lazy-image">
                                    </div>
                                    {% else %}
                                    <div class="flex-shrink-0 w-16 h-16 rounded-lg bg-gradient-to-br {{ article.source_gradient }} flex items-center justify-center relative overflow-hidden">
                                        <div class="absolute inset-0 opacity-10" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 5px, rgba(255,255,255,0.05) 5px, rgba(255,255,255,0.05) 10px);"></div>
                                        <div class="text-lg font-black text-white/90 drop-shadow-lg relative z-10">{{ article.source_initials }}</div>
                                    </div>
                                    {% endif %}
                                    <div class="flex-1 min-w-0">
                                        <div class="flex items-center gap-1 mb-1">
                                            <span class="text-sm">🔥</span>
                                            <h4 class="text-sm font-semibold text-gray-100 group-hover:text-orange-400 transition-colors line-clamp-2">{{ article.title }}</h4>
                                        </div>
                                        <div class="text-xs text-gray-500">{{ article.source_display }} • {{ article.formatted_date.split(' at ')[0] if ' at ' in article.formatted_date else 'Recently' }}</div>
                                    </div>
                                </div>
                            </a>
                            {% endfor %}
                        {% else %}
                            <p class="text-gray-400 text-sm">No trending articles yet.</p>
                        {% endif %}
                    </div>
                </div>
            </aside>
        </div>
        
        <!-- Perfect Masonry Grid Below Hero (3-4 columns) -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6" id="articlesGrid">
            {% if articles and articles|length > 0 %}
                {% for article in articles[:30] %}
            <article class="bg-[#161616] rounded-xl overflow-hidden shadow-lg hover:shadow-2xl hover:shadow-blue-500/20 transition-all duration-300 hover:scale-[1.03] border border-gray-800/30 flex flex-col h-full" data-category="{{ article.category }}" data-neighborhoods="{{ article.neighborhoods|join(',') if article.neighborhoods else '' }}">
                <!-- Large Thumbnail Top -->
                {% if show_images and article.image_url %}
                <div class="relative h-48 overflow-hidden bg-gradient-to-br from-gray-700 to-gray-900">
                    <img data-src="{{ article.image_url }}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="{{ article.title }}" loading="lazy" class="w-full h-full object-cover hover:scale-110 transition-transform duration-500 lazy-image">
                    <!-- Source pill bottom-left -->
                    <div class="absolute bottom-4 left-4 bg-black/60 backdrop-blur-sm px-3 py-1 rounded-full text-xs font-medium text-white">
                        {{ article.source_display }}
                    </div>
                </div>
                {% else %}
                <div class="relative h-48 overflow-hidden bg-gradient-to-br {{ article.source_gradient }} flex items-center justify-center">
                    <!-- Subtle pattern overlay -->
                    <div class="absolute inset-0 opacity-10" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(255,255,255,0.05) 10px, rgba(255,255,255,0.05) 20px);"></div>
                    <!-- City skyline silhouette -->
                    <div class="absolute bottom-0 left-0 right-0 h-16 opacity-5">
                        <svg viewBox="0 0 400 100" class="w-full h-full" preserveAspectRatio="none">
                            <path d="M0,100 L0,80 L20,75 L40,70 L60,65 L80,60 L100,55 L120,50 L140,45 L160,50 L180,55 L200,60 L220,65 L240,70 L260,75 L280,80 L300,75 L320,70 L340,65 L360,60 L380,55 L400,50 L400,100 Z" fill="white"/>
                        </svg>
                    </div>
                    <!-- Source initials -->
                    <div class="text-center relative z-10">
                        <div class="text-6xl font-black text-white/90 drop-shadow-2xl tracking-tight" style="text-shadow: 0 4px 12px rgba(0,0,0,0.3);">{{ article.source_initials }}</div>
                    </div>
                    <!-- Source pill bottom-left -->
                    <div class="absolute bottom-4 left-4 bg-black/60 backdrop-blur-sm px-3 py-1 rounded-full text-xs font-medium text-white">
                        {{ article.source_display }}
                    </div>
                </div>
                {% endif %}
                
                <!-- Content -->
                <div class="p-4 flex-1 flex flex-col">
                    <h3 class="text-base font-bold mb-2 line-clamp-2 text-gray-100 hover:text-blue-400 transition-colors">
                        <a href="{{ article.url }}" target="_blank" rel="noopener">{{ article.title }}</a>
                    </h3>
                    
                    <!-- Exactly 2-line snippet -->
                    <p class="text-xs text-gray-300 mb-3 line-clamp-2 flex-1">{{ article.summary[:100] if article.summary else '' }}{% if article.summary and article.summary|length > 100 %}...{% endif %}</p>
                    
                    <div class="flex items-center justify-between text-xs text-gray-500 pt-4 border-t border-gray-800/30">
                        <span>{{ article.formatted_date.split(' at ')[0] if ' at ' in article.formatted_date else 'Recently' }}</span>
                        {% if article.reading_time %}
                        <span>{{ article.reading_time }}</span>
                        {% endif %}
                    </div>
                    
                    {% if article._related_articles %}
                    <div class="mt-4 pt-4 border-t border-gray-800/30">
                        <button onclick="toggleRelated(this)" class="text-xs text-gray-400 hover:text-gray-300 transition-colors w-full text-left">
                            📎 Related ({{ article._related_articles|length }})
                        </button>
                        <div class="hidden mt-2 pl-4 border-l-2 border-blue-500">
                            {% for related in article._related_articles %}
                            <div class="mb-2">
                                <a href="{{ related.url }}" target="_blank" rel="noopener" class="text-sm text-blue-400 hover:text-blue-300 transition-colors block">
                                    {{ related.title[:60] }}{% if related.title|length > 60 %}...{% endif %}
                                </a>
                                <span class="text-xs text-gray-500">{{ related.source_display }}</span>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                    {% endif %}
                </div>
            </article>
                {% endfor %}
            {% else %}
            <div class="col-span-full text-center py-12">
                <p class="text-gray-400">No articles found. Check back soon!</p>
            </div>
            {% endif %}
        </div>
    </main>
    
    <!-- Footer -->
    <footer class="bg-[#0f0f0f] border-t border-gray-900/30 mt-12">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
                <div>
                    <h4 class="text-lg font-bold text-gray-100 mb-3">Stay Informed</h4>
                    <p class="text-gray-400 text-sm mb-4">Get daily news updates delivered to your inbox.</p>
                    <form class="flex flex-col sm:flex-row gap-2" id="newsletterForm" onsubmit="handleNewsletterSignup(event)">
                        <input type="email" placeholder="Enter your email" class="flex-1 bg-[#161616] border border-gray-800/30 text-gray-100 rounded-lg px-4 py-2 text-sm focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/20 outline-none" id="newsletterEmail" required>
                        <button type="submit" class="bg-blue-500 hover:bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-semibold transition-colors">Subscribe</button>
                    </form>
                    <div class="text-sm mt-2 min-h-[1.2rem]" id="newsletterMessage"></div>
                </div>
                <div>
                    <h4 class="text-lg font-bold text-gray-100 mb-3">Quick Links</h4>
                    <ul class="space-y-2">
                        <li><a href="index.html" class="text-gray-400 hover:text-blue-400 transition-colors text-sm">Home</a></li>
                    </ul>
                </div>
            </div>
            <div class="pt-6 border-t border-gray-900/30 text-center">
                <p class="text-gray-500 text-sm">&copy; {{ current_year }} {{ locale }} News Aggregator. All rights reserved.</p>
            </div>
        </div>
    </footer>
    
    <!-- Mobile Bottom Navigation -->
    <nav class="fixed bottom-0 left-0 right-0 bg-[#0f0f0f]/95 backdrop-blur-md border-t border-gray-900/30 px-4 py-2 flex justify-around items-center z-50 lg:hidden">
        <a href="index.html" class="flex flex-col items-center gap-1 text-gray-400 hover:text-blue-400 transition-colors py-2 px-4 rounded-lg min-h-[44px] min-w-[44px]">
            <span class="text-xl">🏠</span>
            <span class="text-xs">Home</span>
        </a>
        <a href="{{ weather_station_url }}" target="_blank" rel="noopener" class="flex flex-col items-center gap-1 text-gray-400 hover:text-blue-400 transition-colors py-2 px-4 rounded-lg min-h-[44px] min-w-[44px]">
            <span class="text-xl">🌤️</span>
            <span class="text-xs">Weather</span>
        </a>
    </nav>
    
    <!-- Back to Top Button -->
    <button class="fixed bottom-20 right-6 bg-blue-500 hover:bg-blue-600 text-white w-12 h-12 rounded-full shadow-lg hover:shadow-xl transition-all duration-300 hover:scale-110 hidden lg:block z-40" id="backToTop" onclick="scrollToTop()" title="Back to top">↑</button>
    
    <script src="js/main.js"></script>
    <script>
        // Lazy image loading
        document.addEventListener('DOMContentLoaded', function() {
            const images = document.querySelectorAll('img[data-src]');
            const imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        img.src = img.dataset.src;
                        img.classList.add('loaded');
                        observer.unobserve(img);
                    }
                });
            });
            images.forEach(img => imageObserver.observe(img));
        });
    </script>
</body>
</html>"""
        return Template(template_str)
    
    def _get_trending_articles(self, articles: List[Dict], limit: int = 5) -> List[Dict]:
        """Get trending articles based on recency and relevance score"""
        from datetime import datetime, timedelta
        
        now = datetime.now()
        trending = []
        
        for article in articles:
            # Get publication date
            published = article.get("published")
            if not published:
                continue
            
            try:
                pub_date = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
                days_old = (now - pub_date.replace(tzinfo=None)).days
                
                # Only consider articles from last 7 days
                if days_old <= 7:
                    relevance_score = article.get('_relevance_score', 0)
                    
                    # Calculate trending score: relevance + recency bonus
                    trending_score = relevance_score
                    if days_old == 0:
                        trending_score += 20  # Today's news
                    elif days_old <= 1:
                        trending_score += 15  # Yesterday
                    elif days_old <= 3:
                        trending_score += 10  # Last 3 days
                    elif days_old <= 7:
                        trending_score += 5  # This week
                    
                    article['_trending_score'] = trending_score
                    trending.append(article)
            except:
                continue
        
        # Sort by trending score (highest first)
        trending.sort(key=lambda x: x.get('_trending_score', 0), reverse=True)
        return trending[:limit]
    
    def _get_source_initials(self, source: str) -> str:
        """Extract initials from source name"""
        if not source:
            return "FR"
        
        # Handle common sources
        source_lower = source.lower()
        if "fall river reporter" in source_lower or "fallriverreporter" in source_lower:
            return "FR"
        elif "herald news" in source_lower:
            return "HN"
        elif "wpri" in source_lower:
            return "WP"
        elif "taunton gazette" in source_lower:
            return "TG"
        elif "fun107" in source_lower or "fun 107" in source_lower:
            return "F7"
        elif "frcmedia" in source_lower or "fall river community media" in source_lower:
            return "FR"
        elif "masslive" in source_lower:
            return "ML"
        
        # Extract first letters of words
        words = source.split()
        if len(words) >= 2:
            return (words[0][0] + words[1][0]).upper()
        elif len(words) == 1 and len(words[0]) >= 2:
            return words[0][:2].upper()
        else:
            return source[:2].upper() if len(source) >= 2 else "FR"
    
    def _get_source_gradient(self, source: str) -> str:
        """Get gradient colors for source"""
        if not source:
            return "from-blue-600 to-purple-700"
        
        source_lower = source.lower()
        if "fall river reporter" in source_lower or "fallriverreporter" in source_lower:
            return "from-blue-600 to-indigo-700"
        elif "herald news" in source_lower:
            return "from-indigo-600 to-purple-700"
        elif "wpri" in source_lower:
            return "from-cyan-600 to-blue-700"
        elif "taunton gazette" in source_lower:
            return "from-emerald-600 to-teal-700"
        elif "fun107" in source_lower or "fun 107" in source_lower:
            return "from-pink-600 to-rose-700"
        elif "frcmedia" in source_lower or "fall river community media" in source_lower:
            return "from-violet-600 to-purple-700"
        elif "masslive" in source_lower:
            return "from-orange-600 to-red-700"
        else:
            # Default gradient based on hash of source name for consistency
            import hashlib
            hash_val = int(hashlib.md5(source.encode()).hexdigest()[:8], 16)
            gradients = [
                "from-blue-600 to-indigo-700",
                "from-indigo-600 to-purple-700",
                "from-purple-600 to-pink-700",
                "from-cyan-600 to-blue-700",
                "from-emerald-600 to-teal-700",
                "from-violet-600 to-purple-700"
            ]
            return gradients[hash_val % len(gradients)]
    
    def _is_video_article(self, article: Dict) -> bool:
        """Detect if article is a video
        
        Checks media_type/video_url fields first, then falls back to URL pattern matching
        """
        # Check article data fields first
        if article.get('media_type') == 'video' or article.get('video_url'):
            return True
        
        # Fallback: Check URL patterns
        url = article.get('url', '').lower()
        video_patterns = [
            'youtube.com',
            'youtu.be',
            'vimeo.com',
            'facebook.com/video',
            'fb.com/video',
            '/video/',
            '/watch',
            'dailymotion.com',
            'twitch.tv'
        ]
        
        return any(pattern in url for pattern in video_patterns)
    
    def _enrich_single_article(self, article: Dict) -> Dict:
        """Enrich a single article with formatted data"""
        from config import ARTICLE_CATEGORIES
        
        # Format date
        published = article.get("published")
        if published:
            try:
                dt = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
                formatted_date = dt.strftime("%B %d, %Y at %I:%M %p")
            except:
                formatted_date = published[:10] if len(published) >= 10 else "Recently"
        else:
            formatted_date = "Recently"
        
        # Get category info
        category = article.get("category", "news")
        category_info = ARTICLE_CATEGORIES.get(category, ARTICLE_CATEGORIES["news"])
        
        # Source display
        source = article.get("source", "Unknown")
        source_display = article.get("source_display", source)
        
        enriched = dict(article)
        enriched["formatted_date"] = formatted_date
        enriched["category_name"] = category_info["name"]
        enriched["category_icon"] = category_info["icon"]
        enriched["category_color"] = category_info["color"]
        enriched["source_display"] = source_display
        enriched["source_initials"] = self._get_source_initials(source_display)
        enriched["source_gradient"] = self._get_source_gradient(source_display)
        
        return enriched
    
    def _get_landing_template(self) -> Template:
        """Get landing page template (when no zip code provided)"""
        template_str = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Local News by Zip Code</title>
    <meta name="description" content="Get the latest local news for your area by entering your zip code">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        'edge-bg': '#0d0d0d',
                        'edge-surface': '#161616',
                        'edge-elevated': '#1f1f1f',
                    }
                }
            }
        }
    </script>
    <link rel="stylesheet" href="css/style.css">
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
    <div class="min-h-screen flex items-center justify-center px-4">
        <div class="max-w-2xl w-full text-center">
            <h1 class="text-5xl md:text-6xl font-extrabold mb-6 bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
                Local News Portal
            </h1>
            <p class="text-xl text-gray-400 mb-8">
                Get the latest news for your area
            </p>
            
            <form id="zipForm" onsubmit="handleZipSubmit(event)" class="mb-8">
                <div class="flex flex-col sm:flex-row gap-4 max-w-lg mx-auto">
                    <input 
                        type="text" 
                        id="zipInput" 
                        placeholder="Enter your zip code (e.g., 02720)"
                        pattern="[0-9]{5}"
                        maxlength="5"
                        required
                        class="flex-1 px-6 py-4 bg-[#161616] border border-gray-800/30 rounded-xl text-gray-100 text-lg focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-transparent"
                    >
                    <button 
                        type="submit"
                        class="px-8 py-4 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-xl transition-all duration-300 hover:scale-105 shadow-lg hover:shadow-xl"
                    >
                        Get News →
                    </button>
                </div>
                <p class="text-sm text-gray-500 mt-4">
                    Example: 02720 for Fall River, MA • 10001 for New York, NY
                </p>
            </form>
            
            <div class="grid grid-cols-1 md:grid-cols-3 gap-6 mt-12">
                <div class="bg-[#161616] rounded-xl p-6 border border-gray-800/30">
                    <div class="text-4xl mb-4">📰</div>
                    <h3 class="text-lg font-semibold mb-2">Local News</h3>
                    <p class="text-gray-400 text-sm">Stay informed about what's happening in your community</p>
                </div>
                <div class="bg-[#161616] rounded-xl p-6 border border-gray-800/30">
                    <div class="text-4xl mb-4">⚡</div>
                    <h3 class="text-lg font-semibold mb-2">Real-Time Updates</h3>
                    <p class="text-gray-400 text-sm">Get the latest stories from multiple sources</p>
                </div>
                <div class="bg-[#161616] rounded-xl p-6 border border-gray-800/30">
                    <div class="text-4xl mb-4">📍</div>
                    <h3 class="text-lg font-semibold mb-2">Location-Based</h3>
                    <p class="text-gray-400 text-sm">News tailored to your zip code</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function handleZipSubmit(event) {
            event.preventDefault();
            const zipInput = document.getElementById('zipInput');
            const zipCode = zipInput.value.trim();
            
            if (zipCode.length === 5 && /^[0-9]{5}$/.test(zipCode)) {
                window.location.href = `?z=${zipCode}`;
            } else {
                alert('Please enter a valid 5-digit zip code');
                zipInput.focus();
            }
        }
        
        // Auto-focus input on load
        document.addEventListener('DOMContentLoaded', function() {
            document.getElementById('zipInput').focus();
        });
    </script>
</body>
</html>"""
        from jinja2 import Template
        return Template(template_str)
    
    def _get_obituaries_template(self) -> Template:
        """Get obituaries-specific template"""
        # Use FileSystemLoader if available
        if self.use_file_templates and self.jinja_env:
            return self.jinja_env.get_template("obituaries.html.j2")
        
        # Fallback - should not happen if templates are set up correctly
        logger.warning("Obituaries template file not found, using category template as fallback")
        return self._get_category_template()
    
    def _get_category_template(self) -> Template:
        """Get category page template"""
        
        # Use FileSystemLoader if available
        if self.use_file_templates and self.jinja_env:
            return self.jinja_env.get_template("category.html.j2")
        
        # Fallback to string template
        template_str = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ category_name }} - {{ title }}</title>
    <meta name="description" content="{{ category_name }} news and updates from {{ locale }}">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        'edge-bg': '#0d0d0d',
                        'edge-surface': '#161616',
                        'edge-elevated': '#1f1f1f',
                    }
                }
            }
        }
    </script>
    <link rel="stylesheet" href="{{ css_path }}style.css">
    <style>
        .lazy-image { opacity: 0; transition: opacity 0.3s; }
        .lazy-image.loaded { opacity: 1; }
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
            </div>
        </div>
    </div>
    
    <!-- Navigation -->
    <nav class="bg-[#0f0f0f]/80 backdrop-blur-md border-b border-gray-900/20 py-2 sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex flex-col sm:flex-row items-center justify-between gap-4">
                <div class="text-xl font-semibold text-blue-400">FRNA</div>
                {{ nav_tabs }}
            </div>
        </div>
    </nav>
    
    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 relative">
        <!-- Fixed Location Badge (Top-Left) -->
        <div class="fixed top-4 left-4 z-50 bg-purple-600 text-white px-4 py-2 rounded-full text-sm font-semibold shadow-lg">
            {{ location_badge_text }}
        </div>
        
        <!-- Fixed Weather Pill (Top-Right) -->
        <a href="{{ weather_station_url }}" target="_blank" rel="noopener" class="fixed top-4 right-4 z-50 flex items-center gap-2 bg-gradient-to-br from-blue-600 to-blue-800 rounded-lg px-4 py-2 shadow-lg hover:shadow-xl transition-all duration-300 hover:scale-105">
            <span class="text-xl">🌤️</span>
            <div class="text-white">
                <div class="font-bold text-sm leading-tight">{{ weather.current.temperature }}{{ weather.current.unit }}</div>
                <div class="text-blue-100 text-xs">{{ weather.current.condition }}</div>
            </div>
        </a>
        
        <!-- Category Header -->
        <h1 class="text-4xl font-bold mb-10 text-gray-100">{{ category_name }}</h1>
        
        <!-- Hero + Trending Row (65/35 split) -->
        {% if hero_article %}
        <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 mb-10">
            <!-- Massive Hero Card (65% - 8 columns) -->
            <div class="lg:col-span-8">
                <a href="{{ hero_article.url }}" target="_blank" rel="noopener" class="group block relative rounded-xl overflow-hidden shadow-2xl hover:shadow-blue-500/20 transition-all duration-300">
                    {% if show_images and hero_article.image_url %}
                    <div class="relative h-[400px] lg:h-[600px] overflow-hidden">
                        <img data-src="{{ hero_article.image_url }}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="{{ hero_article.title }}" loading="lazy" class="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700 lazy-image">
                        <!-- Dark gradient overlay bottom 40% -->
                        <div class="absolute inset-0 bg-gradient-to-t from-black/90 via-black/50 to-transparent" style="background: linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.5) 40%, transparent 100%);"></div>
                        <!-- Video play icon if video -->
                        {% if hero_article._is_video %}
                        <div class="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-20">
                            <div class="bg-white/90 rounded-full p-4 shadow-2xl">
                                <svg class="w-16 h-16 text-gray-900" fill="currentColor" viewBox="0 0 24 24">
                                    <path d="M8 5v14l11-7z"/>
                                </svg>
                            </div>
                        </div>
                        {% endif %}
                        <!-- Content overlay at bottom -->
                        <div class="absolute bottom-0 left-0 right-0 p-8 lg:p-10">
                            <h2 class="text-3xl lg:text-5xl font-bold text-white mb-4 line-clamp-3 group-hover:text-blue-300 transition-colors" style="font-size: 3rem; line-height: 1.2;">
                                {{ hero_article.title }}
                            </h2>
                            <div class="flex items-center gap-3 text-sm text-gray-200">
                                <span class="font-medium">{{ hero_article.source_display }}</span>
                                <span>•</span>
                                <span>{{ hero_article.formatted_date.split(' at ')[0] if ' at ' in hero_article.formatted_date else 'Recently' }}</span>
                                {% if hero_article.reading_time %}
                                <span>•</span>
                                <span>{{ hero_article.reading_time }}</span>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    {% else %}
                    <div class="relative h-[400px] lg:h-[600px] overflow-hidden bg-gradient-to-br {{ hero_article.source_gradient }}">
                        <!-- Subtle pattern overlay -->
                        <div class="absolute inset-0 opacity-5" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 20px, rgba(255,255,255,0.03) 20px, rgba(255,255,255,0.03) 40px);"></div>
                        <!-- City skyline silhouette -->
                        <div class="absolute bottom-0 left-0 right-0 h-32 opacity-3">
                            <svg viewBox="0 0 400 100" class="w-full h-full" preserveAspectRatio="none">
                                <path d="M0,100 L0,85 L15,82 L30,78 L45,75 L60,72 L75,70 L90,68 L105,66 L120,64 L135,62 L150,60 L165,58 L180,56 L195,54 L210,52 L225,50 L240,52 L255,54 L270,56 L285,58 L300,60 L315,62 L330,64 L345,66 L360,68 L375,70 L385,72 L400,75 L400,100 Z" fill="white"/>
                            </svg>
                        </div>
                        <!-- Video play icon if video -->
                        {% if hero_article._is_video %}
                        <div class="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-20">
                            <div class="bg-white/90 rounded-full p-4 shadow-2xl">
                                <svg class="w-16 h-16 text-gray-900" fill="currentColor" viewBox="0 0 24 24">
                                    <path d="M8 5v14l11-7z"/>
                                </svg>
                            </div>
                        </div>
                        {% endif %}
                        <!-- Content overlay at bottom -->
                        <div class="absolute bottom-0 left-0 right-0 p-8 lg:p-10 bg-gradient-to-t from-black/95 via-black/70 to-transparent">
                            <h2 class="text-3xl lg:text-5xl font-bold text-white mb-4 line-clamp-3 group-hover:text-blue-300 transition-colors" style="font-size: 3rem; line-height: 1.2;">
                                {{ hero_article.title }}
                            </h2>
                            <div class="flex items-center gap-3 text-sm text-gray-200">
                                <span class="font-medium">{{ hero_article.source_display }}</span>
                                <span>•</span>
                                <span>{{ hero_article.formatted_date.split(' at ')[0] if ' at ' in hero_article.formatted_date else 'Recently' }}</span>
                                {% if hero_article.reading_time %}
                                <span>•</span>
                                <span>{{ hero_article.reading_time }}</span>
                                {% endif %}
                            </div>
                        </div>
                    </div>
                    {% endif %}
                </a>
            </div>
            
            <!-- Narrow Trending Sidebar (35% - 4 columns) -->
            <aside class="lg:col-span-4">
                <div class="bg-[#161616] rounded-xl p-6 border border-gray-800/30">
                    <div class="flex items-center gap-2 mb-6">
                        <span class="text-2xl">🔥</span>
                        <h3 class="text-lg font-bold text-gray-100">Trending in {{ locale.split(',')[0] if ',' in locale else locale }}</h3>
                    </div>
                    <div class="space-y-4">
                        {% if trending_articles %}
                            {% for article in trending_articles[:8] %}
                            <a href="{{ article.url }}" target="_blank" rel="noopener" class="block group">
                                <div class="flex items-center gap-3 pb-4 border-b border-gray-800/30 last:border-0 hover:bg-[#1a1a1a] -mx-2 px-2 rounded-lg transition-colors">
                                    {% if show_images and article.image_url %}
                                    <div class="flex-shrink-0 w-16 h-16 rounded-lg overflow-hidden bg-gradient-to-br from-[#161616] to-[#0f0f0f]">
                                        <img data-src="{{ article.image_url }}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="{{ article.title }}" loading="lazy" class="w-full h-full object-cover group-hover:scale-110 transition-transform duration-300 lazy-image">
                                    </div>
                                    {% else %}
                                    <div class="flex-shrink-0 w-16 h-16 rounded-lg bg-gradient-to-br {{ article.source_gradient }} flex items-center justify-center relative overflow-hidden">
                                        <div class="absolute inset-0 opacity-10" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 5px, rgba(255,255,255,0.05) 5px, rgba(255,255,255,0.05) 10px);"></div>
                                        <div class="text-lg font-black text-white/90 drop-shadow-lg relative z-10">{{ article.source_initials }}</div>
                                    </div>
                                    {% endif %}
                                    <div class="flex-1 min-w-0">
                                        <div class="flex items-center gap-1 mb-1">
                                            <span class="text-sm">🔥</span>
                                            <h4 class="text-sm font-semibold text-gray-100 group-hover:text-orange-400 transition-colors line-clamp-2">{{ article.title }}</h4>
                                        </div>
                                        <div class="text-xs text-gray-500">{{ article.source_display }} • {{ article.formatted_date.split(' at ')[0] if ' at ' in article.formatted_date else 'Recently' }}</div>
                                    </div>
                                </div>
                            </a>
                            {% endfor %}
                        {% else %}
                            <p class="text-gray-400 text-sm">No trending articles yet.</p>
                        {% endif %}
                    </div>
                </div>
            </aside>
        </div>
        {% endif %}
        
        <!-- Perfect Masonry Grid Below Hero (3-4 columns) -->
        {% if articles %}
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6" id="articlesGrid">
            {% for article in articles %}
            <article class="bg-[#161616] rounded-xl overflow-hidden shadow-lg hover:shadow-2xl hover:shadow-blue-500/20 transition-all duration-300 hover:scale-[1.03] border border-gray-800/30 flex flex-col h-full" data-category="{{ article.category }}" data-neighborhoods="{{ article.neighborhoods|join(',') if article.neighborhoods else '' }}">
                <!-- Square Thumbnail Top -->
                {% if show_images and article.image_url %}
                <div class="relative aspect-square overflow-hidden bg-gradient-to-br from-gray-700 to-gray-900">
                    <img data-src="{{ article.image_url }}" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3C/svg%3E" alt="{{ article.title }}" loading="lazy" class="w-full h-full object-cover hover:scale-110 transition-transform duration-500 lazy-image">
                    <!-- Source pill bottom-left -->
                    <div class="absolute bottom-4 left-4 bg-black/60 backdrop-blur-sm px-3 py-1 rounded-full text-xs font-medium text-white">
                        {{ article.source_display }}
                    </div>
                </div>
                {% else %}
                <div class="relative aspect-square overflow-hidden bg-gradient-to-br {{ article.source_gradient }} flex items-center justify-center">
                    <!-- Subtle pattern overlay -->
                    <div class="absolute inset-0 opacity-10" style="background-image: repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(255,255,255,0.05) 10px, rgba(255,255,255,0.05) 20px);"></div>
                    <!-- City skyline silhouette -->
                    <div class="absolute bottom-0 left-0 right-0 h-16 opacity-5">
                        <svg viewBox="0 0 400 100" class="w-full h-full" preserveAspectRatio="none">
                            <path d="M0,100 L0,80 L20,75 L40,70 L60,65 L80,60 L100,55 L120,50 L140,45 L160,50 L180,55 L200,60 L220,65 L240,70 L260,75 L280,80 L300,75 L320,70 L340,65 L360,60 L380,55 L400,50 L400,100 Z" fill="white"/>
                        </svg>
                    </div>
                    <!-- Source initials -->
                    <div class="text-center relative z-10">
                        <div class="text-6xl font-black text-white/90 drop-shadow-2xl tracking-tight" style="text-shadow: 0 4px 12px rgba(0,0,0,0.3);">{{ article.source_initials }}</div>
                    </div>
                    <!-- Source pill bottom-left -->
                    <div class="absolute bottom-4 left-4 bg-black/60 backdrop-blur-sm px-3 py-1 rounded-full text-xs font-medium text-white">
                        {{ article.source_display }}
                    </div>
                </div>
                {% endif %}
                
                <!-- Content -->
                <div class="p-4 flex-1 flex flex-col">
                    <h2 class="text-base font-bold mb-2 line-clamp-2 text-gray-100 hover:text-blue-400 transition-colors">
                        <a href="{{ article.url }}" target="_blank" rel="noopener">{{ article.title }}</a>
                    </h2>
                    
                    <!-- Exactly 2-line snippet -->
                    <p class="text-xs text-gray-300 mb-3 line-clamp-2 flex-1">{{ article.summary[:100] if article.summary else '' }}{% if article.summary and article.summary|length > 100 %}...{% endif %}</p>
                    
                    <div class="flex items-center justify-between text-xs text-gray-500 pt-3 border-t border-gray-800/30">
                        <span>{{ article.formatted_date.split(' at ')[0] if ' at ' in article.formatted_date else 'Recently' }}</span>
                        {% if article.reading_time %}
                        <span>{{ article.reading_time }}</span>
                        {% endif %}
                    </div>
                </div>
            </article>
            {% endfor %}
        </div>
        {% else %}
        <div class="bg-[#161616] rounded-xl p-12 text-center border border-gray-800/30">
            <p class="text-gray-400 text-lg mb-2">No articles found in this category.</p>
            <p class="text-gray-500 text-sm">Check back soon for new content!</p>
            <a href="{{ home_path }}index.html" class="mt-4 inline-block text-blue-400 hover:text-blue-300">← Back to Home</a>
        </div>
        {% endif %}
    </main>
    
    <!-- Footer -->
    <footer class="bg-[#0f0f0f] border-t border-gray-900/30 mt-12 py-8">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-gray-400 text-sm">
            <p>&copy; {{ current_year }} {{ locale }} News. All rights reserved.</p>
        </div>
    </footer>
    
    <script src="{{ home_path }}js/main.js"></script>
    <script>
        // Lazy load images with data-src
        document.addEventListener('DOMContentLoaded', function() {
            const images = document.querySelectorAll('img[data-src]');
            const imageObserver = new IntersectionObserver((entries, observer) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const img = entry.target;
                        if (img.dataset.src) {
                            img.src = img.dataset.src;
                            img.removeAttribute('data-src');
                            img.classList.add('loaded');
                            observer.unobserve(img);
                        }
                    }
                });
            }, { rootMargin: '50px' });
            images.forEach(img => imageObserver.observe(img));
        });
    </script>
</body>
</html>"""
        return Template(template_str)
    
    def _generate_category_page(self, category_slug: str, articles: List[Dict], weather: Dict, settings: Dict, zip_code: Optional[str] = None):
        """Generate a category page
        
        Args:
            category_slug: Category slug (e.g., 'local-news', 'crime')
            articles: List of all articles
            weather: Weather data
            settings: Admin settings
            zip_code: Optional zip code for zip-specific generation
        """
        if category_slug not in CATEGORY_SLUGS:
            logger.warning(f"Invalid category slug: {category_slug}")
            return
        
        category_name = CATEGORY_SLUGS[category_slug]
        show_images = settings.get('show_images', '1') == '1'
        
        # Use special template for obituaries
        if category_slug == "obituaries":
            template = self._get_obituaries_template()
        else:
            template = self._get_category_template()
        
        # Filter articles by category
        filtered_articles = self._filter_articles_by_category(articles, category_slug)
        
        # Resolve zip code to city/state if provided
        locale_name = LOCALE
        if zip_code:
            from zip_resolver import resolve_zip
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "")
                state = zip_data.get("state_abbrev", "")
                locale_name = f"{city}, {state}" if city and state else zip_code
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
        for article in filtered_articles:
            formatted = self._format_article_for_display(article, show_images)
            # Add source initials and gradients
            if 'source_initials' not in formatted:
                formatted['source_initials'] = self._get_source_initials(formatted.get('source_display', formatted.get('source', '')))
            if 'source_gradient' not in formatted:
                formatted['source_gradient'] = self._get_source_gradient(formatted.get('source_display', formatted.get('source', '')))
            formatted['_is_video'] = self._is_video_article(formatted)
            formatted_articles.append(formatted)
        
        # CRITICAL FIX: Sort formatted articles by publication date (newest first)
        formatted_articles.sort(key=lambda x: (
            x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
        ), reverse=True)
        
        # Get hero articles - prioritize top-story articles from this category
        if category_slug == "obituaries":
            hero_articles = formatted_articles[:1] if formatted_articles else []  # Single hero for obituaries
        else:
            # Get top-story articles from this category first (already filtered by category)
            category_top_stories = [a for a in filtered_articles if a.get('_is_top_story', 0)]
            # Sort by date (newest first)
            category_top_stories.sort(key=lambda x: (
                x.get("published") or x.get("date_sort") or x.get("created_at") or "1970-01-01"
            ), reverse=True)
            
            # Format top stories for hero carousel
            formatted_top_stories = []
            for article in category_top_stories[:3]:
                formatted = self._format_article_for_display(article, show_images)
                # Add source initials and gradients
                if 'source_initials' not in formatted:
                    formatted['source_initials'] = self._get_source_initials(formatted.get('source_display', formatted.get('source', '')))
                if 'source_gradient' not in formatted:
                    formatted['source_gradient'] = self._get_source_gradient(formatted.get('source_display', formatted.get('source', '')))
                formatted['_is_video'] = self._is_video_article(formatted)
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
        trending_articles_raw = self._get_trending_articles(filtered_articles, limit=8)
        trending_articles = []
        for article in trending_articles_raw:
            formatted = self._format_article_for_display(article, show_images)
            if 'source_initials' not in formatted:
                formatted['source_initials'] = self._get_source_initials(formatted.get('source_display', formatted.get('source', '')))
            if 'source_gradient' not in formatted:
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
        
        # Generate navigation (from category subdirectory)
        nav_tabs = self._get_nav_tabs(f"category-{category_slug}", zip_code, is_category_page=True)
        
        # Update title
        title = f"{locale_name} News" if zip_code else self.title
        
        # Get weather station URL (link to actual weather station page if available)
        weather_station_url = self.weather_ingestor.get_primary_weather_station_url()
        # Adjust URL for category page context (if it's a relative path, make it relative to category/)
        if weather_station_url.startswith("category/"):
            # Already relative, keep as is
            pass
        elif not weather_station_url.startswith("http"):
            # Relative path, adjust for category subdirectory
            weather_station_url = f"../{weather_station_url}"
        # If it's an absolute URL (http/https), use as-is
        
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
        
        # Prepare template variables
        template_vars = {
            "title": title,
            "category_name": category_name,
            "locale": locale_name,
            "articles": grid_articles,
            "hero_articles": hero_articles,  # Hero articles for carousel (up to 3)
            "hero_article": None,  # Keep for backward compatibility but use hero_articles
            "trending_articles": trending_articles[:8],
            "weather": weather,
            "show_images": show_images,
            "current_year": datetime.now().year,
            "current_time": current_time,
            "nav_tabs": nav_tabs,
            "home_path": home_path,
            "css_path": css_path,
            "location_badge_text": location_badge_text,
            "zip_code": zip_code or "02720",
            "weather_station_url": weather_station_url
        }
        
        # Add funeral homes for obituaries template
        if category_slug == "obituaries":
            template_vars["funeral_homes"] = funeral_homes
        
        html = template.render(**template_vars)
        
        output_file = os.path.join(output_path, f"{category_slug}.html")
        with open(output_file, "w", encoding="utf-8", errors='replace') as f:
            f.write(html)
        
        logger.info(f"Generated category page: {output_file} ({len(formatted_articles)} articles)")
    
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
            except:
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





