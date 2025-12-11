"""
Category classification system using Naive Bayes
Learns from user feedback (thumbs up/down per category) and automatically categorizes articles
"""
import logging
import re
import sqlite3
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timedelta
from config import DATABASE_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fixed category list (12 categories)
CATEGORIES = [
    "News", "Crime", "Sports", "Entertainment", "Events", 
    "Politics", "Schools", "Business", "Health", "Traffic", "Fire", "Obits"
]

# Stop words to ignore in feature extraction
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "should", "could", "may", "might", "must", "can", "this", "that",
    "these", "those", "it", "its", "they", "them", "their", "there"
}

# Default keyword seed lists (15-20 keywords per category)
# These are hard-coded defaults that can be imported into the database
DEFAULT_CATEGORY_KEYWORDS = {
    "Crime": [
        "arrest", "police", "shooting", "warrant", "blotter", "charged", 
        "stolen", "suspect", "bail", "robbery", "investigation", "officer", 
        "crime", "criminal", "victim", "assault", "theft", "burglary", 
        "court", "judge", "trial", "detective", "arrested", "charges"
    ],
    "Sports": [
        "durfee", "diman", "trojans", "raiders", "bmc", "playoffs",
        "basketball", "football", "hockey", "game", "team", "player", 
        "coach", "athletic", "score", "win", "loss", "tournament", 
        "championship", "season", "sports", "athlete", "coaching"
    ],
    "Events": [
        "festival", "parade", "supper", "bazaar", "concert", "tree lighting",
        "fundraiser", "celebration", "gathering", "meeting", "announcement", 
        "event", "happening", "occasion", "ceremony", "opening", "show", 
        "performance"
    ],
    "Schools": [
        "school committee", "superintendent", "kuss", "resiliency",
        "durfee", "morton", "bmc", "student", "teacher", "education", 
        "principal", "graduation", "classroom", "academic", "school board", 
        "curriculum", "school", "elementary", "high school", "middle school", 
        "district"
    ],
    "Politics": [
        "mayor", "council", "politics", "election", "vote", "candidate", "government", 
        "city council", "city hall", "budget", "tax", "zoning", "planning board", 
        "committee", "ordinance", "resolution", "elected", "campaign", "ballot", "municipal"
    ],
    "Business": [
        "business", "restaurant", "opening", "closing", "store", "shop", "company", 
        "economic", "retail", "commerce", "market", "industry", "entrepreneur", 
        "startup", "expansion", "local business", "chamber", "economic development", 
        "commercial", "enterprise"
    ],
    "Health": [
        "health", "hospital", "medical", "doctor", "patient", "clinic", "treatment", 
        "healthcare", "wellness", "public health", "emergency", "ambulance", "care", 
        "facility", "service", "nurse", "physician", "medicine", "health department", 
        "medical center"
    ],
    "Traffic": [
        "traffic", "accident", "road", "highway", "construction", "detour", "route", 
        "bridge", "intersection", "lane", "closure", "delay", "commute", "vehicle", 
        "crash", "collision", "roadwork", "congestion", "rush hour", "traffic jam"
    ],
    "Entertainment": [
        "entertainment", "movie", "music", "theater", "show", "performance", "artist", 
        "concert", "venue", "film", "cinema", "stage", "production", "actor", "musician", 
        "band", "gig", "audience", "tickets", "entertainment"
    ],
    "Fire": [
        "fire", "firefighter", "fire department", "blaze", "burning", "smoke", "alarm", 
        "fire station", "rescue", "emergency", "flames", "arson", "fire marshal", 
        "fire truck", "extinguish", "firehouse", "combustion", "inferno", "fire chief", 
        "fire prevention"
    ],
    "Obits": [
        "passed away", "funeral", "obituary", "in loving memory", "died", "death",
        "memorial", "survived by", "predeceased", "visitation", "wake", "burial",
        "cemetery", "services", "remembrance"
    ],
    "News": []  # Default category - no specific keywords, catches everything else
}


class CategoryClassifier:
    """Naive Bayes classifier for article categorization"""
    
    def __init__(self, zip_code: str):
        self.zip_code = zip_code
        self.db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
        self._init_database()
        self._load_model_stats()
    
    def _init_database(self):
        """Initialize database table for category patterns (per zip)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create zip-specific table
            table_name = f"category_patterns_{self.zip_code}"
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {table_name} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feature TEXT NOT NULL,
                    feature_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    positive_count INTEGER DEFAULT 0,
                    negative_count INTEGER DEFAULT 0,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(feature, feature_type, category)
                )
            ''')
            cursor.execute(f'''
                CREATE INDEX IF NOT EXISTS idx_{table_name}_category 
                ON {table_name}(category, feature_type, feature)
            ''')
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error initializing category_patterns table for {self.zip_code}: {e}")
    
    def _load_model_stats(self):
        """Load overall model statistics for this zip"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            table_name = f"category_patterns_{self.zip_code}"
            
            # Count total training examples
            cursor.execute(f'SELECT SUM(positive_count), SUM(negative_count) FROM {table_name}')
            row = cursor.fetchone()
            if row and row[0]:
                self.total_positive = row[0] or 0
                self.total_negative = row[1] or 0
            else:
                self.total_positive = 0
                self.total_negative = 0
            
            conn.close()
        except Exception as e:
            logger.warning(f"Error loading model stats for {self.zip_code}: {e}")
            self.total_positive = 0
            self.total_negative = 0
    
    def load_category_keywords(self, category: str) -> List[str]:
        """Load keywords for a specific category from database, fallback to defaults if empty"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Load from database
            cursor.execute('''
                SELECT keyword FROM category_keywords 
                WHERE zip_code = ? AND category = ?
                ORDER BY keyword
            ''', (self.zip_code, category))
            
            keywords = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            # If no keywords in database, use defaults
            if not keywords and category in DEFAULT_CATEGORY_KEYWORDS:
                keywords = DEFAULT_CATEGORY_KEYWORDS[category]
            
            return keywords
        except Exception as e:
            logger.warning(f"Error loading keywords for {category}: {e}")
            # Fallback to defaults
            return DEFAULT_CATEGORY_KEYWORDS.get(category, [])
    
    def extract_features(self, article: Dict) -> Dict[str, Set[str]]:
        """Extract features from an article for classification"""
        title = article.get("title", "").lower()
        content = article.get("content", article.get("summary", "")).lower()
        combined = f"{title} {content}"
        
        features = {
            "keywords": set(),
            "locations": set(),
            "topics": set(),
            "n_grams": set()
        }
        
        # Extract keywords (nouns, verbs, important words)
        words = re.findall(r'\b[a-z]{3,}\b', combined)
        for word in words:
            if word not in STOP_WORDS and len(word) >= 3:
                features["keywords"].add(word)
        
        # Extract 2-grams (two-word phrases)
        words_list = words
        for i in range(len(words_list) - 1):
            if words_list[i] not in STOP_WORDS and words_list[i+1] not in STOP_WORDS:
                bigram = f"{words_list[i]} {words_list[i+1]}"
                if len(bigram) >= 6:
                    features["n_grams"].add(bigram)
        
        # Extract 3-grams (three-word phrases)
        for i in range(len(words_list) - 2):
            if all(w not in STOP_WORDS for w in words_list[i:i+3]):
                trigram = f"{words_list[i]} {words_list[i+1]} {words_list[i+2]}"
                if len(trigram) >= 10:
                    features["n_grams"].add(trigram)
        
        # Extract locations (capitalized words, place names)
        location_patterns = [
            r'\b[A-Z][a-z]+ (Street|Avenue|Road|Boulevard|Drive|Lane|Park|Plaza)\b',
            r'\b[A-Z][a-z]+ (High School|Elementary|School|Hospital|Center|Park)\b',
            r'\bFall River\b',
            r'\bNew Bedford\b',
            r'\bTaunton\b',
            r'\bSomerset\b',
            r'\bSwansea\b'
        ]
        for pattern in location_patterns:
            matches = re.findall(pattern, title + " " + content)
            for match in matches:
                if isinstance(match, tuple):
                    features["locations"].add(" ".join(match).lower())
                else:
                    features["locations"].add(match.lower())
        
        # Extract topic keywords (crime, sports, health, etc.)
        topic_keywords = {
            "crime": ["arrest", "police", "crime", "charged", "suspect", "investigation"],
            "sports": ["game", "team", "player", "coach", "score", "win", "loss"],
            "health": ["health", "hospital", "medical", "doctor", "patient", "treatment"],
            "education": ["school", "student", "teacher", "education", "graduation"],
            "business": ["business", "restaurant", "opening", "store", "company"],
            "politics": ["mayor", "council", "election", "vote", "government"],
            "weather": ["weather", "forecast", "temperature", "rain", "snow", "storm"],
            "traffic": ["traffic", "accident", "road", "highway", "construction"],
            "events": ["event", "festival", "concert", "celebration", "meeting"]
        }
        
        for topic, keywords in topic_keywords.items():
            if any(kw in combined for kw in keywords):
                features["topics"].add(topic)
        
        return features
    
    def calculate_category_score(self, article: Dict, category: str) -> float:
        """Fast keyword-based scoring with Bayesian adjustment and source category boost"""
        title = article.get("title", "").lower()
        content = article.get("content", article.get("summary", "")).lower()
        combined = f"{title} {content}"
        source = article.get("source", "").lower()
        
        # Load keywords for this category
        keywords = self.load_category_keywords(category)
        
        # Count keyword hits (case-insensitive substring matching)
        hits = sum(1 for keyword in keywords if keyword.lower() in combined)
        
        # Count total words (approximate)
        total_words = len(combined.split())
        
        # Fast base score: (hits + 1) / (total_words + 10)
        # This gives higher scores for articles with more keyword matches relative to article length
        if total_words == 0:
            base_score = 0.0
        else:
            base_score = (hits + 1) / (total_words + 10)
        
        # Apply Bayesian adjustment from training data
        bayesian_adjustment = self._get_bayesian_adjustment(article, category)
        
        # Source category boost - check if source has a matching category
        source_category_boost = 0.0
        try:
            from config import NEWS_SOURCES, CATEGORY_MAPPING
            
            # Check each source
            for source_key, source_config in NEWS_SOURCES.items():
                source_name = source_config.get("name", "").lower()
                if source_name in source or source_key.lower() in source:
                    source_cat = source_config.get("category")
                    if source_cat:
                        # Map source category to classifier category
                        # First map old category to new slug if needed
                        source_cat_slug = CATEGORY_MAPPING.get(source_cat, source_cat)
                        # Then map to classifier category
                        from admin.utils import map_category_to_classifier
                        mapped_source_cat = map_category_to_classifier(source_cat_slug)
                        if mapped_source_cat == category:
                            # Source category matches - add boost
                            source_category_boost = 0.3  # 30% boost
                            break
        except Exception as e:
            logger.debug(f"Could not check source category: {e}")
        
        # Combine: base_score * (1 + adjustment + source_boost)
        # Adjustment ranges from -0.5 to +0.5 typically, source_boost is 0.0 or 0.3
        final_score = base_score * (1.0 + bayesian_adjustment + source_category_boost)
        
        return min(1.0, max(0.0, final_score))
    
    def _get_bayesian_adjustment(self, article: Dict, category: str) -> float:
        """Get Bayesian adjustment factor from training data"""
        try:
            features = self.extract_features(article)
            table_name = f"category_patterns_{self.zip_code}"
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get category-specific counts
            cursor.execute(f'''
                SELECT SUM(positive_count), SUM(negative_count) 
                FROM {table_name} 
                WHERE category = ?
            ''', (category,))
            cat_row = cursor.fetchone()
            cat_positive = cat_row[0] or 0 if cat_row else 0
            cat_negative = cat_row[1] or 0 if cat_row else 0
            
            # If no training data, return 0 (no adjustment)
            if cat_positive + cat_negative == 0:
                conn.close()
                return 0.0
            
            # Calculate adjustment based on feature matches
            total_adjustment = 0.0
            feature_count = 0
            
            for feature_type, feature_set in features.items():
                for feature in feature_set:
                    if not feature or len(feature) < 2:
                        continue
                    
                    # Get counts for this feature in this category
                    cursor.execute(f'''
                        SELECT positive_count, negative_count 
                        FROM {table_name} 
                        WHERE feature = ? AND feature_type = ? AND category = ?
                    ''', (feature, feature_type, category))
                    row = cursor.fetchone()
                    
                    if row:
                        pos_count = row[0] or 0
                        neg_count = row[1] or 0
                    else:
                        pos_count = 0
                        neg_count = 0
                    
                    # Calculate adjustment: (pos - neg) / (pos + neg + 1)
                    # Positive values boost score, negative values reduce it
                    if pos_count + neg_count > 0:
                        adjustment = (pos_count - neg_count) / (pos_count + neg_count + 1.0)
                        total_adjustment += adjustment * 0.1  # Weighted contribution
                        feature_count += 1
            
            conn.close()
            
            # Average adjustment
            if feature_count > 0:
                avg_adjustment = total_adjustment / feature_count
                # Clamp to reasonable range
                return max(-0.5, min(0.5, avg_adjustment))
            else:
                return 0.0
            
        except Exception as e:
            logger.warning(f"Error calculating Bayesian adjustment: {e}")
            return 0.0
    
    def calculate_category_probability(self, article: Dict, category: str) -> float:
        """Calculate P(category | features) using Naive Bayes (legacy method, kept for compatibility)"""
        # Use new fast scoring method
        return self.calculate_category_score(article, category)
    
    def predict_category(self, article: Dict, use_fallback: bool = True) -> Tuple[str, float, str, float]:
        """
        Predict primary and secondary categories for an article using fast keyword scoring + Bayesian
        
        Returns:
            (primary_category, primary_confidence, secondary_category, secondary_confidence)
        """
        # Check if we should use cold-start (pure keyword count, no Bayesian)
        use_cold_start = False
        if use_fallback:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                table_name = f"category_patterns_{self.zip_code}"
                
                # Check total training examples
                cursor.execute(f'SELECT SUM(positive_count + negative_count) FROM {table_name}')
                row = cursor.fetchone()
                total_training = row[0] or 0 if row else 0
                
                # Use cold-start if < 50 training examples
                if total_training < 50:
                    use_cold_start = True
                
                conn.close()
            except:
                use_cold_start = True
        
        # Calculate scores for all categories
        category_scores = {}
        for category in CATEGORIES:
            if use_cold_start:
                # Cold-start: pure keyword count (no Bayesian adjustment)
                score = self._calculate_cold_start_score(article, category)
            else:
                # Full scoring: keyword hits + Bayesian adjustment
                score = self.calculate_category_score(article, category)
            category_scores[category] = score
        
        # Sort by score
        sorted_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)
        
        if not sorted_categories:
            return ("News", 0.5, "News", 0.5)
        
        primary_category, primary_score = sorted_categories[0]
        secondary_category = sorted_categories[1][0] if len(sorted_categories) > 1 else "News"
        secondary_score = sorted_categories[1][1] if len(sorted_categories) > 1 else 0.1
        
        # Normalize confidence to 0-100%
        # For cold-start, scale by max score to get better percentages
        if use_cold_start and primary_score > 0:
            max_possible = max(category_scores.values())
            if max_possible > 0:
                primary_confidence = min(100, max(0, (primary_score / max_possible) * 100))
                secondary_confidence = min(100, max(0, (secondary_score / max_possible) * 100))
            else:
                primary_confidence = 50.0
                secondary_confidence = 10.0
        else:
            primary_confidence = min(100, max(0, primary_score * 100))
            secondary_confidence = min(100, max(0, secondary_score * 100))
        
        return (primary_category, primary_confidence, secondary_category, secondary_confidence)
    
    def _calculate_cold_start_score(self, article: Dict, category: str) -> float:
        """Cold-start scoring: pure keyword count, no Bayesian adjustment"""
        title = article.get("title", "").lower()
        content = article.get("content", article.get("summary", "")).lower()
        combined = f"{title} {content}"
        
        # Load keywords for this category
        keywords = self.load_category_keywords(category)
        
        # Count keyword hits
        hits = sum(1 for keyword in keywords if keyword.lower() in combined)
        
        # Count total words
        total_words = len(combined.split())
        
        # Simple score: hits / max(total_words, 1)
        # Higher hits relative to article length = higher score
        if total_words == 0:
            return 0.0
        
        score = hits / max(total_words, 1)
        return min(1.0, max(0.0, score))
    
    def train_from_feedback(self, article: Dict, category: str, is_positive: bool):
        """Train the model with user feedback (thumbs up/down)"""
        features = self.extract_features(article)
        table_name = f"category_patterns_{self.zip_code}"
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Update or insert features for this category
            for feature_type, feature_set in features.items():
                for feature in feature_set:
                    if not feature or len(feature) < 2:
                        continue
                    
                    if is_positive:
                        cursor.execute(f'''
                            INSERT INTO {table_name} (feature, feature_type, category, positive_count, negative_count, last_updated)
                            VALUES (?, ?, ?, 1, 0, ?)
                            ON CONFLICT(feature, feature_type, category) 
                            DO UPDATE SET 
                                positive_count = positive_count + 1,
                                last_updated = ?
                        ''', (feature, feature_type, category, datetime.now().isoformat(), datetime.now().isoformat()))
                    else:
                        cursor.execute(f'''
                            INSERT INTO {table_name} (feature, feature_type, category, positive_count, negative_count, last_updated)
                            VALUES (?, ?, ?, 0, 1, ?)
                            ON CONFLICT(feature, feature_type, category) 
                            DO UPDATE SET 
                                negative_count = negative_count + 1,
                                last_updated = ?
                        ''', (feature, feature_type, category, datetime.now().isoformat(), datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            
            # Reload stats
            self._load_model_stats()
            
            logger.info(f"Trained category classifier for {category} ({'positive' if is_positive else 'negative'}) - zip {self.zip_code}")
            
        except Exception as e:
            logger.error(f"Error training category classifier: {e}")

