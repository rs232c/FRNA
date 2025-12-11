"""
Zip code resolution service - converts zip codes to city/state
Uses free APIs with caching to avoid repeated calls
Now includes database caching via city_zip_mapping table
"""
import requests
import logging
import sqlite3
from typing import Dict, Optional
from functools import lru_cache
import time
from config import DATABASE_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory cache with TTL (24 hours)
_cache = {}
_cache_ttl = 24 * 60 * 60  # 24 hours in seconds


def resolve_zip(zip_code: str) -> Optional[Dict[str, str]]:
    """
    Resolve zip code to city and state
    Now checks database cache (city_zip_mapping) first, then API, then saves to DB
    
    Args:
        zip_code: 5-digit zip code string (e.g., "02720")
    
    Returns:
        Dict with keys: "city", "state", "state_abbrev", "zip", "city_state" or None if resolution fails
    """
    if not zip_code or len(zip_code) != 5 or not zip_code.isdigit():
        logger.warning(f"Invalid zip code format: {zip_code}")
        return None
    
    # Check database cache first (Phase 3 - city_zip_mapping table)
    try:
        db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT city_name, state_abbrev, city_state FROM city_zip_mapping WHERE zip_code = ?', (zip_code,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            result = {
                "city": row['city_name'],
                "state": row['state_abbrev'],  # State abbreviation
                "state_abbrev": row['state_abbrev'],
                "zip": zip_code,
                "city_state": row['city_state']
            }
            logger.debug(f"Using database cache for zip {zip_code}: {result['city_state']}")
            return result
    except Exception as e:
        logger.warning(f"Error checking database cache for zip {zip_code}: {e}")
    
    # Check in-memory cache
    cache_key = zip_code
    if cache_key in _cache:
        cached_data, cached_time = _cache[cache_key]
        if time.time() - cached_time < _cache_ttl:
            logger.debug(f"Using in-memory cache for zip {zip_code}")
            return cached_data
    
    # Try primary API: zippopotam.us
    try:
        url = f"https://api.zippopotam.us/us/{zip_code}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("places"):
                place = data["places"][0]  # Get first place
                result = {
                    "city": place.get("place name", ""),
                    "state": place.get("state", ""),
                    "state_abbrev": place.get("state abbreviation", ""),
                    "zip": zip_code,
                    "city_state": f"{place.get('place name', '')}, {place.get('state abbreviation', '')}"
                }
                # Save to database cache
                _save_to_db_cache(zip_code, result)
                # Cache in memory
                _cache[cache_key] = (result, time.time())
                logger.info(f"Resolved {zip_code} to {result['city_state']}")
                return result
    except Exception as e:
        logger.warning(f"Zippopotam API failed for {zip_code}: {e}")
    
    # Try fallback API: ziptasticapi.com
    try:
        url = f"https://ziptasticapi.com/{zip_code}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get("city") and data.get("state"):
                result = {
                    "city": data.get("city", ""),
                    "state": data.get("state", ""),
                    "state_abbrev": data.get("state", ""),  # API returns abbrev
                    "zip": zip_code,
                    "city_state": f"{data.get('city', '')}, {data.get('state', '')}"
                }
                # Save to database cache
                _save_to_db_cache(zip_code, result)
                # Cache in memory
                _cache[cache_key] = (result, time.time())
                logger.info(f"Resolved {zip_code} to {result['city_state']} (fallback API)")
                return result
    except Exception as e:
        logger.warning(f"Ziptastic API failed for {zip_code}: {e}")
    
    logger.error(f"Failed to resolve zip code {zip_code} from both APIs")
    return None


def get_city_state(zip_code: str) -> tuple[Optional[str], Optional[str]]:
    """
    Convenience function to get just city and state
    
    Returns:
        Tuple of (city, state_abbrev) or (None, None) if failed
    """
    result = resolve_zip(zip_code)
    if result:
        return result.get("city"), result.get("state_abbrev")
    return None, None


def get_city_state_for_zip(zip_code: str) -> Optional[str]:
    """
    Get city_state composite key (e.g., "Fall River, MA") for a zip code
    Phase 3: Returns cached or resolved city_state
    
    Args:
        zip_code: 5-digit zip code string
    
    Returns:
        City state string like "Fall River, MA" or None if resolution fails
    """
    result = resolve_zip(zip_code)
    if result:
        return result.get("city_state")
    return None


def _save_to_db_cache(zip_code: str, result: Dict[str, str]):
    """
    Save zip resolution to database cache (city_zip_mapping table)
    Phase 3: Database caching for zip → city resolution
    """
    try:
        db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO city_zip_mapping 
            (zip_code, city_name, state_abbrev, city_state, resolved_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            zip_code,
            result.get("city", ""),
            result.get("state_abbrev", ""),
            result.get("city_state", f"{result.get('city', '')}, {result.get('state_abbrev', '')}")
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Error saving zip resolution to database cache: {e}")

