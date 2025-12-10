"""
Relevance score calculator for Fall River articles
"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import sqlite3
import logging
from config import DATABASE_CONFIG

logger = logging.getLogger(__name__)

# Cache for relevance config to avoid repeated database queries (zip-specific)
_relevance_config_cache = {}  # Dict[zip_code or None, config]
_cache_timestamp = {}  # Dict[zip_code or None, timestamp]


def load_relevance_config(force_reload=False, zip_code=None):
    """Load relevance configuration from database with caching (zip-specific)
    
    Args:
        force_reload: If True, clear cache and reload
        zip_code: Optional zip code to load zip-specific config. If None, loads global config.
    
    Returns:
        Dict with relevance configuration
    """
    global _relevance_config_cache, _cache_timestamp
    
    cache_key = zip_code if zip_code else None
    
    # Clear cache if forcing reload
    if force_reload:
        if cache_key in _relevance_config_cache:
            del _relevance_config_cache[cache_key]
        if cache_key in _cache_timestamp:
            del _cache_timestamp[cache_key]
    
    # Return cached config if available and not forcing reload
    if not force_reload and cache_key in _relevance_config_cache:
        return _relevance_config_cache[cache_key]
    
    db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
    config = {
        'high_relevance': [],
        'medium_relevance': [],
        'local_places': [],
        'topic_keywords': {},
        'source_credibility': {},
        'clickbait_patterns': []
    }
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Load zip-specific config if zip_code provided, otherwise load global (zip_code IS NULL)
        if zip_code:
            cursor.execute('SELECT category, item, points FROM relevance_config WHERE zip_code = ?', (zip_code,))
        else:
            cursor.execute('SELECT category, item, points FROM relevance_config WHERE zip_code IS NULL')
        
        rows = cursor.fetchall()
        
        for row in rows:
            category = row['category']
            item = row['item']
            points = row['points']
            
            if category in ['high_relevance', 'medium_relevance', 'local_places', 'clickbait_patterns']:
                config[category].append(item)
            elif category == 'topic_keywords':
                config[category][item] = points if points is not None else 0.0
            elif category == 'source_credibility':
                config[category][item] = points if points is not None else 0.0
        
        # Load category-level points from admin_settings_zip (before closing connection)
        if zip_code:
            try:
                cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key IN (?, ?)', 
                             (zip_code, 'high_relevance_points', 'local_places_points'))
                for row in cursor.fetchall():
                    key = row['key']
                    value = row['value']
                    try:
                        config[key] = float(value)
                    except (ValueError, TypeError):
                        pass
            except Exception as e:
                logger.warning(f"Error loading category points from admin_settings_zip: {e}")
            # Set defaults if not found
            if 'high_relevance_points' not in config:
                config['high_relevance_points'] = 15.0
            if 'local_places_points' not in config:
                config['local_places_points'] = 3.0
        else:
            # Defaults for global config
            config['high_relevance_points'] = 15.0
            config['local_places_points'] = 3.0
        
        conn.close()
        
        # If no config found for zip, use defaults
        if not any(config.values()):
            logger.info(f"No relevance config found for zip {zip_code}, using defaults")
            config = get_default_relevance_config()
        
        # Cache the config
        _relevance_config_cache[cache_key] = config
        _cache_timestamp[cache_key] = datetime.now()
        
        return config
    except Exception as e:
        logger.warning(f"Error loading relevance config from database: {e}. Using defaults.")
        # Return default hardcoded values as fallback
        return get_default_relevance_config()


def get_default_relevance_config():
    """Get default hardcoded relevance configuration"""
    return {
        'high_relevance': ["fall river", "fallriver", "fall river ma", "fall river, ma", 
                          "fall river massachusetts", "fall river, massachusetts"],
        'medium_relevance': ["somerset", "swansea", "westport", "freetown", "taunton", "new bedford", 
                            "bristol county", "massachusetts state police", "bristol county sheriff",
                            "dighton", "rehoboth", "seekonk", "warren ri", "tiverton ri"],
        'local_places': [
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
        ],
        'topic_keywords': {
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
        },
        'source_credibility': {
            "herald news": 25.0,
            "fall river reporter": 25.0,
            "wpri": 8.0,
            "abc6": 8.0,
            "nbc10": 8.0,
            "fun107": 5.0,
            "masslive": 5.0,
            "taunton gazette": 4.0,
            "southcoast today": 4.0
        },
        'clickbait_patterns': [
            "you won't believe", "this one trick", "number 7 will shock you",
            "doctors hate", "one weird trick", "click here", "find out more"
        ]
    }


def calculate_relevance_score(article: Dict, config: Optional[Dict] = None, zip_code: Optional[str] = None) -> float:
    """Calculate relevance score (0-100) with enhanced local knowledge
    
    Args:
        article: Article dict with title, content, source, etc. May include is_stellar field.
        config: Optional pre-loaded relevance config. If None, loads from database.
        zip_code: Optional zip code to use zip-specific relevance config.
    
    Returns:
        Relevance score between 0 and 100
    """
    # Load config from database if not provided
    if config is None:
        config = load_relevance_config(zip_code=zip_code)
    
    content = article.get("content", article.get("summary", "")).lower()
    title = article.get("title", "").lower()
    combined = f"{title} {content}"
    
    score = 0.0
    
    # Stellar article boost (+50 points)
    if article.get('is_stellar', 0) or article.get('id'):
        # Check database if is_stellar not in article dict
        is_stellar = article.get('is_stellar', 0)
        if not is_stellar and article.get('id') and zip_code:
            try:
                conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT is_stellar FROM article_management 
                    WHERE article_id = ? AND zip_code = ?
                    ORDER BY id DESC LIMIT 1
                ''', (article.get('id'), zip_code))
                row = cursor.fetchone()
                if row:
                    is_stellar = row[0] or 0
                conn.close()
            except Exception as e:
                logger.warning(f"Error checking stellar status: {e}")
        
        if is_stellar:
            score += 50.0
    
    # High relevance keywords (15 points each, configurable)
    high_relevance = config.get('high_relevance', [])
    high_relevance_points = config.get('high_relevance_points', 15.0)  # Default 15, but editable
    for keyword in high_relevance:
        if keyword in combined:
            score += float(high_relevance_points)
    
    # Medium relevance keywords - only count if Fall River is also mentioned, otherwise penalize
    # These are nearby towns that should be ignored unless Fall River is also mentioned
    medium_relevance = config.get('medium_relevance', [])
    has_fall_river_mention = any(kw in combined for kw in ['fall river', 'fallriver'])
    
    for keyword in medium_relevance:
        if keyword in combined:
            if has_fall_river_mention:
                # If Fall River is mentioned, give small positive points (1 point instead of 5)
                score += 1.0
            else:
                # If Fall River is NOT mentioned, heavily penalize (these are nearby towns we want to ignore)
                score -= 15.0
    
    # Expanded local landmarks/places (3 points each, configurable)
    local_places = config.get('local_places', [])
    local_places_points = config.get('local_places_points', 3.0)  # Default 3, but editable
    for place in local_places:
        if place in combined:
            score += float(local_places_points)
    
    # Topic-specific scoring (higher weight for important local topics)
    topic_keywords = config.get('topic_keywords', {})
    for keyword, points in topic_keywords.items():
        if keyword in combined:
            score += points
    
    # Source credibility scoring
    source = article.get("source", "").lower()
    source_credibility = config.get('source_credibility', {})
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
    clickbait_patterns = config.get('clickbait_patterns', [])
    for pattern in clickbait_patterns:
        if pattern in combined:
            score -= 5.0
    
    # Penalize if no local connection
    if score == 0:
        score = -10.0  # Negative score for completely unrelated
    
    return min(100.0, max(0.0, score))


def calculate_relevance_score_with_tags(article: Dict, config: Optional[Dict] = None, zip_code: Optional[str] = None) -> Tuple[float, Dict[str, List[str]]]:
    """Calculate relevance score and return matched tags
    
    Args:
        article: Article dict with title, content, source, etc.
        config: Optional pre-loaded relevance config. If None, loads from database.
        zip_code: Optional zip code to use zip-specific relevance config.
    
    Returns:
        Tuple of (score, matched_tags_dict) where matched_tags_dict contains:
        - 'matched': List of matched keywords/tags
        - 'missing': List of important tags that were NOT found
    """
    # Load config from database if not provided
    if config is None:
        config = load_relevance_config(zip_code=zip_code)
    
    content = article.get("content", article.get("summary", "")).lower()
    title = article.get("title", "").lower()
    combined = f"{title} {content}"
    
    score = 0.0
    matched_tags = []
    missing_important_tags = []
    
    # Stellar article boost (+50 points)
    if article.get('is_stellar', 0):
        score += 50.0
        matched_tags.append("⭐ Stellar article")
    
    # High relevance keywords (15 points each, configurable)
    high_relevance = config.get('high_relevance', [])
    high_relevance_points = config.get('high_relevance_points', 15.0)
    found_high_relevance = False
    for keyword in high_relevance:
        if keyword in combined:
            score += float(high_relevance_points)
            matched_tags.append(f"📍 {keyword} (+{high_relevance_points})")
            found_high_relevance = True
    if not found_high_relevance and high_relevance:
        missing_important_tags.append("High relevance keywords (Fall River mentions)")
    
    # Medium relevance keywords
    medium_relevance = config.get('medium_relevance', [])
    has_fall_river_mention = any(kw in combined for kw in ['fall river', 'fallriver'])
    found_medium = []
    for keyword in medium_relevance:
        if keyword in combined:
            if has_fall_river_mention:
                score += 1.0
                matched_tags.append(f"🏘️ {keyword} (+1)")
            else:
                score -= 15.0
                matched_tags.append(f"⚠️ {keyword} (-15, no Fall River mention)")
            found_medium.append(keyword)
    
    # Local landmarks/places
    local_places = config.get('local_places', [])
    local_places_points = config.get('local_places_points', 3.0)
    found_places = []
    for place in local_places:
        if place in combined:
            score += float(local_places_points)
            matched_tags.append(f"🏛️ {place} (+{local_places_points})")
            found_places.append(place)
    
    # Topic-specific scoring
    topic_keywords = config.get('topic_keywords', {})
    found_topics = []
    for keyword, points in topic_keywords.items():
        if keyword in combined:
            score += points
            matched_tags.append(f"📰 {keyword} (+{points})")
            found_topics.append(keyword)
    
    # Source credibility scoring
    source = article.get("source", "").lower()
    source_credibility = config.get('source_credibility', {})
    found_source = False
    for source_name, points in source_credibility.items():
        if source_name in source:
            score += points
            matched_tags.append(f"📺 {source_name} (+{points})")
            found_source = True
            break
    if not found_source:
        missing_important_tags.append("Credible local source")
    
    # Recency weighting
    published = article.get("published")
    if published:
        try:
            pub_date = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
            days_old = (datetime.now() - pub_date.replace(tzinfo=None)).days
            if days_old == 0:
                score += 5.0
                matched_tags.append("🕐 Published today (+5)")
            elif days_old <= 1:
                score += 3.0
                matched_tags.append("🕐 Published yesterday (+3)")
            elif days_old <= 7:
                score += 1.0
                matched_tags.append("🕐 Published this week (+1)")
        except:
            pass
    
    # Penalize clickbait
    clickbait_patterns = config.get('clickbait_patterns', [])
    for pattern in clickbait_patterns:
        if pattern in combined:
            score -= 5.0
            matched_tags.append(f"❌ Clickbait pattern: '{pattern}' (-5)")
    
    # Penalize if no local connection
    if score == 0:
        score = -10.0
        missing_important_tags.append("Any local relevance")
    
    final_score = min(100.0, max(0.0, score))
    
    return final_score, {
        'matched': matched_tags,
        'missing': missing_important_tags
    }