"""
Utility functions for website generator
Helper functions for article processing, formatting, etc.
"""
from typing import List, Dict
from datetime import datetime
import hashlib


def get_trending_articles(articles: List[Dict], limit: int = 5) -> List[Dict]:
    """Get trending articles based on recency and relevance score
    Ensures source diversity - limits articles per source
    """
    from collections import defaultdict
    
    now = datetime.now()
    trending = []
    
    for article in articles:
        # EXCLUDE OBITUARIES - Never show in trending
        article_category = article.get('category', '').lower() if article.get('category') else ''
        if article_category in ['obituaries', 'obituary']:
            continue
        
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
                article['_sort_date'] = pub_date
                trending.append(article)
        except:
            continue
    
    # Sort by trending score (highest first)
    trending.sort(key=lambda x: x.get('_trending_score', 0), reverse=True)
    
    # Ensure source diversity - limit to max 2 articles per source (for limit=5, try to get 3+ sources)
    source_counts = defaultdict(int)
    diverse_trending = []
    max_per_source = max(1, limit // 3)  # At least 1, but try to get 3+ sources
    
    for article in trending:
        source = article.get('source_display', article.get('source', 'Unknown'))
        if source_counts[source] < max_per_source:
            diverse_trending.append(article)
            source_counts[source] += 1
            if len(diverse_trending) >= limit:
                break
    
    # If we didn't fill the limit, add remaining articles regardless of source
    if len(diverse_trending) < limit:
        for article in trending:
            if article not in diverse_trending:
                diverse_trending.append(article)
                if len(diverse_trending) >= limit:
                    break
    
    return diverse_trending


def get_source_initials(source: str) -> str:
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


def get_source_gradient(source: str) -> str:
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


def is_video_article(article: Dict) -> bool:
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


def enrich_single_article(article: Dict) -> Dict:
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
    enriched["source_initials"] = get_source_initials(source_display)
    enriched["source_gradient"] = get_source_gradient(source_display)
    
    return enriched

