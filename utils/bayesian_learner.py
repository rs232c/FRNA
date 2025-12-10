"""
Bayesian learning system for article filtering
Learns from rejected articles and applies patterns to filter similar content
"""
import logging
import re
import sqlite3
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from datetime import datetime
from config import DATABASE_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Nearby towns that might be relevant but need Fall River connection
NEARBY_TOWNS = [
    "cape cod", "tiverton", "somerset", "swansea", "westport", "freetown",
    "taunton", "new bedford", "dartmouth", "seekonk", "bristol county",
    "warren", "barrington", "portsmouth", "middletown", "newport",
    "little compton", "rehoboth", "dighton", "berkley", "assonet"
]

# Stop words to ignore in feature extraction
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "should", "could", "may", "might", "must", "can", "this", "that",
    "these", "those", "it", "its", "they", "them", "their", "there"
}


class BayesianLearner:
    """Naive Bayes classifier that learns from rejected articles"""
    
    def __init__(self):
        self.db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
        self._init_database()
        self.reject_count = 0
        self.accept_count = 0
        self._load_model_stats()
    
    def _init_database(self):
        """Initialize database table for rejection patterns"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rejection_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feature TEXT NOT NULL,
                    feature_type TEXT NOT NULL,
                    reject_count INTEGER DEFAULT 1,
                    accept_count INTEGER DEFAULT 0,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(feature, feature_type)
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_feature_type 
                ON rejection_patterns(feature_type, feature)
            ''')
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error initializing rejection_patterns table: {e}")
    
    def _load_model_stats(self):
        """Load overall model statistics"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Count total rejections and acceptances from patterns
            cursor.execute('SELECT SUM(reject_count), SUM(accept_count) FROM rejection_patterns')
            row = cursor.fetchone()
            if row and row[0]:
                self.reject_count = row[0] or 0
                self.accept_count = row[1] or 0
            
            conn.close()
        except Exception as e:
            logger.warning(f"Error loading model stats: {e}")
    
    def extract_features(self, article: Dict) -> Dict[str, Set[str]]:
        """Extract features from an article for classification"""
        title = article.get("title", "").lower()
        content = article.get("content", article.get("summary", "")).lower()
        combined = f"{title} {content}"
        
        features = {
            "keywords": set(),
            "locations": set(),
            "nearby_towns": set(),
            "topics": set(),
            "has_fall_river": False,
            "n_grams": set()
        }
        
        # Check for Fall River mention
        if "fall river" in combined or "fallriver" in combined:
            features["has_fall_river"] = True
        
        # Extract nearby towns
        for town in NEARBY_TOWNS:
            if town in combined:
                features["nearby_towns"].add(town)
        
        # Extract keywords (important words, not stop words)
        words = re.findall(r'\b[a-z]{3,}\b', combined)
        for word in words:
            if word not in STOP_WORDS and len(word) >= 3:
                # Only add if it appears multiple times or is in title
                count = combined.count(word)
                if count >= 2 or word in title:
                    features["keywords"].add(word)
        
        # Extract 2-3 word phrases (n-grams) from title
        title_words = title.split()
        for i in range(len(title_words) - 1):
            bigram = f"{title_words[i]} {title_words[i+1]}"
            if len(bigram) > 5:  # Filter very short phrases
                features["n_grams"].add(bigram)
        
        # Extract topics (common news topics)
        topic_patterns = {
            "restaurant": ["restaurant", "dining", "food", "menu", "chef"],
            "business": ["business", "company", "store", "shop", "retail"],
            "event": ["event", "festival", "concert", "show", "celebration"],
            "sports": ["sports", "game", "team", "player", "coach"],
            "crime": ["arrest", "crime", "police", "investigation", "charged"],
            "education": ["school", "student", "teacher", "education", "college"],
            "government": ["city", "council", "mayor", "government", "budget"]
        }
        
        for topic, keywords in topic_patterns.items():
            if any(kw in combined for kw in keywords):
                features["topics"].add(topic)
        
        return features
    
    def train_from_rejection(self, article: Dict):
        """Train the model with a rejected article"""
        features = self.extract_features(article)
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Update or insert features
            for feature_type, feature_set in features.items():
                if feature_type == "has_fall_river":
                    continue  # Skip boolean flag
                
                for feature in feature_set:
                    if not feature or len(feature) < 2:
                        continue
                    
                    cursor.execute('''
                        INSERT INTO rejection_patterns (feature, feature_type, reject_count, accept_count, last_updated)
                        VALUES (?, ?, 1, 0, ?)
                        ON CONFLICT(feature, feature_type) 
                        DO UPDATE SET 
                            reject_count = reject_count + 1,
                            last_updated = ?
                    ''', (feature, feature_type, datetime.now().isoformat(), datetime.now().isoformat()))
            
            # Special handling for nearby towns without Fall River connection
            if features["nearby_towns"] and not features["has_fall_river"]:
                for town in features["nearby_towns"]:
                    cursor.execute('''
                        INSERT INTO rejection_patterns (feature, feature_type, reject_count, accept_count, last_updated)
                        VALUES (?, ?, 2, 0, ?)
                        ON CONFLICT(feature, feature_type) 
                        DO UPDATE SET 
                            reject_count = reject_count + 2,
                            last_updated = ?
                    ''', (f"{town}_no_fr", "nearby_town_no_fr", datetime.now().isoformat(), datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            
            self.reject_count += 1
            logger.info(f"Trained model from rejected article: '{article.get('title', '')[:50]}...'")
            
        except Exception as e:
            logger.error(f"Error training from rejection: {e}")
    
    def calculate_rejection_probability(self, article: Dict) -> Tuple[float, List[str]]:
        """
        Calculate probability that article should be rejected
        Returns: (probability, reasons)
        """
        features = self.extract_features(article)
        reasons = []
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Prior probability (base rate of rejections)
            total_articles = self.reject_count + self.accept_count
            if total_articles == 0:
                return (0.0, [])
            
            prior_reject = self.reject_count / total_articles if total_articles > 0 else 0.5
            prior_accept = 1 - prior_reject
            
            # Calculate likelihood for each feature
            log_likelihood_reject = 0.0
            log_likelihood_accept = 0.0
            feature_evidence = []
            
            # Check each feature type
            for feature_type, feature_set in features.items():
                if feature_type == "has_fall_river":
                    continue
                
                for feature in feature_set:
                    if not feature:
                        continue
                    
                    # Get feature statistics
                    cursor.execute('''
                        SELECT reject_count, accept_count 
                        FROM rejection_patterns 
                        WHERE feature = ? AND feature_type = ?
                    ''', (feature, feature_type))
                    row = cursor.fetchone()
                    
                    if row:
                        feat_reject, feat_accept = row[0], row[1]
                        feat_total = feat_reject + feat_accept
                        
                        if feat_total > 0:
                            # Laplace smoothing
                            p_feat_given_reject = (feat_reject + 1) / (self.reject_count + 2)
                            p_feat_given_accept = (feat_accept + 1) / (self.accept_count + 2)
                            
                            # Weight by feature importance
                            weight = 1.0
                            if feature_type == "nearby_towns":
                                weight = 2.0  # Nearby towns are more important
                            elif feature_type == "topics":
                                weight = 1.5
                            elif feature_type == "n_grams":
                                weight = 1.2
                            
                            log_likelihood_reject += weight * (p_feat_given_reject if p_feat_given_reject > 0 else 0.001)
                            log_likelihood_accept += weight * (p_feat_given_accept if p_feat_given_accept > 0 else 0.001)
                            
                            # Track significant evidence
                            if feat_reject > feat_accept * 2 and feat_reject >= 2:
                                feature_evidence.append(f"{feature_type}:{feature} (rejected {feat_reject}x)")
            
            # Check nearby towns without Fall River connection (special case)
            if features["nearby_towns"] and not features["has_fall_river"]:
                for town in features["nearby_towns"]:
                    cursor.execute('''
                        SELECT reject_count, accept_count 
                        FROM rejection_patterns 
                        WHERE feature = ? AND feature_type = ?
                    ''', (f"{town}_no_fr", "nearby_town_no_fr"))
                    row = cursor.fetchone()
                    
                    if row:
                        feat_reject, feat_accept = row[0], row[1]
                        if feat_reject > feat_accept:
                            # Strong evidence for rejection
                            log_likelihood_reject += 3.0
                            reasons.append(f"Nearby town '{town}' mentioned without Fall River connection (rejected {feat_reject}x)")
            
            conn.close()
            
            # Calculate posterior probability using Naive Bayes
            # P(reject | features) = P(features | reject) * P(reject) / P(features)
            # Using log space to avoid underflow
            if log_likelihood_reject == 0 and log_likelihood_accept == 0:
                probability = 0.0
            else:
                # Normalize to probability
                total_likelihood = log_likelihood_reject + log_likelihood_accept
                if total_likelihood > 0:
                    probability = (log_likelihood_reject * prior_reject) / total_likelihood
                else:
                    probability = prior_reject
            
            # Add feature evidence to reasons
            if feature_evidence:
                reasons.extend(feature_evidence[:3])  # Top 3 reasons
            
            return (min(1.0, max(0.0, probability)), reasons)
            
        except Exception as e:
            logger.error(f"Error calculating rejection probability: {e}")
            return (0.0, [])
    
    def should_filter(self, article: Dict, threshold: float = 0.7) -> Tuple[bool, float, List[str]]:
        """
        Determine if article should be filtered based on Bayesian probability
        Returns: (should_filter, probability, reasons)
        """
        probability, reasons = self.calculate_rejection_probability(article)
        should_filter = probability >= threshold
        
        return (should_filter, probability, reasons)
    
    def train_from_acceptance(self, article: Dict):
        """Train the model with an accepted article (to balance the model)"""
        features = self.extract_features(article)
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Update accept counts (but don't create new entries for accepts)
            for feature_type, feature_set in features.items():
                if feature_type == "has_fall_river":
                    continue
                
                for feature in feature_set:
                    if not feature or len(feature) < 2:
                        continue
                    
                    cursor.execute('''
                        UPDATE rejection_patterns 
                        SET accept_count = accept_count + 1,
                            last_updated = ?
                        WHERE feature = ? AND feature_type = ?
                    ''', (datetime.now().isoformat(), feature, feature_type))
            
            conn.commit()
            conn.close()
            
            self.accept_count += 1
            
        except Exception as e:
            logger.warning(f"Error training from acceptance: {e}")

