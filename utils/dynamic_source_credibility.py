"""
Dynamic source credibility system that learns from historical performance
Tracks source performance and adjusts credibility scores over time
"""
import sqlite3
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import logging
from config import DATABASE_CONFIG

logger = logging.getLogger(__name__)

class DynamicSourceCredibility:
    """Learns and adapts source credibility based on historical performance"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DATABASE_CONFIG.get("path", "fallriver_news.db")
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Create source performance tracking table if it doesn't exist"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Source performance tracking table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS source_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    zip_code TEXT,
                    total_articles INTEGER DEFAULT 0,
                    enabled_articles INTEGER DEFAULT 0,
                    avg_relevance_score REAL DEFAULT 0.0,
                    avg_quality_score REAL DEFAULT 0.0,
                    user_engagement_rate REAL DEFAULT 0.0,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_name, zip_code)
                )
            ''')

            # Source credibility adjustments table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS source_credibility_adjustments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    zip_code TEXT,
                    base_credibility REAL DEFAULT 0.0,
                    performance_multiplier REAL DEFAULT 1.0,
                    quality_multiplier REAL DEFAULT 1.0,
                    engagement_multiplier REAL DEFAULT 1.0,
                    final_score REAL DEFAULT 0.0,
                    last_calculated TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_name, zip_code)
                )
            ''')

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Error creating source credibility tables: {e}")

    def update_source_performance(self, source_name: str, relevance_score: float,
                                quality_score: float, is_enabled: bool,
                                zip_code: Optional[str] = None):
        """Update performance metrics for a source"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get current performance data
            cursor.execute('''
                SELECT total_articles, enabled_articles, avg_relevance_score, avg_quality_score
                FROM source_performance
                WHERE source_name = ? AND (zip_code = ? OR zip_code IS NULL)
                ORDER BY zip_code DESC  -- Prefer zip-specific over global
                LIMIT 1
            ''', (source_name, zip_code))

            current = cursor.fetchone()

            if current:
                total_articles, enabled_articles, avg_relevance, avg_quality = current

                # Update running averages
                new_total = total_articles + 1
                new_enabled = enabled_articles + (1 if is_enabled else 0)

                # Exponential moving average for scores (gives more weight to recent articles)
                alpha = 0.1  # Weight for new values
                new_avg_relevance = avg_relevance * (1 - alpha) + relevance_score * alpha
                new_avg_quality = avg_quality * (1 - alpha) + quality_score * alpha

                cursor.execute('''
                    UPDATE source_performance
                    SET total_articles = ?, enabled_articles = ?, avg_relevance_score = ?,
                        avg_quality_score = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE source_name = ? AND (zip_code = ? OR zip_code IS NULL)
                ''', (new_total, new_enabled, new_avg_relevance, new_avg_quality, source_name, zip_code))

            else:
                # Insert new source record
                cursor.execute('''
                    INSERT INTO source_performance
                    (source_name, zip_code, total_articles, enabled_articles,
                     avg_relevance_score, avg_quality_score, last_updated)
                    VALUES (?, ?, 1, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (source_name, zip_code, 1 if is_enabled else 0, relevance_score, quality_score))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Error updating source performance for {source_name}: {e}")

    def calculate_dynamic_credibility(self, source_name: str, zip_code: Optional[str] = None) -> float:
        """Calculate dynamic credibility score for a source"""
        try:
            # Get base credibility from config
            from config import NEWS_SOURCES
            base_credibility = 0.0

            # Find source in config (case-insensitive match)
            for source_key, source_config in NEWS_SOURCES.items():
                if source_config.get('name', '').lower() == source_name.lower():
                    # Get credibility from relevance_config table
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT points FROM relevance_config
                        WHERE category = 'source_credibility'
                        AND item = ?
                        AND (zip_code = ? OR zip_code IS NULL)
                        ORDER BY zip_code DESC
                        LIMIT 1
                    ''', (source_name.lower(), zip_code))
                    result = cursor.fetchone()
                    conn.close()

                    if result:
                        base_credibility = result[0] or 0.0
                    break

            # Get performance data
            performance_multiplier = self._calculate_performance_multiplier(source_name, zip_code)
            quality_multiplier = self._calculate_quality_multiplier(source_name, zip_code)
            engagement_multiplier = self._calculate_engagement_multiplier(source_name, zip_code)

            # Calculate final score
            final_score = base_credibility * performance_multiplier * quality_multiplier * engagement_multiplier

            # Store the calculation
            self._store_credibility_adjustment(source_name, zip_code, base_credibility,
                                             performance_multiplier, quality_multiplier,
                                             engagement_multiplier, final_score)

            return final_score

        except Exception as e:
            logger.error(f"Error calculating dynamic credibility for {source_name}: {e}")
            return 0.0

    def _calculate_performance_multiplier(self, source_name: str, zip_code: Optional[str]) -> float:
        """Calculate performance-based multiplier"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT total_articles, enabled_articles, avg_relevance_score
                FROM source_performance
                WHERE source_name = ? AND (zip_code = ? OR zip_code IS NULL)
                ORDER BY zip_code DESC
                LIMIT 1
            ''', (source_name, zip_code))

            result = cursor.fetchone()
            conn.close()

            if not result or result[0] < 5:  # Need at least 5 articles for reliable stats
                return 1.0

            total_articles, enabled_articles, avg_relevance = result

            # Enablement rate (how often articles from this source get enabled)
            enablement_rate = enabled_articles / total_articles if total_articles > 0 else 0

            # Relevance bonus/penalty
            relevance_multiplier = 1.0
            if avg_relevance > 70:
                relevance_multiplier = 1.2  # Good source
            elif avg_relevance > 50:
                relevance_multiplier = 1.0  # Average
            elif avg_relevance > 30:
                relevance_multiplier = 0.8  # Below average
            else:
                relevance_multiplier = 0.6  # Poor source

            # Combine factors
            performance_multiplier = (enablement_rate * 0.6) + (relevance_multiplier * 0.4)

            # Clamp to reasonable range
            return max(0.3, min(1.5, performance_multiplier))

        except Exception as e:
            logger.error(f"Error calculating performance multiplier for {source_name}: {e}")
            return 1.0

    def _calculate_quality_multiplier(self, source_name: str, zip_code: Optional[str]) -> float:
        """Calculate quality-based multiplier"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT avg_quality_score
                FROM source_performance
                WHERE source_name = ? AND (zip_code = ? OR zip_code IS NULL)
                ORDER BY zip_code DESC
                LIMIT 1
            ''', (source_name, zip_code))

            result = cursor.fetchone()
            conn.close()

            if not result or result[0] is None:
                return 1.0

            avg_quality = result[0]

            # Quality multiplier
            if avg_quality > 80:
                return 1.3  # Excellent quality
            elif avg_quality > 70:
                return 1.1  # Good quality
            elif avg_quality > 60:
                return 1.0  # Average quality
            elif avg_quality > 50:
                return 0.9  # Below average
            else:
                return 0.7  # Poor quality

        except Exception as e:
            logger.error(f"Error calculating quality multiplier for {source_name}: {e}")
            return 1.0

    def _calculate_engagement_multiplier(self, source_name: str, zip_code: Optional[str]) -> float:
        """Calculate engagement-based multiplier (placeholder for future user tracking)"""
        # For now, return neutral multiplier
        # This could be expanded to track user clicks, time spent, shares, etc.
        return 1.0

    def _store_credibility_adjustment(self, source_name: str, zip_code: str,
                                    base_credibility: float, performance_mult: float,
                                    quality_mult: float, engagement_mult: float,
                                    final_score: float):
        """Store credibility calculation for auditing"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO source_credibility_adjustments
                (source_name, zip_code, base_credibility, performance_multiplier,
                 quality_multiplier, engagement_multiplier, final_score, last_calculated)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (source_name, zip_code, base_credibility, performance_mult,
                  quality_mult, engagement_mult, final_score))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Error storing credibility adjustment for {source_name}: {e}")

    def get_source_stats(self, source_name: str, zip_code: Optional[str] = None) -> Dict:
        """Get comprehensive stats for a source"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get performance stats
            cursor.execute('''
                SELECT total_articles, enabled_articles, avg_relevance_score, avg_quality_score
                FROM source_performance
                WHERE source_name = ? AND (zip_code = ? OR zip_code IS NULL)
                ORDER BY zip_code DESC
                LIMIT 1
            ''', (source_name, zip_code))

            perf_result = cursor.fetchone()

            # Get credibility adjustment
            cursor.execute('''
                SELECT base_credibility, performance_multiplier, quality_multiplier,
                       engagement_multiplier, final_score
                FROM source_credibility_adjustments
                WHERE source_name = ? AND (zip_code = ? OR zip_code IS NULL)
                ORDER BY zip_code DESC
                LIMIT 1
            ''', (source_name, zip_code))

            cred_result = cursor.fetchone()
            conn.close()

            stats = {
                'source_name': source_name,
                'zip_code': zip_code,
                'performance': {},
                'credibility': {}
            }

            if perf_result:
                total, enabled, avg_rel, avg_qual = perf_result
                stats['performance'] = {
                    'total_articles': total,
                    'enabled_articles': enabled,
                    'enablement_rate': (enabled / total * 100) if total > 0 else 0,
                    'avg_relevance_score': avg_rel,
                    'avg_quality_score': avg_qual
                }

            if cred_result:
                base, perf_mult, qual_mult, eng_mult, final = cred_result
                stats['credibility'] = {
                    'base_credibility': base,
                    'performance_multiplier': perf_mult,
                    'quality_multiplier': qual_mult,
                    'engagement_multiplier': eng_mult,
                    'final_score': final
                }

            return stats

        except Exception as e:
            logger.error(f"Error getting source stats for {source_name}: {e}")
            return {}

    def get_top_sources(self, zip_code: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """Get top-performing sources by final credibility score"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT source_name, final_score, base_credibility,
                       performance_multiplier, quality_multiplier
                FROM source_credibility_adjustments
                WHERE (zip_code = ? OR zip_code IS NULL)
                ORDER BY final_score DESC
                LIMIT ?
            ''', (zip_code, limit))

            results = cursor.fetchall()
            conn.close()

            top_sources = []
            for source_name, final_score, base, perf_mult, qual_mult in results:
                top_sources.append({
                    'source_name': source_name,
                    'final_credibility': final_score,
                    'base_credibility': base,
                    'performance_multiplier': perf_mult,
                    'quality_multiplier': qual_mult
                })

            return top_sources

        except Exception as e:
            logger.error(f"Error getting top sources: {e}")
            return []
