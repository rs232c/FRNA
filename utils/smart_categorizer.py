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
        """Analyze text and return category scores"""
        if not text:
            return {cat: 0.0 for cat in self.categories}

        text_lower = text.lower()
        words = set(re.findall(r'\b\w+\b', text_lower))

        category_scores = {}

        for category in self.categories:
            keywords = self.get_category_keywords(category)
            if not keywords:
                category_scores[category] = 0.0
                continue

            # Count keyword matches
            matches = keywords.intersection(words)
            match_count = len(matches)

            # Calculate score based on:
            # 1. Number of keyword matches
            # 2. Density of keywords in text
            # 3. Length of matching keywords (longer = more specific)

            if match_count > 0:
                # Base score from match count
                base_score = min(match_count * 10, 50)  # Cap at 50

                # Density bonus (keywords per 100 words)
                total_words = len(words)
                density = (match_count / total_words) * 100 if total_words > 0 else 0
                density_bonus = min(density * 2, 20)  # Cap at 20

                # Specificity bonus (longer keywords are more specific)
                avg_keyword_length = sum(len(kw) for kw in matches) / match_count
                specificity_bonus = min((avg_keyword_length - 3) * 2, 15)  # Cap at 15

                total_score = base_score + density_bonus + specificity_bonus

                # Boost obituaries (they have very specific patterns)
                if category == 'obituaries':
                    obituary_indicators = ['died', 'passed away', 'in loving memory', 'funeral', 'burial']
                    if any(indicator in text_lower for indicator in obituary_indicators):
                        total_score *= 1.5

                category_scores[category] = min(total_score, 100)
            else:
                category_scores[category] = 0.0

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

            # If no category scores above threshold, default to 'local-news'
            if confidence < 10:
                primary_category = 'local-news'
                confidence = 50  # Default confidence for fallback
                all_scores[primary_category] = confidence
        else:
            primary_category = 'local-news'
            confidence = 50
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
