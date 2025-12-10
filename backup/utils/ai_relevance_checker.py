"""
AI-based relevance checker for articles
Uses AI to determine if articles are truly relevant to Fall River, MA
"""
import logging
import os
from typing import Dict, Tuple, Optional
from config import LOCALE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import OpenAI (optional)
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.info("OpenAI not available - will use heuristic-based AI filtering")


class AIRelevanceChecker:
    """AI-based relevance checker for Fall River articles"""
    
    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.enabled = bool(self.api_key) and OPENAI_AVAILABLE
        self.use_ai = self.enabled
        
        if not self.enabled:
            logger.info("AI relevance checking disabled (no OpenAI API key). Using enhanced heuristic method.")
    
    def check_relevance(self, article: Dict) -> Tuple[bool, str, float]:
        """
        Check if article is relevant to Fall River using AI or enhanced heuristics
        Returns: (is_relevant, reason, confidence)
        """
        if self.use_ai and self.api_key:
            return self._check_with_ai(article)
        else:
            return self._check_with_heuristics(article)
    
    def _check_with_ai(self, article: Dict) -> Tuple[bool, str, float]:
        """Use OpenAI API to check relevance"""
        try:
            title = article.get("title", "")
            content = article.get("content", article.get("summary", ""))
            source = article.get("source", "")
            
            # Truncate content for API (keep first 1000 chars)
            content_preview = content[:1000] if len(content) > 1000 else content
            
            prompt = f"""You are a content filter for a local news aggregator in Fall River, Massachusetts.

Article Title: {title}
Article Source: {source}
Article Content (preview): {content_preview}

Determine if this article is TRULY relevant to Fall River, Massachusetts. Consider:
1. Does it mention Fall River, MA specifically?
2. Does it discuss local landmarks, neighborhoods, or people in Fall River?
3. Does it cover events, news, or topics happening IN Fall River?
4. Is it about nearby towns (Somerset, Swansea, Tiverton, etc.) that might affect Fall River residents?

EXCLUDE articles that are:
- About other cities/towns without Fall River connection
- National or regional news not specific to Fall River
- Generic topics (weather, sports, entertainment) not tied to Fall River
- About Cape Cod, Boston, or other areas far from Fall River

Respond with ONLY a JSON object:
{{"relevant": true/false, "reason": "brief explanation", "confidence": 0.0-1.0}}

Be strict - only mark as relevant if there's a clear Fall River connection."""

            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",  # Fast and cheap model
                messages=[
                    {"role": "system", "content": "You are a strict content filter for Fall River, Massachusetts local news. Be conservative - only approve articles with clear local relevance."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150,
                temperature=0.1  # Low temperature for consistent results
            )
            
            import json
            result_text = response.choices[0].message.content.strip()
            
            # Try to parse JSON response
            try:
                # Remove markdown code blocks if present
                if result_text.startswith("```"):
                    result_text = result_text.split("```")[1]
                    if result_text.startswith("json"):
                        result_text = result_text[4:]
                result = json.loads(result_text)
                
                is_relevant = result.get("relevant", False)
                reason = result.get("reason", "AI analysis")
                confidence = float(result.get("confidence", 0.5))
                
                return (is_relevant, reason, confidence)
            except json.JSONDecodeError:
                # Fallback if JSON parsing fails
                logger.warning(f"AI returned non-JSON response: {result_text[:100]}")
                return self._check_with_heuristics(article)
                
        except Exception as e:
            logger.warning(f"AI relevance check failed: {e}. Falling back to heuristics.")
            return self._check_with_heuristics(article)
    
    def _check_with_heuristics(self, article: Dict) -> Tuple[bool, str, float]:
        """Enhanced heuristic-based relevance checking"""
        title = article.get("title", "").lower()
        content = article.get("content", article.get("summary", "")).lower()
        combined = f"{title} {content}"
        
        # Strong indicators of Fall River relevance
        strong_indicators = [
            "fall river", "fallriver", "fall-river",
            "battleship cove", "durfee high", "b.m.c. durfee",
            "saint anne's hospital", "st. anne's hospital",
            "charlton memorial", "mayor coogan", "mayor paul coogan",
            "fall river city council", "fall river school",
            "government center", "kennedy park", "lafayette park"
        ]
        
        # Nearby towns that might be relevant (but need Fall River connection)
        nearby_towns = [
            "somerset", "swansea", "tiverton", "westport", "freetown",
            "taunton", "new bedford", "dartmouth"
        ]
        
        # Strong negative indicators (definitely not Fall River)
        negative_indicators = [
            "cape cod", "boston", "worcester", "springfield",
            "lowell", "cambridge", "somerville", "quincy",
            "new york", "rhode island"  # Too generic
        ]
        
        # Check for strong negative indicators first
        for neg in negative_indicators:
            if neg in combined:
                # But allow if Fall River is also mentioned
                if "fall river" not in combined and "fallriver" not in combined:
                    return (False, f"Article mentions {neg} without Fall River connection", 0.9)
        
        # Check for strong positive indicators
        strong_count = sum(1 for indicator in strong_indicators if indicator in combined)
        if strong_count >= 2:
            return (True, f"Multiple Fall River indicators found ({strong_count})", 0.95)
        elif strong_count == 1:
            # Single strong indicator is enough
            return (True, "Fall River indicator found", 0.85)
        elif "fall river" in combined or "fallriver" in combined:
            # Explicit Fall River mention is always relevant
            return (True, "Explicit Fall River mention", 0.9)
        
        # Check for nearby towns
        nearby_count = sum(1 for town in nearby_towns if town in combined)
        if nearby_count > 0:
            # Nearby town mentioned - need Fall River connection or high relevance
            if "fall river" in combined or "fallriver" in combined:
                return (True, f"Nearby town ({nearby_towns[0] if nearby_count > 0 else ''}) with Fall River mention", 0.7)
            else:
                # Nearby town without Fall River - likely not relevant
                return (False, f"Nearby town mentioned ({nearby_towns[0] if nearby_count > 0 else ''}) without Fall River connection", 0.6)
        
        # No clear indicators - likely not relevant
        return (False, "No clear Fall River indicators found", 0.5)
    
    def should_include(self, article: Dict, threshold: float = 0.6) -> Tuple[bool, str]:
        """
        Determine if article should be included based on AI/heuristic check
        Returns: (should_include, reason)
        """
        is_relevant, reason, confidence = self.check_relevance(article)
        
        if is_relevant and confidence >= threshold:
            return (True, f"AI: {reason} (confidence: {confidence:.1%})")
        elif not is_relevant:
            return (False, f"AI: {reason} (confidence: {confidence:.1%})")
        else:
            # Low confidence - be conservative
            return (False, f"AI: Low confidence ({confidence:.1%}) - {reason}")

