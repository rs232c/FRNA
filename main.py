"""
Main orchestrator for Fall River News Aggregator
"""
import logging
import schedule
import time
from datetime import datetime, timezone
from aggregator import NewsAggregator
from website_generator import WebsiteGenerator
from social_poster import SocialPoster
from deploy import WebsiteDeployer
from database import ArticleDatabase
from config import POSTING_SCHEDULE, WEBSITE_CONFIG, DATABASE_CONFIG
from monitoring.metrics import get_metrics, TimingContext
import os
import sqlite3
from typing import List, Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NewsAggregatorApp:
    """Main application class"""
    
    def __init__(self, force_refresh: bool = False):
        self.aggregator = NewsAggregator()
        self.website_generator = WebsiteGenerator()
        self.social_poster = SocialPoster()
        self.deployer = WebsiteDeployer()
        self.database = ArticleDatabase()
        self.force_refresh = force_refresh
        self._last_regenerate_time = None
    
    def _get_regenerate_settings(self):
        """Get regeneration settings from admin"""
        try:
            conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
            cursor = conn.cursor()
            
            # Get auto_regenerate setting
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('auto_regenerate',))
            row = cursor.fetchone()
            auto_regenerate = row[0] == '1' if row else False
            
            # Get regenerate_interval setting (default 10 minutes)
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('regenerate_interval',))
            row = cursor.fetchone()
            regenerate_interval = int(row[0]) if row and row[0] else 10
            
            # Get regenerate_on_load setting
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('regenerate_on_load',))
            row = cursor.fetchone()
            regenerate_on_load = row[0] == '1' if row else False
            
            conn.close()
            return {
                'auto_regenerate': auto_regenerate,
                'regenerate_interval': regenerate_interval,
                'regenerate_on_load': regenerate_on_load
            }
        except Exception as e:
            logger.warning(f"Could not load regenerate settings: {e}, using defaults")
            return {
                'auto_regenerate': True,
                'regenerate_interval': 10,
                'regenerate_on_load': False
            }
    
    def _filter_rejected_articles(self, articles: List[Dict]) -> List[Dict]:
        """Filter out articles that are already in database and marked as rejected"""
        try:
            conn = sqlite3.connect(self.database.db_path)
            cursor = conn.cursor()
            
            # Get all rejected article URLs and titles
            cursor.execute('''
                SELECT DISTINCT a.url, a.title, a.source
                FROM articles a
                JOIN article_management am ON a.id = am.article_id
                WHERE am.is_rejected = 1
            ''')
            rejected = cursor.fetchall()
            conn.close()
            
            # Create sets for fast lookup - normalize URLs by removing query params
            rejected_urls = set()
            for r in rejected:
                if r[0]:  # if URL exists
                    # Normalize URL by removing query parameters and trailing slashes
                    url = r[0].split('?')[0].rstrip('/')
                    rejected_urls.add(url)
                    rejected_urls.add(r[0])  # Also keep original for exact match
            
            rejected_titles_sources = {(r[1].lower().strip() if r[1] else '', r[2] if r[2] else '') for r in rejected}
            
            # Filter articles
            filtered = []
            for article in articles:
                url = article.get("url", "") or ""
                title = article.get("title", "").strip()
                source = article.get("source", "") or ""
                
                # Normalize URL for comparison
                url_normalized = url.split('?')[0].rstrip('/') if url else ""
                
                # Check if rejected by URL (original or normalized)
                if url and (url in rejected_urls or url_normalized in rejected_urls):
                    logger.info(f"Filtering out rejected article by URL: {title[:50]}")
                    continue
                
                # Check if rejected by title + source
                title_source_key = (title.lower(), source)
                if title_source_key in rejected_titles_sources:
                    logger.info(f"Filtering out rejected article by title+source: {title[:50]}")
                    continue
                
                filtered.append(article)
            
            return filtered
        except Exception as e:
            logger.warning(f"Error filtering rejected articles: {e}")
            return articles  # Return all if filtering fails
    
    def _ensure_default_regenerate_settings(self):
        """Ensure default regenerate settings exist in database"""
        try:
            conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
            cursor = conn.cursor()
            
            # Check if settings exist, if not, set defaults
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('auto_regenerate',))
            if not cursor.fetchone():
                cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', ('auto_regenerate', '1'))
            
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('regenerate_interval',))
            if not cursor.fetchone():
                cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', ('regenerate_interval', '10'))
            
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('regenerate_on_load',))
            if not cursor.fetchone():
                cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', ('regenerate_on_load', '0'))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Could not ensure default regenerate settings: {e}")
    
    def run_aggregation_cycle(self, zip_code: Optional[str] = None):
        """Run one complete aggregation cycle
        Phase 3 & 8: Resolves zip → city_state before aggregation
        
        Args:
            zip_code: Optional zip code for zip-specific aggregation
        """
        logger.info("=" * 60)
        logger.info(f"Starting aggregation cycle{' for zip ' + zip_code if zip_code else ''}")
        logger.info("=" * 60)
        
        # Phase 3 & 8: Resolve zip to city_state and ensure city setup
        city_state = None
        if zip_code:
            try:
                from zip_resolver import get_city_state_for_zip
                city_state = get_city_state_for_zip(zip_code)
                if city_state:
                    logger.info(f"Resolved zip {zip_code} to city_state: {city_state}")
                    # Ensure city is set up (Phase 8: auto-start)
                    self._ensure_city_setup(zip_code, city_state)
                else:
                    logger.warning(f"Could not resolve city_state for zip {zip_code}, proceeding with zip_code only")
            except Exception as e:
                logger.warning(f"Error resolving city_state for zip {zip_code}: {e}")
        
        metrics = get_metrics()
        
        try:
            # Remove duplicates from database first
            with TimingContext("remove_duplicates"):
                logger.info("Cleaning duplicate articles from database...")
                removed = self.database.remove_duplicates()
                if removed > 0:
                    logger.info(f"Removed {removed} duplicate articles from database")
                    metrics.record_count("duplicates_removed", removed)
            
            # Aggregate news (async, but called from sync context)
            try:
                with TimingContext("aggregate_articles"):
                    # Use force_refresh from instance or environment variable
                    force_refresh = self.force_refresh or (os.environ.get('FORCE_REFRESH', '0') == '1')
                    if force_refresh:
                        logger.info("Force refresh enabled - fetching fresh data from all sources")
                    logger.info("Starting article aggregation from all sources...")
                    articles = self.aggregator.aggregate(force_refresh=force_refresh, zip_code=zip_code, city_state=city_state)
                    logger.info(f"Aggregation complete: {len(articles)} articles collected")
                    metrics.record_count("articles_aggregated", len(articles))
            except Exception as e:
                logger.error(f"Error during aggregation: {e}", exc_info=True)
                articles = []
            
            if not articles:
                logger.warning("No new articles aggregated")
            else:
                logger.info(f"Successfully aggregated {len(articles)} articles")
                
                # Filter out rejected articles before saving
                with TimingContext("filter_rejected"):
                    logger.info("Filtering out rejected articles...")
                    filtered_articles = self._filter_rejected_articles(articles)
                    logger.info(f"Filtered {len(articles) - len(filtered_articles)} rejected articles")
                    articles = filtered_articles
                
                # Save articles to database (with deduplication)
                with TimingContext("save_articles"):
                    logger.info("Saving articles to database...")
                    # Use zip_code parameter or environment variable
                    save_zip_code = zip_code or os.environ.get('ZIP_CODE')
                    self.database.save_articles(articles, zip_code=save_zip_code)
            
            # Get articles from database (to ensure no duplicates)
            # Get all articles, not just recent ones, sorted by publication date
            # This ensures website is generated even if no new articles were aggregated
            # Phase 2: Use city_state for city-based consolidation
            with TimingContext("get_articles_from_db"):
                db_articles = self.database.get_all_articles(limit=500, zip_code=zip_code, city_state=city_state)
                logger.info(f"Retrieved {len(db_articles)} articles from database")
            
            # Enrich articles with formatted dates and metadata before generating website
            # This ensures articles have formatted_date set from their actual publication date
            with TimingContext("enrich_articles"):
                logger.info("Enriching articles with metadata...")
                enriched_articles = self.aggregator.enrich_articles(db_articles)
                logger.info(f"Enriched {len(enriched_articles)} articles")
            
            # Generate website from enriched articles (Phase 6: city-based generation)
            with TimingContext("generate_website"):
                logger.info("=" * 60)
                logger.info("Starting website generation...")
                logger.info(f"Input: {len(enriched_articles)} enriched articles")
                logger.info("=" * 60)
                self.website_generator.generate(enriched_articles, zip_code=zip_code, city_state=city_state)
                logger.info("=" * 60)
                logger.info("✓ Website generation completed successfully")
                logger.info("=" * 60)
            
            # Save metrics
            metrics.save_metrics()
            
            # Update last regenerate time in database
            try:
                conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO admin_settings (key, value)
                    VALUES ('last_regeneration_time', ?)
                ''', (datetime.now(timezone.utc).isoformat(),))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning(f"Could not update last regeneration time: {e}")
            
            # Auto-deploy if enabled
            if WEBSITE_CONFIG.get("auto_deploy", False):
                logger.info("Auto-deploying website...")
                self.deployer.deploy()
            
            logger.info("=" * 60)
            logger.info("Aggregation cycle completed successfully")
            logger.info("=" * 60)
        
        except Exception as e:
            logger.error(f"Error in aggregation cycle: {e}", exc_info=True)
    
    def _ensure_city_setup(self, zip_code: str, city_state: str):
        """Ensure city is set up for aggregation (Phase 8: auto-start)
        
        Args:
            zip_code: Zip code
            city_state: City state string (e.g., "Fall River, MA")
        """
        try:
            # Initialize relevance config if new city (Phase 5)
            from utils.relevance_calculator import load_relevance_config
            config = load_relevance_config(zip_code=None, city_state=city_state)
            
            # Check if config is empty (new city)
            if not any(config.values()) or len(config.get('high_relevance', [])) == 0:
                logger.info(f"New city detected: {city_state}, initializing relevance config...")
                from utils.relevance_calculator import initialize_relevance_for_city
                # Parse city_state to get city_name and state
                parts = city_state.split(", ")
                if len(parts) == 2:
                    city_name = parts[0]
                    state_abbrev = parts[1]
                    initialize_relevance_for_city(city_state, city_name, state_abbrev)
                    logger.info(f"Initialized relevance config for {city_state}")
        except Exception as e:
            logger.warning(f"Error ensuring city setup for {city_state}: {e}")
    
    def setup_scheduler(self):
        """Setup scheduled tasks based on admin settings"""
        settings = self._get_regenerate_settings()
        
        # If regenerate_on_load is enabled, we'll regenerate on every page load
        # This is handled by the website generator, not the scheduler
        if settings.get('regenerate_on_load'):
            logger.info("Regenerate on every load is enabled - scheduler will still run for background updates")
        
        # Get regeneration interval from admin settings (default 10 minutes)
        interval_minutes = settings.get('regenerate_interval', 10)
        
        if settings.get('auto_regenerate', True):
            # Schedule aggregation cycle every X minutes
            schedule.every(interval_minutes).minutes.do(self.run_aggregation_cycle)
            logger.info(f"Aggregation scheduled to run every {interval_minutes} minutes")
        else:
            logger.info("Auto-regeneration is disabled - will only run manually")
        
        # Also setup social media posting schedule (separate from regeneration)
        frequency = POSTING_SCHEDULE.get("frequency", "hourly")
        if frequency == "hourly":
            schedule.every().hour.do(self._post_to_social_media)
        elif frequency == "daily":
            schedule.every().day.at("09:00").do(self._post_to_social_media)
        elif frequency == "twice_daily":
            schedule.every().day.at("09:00").do(self._post_to_social_media)
            schedule.every().day.at("18:00").do(self._post_to_social_media)
        
        logger.info(f"Social media posting scheduled: {frequency}")
    
    def _post_to_social_media(self):
        """Post to social media (separate from aggregation)"""
        try:
            # Get recent articles from database
            articles = self.database.get_recent_articles(hours=24, limit=10)
            if articles:
                logger.info("Posting to social media...")
                results = self.social_poster.post_articles(
                    articles,
                    max_posts=POSTING_SCHEDULE.get("max_posts_per_day", 10)
                )
                logger.info(f"Social media posting results: {results}")
        except Exception as e:
            logger.error(f"Error posting to social media: {e}")
    
    def run(self, run_once: bool = False, zip_code: Optional[str] = None):
        """Run the aggregator
        
        Args:
            run_once: If True, run once and exit
            zip_code: Optional zip code for zip-specific aggregation
        """
        # Ensure default settings exist
        self._ensure_default_regenerate_settings()
        
        # Run immediately on startup
        self.run_aggregation_cycle(zip_code=zip_code)
        
        if run_once:
            logger.info("Run once mode - exiting")
            return
        
        # Setup scheduler for continuous operation
        self.setup_scheduler()
        
        logger.info("Starting scheduler...")
        logger.info("Press Ctrl+C to stop")
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            logger.info("Shutting down...")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Fall River News Aggregator")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (don't schedule)"
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Force refresh all sources (ignore fetch tracking)"
    )
    parser.add_argument(
        "--zip",
        type=str,
        help="Zip code for zip-specific aggregation (e.g., 02720)"
    )
    args = parser.parse_args()
    
    force_refresh = args.force_refresh or (os.environ.get('FORCE_REFRESH', '0') == '1')
    zip_code = args.zip or os.environ.get('ZIP_CODE')
    
    app = NewsAggregatorApp(force_refresh=force_refresh)
    
    # If zip_code provided, run once for that zip
    if zip_code:
        logger.info(f"Running aggregation for zip code: {zip_code}")
        app.run_aggregation_cycle(zip_code=zip_code)
        logger.info("Zip-specific aggregation completed")
    else:
        app.run(run_once=args.once)


if __name__ == "__main__":
    main()

