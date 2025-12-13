"""
Optimized relevance calculator for Fall River articles - simplified and effective
"""
from datetime import datetime
from typing import Dict, List, Optional
import logging
from config import DATABASE_CONFIG

logger = logging.getLogger(__name__)


def calculate_relevance_score(article: Dict, zip_code: Optional[str] = None) -> float:
    """Calculate relevance score (0-100) with optimized local knowledge and clear scoring rules

    Args:
        article: Article dict with title, content, source, etc.
        zip_code: Optional zip code for zip-specific filtering

    Returns:
        Relevance score between 0 and 100
    """
    content = article.get("content", article.get("summary", "")).lower()
    title = article.get("title", "").lower()
    combined = f"{title} {content}"

    score = 0.0

    # === HIGH-RELEVANCE LOCAL CONTENT (40-60 points) ===
    # Fall River mentions get massive boost - this is the core of local relevance
    fall_river_keywords = ["fall river", "fallriver", "fall river ma", "fall river, ma",
                          "fall river mass", "fall river mass.", "fall river massachusetts"]
    fall_river_boost = 0

    for keyword in fall_river_keywords:
        if keyword in combined:
            fall_river_boost = 40  # Base boost for Fall River mention
            break

    # Additional boost for prominent placement (title > content)
    if fall_river_boost > 0:
        if any(kw in title for kw in fall_river_keywords):
            fall_river_boost += 10  # Extra boost if in title
        score += fall_river_boost

    # === LOCAL PLACES & INSTITUTIONS (5-20 points) ===
    local_places = [
        # High-value landmarks (8 points each)
        "durfee", "bmc durfee", "durfee high", "city hall", "fall river city hall",
        "st. anne's", "st. anne's hospital", "battleship cove", "lizzie borden",

        # Medium-value landmarks (5 points each)
        "highlands", "north end", "south end", "watuppa", "quequechan",
        "taunton river", "marine museum", "gates of the city",

        # Standard local places (3 points each)
        "pleasant street", "south main street", "north main street", "eastern avenue",
        "kennedy park", "lafayette park", "riker park", "bicentennial park",
        "fall river chamber", "fall river economic development", "fall river housing authority",
        "fall river water department", "fall river gas company", "fall river public schools"
    ]

    local_place_matches = 0
    for place in local_places:
        if place in combined:
            if place in ["durfee", "city hall", "st. anne's", "battleship cove", "lizzie borden"]:
                score += 8  # High-value local landmarks
            elif place in ["highlands", "north end", "south end", "watuppa", "marine museum"]:
                score += 5  # Medium-value landmarks
            else:
                score += 3  # Other local places
            local_place_matches += 1
            if local_place_matches >= 5:  # Cap at 5 matches to prevent inflation
                break

    # === TOPIC RELEVANCE (10-30 points) ===
    topic_scoring = {
        # Government & Politics (6-8 points)
        "city council": 8, "mayor": 8, "mayor paul coogan": 10, "school committee": 7, "school board": 7,
        "city budget": 7, "tax rate": 7, "zoning": 6, "planning board": 6,

        # Crime & Safety (5-7 points)
        "police": 6, "arrest": 7, "crime": 6, "court": 5, "charges": 6, "suspect": 6,
        "investigation": 5, "murder": 7, "robbery": 6, "assault": 6,

        # Schools & Education (4-6 points)
        "school": 5, "student": 5, "teacher": 5, "education": 4, "principal": 5,
        "graduation": 5, "college": 4, "university": 4,

        # Local Business & Economy (3-5 points)
        "business": 4, "restaurant": 5, "opening": 4, "closing": 4, "job": 4, "employment": 4,

        # Events & Community (2-4 points)
        "event": 3, "festival": 4, "concert": 4, "community": 3, "fundraiser": 3, "charity": 3
    }

    topic_score = 0
    for keyword, points in topic_scoring.items():
        if keyword in combined:
            topic_score += points

    score += min(topic_score, 30)  # Cap topic score at 30

    # === SOURCE CREDIBILITY (5-25 points) ===
    source = article.get("source", "").lower()
    source_credibility = {
        "herald news": 20, "fall river reporter": 20, "wpri": 8, "abc6": 8,
        "nbc10": 8, "fun107": 6, "masslive": 5, "taunton gazette": 4, "southcoast today": 4
    }

    for source_name, points in source_credibility.items():
        if source_name in source:
            score += points
            break

    # === RECENCY BONUS (multiplier 0.7-2.0) ===
    published = article.get("published")
    recency_multiplier = 1.0
    if published:
        try:
            pub_date = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
            hours_old = (datetime.now() - pub_date.replace(tzinfo=None)).total_seconds() / 3600

            if hours_old < 6:
                recency_multiplier = 2.0  # Breaking news boost
            elif hours_old < 24:
                recency_multiplier = 1.5  # Recent news boost
            elif hours_old < 72:
                recency_multiplier = 1.0  # Normal recency
            else:
                recency_multiplier = 0.7  # Older news penalty
        except:
            pass

    # === JUNK CONTENT PENALTIES (-50 to 0 points) ===
    junk_penalties = 0

    # Casino/gambling content - massive penalty
    if any(word in combined for word in ["casino", "gambling", "slots", "poker", "blackjack", "twin river"]):
        junk_penalties -= 50

    # Sponsored content
    if any(word in combined for word in ["sponsored", "advertisement", "ad", "promo", "brought to you by"]):
        junk_penalties -= 40

    # National politics (unless it has local angle)
    national_keywords = ["trump", "biden", "president", "congress", "senate", "washington dc"]
    if any(kw in combined for kw in national_keywords) and fall_river_boost == 0:
        junk_penalties -= 30

    # Clickbait patterns
    clickbait_patterns = ["you won't believe", "this one trick", "number 7 will shock you",
                         "doctors hate", "one weird trick", "click here", "find out more"]
    for pattern in clickbait_patterns:
        if pattern in combined:
            junk_penalties -= 10

    # Content quality check
    content_length = len(content.split())
    if content_length < 50:
        junk_penalties -= 15  # Too short
    elif content_length > 2000:
        junk_penalties -= 5   # Potentially bloated/scraped

    # === STELLAR ARTICLE BOOST ===
    if article.get('is_stellar', 0):
        score += 25  # Significant boost for editor-picked articles

    # === APPLY RECENCY MULTIPLIER ===
    score = score * recency_multiplier

    # === APPLY JUNK PENALTIES ===
    score += junk_penalties

    # === MINIMUM SCORE GUARANTEE ===
    # If we passed hard filter but score is still 0, give minimum local relevance
    if score <= 0 and fall_river_boost == 0:
        # Check for any regional Massachusetts content
        mass_keywords = ["massachusetts", "mass.", "ma ", "bristol county", "taunton", "new bedford"]
        if any(kw in combined for kw in mass_keywords):
            score = 15  # Minimum regional relevance
        else:
            score = 5   # Minimum baseline relevance

    # === FINAL SCORE CLAMPING ===
    final_score = min(100.0, max(0.0, score))

    return final_score