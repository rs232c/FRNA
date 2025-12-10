"""
Configuration file for Fall River News Aggregator
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Version tracking - includes build date
from datetime import datetime
BUILD_DATE = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
VERSION = f"1.0.0 (Build: {BUILD_DATE})"

# Locale Configuration
LOCALE = "Fall River, MA"
LOCALE_HASHTAG = "#FallRiverMA"
LOCALE_SHORT = "FallRiver"

# News Sources
NEWS_SOURCES = {
    "herald_news": {
        "name": "Herald News",
        "url": "https://www.heraldnews.com",
        "rss": None,  # RSS feed exists but is empty, will use web scraping
        "category": "news",
        "enabled": True,
        "require_fall_river": True  # Only Fall River articles
    },
    "fall_river_reporter": {
        "name": "Fall River Reporter",
        "url": "https://www.fallriverreporter.com",
        "rss": "https://fallriverreporter.com/feed/",  # Found actual RSS feed
        "category": "news",
        "enabled": True,
        "require_fall_river": True  # Filter out non-Fall River content
    },
    "fun107": {
        "name": "Fun107",
        "url": "https://fun107.com",
        "rss": "https://fun107.com/feed/",  # Try RSS feed
        "category": "entertainment",
        "enabled": True,
        "require_fall_river": True  # Only include if mentions Fall River
    },
    "wpri": {
        "name": "WPRI 12 Fall River",
        "url": "https://www.wpri.com/news/se-mass/",
        "rss": "https://www.wpri.com/feed/",
        "category": "news",
        "enabled": True,
        "require_fall_river": True
    },
    "taunton_gazette": {
        "name": "Taunton Gazette",
        "url": "https://www.tauntongazette.com",
        "rss": None,
        "category": "news",
        "enabled": True,
        "require_fall_river": True
    },
    "masslive": {
        "name": "MassLive Fall River",
        "url": "https://www.masslive.com/topic/fall-river/",
        "rss": "https://www.masslive.com/topic/fall-river/feed/",
        "category": "news",
        "enabled": True,
        "require_fall_river": True
    },
    "abc6": {
        "name": "ABC6 (WLNE) Fall River",
        "url": "https://www.abc6.com/news/fall-river/",
        "rss": "https://www.abc6.com/rss-feeds/fall-river/",  # Try Fall River specific feed
        "category": "news",
        "enabled": True,
        "require_fall_river": True
    },
    "nbc10": {
        "name": "NBC10/WJAR Fall River",
        "url": "https://turnto10.com/topic/Fall%20River",
        "rss": "https://turnto10.com/topic/Fall%20River/feed/",
        "category": "news",
        "enabled": True,
        "require_fall_river": True
    },
    "southcoast_today": {
        "name": "Southcoast Today",
        "url": "https://www.southcoasttoday.com",
        "rss": "https://www.southcoasttoday.com/feed/",
        "category": "news",
        "enabled": True,
        "require_fall_river": True
    },
    "patch_fall_river": {
        "name": "Patch Fall River",
        "url": "https://patch.com/massachusetts/fallriver",
        "rss": None,
        "category": "local",
        "enabled": True,
        "require_fall_river": True
    },
    "frcmedia": {
        "name": "FRCMedia (Fall River Community Media)",
        "url": "https://frmedia.org/",
        "rss": "https://frmedia.org/feed/",  # Try common feed path
        "category": "news",
        "enabled": True,  # Try RSS first
        "require_fall_river": False  # Already Fall River specific, don't require explicit mention
    },
    "wsar_radio": {
        "name": "WSAR Radio",
        "url": "https://wsar.com/",
        "rss": "https://wsar.com/feed/",  # Try common feed path
        "category": "news",
        "enabled": True,  # Try RSS first
        "require_fall_river": True
    },
    "fredtv": {
        "name": "FREDTV",
        "url": "https://fredtv.org/",  # Common pattern for TV stations
        "rss": "https://fredtv.org/feed/",
        "category": "media",
        "enabled": True,  # Try common URL pattern
        "require_fall_river": True
    },
    "frgtv": {
        "name": "FRGTV",
        "url": "https://frgtv.org/",  # Common pattern for TV stations
        "rss": "https://frgtv.org/feed/",
        "category": "media",
        "enabled": True,  # Try common URL pattern
        "require_fall_river": True
    },
    "new_bedford_light": {
        "name": "New Bedford Light",
        "url": "https://newbedfordlight.org/",
        "rss": None,  # Check site for RSS
        "category": "news",
        "enabled": False,
        "require_fall_river": True
    },
    "anchor_news": {
        "name": "Anchor News (Diocese)",
        "url": None,
        "rss": None,  # Potential RSS
        "category": "local",
        "enabled": False,
        "require_fall_river": True
    },
    "fall_river_dev_news": {
        "name": "Fall River Development News FB Page",
        "url": None,
        "rss": None,
        "category": "local",
        "enabled": False,  # Manual curation
        "require_fall_river": True,
        "source_type": "facebook"
    },
    # Fall River Funeral Homes - Obituaries Sources
    "legacy_fall_river": {
        "name": "Legacy.com Fall River",
        "url": "https://www.legacy.com/us/obituaries/local/massachusetts/fall-river-area",
        "rss": "https://www.legacy.com/obituaries/local/massachusetts/fall-river-obituaries/rss",
        "category": "obituaries",
        "enabled": True,
        "require_fall_river": False  # Already Fall River specific
    },
    "herald_news_obituaries": {
        "name": "Herald News Obituaries",
        "url": "https://www.heraldnews.com/obituaries/",
        "rss": None,  # No native RSS - will need web scraping or RSS.app generator
        "category": "obituaries",
        "enabled": True,
        "require_fall_river": False  # Already Fall River specific
    },
    "hathaway_funeral_homes": {
        "name": "Hathaway Funeral Homes",
        "url": "https://www.hathawayfuneralhomes.com/listings",
        "rss": "https://www.hathawayfuneralhomes.com/listings/rss",
        "category": "obituaries",
        "enabled": True,
        "require_fall_river": False
    },
    "southcoast_funeral_service": {
        "name": "South Coast Funeral Service",
        "url": "https://www.southcoastchapel.com/obituaries",
        "rss": "https://www.southcoastchapel.com/obituaries/rss",
        "category": "obituaries",
        "enabled": True,
        "require_fall_river": False
    },
    "waring_sullivan": {
        "name": "Waring-Sullivan (Dignity Memorial)",
        "url": "https://www.dignitymemorial.com/obituaries/fall-river-ma",
        "rss": "https://www.dignitymemorial.com/obituaries/fall-river-ma/rss",
        "category": "obituaries",
        "enabled": True,
        "require_fall_river": False
    },
    "oliveira_funeral_homes": {
        "name": "Oliveira Funeral Homes",
        "url": "https://www.oliveirafuneralhomes.com/obituaries",
        "rss": "https://www.oliveirafuneralhomes.com/rss/obituaries",
        "category": "obituaries",
        "enabled": True,
        "require_fall_river": False
    }
}

# Article Categories - Modern, cohesive color palette
ARTICLE_CATEGORIES = {
    "news": {
        "name": "News",
        "icon": "📰",
        "color": "#1e88e5"  # Soft professional blue
    },
    "entertainment": {
        "name": "Entertainment",
        "icon": "🎬",
        "color": "#8e24aa"  # Rich purple
    },
    "sports": {
        "name": "Sports",
        "icon": "⚽",
        "color": "#00acc1"  # Teal/cyan
    },
    "local": {
        "name": "Local",
        "icon": "📍",
        "color": "#f57c00"  # Warm orange
    },
    "custom": {
        "name": "Custom",
        "icon": "📝",
        "color": "#5e35b1"  # Deep purple
    },
    "media": {
        "name": "Media",
        "icon": "🎥",
        "color": "#c2185b"  # Deep pink/magenta
    }
}

# Category Slugs - URL-friendly identifiers for category pages
CATEGORY_SLUGS = {
    "local-news": "Local News",
    "crime": "Crime & Public Safety",
    "sports": "Sports",
    "events": "Entertainment & Events",
    "weather": "Weather",
    "business": "Business & Development",
    "schools": "Schools",
    "food": "Food & Drink",
    "obituaries": "Obituaries"
}

# Category Mapping - Maps old article categories to new category slugs
CATEGORY_MAPPING = {
    "news": "local-news",
    "entertainment": "events",
    "sports": "sports",
    "local": "local-news",
    "custom": "local-news",  # Default custom to local-news
    "media": "events",  # Media content goes to events
    "crime": "crime",  # Add direct mapping
    "obituaries": "obituaries",  # Add direct mapping
    "obituary": "obituaries",  # Add variant
    "business": "business",  # Add direct mapping
    "schools": "schools",  # Add direct mapping
    "education": "schools",  # Add variant
    "food": "food",  # Add direct mapping
    "weather": "weather"  # Add direct mapping
}

# Facebook Configuration
FACEBOOK_CONFIG = {
    "city_page": os.getenv("FACEBOOK_CITY_PAGE_ID", ""),
    "city_page_token": os.getenv("FACEBOOK_CITY_PAGE_TOKEN", ""),
    "local_columnists": [
        # Add Facebook page IDs or usernames for local columnists
        os.getenv("COLUMNIST_1_FB_ID", ""),
        os.getenv("COLUMNIST_2_FB_ID", ""),
    ],
    "app_id": os.getenv("FACEBOOK_APP_ID", ""),
    "app_secret": os.getenv("FACEBOOK_APP_SECRET", ""),
    "page_id": os.getenv("FACEBOOK_PAGE_ID", ""),
    "page_access_token": os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
}

# Instagram Configuration
INSTAGRAM_CONFIG = {
    "username": os.getenv("INSTAGRAM_USERNAME", ""),
    "password": os.getenv("INSTAGRAM_PASSWORD", ""),
    "enabled": True
}

# TikTok Configuration (Note: TikTok API requires business account)
TIKTOK_CONFIG = {
    "client_key": os.getenv("TIKTOK_CLIENT_KEY", ""),
    "client_secret": os.getenv("TIKTOK_CLIENT_SECRET", ""),
    "access_token": os.getenv("TIKTOK_ACCESS_TOKEN", ""),
    "enabled": True
}

# Website Configuration
WEBSITE_CONFIG = {
    "title": f"{LOCALE} News Aggregator",
    "description": f"Latest news and updates from {LOCALE}",
    "domain": os.getenv("WEBSITE_DOMAIN", "fallrivernews.local"),
    "output_dir": "website_output",
    "auto_deploy": os.getenv("AUTO_DEPLOY", "false").lower() == "true",
    "deploy_method": os.getenv("DEPLOY_METHOD", "github_pages")  # github_pages, netlify, vercel
}

# Database Configuration
DATABASE_CONFIG = {
    "type": "sqlite",
    "path": "fallriver_news.db"
}

# Weather API Configuration
WEATHER_CONFIG = {
    "openweathermap_api_key": os.getenv("OPENWEATHERMAP_API_KEY", ""),
    # Get free API key at: https://openweathermap.org/api
    # Free tier: 1000 calls/day, 60 calls/minute
}

# Aggregation Settings
AGGREGATION_CONFIG = {
    "deduplication_window_hours": 24,
    "min_article_length": 100,
    "keywords_filter": [
        "Fall River",
        "Fall River, MA",
        "Fall River, Massachusetts"
    ],
    "exclude_keywords": []
}

# Posting Schedule
POSTING_SCHEDULE = {
    "frequency": "hourly",  # hourly, daily, twice_daily
    "max_posts_per_day": 10,
    "posting_times": ["09:00", "12:00", "15:00", "18:00"]  # 24-hour format
}

# Hashtags
HASHTAGS = [
    LOCALE_HASHTAG,
    "#FallRiver",
    "#FallRiverMassachusetts",
    "#LocalNews",
    "#CommunityNews"
]

