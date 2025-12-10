"""
Zip code resolution service - converts zip codes to city/state
Uses free APIs with caching to avoid repeated calls
"""
import requests
import logging
from typing import Dict, Optional
from functools import lru_cache
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory cache with TTL (24 hours)
_cache = {}
_cache_ttl = 24 * 60 * 60  # 24 hours in seconds


def resolve_zip(zip_code: str) -> Optional[Dict[str, str]]:
    """
    Resolve zip code to city and state
    
    Args:
        zip_code: 5-digit zip code string (e.g., "02720")
    
    Returns:
        Dict with keys: "city", "state", "zip" or None if resolution fails
    """
    if not zip_code or len(zip_code) != 5 or not zip_code.isdigit():
        logger.warning(f"Invalid zip code format: {zip_code}")
        return None
    
    # Check cache first
    cache_key = zip_code
    if cache_key in _cache:
        cached_data, cached_time = _cache[cache_key]
        if time.time() - cached_time < _cache_ttl:
            logger.debug(f"Using cached data for zip {zip_code}")
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
                    "zip": zip_code
                }
                # Cache the result
                _cache[cache_key] = (result, time.time())
                logger.info(f"Resolved {zip_code} to {result['city']}, {result['state_abbrev']}")
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
                    "zip": zip_code
                }
                # Cache the result
                _cache[cache_key] = (result, time.time())
                logger.info(f"Resolved {zip_code} to {result['city']}, {result['state_abbrev']} (fallback API)")
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

