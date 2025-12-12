"""
Semantic deduplication module for detecting similar articles
Uses multiple similarity algorithms to identify near-duplicate content
"""
import re
import math
from typing import List, Dict, Set, Tuple, Optional
from collections import Counter
import logging

logger = logging.getLogger(__name__)

class SemanticDeduplicator:
    """Detects semantically similar articles to prevent duplicates"""

    def __init__(self):
        # Common stop words to ignore
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
            'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does',
            'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'shall',
            'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me',
            'him', 'her', 'us', 'them', 'my', 'your', 'his', 'its', 'our', 'their', 'what', 'which',
            'who', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more',
            'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
            'than', 'too', 'very', 'just', 'now'
        }

    def preprocess_text(self, text: str) -> Set[str]:
        """Preprocess text for similarity comparison"""
        if not text:
            return set()

        # Convert to lowercase
        text = text.lower()

        # Remove URLs, emails, phone numbers
        text = re.sub(r'https?://\S+', '', text)
        text = re.sub(r'\S+@\S+', '', text)
        text = re.sub(r'\d{3}-\d{3}-\d{4}', '', text)

        # Remove punctuation and split into words
        words = re.findall(r'\b\w+\b', text)

        # Remove stop words and short words
        filtered_words = {word for word in words if len(word) > 2 and word not in self.stop_words}

        return filtered_words

    def jaccard_similarity(self, set1: Set[str], set2: Set[str]) -> float:
        """Calculate Jaccard similarity between two word sets"""
        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0

        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))

        return intersection / union if union > 0 else 0.0

    def cosine_similarity(self, text1: str, text2: str) -> float:
        """Calculate cosine similarity using TF-IDF"""
        words1 = self.preprocess_text(text1)
        words2 = self.preprocess_text(text2)

        if not words1 and not words2:
            return 1.0
        if not words1 or not words2:
            return 0.0

        # Create word frequency vectors
        all_words = words1.union(words2)
        vec1 = Counter(words1)
        vec2 = Counter(words2)

        # Calculate dot product
        dot_product = sum(vec1[word] * vec2[word] for word in all_words)

        # Calculate magnitudes
        mag1 = math.sqrt(sum(vec1[word] ** 2 for word in all_words))
        mag2 = math.sqrt(sum(vec2[word] ** 2 for word in all_words))

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot_product / (mag1 * mag2)

    def title_similarity(self, title1: str, title2: str) -> float:
        """Specialized similarity for titles (more strict)"""
        if not title1 or not title2:
            return 0.0

        # For titles, use exact word matching but allow for reordering
        words1 = set(self.preprocess_text(title1))
        words2 = set(self.preprocess_text(title2))

        if not words1 or not words2:
            return 0.0

        # Require higher overlap for titles
        similarity = self.jaccard_similarity(words1, words2)

        # Boost if titles are very similar in length
        len_diff = abs(len(title1) - len(title2)) / max(len(title1), len(title2))
        if len_diff < 0.3:  # Length difference < 30%
            similarity *= 1.2

        return min(similarity, 1.0)

    def content_similarity(self, content1: str, content2: str) -> float:
        """Calculate overall content similarity"""
        if not content1 or not content2:
            return 0.0

        # Use cosine similarity for content
        return self.cosine_similarity(content1, content2)

    def is_duplicate(self, article1: Dict, article2: Dict, threshold: float = 0.7) -> Tuple[bool, float, str]:
        """
        Check if two articles are duplicates

        Args:
            article1, article2: Article dictionaries
            threshold: Similarity threshold (0-1)

        Returns:
            (is_duplicate, similarity_score, reason)
        """
        title1 = article1.get('title', '')
        title2 = article2.get('title', '')
        content1 = article1.get('content', '') or article1.get('summary', '')
        content2 = article2.get('content', '') or article2.get('summary', '')

        # Title similarity (most important)
        title_sim = self.title_similarity(title1, title2)

        # Content similarity
        content_sim = self.content_similarity(content1, content2)

        # Combined similarity (weighted average)
        combined_sim = (title_sim * 0.7) + (content_sim * 0.3)

        # Determine if duplicate
        is_duplicate = combined_sim >= threshold

        # Determine reason
        if is_duplicate:
            if title_sim >= 0.8:
                reason = f"Very similar titles ({title_sim:.2f})"
            elif content_sim >= 0.6:
                reason = f"Similar content ({content_sim:.2f})"
            else:
                reason = f"Overall similarity ({combined_sim:.2f})"
        else:
            reason = f"Below threshold ({combined_sim:.2f} < {threshold})"

        return is_duplicate, combined_sim, reason

    def find_similar_articles(self, new_article: Dict, existing_articles: List[Dict],
                            threshold: float = 0.7) -> List[Tuple[Dict, float, str]]:
        """
        Find articles similar to the new one

        Args:
            new_article: The new article to check
            existing_articles: List of existing articles to compare against
            threshold: Similarity threshold

        Returns:
            List of (article, similarity_score, reason) tuples for similar articles
        """
        similar_articles = []

        for existing in existing_articles:
            is_dup, similarity, reason = self.is_duplicate(new_article, existing, threshold)
            if is_dup:
                similar_articles.append((existing, similarity, reason))

        # Sort by similarity (highest first)
        similar_articles.sort(key=lambda x: x[1], reverse=True)

        return similar_articles

    def deduplicate_batch(self, articles: List[Dict], threshold: float = 0.7) -> Tuple[List[Dict], List[Dict]]:
        """
        Remove duplicates from a batch of articles

        Args:
            articles: List of article dictionaries
            threshold: Similarity threshold

        Returns:
            (unique_articles, duplicates_with_reasons)
        """
        if not articles:
            return [], []

        unique_articles = []
        duplicates = []

        for article in articles:
            # Check against already accepted articles
            similar = self.find_similar_articles(article, unique_articles, threshold)

            if similar:
                # Found similar article, mark as duplicate
                most_similar = similar[0]
                duplicates.append({
                    'article': article,
                    'similar_to': most_similar[0],
                    'similarity': most_similar[1],
                    'reason': most_similar[2]
                })
            else:
                # No similar articles found, add to unique
                unique_articles.append(article)

        return unique_articles, duplicates
