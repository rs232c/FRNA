"""
Image thumbnail caching system
Manages creation and retrieval of image thumbnails
"""
import json
import logging
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib

from .image_processor import create_thumbnail, THUMBNAIL_SIZES

logger = logging.getLogger(__name__)


class ImageCache:
    """
    Manages thumbnail caching for images.
    Provides thread-safe access to cached thumbnails with automatic cleanup.
    """

    def __init__(self, base_dir: Path, max_cache_size_mb: int = 500):
        """
        Initialize image cache.

        Args:
            base_dir: Base directory for cache (e.g., build/zips/zip_02720/)
            max_cache_size_mb: Maximum cache size before cleanup
        """
        self.base_dir = Path(base_dir)
        self.images_dir = self.base_dir / 'images'
        self.thumbnails_dir = self.images_dir / 'thumbnails'
        self.cache_file = self.images_dir / 'cache.json'
        self.max_cache_size_mb = max_cache_size_mb

        # Create directory structure
        for size_name in THUMBNAIL_SIZES.keys():
            (self.thumbnails_dir / size_name).mkdir(parents=True, exist_ok=True)

        # Load existing cache
        self.cache = self._load_cache()

        # Thread pool for async thumbnail creation
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumbnail")

    def _load_cache(self) -> Dict:
        """Load cache metadata from disk"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Could not load image cache: {e}")
                return {}
        return {}

    def _save_cache(self):
        """Save cache metadata to disk"""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Could not save image cache: {e}")

    def get_or_create_thumbnail(self, image_url: str, size_name: str) -> Optional[str]:
        """
        Get cached thumbnail path, or create it if it doesn't exist.

        Args:
            image_url: Original image URL
            size_name: Thumbnail size ('small', 'medium', 'large')

        Returns:
            Relative path to thumbnail, or None if failed
        """
        if not image_url or size_name not in THUMBNAIL_SIZES:
            return None

        # Check cache first
        cache_key = f"{image_url}_{size_name}"
        if cache_key in self.cache:
            cached_path = self.cache[cache_key].get('path')
            if cached_path and (self.base_dir / cached_path).exists():
                # Update access time
                self.cache[cache_key]['accessed'] = datetime.now().isoformat()
                return cached_path

        # Create thumbnail
        try:
            thumb_path = create_thumbnail(image_url, size_name, self.thumbnails_dir / size_name)
            if thumb_path:
                # Cache the result
                self.cache[cache_key] = {
                    'path': thumb_path,
                    'created': datetime.now().isoformat(),
                    'accessed': datetime.now().isoformat(),
                    'original_url': image_url,
                    'size': size_name
                }
                self._save_cache()

                # Check if we need cleanup
                self._check_cache_size()

                return thumb_path

        except Exception as e:
            logger.warning(f"Failed to create thumbnail for {image_url}: {e}")

        return None

    def get_cached_thumbnail(self, image_url: str, size_name: str) -> Optional[str]:
        """
        Get cached thumbnail path without creating it.

        Args:
            image_url: Original image URL
            size_name: Thumbnail size

        Returns:
            Relative path to cached thumbnail, or None
        """
        cache_key = f"{image_url}_{size_name}"
        if cache_key in self.cache:
            cached_path = self.cache[cache_key].get('path')
            if cached_path and (self.base_dir / cached_path).exists():
                # Update access time
                self.cache[cache_key]['accessed'] = datetime.now().isoformat()
                return cached_path

        return None

    def get_all_thumbnails(self, image_url: str) -> Dict[str, Optional[str]]:
        """
        Get all available thumbnail sizes for an image.

        Args:
            image_url: Original image URL

        Returns:
            Dict mapping size names to thumbnail paths
        """
        thumbnails = {}
        for size_name in THUMBNAIL_SIZES.keys():
            thumbnails[size_name] = self.get_cached_thumbnail(image_url, size_name)
        return thumbnails

    def _check_cache_size(self):
        """Check if cache is too large and trigger cleanup if needed"""
        try:
            total_size = sum(
                (self.base_dir / entry['path']).stat().st_size
                for entry in self.cache.values()
                if 'path' in entry and (self.base_dir / entry['path']).exists()
            ) / (1024 * 1024)  # Convert to MB

            if total_size > self.max_cache_size_mb:
                logger.info(f"Cache size {total_size:.1f}MB exceeds limit {self.max_cache_size_mb}MB, triggering cleanup")
                self.cleanup_cache()

        except Exception as e:
            logger.warning(f"Could not check cache size: {e}")

    def cleanup_cache(self, max_age_days: int = 30, keep_recent: int = 1000):
        """
        Clean up old cache entries.

        Args:
            max_age_days: Remove thumbnails older than this many days
            keep_recent: Keep at least this many recently accessed thumbnails
        """
        try:
            now = datetime.now()
            cutoff_date = now - timedelta(days=max_age_days)

            # Sort by access time (most recent first)
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: x[1].get('accessed', x[1].get('created', '2000-01-01')),
                reverse=True
            )

            # Keep most recent entries
            to_keep = sorted_entries[:keep_recent]

            # Also keep entries newer than cutoff
            recent_cutoff = []
            for cache_key, entry in sorted_entries[keep_recent:]:
                created = entry.get('created', '2000-01-01')
                try:
                    created_date = datetime.fromisoformat(created)
                    if created_date > cutoff_date:
                        recent_cutoff.append((cache_key, entry))
                except:
                    pass

            # Combine kept entries
            kept_entries = dict(to_keep + recent_cutoff)
            removed_count = len(self.cache) - len(kept_entries)

            if removed_count > 0:
                logger.info(f"Cache cleanup: removed {removed_count} old thumbnails")

                # Remove files that are no longer in cache
                for cache_key, entry in self.cache.items():
                    if cache_key not in kept_entries and 'path' in entry:
                        try:
                            thumb_file = self.base_dir / entry['path']
                            if thumb_file.exists():
                                thumb_file.unlink()
                        except Exception as e:
                            logger.warning(f"Could not remove cached thumbnail {entry['path']}: {e}")

                # Update cache
                self.cache = kept_entries
                self._save_cache()

        except Exception as e:
            logger.error(f"Cache cleanup failed: {e}")

    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        try:
            total_files = len(self.cache)
            total_size = 0
            size_counts = {size: 0 for size in THUMBNAIL_SIZES.keys()}

            for entry in self.cache.values():
                if 'path' in entry:
                    try:
                        file_path = self.base_dir / entry['path']
                        if file_path.exists():
                            total_size += file_path.stat().st_size
                            # Extract size from path
                            if 'small' in entry['path']:
                                size_counts['small'] += 1
                            elif 'medium' in entry['path']:
                                size_counts['medium'] += 1
                            elif 'large' in entry['path']:
                                size_counts['large'] += 1
                    except:
                        pass

            return {
                'total_files': total_files,
                'total_size_mb': total_size / (1024 * 1024),
                'size_breakdown': size_counts,
                'max_cache_size_mb': self.max_cache_size_mb
            }

        except Exception as e:
            logger.error(f"Could not get cache stats: {e}")
            return {}

    def clear_cache(self):
        """Clear all cached thumbnails"""
        try:
            for entry in self.cache.values():
                if 'path' in entry:
                    try:
                        thumb_file = self.base_dir / entry['path']
                        if thumb_file.exists():
                            thumb_file.unlink()
                    except Exception as e:
                        logger.warning(f"Could not remove {entry['path']}: {e}")

            self.cache = {}
            self._save_cache()
            logger.info("Image cache cleared")

        except Exception as e:
            logger.error(f"Could not clear cache: {e}")


# Global cache instance
_cache_instance = None


def get_image_cache(base_dir: Path) -> ImageCache:
    """Get or create global image cache instance"""
    global _cache_instance
    if _cache_instance is None or _cache_instance.base_dir != base_dir:
        _cache_instance = ImageCache(base_dir)
    return _cache_instance