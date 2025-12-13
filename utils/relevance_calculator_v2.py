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
    source = article.get("source", "").lower()

    score = 0.0
    local_politics_override = False  # Flag for local politics that should override national penalties

    # === LOCAL POLITICS DETECTION (must check first) ===
    # Detect if this is local politics/government that should override national politics penalties
    local_politics_keywords = [
        "school committee", "school board", "city council", "mayor", "mayor paul coogan",
        "city hall", "police department", "fire department", "fall river police",
        "fall river fire", "fall river school", "bmc durfee", "durfee high",
        "city budget", "tax rate", "zoning", "planning board", "local government",
        "municipal", "city officials", "school officials", "police chief", "fire chief"
    ]

    for keyword in local_politics_keywords:
        if keyword in combined:
            local_politics_override = True
            score += 15  # Base boost for local politics
            break

    # === HIGH-RELEVANCE LOCAL CONTENT (40-60 points) ===
    # Fall River mentions get massive boost - this is the core of local relevance
    fall_river_keywords = ["fall river", "fallriver", "fall river ma", "fall river, ma",
                          "fall river mass", "fall river mass.", "fall river massachusetts",
                          "fall river, massachusetts", "fr ma", "fall river, mass"]
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

        # Extra boost for Fall River + local politics combination
        if local_politics_override:
            score += 10  # Fall River politics gets maximum boost

    # === LOCAL PLACES & INSTITUTIONS (5-25 points) ===
    local_places = [
        # High-value landmarks (10 points each)
        "durfee", "bmc durfee", "durfee high", "city hall", "fall river city hall",
        "st. anne's", "st. anne's hospital", "battleship cove", "lizzie borden",
        "bishop connolly", "diman", "diman regional",

        # Medium-value landmarks (7 points each)
        "highlands", "north end", "south end", "watuppa", "quequechan",
        "taunton river", "marine museum", "gates of the city", "pleasant street",

        # Government & services (6 points each)
        "fall river chamber", "fall river economic development", "fall river housing authority",
        "fall river water department", "fall river gas company", "fall river public schools",
        "fall river police", "fall river fire department",

        # Standard local places (4 points each)
        "south main street", "north main street", "eastern avenue",
        "kennedy park", "lafayette park", "riker park", "bicentennial park",
        "maplewood", "flint village", "the hill"
    ]

    local_place_matches = 0
    for place in local_places:
        if place in combined:
            if place in ["durfee", "city hall", "st. anne's", "battleship cove", "lizzie borden",
                        "fall river police", "fall river fire department"]:
                score += 10  # High-value local landmarks and services
            elif place in ["highlands", "north end", "south end", "watuppa", "marine museum",
                          "fall river chamber", "fall river economic development"]:
                score += 7  # Medium-value landmarks and services
            else:
                score += 4  # Other local places
            local_place_matches += 1
            if local_place_matches >= 6:  # Cap at 6 matches to prevent inflation
                break

    # === TOPIC RELEVANCE (10-35 points) ===
    topic_scoring = {
        # Government & Politics (8-12 points)
        "city council": 10, "mayor": 10, "mayor paul coogan": 12, "school committee": 9, "school board": 9,
        "city budget": 9, "tax rate": 8, "zoning": 8, "planning board": 8,
        "city hall": 10, "municipal": 7, "government": 6,

        # Crime & Safety (6-9 points)
        "police": 8, "arrest": 9, "crime": 7, "court": 6, "charges": 7, "suspect": 7,
        "investigation": 6, "murder": 9, "robbery": 8, "assault": 8,
        "fire department": 8, "emergency": 6,

        # Schools & Education (5-8 points)
        "school": 7, "student": 6, "teacher": 7, "education": 5, "principal": 7,
        "graduation": 6, "college": 5, "university": 5, "academic": 5,

        # Local Business & Economy (4-7 points)
        "business": 5, "restaurant": 7, "opening": 5, "closing": 5, "job": 5, "employment": 6,
        "economic": 5, "commerce": 5, "development": 5,

        # Events & Community (3-6 points)
        "event": 4, "festival": 6, "concert": 6, "community": 4, "fundraiser": 4, "charity": 4,
        "local event": 5, "town meeting": 7
    }

    topic_score = 0
    for keyword, points in topic_scoring.items():
        if keyword in combined:
            topic_score += points

    score += min(topic_score, 35)  # Cap topic score at 35

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

    # === RECENCY BONUS (multiplier 0.7-2.5) ===
    # Local articles get stronger recency weighting - recent local news matters more
    # Local articles get stronger recency weighting - recent local news matters more
    published = article.get("published")
    recency_multiplier = 1.0
    if published:
        try:
            pub_date = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
            hours_old = (datetime.now() - pub_date.replace(tzinfo=None)).total_seconds() / 3600

            # Base recency multipliers (for non-local content)
            if hours_old < 6:
                base_multiplier = 2.0  # Breaking news boost
            elif hours_old < 24:
                base_multiplier = 1.5  # Recent news boost
            elif hours_old < 72:
                base_multiplier = 1.0  # Normal recency
            else:
                base_multiplier = 0.7  # Older news penalty

            # Local articles get enhanced recency weighting
            if fall_river_boost > 0 or local_politics_override:
                if hours_old < 6:
                    recency_multiplier = 2.5  # Breaking LOCAL news gets maximum boost
                elif hours_old < 24:
                    recency_multiplier = 2.0  # Recent LOCAL news very important
                elif hours_old < 72:
                    recency_multiplier = 1.3  # LOCAL news still gets slight boost
                else:
                    recency_multiplier = 0.8  # LOCAL news ages more gracefully
            else:
                # Non-local content gets standard recency weighting
                recency_multiplier = base_multiplier

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

    # National politics - ONLY penalize if NO local connection AND not local politics
    national_keywords = ["trump", "biden", "president", "congress", "senate", "washington dc", "white house"]
    has_national_keywords = any(kw in combined for kw in national_keywords)

    if has_national_keywords:
        # Don't penalize if article has Fall River boost OR local politics override
        if fall_river_boost == 0 and not local_politics_override:
            # Only penalize if the national content appears to be the main focus
            national_mentions = sum(1 for kw in national_keywords if kw in combined)
            if national_mentions >= 2 or score < 40:
                junk_penalties -= 25  # Reduced penalty, only for clear national politics focus
        # If it has local politics override, actually give a small boost for national context
        elif local_politics_override:
            score += 5  # Local official commenting on national issues = still relevant

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