"""
Smart categorizer with learning capabilities
Uses keyword analysis and machine learning to categorize articles
"""
import re
import sqlite3
from typing import Dict, List, Optional, Tuple, Set
from collections import Counter
import logging
from config import DATABASE_CONFIG

logger = logging.getLogger(__name__)

class SmartCategorizer:
    """Intelligent article categorizer with learning capabilities"""

    def __init__(self, zip_code: Optional[str] = None):
        self.zip_code = zip_code
        self.db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
        self.categories = ['business', 'crime', 'events', 'food', 'local-news',
                          'obituaries', 'schools', 'sports', 'weather']

    def get_category_keywords(self, category: str) -> Set[str]:
        """Get keywords for a specific category"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT keyword FROM category_keywords
                WHERE category = ? AND (zip_code = ? OR zip_code IS NULL)
                ORDER BY zip_code DESC  -- Prefer zip-specific keywords
            ''', (category, self.zip_code))

            keywords = {row[0].lower() for row in cursor.fetchall()}
            conn.close()

            return keywords

        except Exception as e:
            logger.error(f"Error getting keywords for category {category}: {e}")
            return set()

    def analyze_text(self, text: str) -> Dict[str, float]:
        """Analyze text and return category scores with improved matching"""
        if not text:
            return {cat: 0.0 for cat in self.categories}

        text_lower = text.lower()
        words = set(re.findall(r'\b\w+\b', text_lower))

        category_scores = {}

        for category in self.categories:
            score = 0.0

            # RULE-BASED PATTERNS FIRST (highest priority)
            if category == 'obituaries':
                obituary_patterns = [
                    r'\bobituary\b', r'\bdied\b', r'\bpassed away\b', r'\bdeceased\b',
                    r'\bin loving memory\b', r'\bfuneral\b', r'\bburial\b', r'\bmemorial\b',
                    r'\bsurvived by\b', r'\bpredeceased\b', r'\bvisitation\b', r'\bwake\b',
                    r'\bcalling hours\b', r'\bfuneral home\b', r'\bdignity memorial\b'
                ]
                for pattern in obituary_patterns:
                    if re.search(pattern, text_lower):
                        score += 30  # Strong obituary signal
                        break

            elif category == 'crime':
                crime_patterns = [
                    r'\barrested\b', r'\bcharged\b', r'\bpolice\b', r'\bcrime\b',
                    r'\binvestigation\b', r'\bsuspect\b', r'\bcharges\b', r'\bcourt\b',
                    r'\bmurder\b', r'\bassault\b', r'\brobbery\b', r'\btheft\b',
                    r'\bstolen\b', r'\barson\b', r'\bdrug\b', r'\btrafficking\b'
                ]
                for pattern in crime_patterns:
                    if re.search(pattern, text_lower):
                        score += 25
                        break

            elif category == 'sports':
                sports_patterns = [
                    r'\bfootball\b', r'\bbasketball\b', r'\bbaseball\b', r'\bhockey\b',
                    r'\bsoccer\b', r'\bgame\b', r'\bteam\b', r'\bplayer\b', r'\bcoach\b',
                    r'\bchampionship\b', r'\bscore\b', r'\bseason\b', r'\btournament\b'
                ]
                for pattern in sports_patterns:
                    if re.search(pattern, text_lower):
                        score += 20
                        break

            elif category == 'weather':
                weather_patterns = [
                    r'\bweather\b', r'\bforecast\b', r'\btemperature\b', r'\brain\b',
                    r'\bsnow\b', r'\bstorm\b', r'\bwind\b', r'\bhurricane\b', r'\bclimate\b'
                ]
                for pattern in weather_patterns:
                    if re.search(pattern, text_lower):
                        score += 25
                        break

            elif category == 'schools':
                school_patterns = [
                    r'\bschool\b', r'\bstudent\b', r'\bteacher\b', r'\beducation\b',
                    r'\bprincipal\b', r'\bclassroom\b', r'\bgraduation\b', r'\bcollege\b',
                    r'\buniversity\b', r'\bacademic\b', r'\bdurfee\b', r'\bbmc durfee\b'
                ]
                for pattern in school_patterns:
                    if re.search(pattern, text_lower):
                        score += 20
                        break

            elif category == 'business':
                business_patterns = [
                    r'\bbusiness\b', r'\bcompany\b', r'\bopening\b', r'\bclosing\b',
                    r'\brestaurant\b', r'\beconomic\b', r'\bcommerce\b', r'\bretail\b',
                    r'\bshop\b', r'\bstore\b', r'\bjob\b', r'\bemployment\b'
                ]
                for pattern in business_patterns:
                    if re.search(pattern, text_lower):
                        score += 18
                        break

            elif category == 'food':
                food_patterns = [
                    r'\brestaurant\b', r'\bfood\b', r'\bdining\b', r'\bcuisine\b',
                    r'\bchef\b', r'\bmenu\b', r'\brecipe\b', r'\bkitchen\b', r'\bcafe\b'
                ]
                for pattern in food_patterns:
                    if re.search(pattern, text_lower):
                        score += 15
                        break

            elif category == 'events':
                event_patterns = [
                    r'\bevent\b', r'\bfestival\b', r'\bconcert\b', r'\bcommunity\b',
                    r'\bfundraiser\b', r'\bcharity\b', r'\bcelebration\b', r'\bgathering\b'
                ]
                for pattern in event_patterns:
                    if re.search(pattern, text_lower):
                        score += 15
                        break

            elif category == 'entertainment':
                entertainment_patterns = [
                    r'\bmusic\b', r'\bshow\b', r'\bconcert\b', r'\btheater\b',
                    r'\bentertainment\b', r'\bfun\b', r'\bperformance\b', r'\bart\b'
                ]
                for pattern in entertainment_patterns:
                    if re.search(pattern, text_lower):
                        score += 12
                        break

            # KEYWORD-BASED SCORING (secondary, if no rule-based match)
            if score == 0:
                keywords = self.get_category_keywords(category)
                if keywords:
                    # Count keyword matches (both exact and partial)
                    exact_matches = keywords.intersection(words)
                    partial_matches = 0

                    # Check for partial matches (keywords within longer phrases)
                    for keyword in keywords:
                        if len(keyword.split()) > 1:  # Multi-word keywords
                            if keyword in text_lower:
                                partial_matches += 1

                    match_count = len(exact_matches) + partial_matches

                    if match_count > 0:
                        # Base score from match count
                        base_score = min(match_count * 8, 40)  # Cap at 40

                        # Density bonus (keywords per 100 words)
                        total_words = len(words)
                        density = (match_count / total_words) * 100 if total_words > 0 else 0
                        density_bonus = min(density * 1.5, 15)  # Cap at 15

                        score = base_score + density_bonus

            # Boost for local Fall River content
            if 'fall river' in text_lower or 'fallriver' in text_lower:
                if score > 0:
                    score += 10  # Boost existing category matches
                elif category == 'local-news':
                    score = 25  # Default boost for local news

            category_scores[category] = min(score, 100)

        return category_scores

    def categorize_article(self, article: Dict) -> Tuple[str, float, Dict[str, float]]:
        """
        Categorize an article and return (primary_category, confidence, all_scores)

        Returns:
            primary_category: The best matching category
            confidence: Confidence score (0-100)
            all_scores: Dict of all category scores
        """
        title = article.get('title', '')
        content = article.get('content', '') or article.get('summary', '')
        combined_text = f"{title} {content}"

        # Analyze combined text
        all_scores = self.analyze_text(combined_text)

        # Find best category
        if all_scores:
            primary_category = max(all_scores.keys(), key=lambda k: all_scores[k])
            confidence = all_scores[primary_category]

            # If confidence is very low, try fallback logic
            if confidence < 15:
                # Check for Fall River specific content
                if 'fall river' in combined_text.lower() or 'fallriver' in combined_text.lower():
                    primary_category = 'local-news'
                    confidence = 60
                    all_scores[primary_category] = confidence
                # Check for obvious obituary patterns
                elif any(word in combined_text.lower() for word in ['obituary', 'died', 'passed away', 'funeral']):
                    primary_category = 'obituaries'
                    confidence = 80
                    all_scores[primary_category] = confidence
                # Check for obvious crime patterns
                elif any(word in combined_text.lower() for word in ['police', 'arrest', 'charged', 'crime']):
                    primary_category = 'crime'
                    confidence = 70
                    all_scores[primary_category] = confidence
                # Default to local-news with low confidence
                else:
                    primary_category = 'local-news'
                    confidence = 30
                    all_scores[primary_category] = confidence
        else:
            primary_category = 'local-news'
            confidence = 30
            all_scores = {cat: 0.0 for cat in self.categories}
            all_scores[primary_category] = confidence

        return primary_category, confidence, all_scores

    def learn_from_correction(self, article: Dict, correct_category: str,
                            actual_category: str, confidence: float):
        """
        Learn from user corrections to improve future categorization

        Args:
            article: The article that was corrected
            correct_category: What the user said it should be
            actual_category: What the system predicted
            confidence: How confident the system was
        """
        try:
            # Extract keywords that should be associated with the correct category
            title = article.get('title', '')
            content = article.get('content', '') or article.get('summary', '')
            combined_text = f"{title} {content}"

            # Find words that appear in the article but aren't already keywords for this category
            existing_keywords = self.get_category_keywords(correct_category)
            words = set(re.findall(r'\b\w+\b', combined_text.lower()))

            # Filter out common words and existing keywords
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
            potential_keywords = words - stop_words - existing_keywords

            # Only consider words that appear multiple times or are relatively long
            word_counts = Counter(re.findall(r'\b\w+\b', combined_text.lower()))
            good_keywords = {word for word in potential_keywords
                           if len(word) > 3 and word_counts[word] >= 2}

            if good_keywords:
                # Add these keywords to the category
                self._add_keywords_to_category(correct_category, list(good_keywords))
                logger.info(f"Learned {len(good_keywords)} new keywords for category {correct_category}")

        except Exception as e:
            logger.error(f"Error learning from correction: {e}")

    def _add_keywords_to_category(self, category: str, keywords: List[str]):
        """Add keywords to a category"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            for keyword in keywords:
                cursor.execute('''
                    INSERT OR IGNORE INTO category_keywords (zip_code, category, keyword)
                    VALUES (?, ?, ?)
                ''', (self.zip_code, category, keyword.lower()))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Error adding keywords to category {category}: {e}")

    def get_category_stats(self) -> Dict[str, Dict]:
        """Get statistics about category performance"""
        stats = {}

        for category in self.categories:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                # Count keywords
                cursor.execute('''
                    SELECT COUNT(*) FROM category_keywords
                    WHERE category = ? AND (zip_code = ? OR zip_code IS NULL)
                ''', (category, self.zip_code))

                keyword_count = cursor.fetchone()[0]

                # Count articles in this category (rough estimate)
                cursor.execute('''
                    SELECT COUNT(*) FROM articles
                    WHERE category = ? AND (zip_code = ? OR zip_code IS NULL)
                ''', (category, self.zip_code))

                article_count = cursor.fetchone()[0]

                conn.close()

                stats[category] = {
                    'keyword_count': keyword_count,
                    'article_count': article_count,
                    'avg_keywords_per_article': article_count / keyword_count if keyword_count > 0 else 0
                }

            except Exception as e:
                logger.error(f"Error getting stats for category {category}: {e}")
                stats[category] = {'keyword_count': 0, 'article_count': 0, 'avg_keywords_per_article': 0}

        return stats

    def suggest_new_keywords(self, category: str, sample_articles: List[Dict] = None, limit: int = 20) -> List[str]:
        """
        Suggest new keywords for a category based on article analysis

        Args:
            category: Category to suggest keywords for
            sample_articles: Optional list of articles to analyze (if None, gets from DB)
            limit: Maximum number of suggestions to return
        """
        if sample_articles is None:
            # Get recent articles from this category
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT title, content, summary FROM articles
                    WHERE category = ? AND (zip_code = ? OR zip_code IS NULL)
                    ORDER BY created_at DESC
                    LIMIT 50
                ''', (category, self.zip_code))

                sample_articles = []
                for row in cursor.fetchall():
                    sample_articles.append({
                        'title': row[0] or '',
                        'content': row[1] or '',
                        'summary': row[2] or ''
                    })

                conn.close()

            except Exception as e:
                logger.error(f"Error getting sample articles for {category}: {e}")
                return []

        if not sample_articles:
            return []

        # Analyze all articles for common words
        all_words = []
        existing_keywords = self.get_category_keywords(category)

        for article in sample_articles:
            text = f"{article.get('title', '')} {article.get('content', '')} {article.get('summary', '')}"
            words = re.findall(r'\b\w+\b', text.lower())
            # Filter out stop words and existing keywords
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
            filtered_words = [w for w in words if len(w) > 3 and w not in stop_words and w not in existing_keywords]
            all_words.extend(filtered_words)

        # Find most common words
        word_counts = Counter(all_words)
        suggestions = [word for word, count in word_counts.most_common(limit) if count >= 3]  # Must appear in at least 3 articles

        return suggestions
