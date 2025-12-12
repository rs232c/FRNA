"""
Content quality analyzer for articles
Assesses article quality based on multiple signals
"""
import re
import math
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class ContentQualityAnalyzer:
    """Analyzes article content quality using multiple metrics"""

    def __init__(self):
        # Common filler words and phrases
        self.filler_phrases = [
            "click here", "read more", "find out", "you won't believe",
            "this is why", "what happened next", "the shocking truth",
            "in a surprising turn", "sources say", "according to reports"
        ]

        # Quality thresholds
        self.min_content_length = 200  # Minimum characters
        self.max_content_length = 10000  # Maximum characters (too long might be spam)
        self.min_sentences = 3  # Minimum sentences
        self.max_sentences = 50  # Maximum sentences

    def analyze_length(self, content: str) -> Dict:
        """Analyze content length and structure"""
        if not content:
            return {
                'word_count': 0,
                'char_count': 0,
                'sentence_count': 0,
                'avg_words_per_sentence': 0,
                'length_score': 0,
                'issues': ['No content']
            }

        # Basic counts
        char_count = len(content)
        words = content.split()
        word_count = len(words)

        # Sentence count (rough approximation)
        sentences = re.split(r'[.!?]+', content)
        sentence_count = len([s for s in sentences if s.strip()])

        avg_words_per_sentence = word_count / sentence_count if sentence_count > 0 else 0

        # Length scoring
        length_score = 0
        issues = []

        if char_count < self.min_content_length:
            issues.append(f"Too short ({char_count} chars < {self.min_content_length})")
        elif char_count > self.max_content_length:
            issues.append(f"Too long ({char_count} chars > {self.max_content_length})")
            length_score -= 20
        else:
            length_score += 30

        if sentence_count < self.min_sentences:
            issues.append(f"Too few sentences ({sentence_count} < {self.min_sentences})")
        elif sentence_count > self.max_sentences:
            issues.append(f"Too many sentences ({sentence_count} > {self.max_sentences})")
        else:
            length_score += 20

        if avg_words_per_sentence < 8:
            issues.append("Sentences too short")
        elif avg_words_per_sentence > 30:
            issues.append("Sentences too long")
        else:
            length_score += 10

        return {
            'word_count': word_count,
            'char_count': char_count,
            'sentence_count': sentence_count,
            'avg_words_per_sentence': avg_words_per_sentence,
            'length_score': max(0, length_score),
            'issues': issues
        }

    def analyze_readability(self, content: str) -> Dict:
        """Analyze content readability using simple metrics"""
        if not content:
            return {'flesch_score': 0, 'readability_score': 0, 'issues': ['No content']}

        words = content.split()
        if len(words) < 10:
            return {'flesch_score': 0, 'readability_score': 0, 'issues': ['Content too short for readability analysis']}

        # Count syllables (simplified)
        def count_syllables(word: str) -> int:
            word = word.lower()
            count = 0
            vowels = "aeiouy"
            prev_vowel = False

            for char in word:
                is_vowel = char in vowels
                if is_vowel and not prev_vowel:
                    count += 1
                prev_vowel = is_vowel

            # Adjust for silent 'e'
            if word.endswith('e'):
                count -= 1
            if word.endswith('le') and len(word) > 2 and word[-3] not in vowels:
                count += 1
            if count == 0:
                count += 1

            return count

        total_syllables = sum(count_syllables(word) for word in words)
        total_words = len(words)

        # Count sentences
        sentences = re.split(r'[.!?]+', content)
        total_sentences = len([s for s in sentences if s.strip()])

        if total_sentences == 0:
            total_sentences = 1

        # Flesch Reading Ease formula (simplified)
        flesch_score = 206.835 - (1.015 * (total_words / total_sentences)) - (84.6 * (total_syllables / total_words))

        # Clamp to reasonable range
        flesch_score = max(0, min(100, flesch_score))

        readability_score = 0
        issues = []

        if flesch_score < 30:
            issues.append("Very difficult to read")
            readability_score -= 30
        elif flesch_score < 50:
            issues.append("Difficult to read")
            readability_score -= 15
        elif flesch_score > 90:
            issues.append("Too simple")
            readability_score -= 10
        elif flesch_score > 70:
            readability_score += 20
        else:
            readability_score += 10

        return {
            'flesch_score': flesch_score,
            'readability_score': readability_score,
            'issues': issues
        }

    def analyze_quality_signals(self, article: Dict) -> Dict:
        """Analyze various quality signals"""
        title = article.get('title', '')
        content = article.get('content', '') or article.get('summary', '')
        source = article.get('source', '')

        signals = {
            'has_title': bool(title.strip()),
            'has_content': bool(content.strip()),
            'title_length': len(title),
            'content_length': len(content),
            'has_image': bool(article.get('image_url')),
            'quality_score': 0,
            'issues': []
        }

        # Title quality
        if signals['has_title']:
            if len(title) < 10:
                signals['issues'].append("Title too short")
                signals['quality_score'] -= 10
            elif len(title) > 100:
                signals['issues'].append("Title too long")
                signals['quality_score'] -= 5
            else:
                signals['quality_score'] += 15

            # Check for clickbait patterns
            title_lower = title.lower()
            clickbait_words = ['shocking', 'unbelievable', 'amazing', 'incredible', 'secret', 'hack']
            if any(word in title_lower for word in clickbait_words):
                signals['issues'].append("Possible clickbait title")
                signals['quality_score'] -= 10
        else:
            signals['issues'].append("Missing title")
            signals['quality_score'] -= 20

        # Content quality
        if signals['has_content']:
            if len(content) < 100:
                signals['issues'].append("Content too short")
                signals['quality_score'] -= 15
            elif len(content) > 5000:
                signals['issues'].append("Content suspiciously long")
                signals['quality_score'] -= 5
            else:
                signals['quality_score'] += 20

            # Check for filler content
            content_lower = content.lower()
            filler_count = sum(1 for phrase in self.filler_phrases if phrase in content_lower)
            if filler_count > 2:
                signals['issues'].append(f"High filler content ({filler_count} phrases)")
                signals['quality_score'] -= filler_count * 5
        else:
            signals['issues'].append("Missing content")
            signals['quality_score'] -= 25

        # Image presence
        if signals['has_image']:
            signals['quality_score'] += 5

        return signals

    def calculate_quality_score(self, article: Dict) -> Dict:
        """Calculate overall quality score for an article"""
        title = article.get('title', '')
        content = article.get('content', '') or article.get('summary', '')

        # Analyze different aspects
        length_analysis = self.analyze_length(content)
        readability_analysis = self.analyze_readability(content)
        signals_analysis = self.analyze_quality_signals(article)

        # Combine scores (weighted)
        total_score = (
            length_analysis['length_score'] * 0.4 +
            readability_analysis['readability_score'] * 0.3 +
            signals_analysis['quality_score'] * 0.3
        )

        # Clamp to 0-100 range
        total_score = max(0, min(100, total_score))

        # Combine all issues
        all_issues = []
        all_issues.extend(length_analysis.get('issues', []))
        all_issues.extend(readability_analysis.get('issues', []))
        all_issues.extend(signals_analysis.get('issues', []))

        return {
            'quality_score': total_score,
            'length_analysis': length_analysis,
            'readability_analysis': readability_analysis,
            'signals_analysis': signals_analysis,
            'issues': all_issues,
            'grade': self._score_to_grade(total_score)
        }

    def _score_to_grade(self, score: float) -> str:
        """Convert numerical score to letter grade"""
        if score >= 90:
            return 'A'
        elif score >= 80:
            return 'B'
        elif score >= 70:
            return 'C'
        elif score >= 60:
            return 'D'
        else:
            return 'F'

    def should_reject_article(self, article: Dict, quality_threshold: float = 40.0) -> Tuple[bool, str]:
        """Determine if article should be rejected based on quality"""
        analysis = self.calculate_quality_score(article)

        if analysis['quality_score'] < quality_threshold:
            reasons = analysis.get('issues', [])
            reason_text = '; '.join(reasons) if reasons else f"Quality score too low ({analysis['quality_score']:.1f})"
            return True, reason_text

        return False, ""
