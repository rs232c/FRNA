"""
Main aggregation module that combines all news sources
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional
import asyncio
from ingestors.news_ingestor import (
    NewsIngestor, HeraldNewsIngestor, FallRiverReporterIngestor
)
from ingestors.fun107_ingestor import Fun107Ingestor
from ingestors.facebook_ingestor import FacebookIngestor
from ingestors.weather_ingestor import WeatherIngestor
from config import (
    NEWS_SOURCES, AGGREGATION_CONFIG, LOCALE_HASHTAG, HASHTAGS, ARTICLE_CATEGORIES
)
from database import ArticleDatabase
from cache import get_cache
import hashlib
import re
import sqlite3
import json
from typing import Dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NewsAggregator:
    """Main aggregator that collects and processes news from all sources"""
    
    def __init__(self):
        self.news_ingestors = {}
        self.facebook_ingestor = FacebookIngestor()
        self.database = ArticleDatabase()
        self.cache = get_cache()
        self._source_fetch_interval = 30 * 60  # 30 minutes default
        self._setup_ingestors()
    
    def _load_source_overrides(self) -> Dict:
        """Load source configuration overrides from database"""
        try:
            conn = sqlite3.connect(self.database.db_path)
            cursor = conn.cursor()
            
            # Get all source overrides
            cursor.execute('SELECT key, value FROM admin_settings WHERE key LIKE "source_override_%"')
            overrides = {}
            
            for row in cursor.fetchall():
                key = row[0].replace('source_override_', '')
                try:
                    import json
                    override_data = json.loads(row[1])
                    overrides[key] = override_data
                except:
                    pass
            
            conn.close()
            return overrides
        except Exception as e:
            logger.warning(f"Could not load source overrides: {e}")
            return {}
    
    def _setup_ingestors(self):
        """Initialize news source ingestors"""
        # Load source overrides from database
        source_overrides = self._load_source_overrides()
        
        for source_key, source_config in NEWS_SOURCES.items():
            if not source_config.get("enabled", True):
                continue
            
            # Apply database overrides if they exist
            if source_key in source_overrides:
                source_config = {**source_config, **source_overrides[source_key]}
            
            if source_key == "herald_news":
                ingestor = HeraldNewsIngestor(source_config)
            elif source_key == "fall_river_reporter":
                ingestor = FallRiverReporterIngestor(source_config)
            elif source_key == "fun107":
                ingestor = Fun107Ingestor(source_config)
            else:
                ingestor = NewsIngestor(source_config)
            
            # Store source key for retry logic
            ingestor._source_key = source_key
            self.news_ingestors[source_key] = ingestor
    
    def collect_all_articles(self) -> List[Dict]:
        """Collect articles from all sources (synchronous wrapper)"""
        return asyncio.run(self.collect_all_articles_async())
    
    async def collect_all_articles_async(self, force_refresh: bool = False) -> List[Dict]:
        """Collect articles from all sources in parallel (async) with selective updates"""
        all_articles = []
        
        # Check which sources need updating
        sources_to_fetch = self._get_sources_to_fetch(force_refresh)
        
        if not sources_to_fetch:
            logger.info("No sources need updating (all recently fetched)")
            return []
        
        # Create async tasks for sources that need updating
        tasks = []
        source_keys = []
        
        for source_key, ingestor in sources_to_fetch.items():
            source_keys.append(source_key)
            # Wrap in async function with timeout
            async def fetch_with_logging(key, ing):
                try:
                    logger.info(f"Fetching articles from {key}...")
                    articles = await ing.fetch_articles_async()
                    logger.info(f"Fetched {len(articles)} articles from {key}")
                    # Update fetch tracking
                    self._update_source_fetch_time(key, len(articles))
                    return (key, articles, None)
                except Exception as e:
                    logger.error(f"Error fetching from {key}: {e}")
                    return (key, [], e)
            
            tasks.append(fetch_with_logging(source_key, ingestor))
        
        # Fetch all sources in parallel with timeout
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Source fetch failed with exception: {result}")
                    continue
                
                source_key, articles, error = result
                if error:
                    continue
                
                all_articles.extend(articles)
        except Exception as e:
            logger.error(f"Error in parallel fetching: {e}")
        
        # Collect from Facebook (keep synchronous for now, can be async later)
        try:
            logger.info("Fetching Facebook posts...")
            facebook_posts = self.facebook_ingestor.fetch_all_facebook_content()
            all_articles.extend(facebook_posts)
            logger.info(f"Fetched {len(facebook_posts)} Facebook posts")
        except Exception as e:
            logger.error(f"Error fetching Facebook posts: {e}")
        
        # Close all aiohttp sessions
        for source_key, ingestor in self.news_ingestors.items():
            try:
                await ingestor._close_session()
            except Exception as e:
                logger.warning(f"Error closing session for {source_key}: {e}")
        
        return all_articles
    
    def calculate_relevance_score(self, article: Dict) -> float:
        """Calculate Fall River relevance score (0-100) with enhanced local knowledge"""
        from datetime import datetime, timedelta
        
        content = article.get("content", article.get("summary", "")).lower()
        title = article.get("title", "").lower()
        byline = article.get("byline", article.get("author", "")).lower() if article.get("byline") or article.get("author") else ""
        combined = f"{title} {content} {byline}"
        
        score = 0.0
        
        # BONUS: Extra points if "Fall River" appears in body/content (not just title)
        # This ensures articles actually about Fall River get boosted
        fall_river_in_body = any(kw in content for kw in ["fall river", "fallriver"])
        fall_river_in_byline = any(kw in byline for kw in ["fall river", "fallriver"]) if byline else False
        
        if fall_river_in_body:
            # "Fall River" in body gets significant bonus (15 points)
            score += 15.0
        if fall_river_in_byline:
            # "Fall River" in byline gets bonus (10 points)
            score += 10.0
        
        # High relevance keywords (10 points each)
        high_relevance = ["fall river", "fallriver", "fall river ma", "fall river, ma", 
                         "fall river massachusetts", "fall river, massachusetts"]
        for keyword in high_relevance:
            if keyword in combined:
                score += 10.0
        
        # Medium relevance keywords (5 points each) - surrounding towns
        medium_relevance = ["somerset", "swansea", "westport", "freetown", "taunton", "new bedford", 
                           "bristol county", "massachusetts state police", "bristol county sheriff",
                           "dighton", "rehoboth", "seekonk", "warren ri", "tiverton ri"]
        for keyword in medium_relevance:
            if keyword in combined:
                score += 5.0
        
        # Expanded local landmarks/places (3 points each)
        local_places = [
            # Bodies of Water
            "watuppa", "wattupa", "quequechan", "taunton river", "mount hope bay",
            # Landmarks & Attractions
            "battleship cove", "lizzie borden", "lizzie borden house", "fall river heritage state park",
            "marine museum", "narrows center", "gates of the city",
            # Schools
            "durfee", "bmc durfee", "b.m.c. durfee", "durfee high", "durfee high school",
            "saint anne's", "saint anne", "st. anne's", "st. anne", "bishop connolly",
            "diman", "diman regional", "diman vocational", "bristol community college", "bcc",
            "fall river public schools", "f.r.p.s.",
            # Hospitals & Healthcare
            "saint anne's hospital", "st. anne's hospital", "charlton memorial", "southcoast health",
            # Neighborhoods
            "north end", "south end", "highlands", "flint village", "maplewood",
            "lower highlands", "upper highlands", "downtown fall river", "the hill",
            # Streets & Areas
            "pleasant street", "south main street", "north main street", "eastern avenue",
            "highland avenue", "bedford street", "davol street", "government center",
            # Government & Civic
            "city hall", "fall river city hall", "government center", "city council",
            "mayor paul coogan", "mayor coogan", "school committee", "school board",
            # Businesses & Organizations
            "fall river chamber", "fall river economic development", "fall river housing authority",
            "fall river water department", "fall river gas company",
            # Parks & Recreation
            "kennedy park", "lafayette park", "riker park", "bicentennial park",
            "fall river little league", "fall river youth soccer"
        ]
        for place in local_places:
            if place in combined:
                score += 3.0
        
        # Topic-specific scoring (higher weight for important local topics)
        topic_keywords = {
            # Government & Politics (8 points)
            "city council": 8.0, "mayor": 8.0, "school committee": 8.0, "school board": 8.0,
            "city budget": 8.0, "tax rate": 8.0, "zoning": 8.0, "planning board": 8.0,
            # Crime & Safety (7 points)
            "police": 7.0, "arrest": 7.0, "fire department": 7.0, "emergency": 7.0,
            "crime": 7.0, "investigation": 7.0, "suspected": 7.0,
            # Schools & Education (6 points)
            "school": 6.0, "student": 6.0, "teacher": 6.0, "education": 6.0,
            "graduation": 6.0, "principal": 6.0,
            # Local Business (5 points)
            "business": 5.0, "restaurant": 5.0, "opening": 5.0, "closing": 5.0,
            "new business": 5.0, "local business": 5.0,
            # Events & Community (4 points)
            "event": 4.0, "festival": 4.0, "concert": 4.0, "community": 4.0,
            "fundraiser": 4.0, "charity": 4.0
        }
        for keyword, points in topic_keywords.items():
            if keyword in combined:
                score += points
        
        # Source credibility scoring
        source = article.get("source", "").lower()
        source_credibility = {
            "herald news": 25.0,  # Primary local source
            "fall river reporter": 25.0,  # Primary local source
            "wpri": 8.0,  # Regional TV news
            "abc6": 8.0,  # Regional TV news
            "nbc10": 8.0,  # Regional TV news
            "fun107": 5.0,  # Regional radio
            "masslive": 5.0,  # Regional online
            "taunton gazette": 4.0,  # Nearby town paper
            "southcoast today": 4.0  # Regional paper
        }
        for source_name, points in source_credibility.items():
            if source_name in source:
                score += points
                break
        
        # Recency weighting (newer articles get bonus)
        published = article.get("published")
        if published:
            try:
                pub_date = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
                days_old = (datetime.now() - pub_date.replace(tzinfo=None)).days
                if days_old == 0:
                    score += 5.0  # Today's news
                elif days_old <= 1:
                    score += 3.0  # Yesterday
                elif days_old <= 7:
                    score += 1.0  # This week
                # Articles older than a week get no recency bonus
            except:
                pass
        
        # Penalize clickbait/low-quality content
        clickbait_patterns = [
            "you won't believe", "this one trick", "number 7 will shock you",
            "doctors hate", "one weird trick", "click here", "find out more"
        ]
        for pattern in clickbait_patterns:
            if pattern in combined:
                score -= 5.0
        
        # Penalize if no local connection
        if score == 0:
            score = -10.0  # Negative score for completely unrelated
        
        return min(100.0, max(0.0, score))
    
    def _generate_better_summary(self, article: Dict) -> str:
        """Generate a better summary that captures key facts (who, what, when, where)"""
        content = article.get("content", article.get("summary", ""))
        title = article.get("title", "")
        
        if not content:
            return title if title else "No summary available"
        
        # Try to extract first meaningful sentences (skip headlines/intros)
        sentences = content.split('.')
        meaningful_sentences = []
        
        for sentence in sentences[:5]:  # Look at first 5 sentences
            sentence = sentence.strip()
            if len(sentence) < 20:  # Skip very short sentences
                continue
            # Skip common intro phrases
            if any(phrase in sentence.lower() for phrase in [
                "click here", "read more", "continue reading", "full story",
                "subscribe", "sign up", "follow us"
            ]):
                continue
            meaningful_sentences.append(sentence)
            if len(meaningful_sentences) >= 2:  # Get first 2-3 meaningful sentences
                break
        
        # If we found good sentences, combine them
        if meaningful_sentences:
            summary = '. '.join(meaningful_sentences)
            if not summary.endswith('.'):
                summary += '.'
            # Limit to 250 characters for display
            if len(summary) > 250:
                summary = summary[:247] + "..."
            return summary
        
        # Fallback: use first 200 characters of content
        summary = content[:200].strip()
        # Try to end at a sentence boundary
        last_period = summary.rfind('.')
        if last_period > 100:  # If we have a period after 100 chars, use it
            summary = summary[:last_period + 1]
        else:
            summary = summary + "..."
        
        return summary
    
    def filter_relevant_articles(self, articles: List[Dict]) -> List[Dict]:
        """Filter and weight articles by Fall River relevance"""
        from datetime import datetime, timedelta
        import sqlite3
        from config import DATABASE_CONFIG
        
        # Get source settings, AI filtering setting, and relevance threshold from database
        source_settings = {}
        ai_filtering_enabled = False
        relevance_threshold = 10.0  # Default threshold
        try:
            conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM admin_settings WHERE key LIKE "source_%" OR key = "ai_filtering_enabled" OR key = "relevance_threshold"')
            for row in cursor.fetchall():
                key = row['key']
                if key == 'ai_filtering_enabled':
                    ai_filtering_enabled = row['value'] == '1'
                elif key == 'relevance_threshold':
                    try:
                        relevance_threshold = float(row['value'])
                    except:
                        relevance_threshold = 10.0
                else:
                    parts = key.replace('source_', '').split('_', 1)
                    if len(parts) == 2:
                        source_key = parts[0]
                        setting = parts[1]
                        if source_key not in source_settings:
                            source_settings[source_key] = {}
                        source_settings[source_key][setting] = row['value'] == '1'
            conn.close()
        except:
            pass
        
        relevant = []
        keywords = AGGREGATION_CONFIG.get("keywords_filter", [])
        exclude_keywords = AGGREGATION_CONFIG.get("exclude_keywords", [])
        min_length = AGGREGATION_CONFIG.get("min_article_length", 100)
        
        for article in articles:
            # Check if source requires Fall River mention (do this early for logging)
            source = article.get("source", "").lower()
            source_key = None
            for key, config in NEWS_SOURCES.items():
                if config["name"].lower() in source or key in source:
                    source_key = key
                    break
            
            # Check minimum length (more lenient for Fall River Reporter)
            content = article.get("content", article.get("summary", ""))
            min_length_for_source = 50 if source_key == "fall_river_reporter" else min_length
            if len(content) < min_length_for_source:
                if source_key == "fall_river_reporter":
                    logger.info(f"Filtering out Fall River Reporter article '{article.get('title', '')[:50]}...' - content too short: {len(content)} < {min_length_for_source}")
                continue
            
            # Check date
            try:
                pub_str = article.get("published", "")
                if pub_str:
                    pub_date = datetime.fromisoformat(pub_str.replace('Z', '+00:00').split('+')[0])
                    days_old = (datetime.now() - pub_date.replace(tzinfo=None)).days
                    if days_old > 45:
                        if source_key == "fall_river_reporter":
                            logger.info(f"Filtering out Fall River Reporter article '{article.get('title', '')[:50]}...' - too old: {days_old} days")
                        continue
            except:
                pass
            
            # Check for relevant keywords
            content_lower = content.lower()
            title_lower = article.get("title", "").lower()
            combined_text = f"{title_lower} {content_lower}"
            
            # Calculate relevance score
            relevance_score = self.calculate_relevance_score(article)
            article['_relevance_score'] = relevance_score
            
            # Auto-filter articles below relevance threshold
            if relevance_score < relevance_threshold:
                logger.info(f"🔴 AUTO-FILTER: Filtering out article '{title_lower[:50]}...' - relevance score below threshold: {relevance_score:.1f} < {relevance_threshold}")
                
                # Save auto-filtered article to database for review
                try:
                    import sqlite3
                    from config import DATABASE_CONFIG
                    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
                    cursor = conn.cursor()
                    
                    # Save article first
                    cursor.execute('''
                        INSERT OR IGNORE INTO articles 
                        (title, url, published, summary, content, source, source_type, ingested_at, relevance_score)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        article.get("title", ""),
                        article.get("url", ""),
                        article.get("published", ""),
                        article.get("summary", ""),
                        article.get("content", ""),
                        article.get("source", ""),
                        article.get("source_type", ""),
                        article.get("ingested_at", ""),
                        relevance_score
                    ))
                    
                    # Get article ID (either new or existing)
                    if article.get("url"):
                        cursor.execute('SELECT id FROM articles WHERE url = ?', (article.get("url"),))
                        row = cursor.fetchone()
                        article_id = row[0] if row else cursor.lastrowid
                    else:
                        article_id = cursor.lastrowid
                    
                    if article_id:
                        # Mark as auto-rejected due to low relevance score
                        reason = f"Relevance score {relevance_score:.1f} below threshold {relevance_threshold}"
                        cursor.execute('''
                            INSERT OR REPLACE INTO article_management 
                            (article_id, enabled, is_rejected, is_auto_rejected, auto_reject_reason)
                            VALUES (?, 0, 1, 1, ?)
                        ''', (article_id, reason))
                    
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logger.warning(f"Could not save auto-filtered article: {e}")
                
                continue
            
            # Smart require_fall_river filtering: Use relevance score to determine true local relevance
            if source_key:
                require_fr = source_settings.get(source_key, {}).get('require_fall_river', 
                    NEWS_SOURCES.get(source_key, {}).get('require_fall_river', False))
                
                if require_fr:
                    # Log articles when require_fall_river is enabled for debugging
                    has_explicit = "fall river" in combined_text or "fallriver" in combined_text
                    logger.info(f"Article from {source_key}: '{title_lower[:50]}...' - relevance: {relevance_score:.1f}, explicit mention: {has_explicit}, length: {len(content)}")
                    
                    # Smart detection: Use relevance score to determine true local relevance
                    # Accept if: Explicit "Fall River" mention AND relevance_score >= 10
                    # OR accept if: relevance_score >= 20 (catches local landmarks/neighborhoods/nearby towns)
                    has_explicit_mention = "fall river" in combined_text or "fallriver" in combined_text
                    
                    if has_explicit_mention:
                        # Explicit mention - more lenient threshold (10 points)
                        if relevance_score < 10.0:
                            logger.info(f"Filtering out article '{title_lower[:50]}...' - explicit Fall River mention but relevance score too low: {relevance_score:.1f}")
                            continue
                    else:
                        # No explicit mention - stricter threshold (20 points) to catch local landmarks/neighborhoods
                        if relevance_score < 20.0:
                            logger.info(f"Filtering out article '{title_lower[:50]}...' - no Fall River mention and relevance score too low: {relevance_score:.1f} (needs >= 20 for local landmarks/neighborhoods)")
                            continue
            
            # Must not contain excluded keywords
            if exclude_keywords:
                if any(keyword.lower() in combined_text for keyword in exclude_keywords):
                    continue
            
            # AI-based relevance check: Use AI to verify article is truly about Fall River
            # Only run if enabled in admin settings
            if ai_filtering_enabled:
                try:
                    from utils.ai_relevance_checker import AIRelevanceChecker
                    ai_checker = AIRelevanceChecker()
                    
                    # Run AI check for all articles when enabled
                    should_include, ai_reason = ai_checker.should_include(article, threshold=0.6)
                    
                    if not should_include:
                        logger.info(f"🤖 AI FILTER: Filtering out article '{title_lower[:50]}...' - {ai_reason}")
                        continue
                    elif ai_checker.enabled:
                        logger.debug(f"🤖 AI CHECK: Article '{title_lower[:50]}...' passed AI relevance check - {ai_reason}")
                except Exception as e:
                    logger.warning(f"Error in AI relevance checking: {e}")
                    # Continue processing if AI check fails
            
            # Bayesian filtering: Check if article should be rejected based on learned patterns
            try:
                from utils.bayesian_learner import BayesianLearner
                learner = BayesianLearner()
                should_filter, probability, reasons = learner.should_filter(article, threshold=0.7)
                
                if should_filter:
                    reason_str = "; ".join(reasons[:3]) if reasons else "High similarity to previously rejected articles"
                    logger.info(f"🔴 BAYESIAN FILTER: Filtering out article '{title_lower[:50]}...' - Rejection probability: {probability:.1%} - Reasons: {reason_str}")
                    
                    # Save auto-filtered article to database for review
                    try:
                        import sqlite3
                        from config import DATABASE_CONFIG
                        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
                        cursor = conn.cursor()
                        
                        # Save article first
                        cursor.execute('''
                            INSERT OR IGNORE INTO articles 
                            (title, url, published, summary, content, source, source_type, ingested_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            article.get("title", ""),
                            article.get("url", ""),
                            article.get("published", ""),
                            article.get("summary", ""),
                            article.get("content", ""),
                            article.get("source", ""),
                            article.get("source_type", ""),
                            article.get("ingested_at", "")
                        ))
                        
                        # Get article ID (either new or existing)
                        if article.get("url"):
                            cursor.execute('SELECT id FROM articles WHERE url = ?', (article.get("url"),))
                            row = cursor.fetchone()
                            article_id = row[0] if row else cursor.lastrowid
                        else:
                            article_id = cursor.lastrowid
                        
                        if article_id:
                            # Mark as auto-rejected
                            cursor.execute('''
                                INSERT OR REPLACE INTO article_management 
                                (article_id, enabled, is_rejected, is_auto_rejected, auto_reject_reason)
                                VALUES (?, 0, 1, 1, ?)
                            ''', (article_id, reason_str))
                        
                        conn.commit()
                        conn.close()
                    except Exception as e:
                        logger.warning(f"Could not save auto-filtered article: {e}")
                    
                    continue
                elif probability > 0.5:  # Log warnings for medium probability
                    reason_str = "; ".join(reasons[:2]) if reasons else "Some similarity to rejected articles"
                    logger.debug(f"⚠️  BAYESIAN WARNING: Article '{title_lower[:50]}...' has {probability:.1%} rejection probability - {reason_str}")
            except Exception as e:
                logger.warning(f"Error in Bayesian filtering: {e}")
                # Continue processing if Bayesian filtering fails
            
            relevant.append(article)
        
        # Sort by relevance score (highest first), then by date
        relevant.sort(key=lambda x: (
            -x.get('_relevance_score', 0),
            x.get('date_sort', '')
        ))
        
        return relevant
    
    def deduplicate_articles(self, articles: List[Dict]) -> List[Dict]:
        """Remove duplicate articles based on title, URL, source, and published date"""
        seen_keys: Set[str] = set()
        unique_articles = []
        
        for article in articles:
            url = (article.get("url", "") or "").strip()
            title = (article.get("title", "") or "").strip().lower()
            source = (article.get("source", "") or "").strip()
            published = (article.get("published", "") or "").strip()
            
            # Create unique key: prefer URL, fallback to title+source+published
            if url:
                key = f"url:{url}"
            else:
                # Use title + source + published date as unique identifier
                key = f"title:{title}|source:{source}|published:{published}"
            
            # Skip if we've already seen this article
            if key in seen_keys:
                continue
            
            seen_keys.add(key)
            unique_articles.append(article)
        
        return unique_articles
    
    def enrich_articles(self, articles: List[Dict]) -> List[Dict]:
        """Add metadata and formatting to articles"""
        enriched = []
        
        for article in articles:
            # Check if category is manually overridden (don't recalculate)
            category_override = article.get("category_override", 0)
            
            # Detect/assign category if not set or if override is not set
            if not article.get("category") or (not category_override and article.get("category_override") is None):
                # Recalculate category using learned patterns (will use training data)
                detected_category = self._detect_category(article)
                article["category"] = detected_category
                
                # Update database if article has an ID
                if article.get("id"):
                    try:
                        from config import DATABASE_CONFIG
                        import sqlite3
                        db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        cursor.execute('''
                            UPDATE articles 
                            SET category = ?
                            WHERE id = ? AND (category_override = 0 OR category_override IS NULL)
                        ''', (detected_category, article["id"]))
                        conn.commit()
                        conn.close()
                    except Exception as e:
                        logger.warning(f"Error updating category in database: {e}")
            
            # Detect neighborhoods
            article["neighborhoods"] = self._detect_neighborhoods(article)
            
            # Add category info
            category_info = ARTICLE_CATEGORIES.get(article["category"], ARTICLE_CATEGORIES["news"])
            article["category_name"] = category_info["name"]
            article["category_icon"] = category_info["icon"]
            article["category_color"] = category_info["color"]
            
            # Add hashtags
            article["hashtags"] = self._generate_hashtags(article)
            
            # Add formatted date - use actual publication date, NOT today's date
            pub_date = None
            published_str = article.get("published")
            
            # Try to parse published date first
            if published_str:
                try:
                    # Handle various ISO formats
                    pub_str_clean = published_str.replace('Z', '+00:00').split('+')[0].split('.')[0]
                    pub_date = datetime.fromisoformat(pub_str_clean)
                except:
                    try:
                        # Try parsing just the date part
                        pub_date = datetime.fromisoformat(published_str.split('T')[0])
                    except:
                        pass
            
            # If no published date, try date_sort (from database)
            if not pub_date:
                date_sort_str = article.get("date_sort")
                if date_sort_str:
                    try:
                        date_sort_clean = date_sort_str.replace('Z', '+00:00').split('+')[0].split('.')[0]
                        pub_date = datetime.fromisoformat(date_sort_clean)
                    except:
                        try:
                            pub_date = datetime.fromisoformat(date_sort_str.split('T')[0])
                        except:
                            pass
            
            # If still no date, try created_at (ingestion date) as last resort
            if not pub_date:
                created_str = article.get("created_at")
                if created_str:
                    try:
                        created_clean = created_str.replace('Z', '+00:00').split('+')[0].split('.')[0]
                        pub_date = datetime.fromisoformat(created_clean)
                    except:
                        try:
                            pub_date = datetime.fromisoformat(created_str.split('T')[0])
                        except:
                            pass
            
            # Format the date if we found one
            if pub_date:
                article["formatted_date"] = pub_date.strftime("%B %d, %Y at %I:%M %p")
                article["date_sort"] = pub_date.isoformat()
            else:
                # Only use "Recently" if we truly can't find any date
                article["formatted_date"] = "Recently"
                # Don't set date_sort to today - leave it empty or use a very old date
                article["date_sort"] = "1970-01-01T00:00:00"
            
            # Generate better summary
            existing_summary = article.get("summary", "")
            if not existing_summary or len(existing_summary) < 50:
                # Generate new summary if missing or too short
                article["summary"] = self._generate_better_summary(article)
            else:
                # Improve existing summary if it's too long or low quality
                if len(existing_summary) > 250:
                    article["summary"] = self._generate_better_summary(article)
                else:
                    # Keep existing summary but ensure it ends properly
                    summary = existing_summary.strip()
                    if not summary.endswith(('.', '!', '?')):
                        summary = summary.rstrip('.') + "..."
                    article["summary"] = summary
            
            # Calculate reading time estimate (average 200 words per minute)
            content = article.get("content", article.get("summary", ""))
            word_count = len(content.split())
            reading_time = max(1, round(word_count / 200))
            article["reading_time"] = f"{reading_time} min read"
            
            # Add source display name
            if not article.get("source_display"):
                article["source_display"] = article.get("source", "Unknown Source")
            
            enriched.append(article)
        
        # Sort by published date (newest first), fallback to date_sort
        # Handle None values properly for sorting
        enriched.sort(key=lambda x: x.get("published") or x.get("date_sort") or "1970-01-01T00:00:00", reverse=True)
        
        return enriched
    
    def _find_related_articles(self, article: Dict, all_articles: List[Dict], limit: int = 5) -> List[Dict]:
        """Find related articles based on keywords, topics, and categories"""
        if not all_articles:
            return []
        
        article_title = article.get("title", "").lower()
        article_content = article.get("content", article.get("summary", "")).lower()
        article_category = article.get("category", "")
        article_source = article.get("source", "")
        
        # Extract key terms from article (excluding common words)
        common_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "can", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "what", "which", "who", "when", "where", "why", "how"}
        
        # Get meaningful words from title and content
        title_words = set(word.strip('.,!?;:"()[]') for word in article_title.split() if len(word) > 3 and word.lower() not in common_words)
        content_words = set(word.strip('.,!?;:"()[]') for word in article_content.split() if len(word) > 4 and word.lower() not in common_words)
        key_terms = title_words | content_words
        
        # Score each article for relatedness
        related_scores = []
        for other_article in all_articles:
            # Skip the same article
            if other_article.get("id") == article.get("id") or other_article.get("url") == article.get("url"):
                continue
            
            score = 0.0
            
            # Category match (high weight)
            if other_article.get("category") == article_category:
                score += 10.0
            
            # Source match (medium weight)
            if other_article.get("source") == article_source:
                score += 5.0
            
            # Keyword matches
            other_title = other_article.get("title", "").lower()
            other_content = other_article.get("content", other_article.get("summary", "")).lower()
            other_text = f"{other_title} {other_content}"
            
            # Count matching key terms
            matches = sum(1 for term in key_terms if term in other_text)
            score += matches * 2.0
            
            # Check for specific topic matches (crime, government, schools, etc.)
            topic_keywords = ["police", "arrest", "city council", "mayor", "school", "student", "business", "restaurant", "event", "festival"]
            for topic in topic_keywords:
                if topic in article_content and topic in other_content:
                    score += 3.0
            
            if score > 0:
                related_scores.append((score, other_article))
        
        # Sort by score and return top matches
        related_scores.sort(key=lambda x: x[0], reverse=True)
        return [article for _, article in related_scores[:limit]]
    
    def _detect_neighborhoods(self, article: Dict) -> List[str]:
        """Detect neighborhoods mentioned in article"""
        neighborhoods = []
        content = article.get("content", article.get("summary", "")).lower()
        title = article.get("title", "").lower()
        combined = f"{title} {content}"
        
        neighborhood_keywords = {
            "north end": ["north end", "northend"],
            "south end": ["south end", "southend"],
            "highlands": ["highlands", "highland", "the highlands"],
            "flint village": ["flint village", "flintvillage"],
            "maplewood": ["maplewood"],
            "lower highlands": ["lower highlands"],
            "upper highlands": ["upper highlands"],
            "downtown": ["downtown fall river", "downtown"],
            "the hill": ["the hill", "hill neighborhood"]
        }
        
        for neighborhood, keywords in neighborhood_keywords.items():
            if any(keyword in combined for keyword in keywords):
                neighborhoods.append(neighborhood)
        
        return neighborhoods
    
    def _detect_category(self, article: Dict) -> str:
        """Detect article category based on content and source, with source override
        Also learns from manual recategorizations stored in category_training table"""
        from config import NEWS_SOURCES, DATABASE_CONFIG
        import sqlite3
        
        source = article.get("source", "").lower()
        source_display = article.get("source_display", "").lower()
        url = article.get("url", "").lower()
        
        # Check training data for similar articles (learned patterns)
        title = article.get("title", "").lower()
        content = article.get("content", article.get("summary", "")).lower()
        combined = f"{title} {content}"
        
        try:
            db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Create category_training table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS category_training (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER,
                    title TEXT,
                    content TEXT,
                    summary TEXT,
                    source TEXT,
                    url TEXT,
                    original_category TEXT,
                    corrected_category TEXT,
                    zip_code TEXT,
                    trained_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (article_id) REFERENCES articles (id)
                )
            ''')
            
            # Get zip_code from article or use default
            zip_code = article.get("zip_code", "02720")
            
            # Find similar training examples by extracting keywords and matching
            # Look for training examples with similar keywords
            cursor.execute('''
                SELECT corrected_category, COUNT(*) as count
                FROM category_training
                WHERE zip_code = ? OR zip_code IS NULL
                GROUP BY corrected_category
            ''', (zip_code,))
            
            training_categories = {}
            for row in cursor.fetchall():
                cat, count = row
                training_categories[cat] = count
            
            # Extract keywords from training examples for each category
            learned_keywords = {}
            for category in training_categories.keys():
                cursor.execute('''
                    SELECT title, content, summary, source
                    FROM category_training
                    WHERE corrected_category = ? AND (zip_code = ? OR zip_code IS NULL)
                    LIMIT 50
                ''', (category, zip_code))
                
                category_texts = []
                for row in cursor.fetchall():
                    title_text, content_text, summary_text, source_text = row
                    combined_text = f"{title_text or ''} {content_text or ''} {summary_text or ''} {source_text or ''}".lower()
                    category_texts.append(combined_text)
                
                # Extract common keywords (2-4 word phrases) from training examples
                if category_texts:
                    # Simple keyword extraction: find words that appear frequently
                    word_counts = {}
                    for text in category_texts:
                        words = text.split()
                        # Look for 2-3 word phrases
                        for i in range(len(words) - 1):
                            phrase = f"{words[i]} {words[i+1]}"
                            word_counts[phrase] = word_counts.get(phrase, 0) + 1
                        for i in range(len(words) - 2):
                            phrase = f"{words[i]} {words[i+1]} {words[i+2]}"
                            word_counts[phrase] = word_counts.get(phrase, 0) + 1
                    
                    # Get top keywords for this category (appear in at least 2 examples)
                    top_keywords = [kw for kw, count in word_counts.items() if count >= 2 and len(kw) > 3]
                    learned_keywords[category] = top_keywords[:20]  # Top 20 keywords per category
            
            conn.close()
            
            # Check if current article matches learned patterns
            for category, keywords in learned_keywords.items():
                matches = sum(1 for kw in keywords if kw in combined)
                if matches >= 2:  # If 2+ learned keywords match, use this category
                    logger.debug(f"Detected category '{category}' from learned patterns ({matches} keyword matches)")
                    return category
                    
        except Exception as e:
            logger.warning(f"Error loading category training data: {e}")
            # Continue with normal detection if training data fails
        
        # FIRST: Check URL for obituary patterns (most reliable indicator)
        # This catches articles from general news sources that have obituary sections
        # Examples: heraldnews.com/obituaries/..., tauntongazette.com/obituary/...
        obituary_url_patterns = [
            "/obituaries", "/obituary", "/obits", "/obit",
            "/death-notices", "/death-notice", "/death-notices/",
            "/memorials", "/memorial", "/memorial/",
            "/funeral-notices", "/funeral-notice", "/funeral-notices/",
            "/legacy", "/tributes", "/tribute",
            "obituaries/", "obituary/", "obits/", "obit/"
        ]
        if url:
            url_lower = url.lower()
            if any(pattern in url_lower for pattern in obituary_url_patterns):
                # URL contains obituary path - definitely an obituary
                logger.debug(f"Detected obituary from URL pattern: {url}")
                return "obituaries"
        
        # Check if source has a default category in config
        # For funeral homes, ALWAYS use "obituaries" category regardless of content
        source_category = None
        for source_key, source_config in NEWS_SOURCES.items():
            if source_key.lower() in source or source_config.get("name", "").lower() in source or source_config.get("name", "").lower() in source_display:
                source_category = source_config.get("category", "news")
                # If source is configured as obituaries, always return obituaries
                if source_category == "obituaries":
                    return "obituaries"
                break
        
        # Content-based detection (takes priority for news/crime)
        title = article.get("title", "").lower()
        content = article.get("content", article.get("summary", "")).lower()
        combined = f"{title} {content}"

        # Check for obituaries FIRST (very specific)
        # EXCLUDE news articles about deaths (fires, accidents, etc.) - these are NOT obituaries
        news_death_keywords = ["fire", "accident", "crash", "injured", "killed in", "died in", "dead in", "fatal crash", "fatal accident", "fatal fire"]
        if any(keyword in combined for keyword in news_death_keywords):
            # This is a news article about a death, not an obituary - skip obituary detection
            pass
        elif any(word in combined for word in ["obituary", "passed away", "memorial service", "funeral service", "survived by", "predeceased", "visitation", "wake", "calling hours"]):
            # Strong obituary keywords - definitely an obituary
            return "obituaries"
        elif "died" in combined or "passed" in combined:
            # "died" or "passed" alone - only if it has other obituary context
            if any(word in combined for word in ["survived by", "memorial", "funeral", "obituary", "visitation", "wake", "calling hours"]):
                return "obituaries"
        
        # Check for crime/police SECOND (before general news)
        if any(word in combined for word in ["police", "arrest", "crime", "court", "charges", "suspect", "investigation", 
                                            "fire department", "emergency", "accident", "crash", "fatal", "victim",
                                            "murder", "robbery", "theft", "assault", "officer", "detective"]):
            return "crime"
        
        # Check content-based category
        if any(word in combined for word in ["sport", "football", "basketball", "baseball", "hockey", "athlete", "game", "team", "player of the week", "coach", "championship", "score"]):
            return "sports"
        
        # Entertainment keywords (but exclude if it's clearly news/crime)
        if any(word in combined for word in ["music", "concert", "show", "entertainment", "fun", "event", "festival", "theater"]) and not any(word in combined for word in ["police", "arrest", "crime"]):
            return "entertainment"
        
        # Check for business keywords
        if any(word in combined for word in ["business", "company", "development", "economic", "commerce", "retail", "store", "shop", "opening", "closing"]):
            return "business"
        
        # Check for schools/education keywords
        if any(word in combined for word in ["school", "student", "teacher", "education", "academic", "college", "university", "graduation", "principal", "classroom"]):
            return "schools"
        
        # Check for food keywords
        if any(word in combined for word in ["food", "restaurant", "dining", "cafe", "menu", "chef", "cuisine", "meal", "recipe", "kitchen"]):
            return "food"
        
        # Check for weather keywords
        if any(word in combined for word in ["weather", "forecast", "temperature", "rain", "snow", "storm", "climate"]):
            return "weather"
        
        # General news keywords (government, city council, etc.)
        if any(word in combined for word in ["government", "city council", "mayor", "election", "vote", "proposal"]):
            return "news"
        
        # Use source category if set, otherwise default to news
        if source_category:
            return source_category
        
        if article.get("source_type") == "custom":
            return "custom"
        
        # Default to news
        return "news"
    
    def _generate_hashtags(self, article: Dict) -> List[str]:
        """Generate relevant hashtags for an article"""
        tags = list(HASHTAGS)  # Start with base hashtags
        
        # Add source-specific tags
        source = article.get("source", "").lower()
        if "herald" in source:
            tags.append("#HeraldNews")
        elif "reporter" in source:
            tags.append("#FallRiverReporter")
        
        # Add content-based tags (simple keyword matching)
        content = f"{article.get('title', '')} {article.get('content', '')}".lower()
        if any(word in content for word in ["city", "mayor", "council", "government"]):
            tags.append("#CityNews")
        if any(word in content for word in ["school", "education", "student"]):
            tags.append("#Education")
        if any(word in content for word in ["business", "economy", "jobs"]):
            tags.append("#Business")
        
        return tags
    
    def aggregate(self, force_refresh: bool = False, zip_code: Optional[str] = None) -> List[Dict]:
        """Main aggregation method (synchronous wrapper)
        
        Args:
            force_refresh: Force refresh all sources
            zip_code: Optional zip code for zip-specific aggregation
        """
        return asyncio.run(self.aggregate_async(force_refresh, zip_code))
    
    async def aggregate_async(self, force_refresh: bool = False, zip_code: Optional[str] = None) -> List[Dict]:
        """Main aggregation method (async)
        
        Args:
            force_refresh: Force refresh all sources
            zip_code: Optional zip code for zip-specific aggregation
        """
        logger.info(f"Starting aggregation{' for zip ' + zip_code if zip_code else ''}...")
        
        all_articles = []
        
        # If zip_code provided, fetch from Google News
        if zip_code:
            from zip_resolver import resolve_zip
            from ingestors.google_news_ingestor import GoogleNewsIngestor
            
            zip_data = resolve_zip(zip_code)
            if zip_data:
                city = zip_data.get("city", "")
                state = zip_data.get("state_abbrev", "")
                
                if city and state:
                    # Fetch from Google News
                    google_ingestor = GoogleNewsIngestor(city, state, zip_code)
                    google_articles = await google_ingestor.fetch_articles_async()
                    all_articles.extend(google_articles)
                    logger.info(f"Fetched {len(google_articles)} articles from Google News for {city}, {state}")
            
            # Also include existing local RSS feeds if zip matches supported zips (02720, etc.)
            # Check if zip_code is in supported zips (Fall River area)
            supported_zips = ["02720", "02721", "02722", "02723", "02724", "02725", "02726"]
            if zip_code in supported_zips:
                # Collect from existing local sources
                local_articles = await self.collect_all_articles_async(force_refresh=force_refresh)
                # Tag local articles with zip_code
                for article in local_articles:
                    article["zip_code"] = zip_code
                all_articles.extend(local_articles)
                logger.info(f"Added {len(local_articles)} articles from local sources for zip {zip_code}")
        else:
            # Default behavior: collect from all sources (Fall River)
            all_articles = await self.collect_all_articles_async(force_refresh=force_refresh)
        
        logger.info(f"Collected {len(all_articles)} total articles from all sources")
        
        # Deduplicate first (before filtering)
        unique = self.deduplicate_articles(all_articles)
        logger.info(f"Deduplicated to {len(unique)} unique articles")
        
        # Filter relevant articles (skip for zip_code aggregation - Google News is already filtered)
        if zip_code:
            # For zip_code aggregation, skip relevance filtering (Google News is already location-specific)
            relevant = unique
        else:
            relevant = self.filter_relevant_articles(unique)
            logger.info(f"Filtered to {len(relevant)} relevant articles (filtered out {len(unique) - len(relevant)})")
        
        # Enrich with metadata
        enriched = self.enrich_articles(relevant)
        logger.info(f"Final aggregated articles: {len(enriched)}")
        
        return enriched
    
    def _get_sources_to_fetch(self, force_refresh: bool = False) -> Dict:
        """Get sources that need fetching (skip recently updated ones)"""
        if force_refresh:
            return self.news_ingestors
        
        sources_to_fetch = {}
        cutoff_time = datetime.now() - timedelta(seconds=self._source_fetch_interval)
        
        for source_key, ingestor in self.news_ingestors.items():
            last_fetch = self._get_source_last_fetch_time(source_key)
            if not last_fetch or last_fetch < cutoff_time:
                sources_to_fetch[source_key] = ingestor
            else:
                logger.debug(f"Skipping {source_key} - fetched {int((datetime.now() - last_fetch).total_seconds() / 60)} min ago")
        
        return sources_to_fetch
    
    def _get_source_last_fetch_time(self, source_key: str) -> Optional[datetime]:
        """Get last fetch time for a source"""
        try:
            import sqlite3
            from config import DATABASE_CONFIG
            conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
            cursor = conn.cursor()
            cursor.execute('SELECT last_fetch_time FROM source_fetch_tracking WHERE source_key = ?', (source_key,))
            row = cursor.fetchone()
            conn.close()
            
            if row and row[0]:
                return datetime.fromisoformat(row[0])
        except:
            pass
        return None
    
    def _update_source_fetch_time(self, source_key: str, article_count: int):
        """Update last fetch time for a source"""
        try:
            import sqlite3
            from config import DATABASE_CONFIG
            conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO source_fetch_tracking (source_key, last_fetch_time, last_article_count)
                VALUES (?, ?, ?)
            ''', (source_key, datetime.now().isoformat(), article_count))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Could not update source fetch time for {source_key}: {e}")

