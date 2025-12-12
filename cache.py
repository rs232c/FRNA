"""
Intelligent caching layer for news aggregation
Uses in-memory cache with file-based persistence

CACHING DISABLED: 2024-12-11
All caching is disabled to ensure fresh data on every page load.
"""
import json
import hashlib
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from functools import lru_cache
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CACHING DISABLED - Always fetch fresh data
CACHE_DISABLED = True

# Cache directory (kept for compatibility but not used when disabled)
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

# Cache TTLs (in seconds) - NOT USED when CACHE_DISABLED=True
CACHE_TTLS = {
    "rss": 0,  # DISABLED
    "scraped": 0,  # DISABLED
    "weather": 0,  # DISABLED
    "articles": 0,  # DISABLED
    "meetings": 0,  # DISABLED
}


class CacheManager:
    """Manages caching for RSS feeds, scraped content, and other data
    
    NOTE: Caching is currently DISABLED (CACHE_DISABLED=True)
    All get() calls return None to force fresh data fetches.
    """
    
    def __init__(self):
        self.memory_cache = {}  # In-memory cache
        self.cache_dir = CACHE_DIR
        if CACHE_DISABLED:
            logger.info("[CACHE] ⚠️ Caching is DISABLED - all requests will fetch fresh data")
    
    def _get_cache_key(self, cache_type: str, identifier: str) -> str:
        """Generate cache key"""
        key_string = f"{cache_type}:{identifier}"
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """Get file path for cache entry"""
        return self.cache_dir / f"{cache_key}.json"
    
    def get(self, cache_type: str, identifier: str) -> Optional[Any]:
        """Get cached value if exists and not expired
        
        DISABLED: Always returns None to force fresh data
        """
        # CACHING DISABLED - always return None to force fresh fetch
        if CACHE_DISABLED:
            logger.debug(f"[CACHE] DISABLED - forcing fresh fetch for {cache_type}:{identifier}")
            return None
        
        cache_key = self._get_cache_key(cache_type, identifier)
        
        # Check memory cache first
        if cache_key in self.memory_cache:
            entry = self.memory_cache[cache_key]
            if time.time() < entry.get("expires_at", 0):
                logger.debug(f"Cache hit (memory): {cache_type}:{identifier}")
                return entry.get("data")
            else:
                # Expired, remove from memory
                del self.memory_cache[cache_key]
        
        # Check file cache
        cache_path = self._get_cache_path(cache_key)
        if cache_path.exists():
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    entry = json.load(f)
                
                expires_at = entry.get("expires_at", 0)
                if time.time() < expires_at:
                    # Load into memory cache
                    self.memory_cache[cache_key] = entry
                    logger.debug(f"Cache hit (file): {cache_type}:{identifier}")
                    return entry.get("data")
                else:
                    # Expired, delete file
                    cache_path.unlink()
                    logger.debug(f"Cache expired: {cache_type}:{identifier}")
            except Exception as e:
                logger.warning(f"Error reading cache file {cache_path}: {e}")
        
        logger.debug(f"Cache miss: {cache_type}:{identifier}")
        return None
    
    def set(self, cache_type: str, identifier: str, data: Any, ttl: Optional[int] = None):
        """Set cached value
        
        DISABLED: Does nothing when caching is disabled
        """
        # CACHING DISABLED - don't store anything
        if CACHE_DISABLED:
            logger.debug(f"[CACHE] DISABLED - not caching {cache_type}:{identifier}")
            return
        
        cache_key = self._get_cache_key(cache_type, identifier)
        
        # Get TTL
        if ttl is None:
            ttl = CACHE_TTLS.get(cache_type, 10 * 60)  # Default 10 minutes
        
        expires_at = time.time() + ttl
        
        entry = {
            "cache_type": cache_type,
            "identifier": identifier,
            "data": data,
            "expires_at": expires_at,
            "cached_at": time.time()
        }
        
        # Store in memory
        self.memory_cache[cache_key] = entry
        
        # Store in file
        cache_path = self._get_cache_path(cache_key)
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(entry, f, default=str)
        except Exception as e:
            logger.warning(f"Error writing cache file {cache_path}: {e}")
    
    def invalidate(self, cache_type: str, identifier: Optional[str] = None):
        """Invalidate cache entries"""
        if identifier:
            cache_key = self._get_cache_key(cache_type, identifier)
            # Remove from memory
            if cache_key in self.memory_cache:
                del self.memory_cache[cache_key]
            # Remove file
            cache_path = self._get_cache_path(cache_key)
            if cache_path.exists():
                cache_path.unlink()
            logger.info(f"Invalidated cache: {cache_type}:{identifier}")
        else:
            # Invalidate all of this type
            keys_to_remove = []
            for key, entry in self.memory_cache.items():
                if entry.get("cache_type") == cache_type:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self.memory_cache[key]
            
            # Remove files
            for cache_file in self.cache_dir.glob("*.json"):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as f:
                        entry = json.load(f)
                    if entry.get("cache_type") == cache_type:
                        cache_file.unlink()
                except:
                    pass
            
            logger.info(f"Invalidated all cache entries of type: {cache_type}")
    
    def clear_all(self):
        """Clear all cache"""
        self.memory_cache.clear()
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
        logger.info("Cleared all cache")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        memory_entries = len(self.memory_cache)
        file_entries = len(list(self.cache_dir.glob("*.json")))
        
        return {
            "memory_entries": memory_entries,
            "file_entries": file_entries,
            "cache_dir": str(self.cache_dir)
        }


# Global cache instance
_cache_manager = CacheManager()


def get_cache() -> CacheManager:
    """Get global cache manager instance"""
    return _cache_manager

