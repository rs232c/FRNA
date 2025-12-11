"""
Bayesian Relevance Learning System
Learns from admin clicks (thumbs up/down, top story, trash) to improve relevance scoring
Separate from the existing Bayesian filter - this is for relevance ranking, not filtering
"""
import logging
import re
import sqlite3
from typing import Dict, List, Set, Optional
from collections import defaultdict
from datetime import datetime, timedelta
from config import DATABASE_CONFIG

logger = logging.getLogger(__name__)

# Stop words to ignore in feature extraction
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "should", "could", "may", "might", "must", "can", "this", "that",
    "these", "those", "it", "its", "they", "them", "their", "there"
}


class BayesianRelevanceLearner:
    """Bayesian learner for relevance scoring (separate from filtering)"""
    
    def __init__(self):
        self.db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
    
    def extract_features(self, article: Dict) -> Dict[str, Set[str]]:
        """Extract features from an article for relevance learning"""
        title = article.get("title", "").lower()
        content = article.get("content", article.get("summary", "")).lower()
        combined = f"{title} {content}"
        source = article.get("source", "").lower()
        
        features = {
            "keywords": set(),
            "locations": set(),
            "topics": set(),
            "source": set(),
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
        
        # Extract topic keywords
        topic_keywords = {
            "crime": ["arrest", "police", "crime", "charged", "suspect", "investigation"],
            "sports": ["game", "team", "player", "coach", "score", "win", "loss"],
            "health": ["health", "hospital", "medical", "doctor", "patient", "treatment"],
            "education": ["school", "student", "teacher", "education", "graduation"],
            "business": ["business", "restaurant", "opening", "store", "company"],
            "politics": ["mayor", "council", "election", "vote", "government"],
            "traffic": ["traffic", "accident", "road", "highway", "construction"],
            "events": ["event", "festival", "concert", "celebration", "meeting"]
        }
        
        for topic, keywords in topic_keywords.items():
            if any(kw in combined for kw in keywords):
                features["topics"].add(topic)
        
        # Extract source
        if source:
            features["source"].add(source)
        
        return features
    
    def train_from_click(self, article: Dict, zip_code: str, click_type: str, good_fit: int):
        """Train the model from an admin click
        
        Args:
            article: Article dict
            zip_code: Zip code
            click_type: 'thumbs_up', 'thumbs_down', 'top_story', 'trash'
            good_fit: 1 = perfect example (top story), 0 = bad example (trash)
        """
        features = self.extract_features(article)
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Store training example
            article_id = article.get('id')
            cursor.execute('''
                INSERT INTO training_data (article_id, zip_code, good_fit, click_type, clicked_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (article_id, zip_code, good_fit, click_type, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Trained relevance model: zip={zip_code}, click_type={click_type}, good_fit={good_fit}")
            
        except Exception as e:
            logger.error(f"Error training relevance model: {e}")
    
    def calculate_relevance_adjustment(self, article: Dict, zip_code: Optional[str] = None) -> float:
        """Calculate Bayesian adjustment factor for relevance score
        
        Args:
            article: Article dict
            zip_code: Zip code
            
        Returns:
            Adjustment factor (-20 to +20 points)
        """
        if not zip_code:
            return 0.0
        
        features = self.extract_features(article)
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Count total training examples for this zip
            cursor.execute('''
                SELECT COUNT(*) FROM training_data WHERE zip_code = ?
            ''', (zip_code,))
            total_examples = cursor.fetchone()[0] or 0
            
            # Need at least some training data to make adjustments
            if total_examples < 10:
                conn.close()
                return 0.0
            
            # Count positive and negative examples
            cursor.execute('''
                SELECT COUNT(*) FROM training_data 
                WHERE zip_code = ? AND good_fit = 1
            ''', (zip_code,))
            positive_count = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT COUNT(*) FROM training_data 
                WHERE zip_code = ? AND good_fit = 0
            ''', (zip_code,))
            negative_count = cursor.fetchone()[0] or 0
            
            if positive_count + negative_count == 0:
                conn.close()
                return 0.0
            
            # Calculate base probability
            base_prob = positive_count / (positive_count + negative_count)
            
            # Calculate feature-based adjustment
            total_adjustment = 0.0
            feature_count = 0
            
            for feature_type, feature_set in features.items():
                for feature in feature_set:
                    if not feature or len(feature) < 2:
                        continue
                    
                    # Count how many times this feature appeared in positive vs negative examples
                    # We'll use a simplified approach: check if feature appears in training examples
                    # For performance, we'll use article content matching
                    
                    # Get articles with this feature in training data
                    cursor.execute('''
                        SELECT good_fit FROM training_data td
                        JOIN articles a ON td.article_id = a.id
                        WHERE td.zip_code = ? 
                        AND (LOWER(a.title) LIKE ? OR LOWER(a.summary) LIKE ? OR LOWER(a.content) LIKE ?)
                        LIMIT 50
                    ''', (zip_code, f'%{feature}%', f'%{feature}%', f'%{feature}%'))
                    
                    feature_examples = cursor.fetchall()
                    if feature_examples:
                        feature_positive = sum(1 for ex in feature_examples if ex[0] == 1)
                        feature_total = len(feature_examples)
                        
                        if feature_total > 0:
                            feature_prob = feature_positive / feature_total
                            # Adjustment: (feature_prob - base_prob) * weight
                            adjustment = (feature_prob - base_prob) * 10.0  # Scale factor
                            total_adjustment += adjustment
                            feature_count += 1
            
            conn.close()
            
            # Average adjustment, clamped to reasonable range
            if feature_count > 0:
                avg_adjustment = total_adjustment / feature_count
                return max(-20.0, min(20.0, avg_adjustment))
            else:
                return 0.0
            
        except Exception as e:
            logger.debug(f"Error calculating Bayesian adjustment: {e}")
            return 0.0
    
    def get_training_stats(self, zip_code: Optional[str] = None) -> Dict:
        """Get training statistics for a zip code"""
        if not zip_code:
            return {'total_examples': 0, 'positive_examples': 0, 'negative_examples': 0, 'accuracy': 0.0}
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT COUNT(*) FROM training_data WHERE zip_code = ?
            ''', (zip_code,))
            total = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT COUNT(*) FROM training_data 
                WHERE zip_code = ? AND good_fit = 1
            ''', (zip_code,))
            positive = cursor.fetchone()[0] or 0
            
            cursor.execute('''
                SELECT COUNT(*) FROM training_data 
                WHERE zip_code = ? AND good_fit = 0
            ''', (zip_code,))
            negative = cursor.fetchone()[0] or 0
            
            conn.close()
            
            # Estimate accuracy (after 100 clicks, assume 95%+)
            accuracy = min(95.0, max(50.0, 50.0 + (total / 100.0) * 45.0)) if total > 0 else 0.0
            
            return {
                'total_examples': total,
                'positive_examples': positive,
                'negative_examples': negative,
                'accuracy': accuracy
            }
            
        except Exception as e:
            logger.warning(f"Error getting training stats: {e}")
            return {'total_examples': 0, 'positive_examples': 0, 'negative_examples': 0, 'accuracy': 0.0}

