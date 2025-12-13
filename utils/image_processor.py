"""
Image optimization utilities
Resize images and convert to WebP format
"""
import os
from pathlib import Path
from typing import Optional
import logging
import io
import requests

logger = logging.getLogger(__name__)

# Try to import PIL, make it optional
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL/Pillow not available. Image optimization will be disabled.")

# Max image dimensions
MAX_IMAGE_WIDTH = 1200
MAX_IMAGE_HEIGHT = 800
WEBP_QUALITY = 85

# Thumbnail sizes for different use cases
THUMBNAIL_SIZES = {
    'small': (200, 150),    # For trending sidebar, compact views
    'medium': (400, 300),   # For article grid, standard cards
    'large': (600, 400),    # For hero images, featured articles
}


def optimize_image(image_url: str, output_dir: Optional[Path] = None) -> Optional[str]:
    """
    Download, resize, and optimize an image
    Returns the path to the optimized image or original URL if optimization fails
    """
    if not PIL_AVAILABLE:
        logger.debug(f"PIL not available, skipping optimization for {image_url}")
        return image_url
    
    try:
        # Download image
        response = requests.get(image_url, timeout=10, stream=True)
        if response.status_code != 200:
            return image_url
        
        # Load image
        img = Image.open(io.BytesIO(response.content))
        
        # Convert RGBA to RGB if needed (for JPEG compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        
        # Resize if too large
        if img.width > MAX_IMAGE_WIDTH or img.height > MAX_IMAGE_HEIGHT:
            img.thumbnail((MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT), Image.Resampling.LANCZOS)
        
        # Generate output path
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            # Create hash-based filename
            import hashlib
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
            output_path = output_dir / f"{url_hash}.webp"
            
            # Save as WebP
            img.save(output_path, 'WEBP', quality=WEBP_QUALITY, optimize=True)
            logger.debug(f"Optimized image: {image_url} -> {output_path}")
            return str(output_path.relative_to(Path.cwd()))
        else:
            # Return original if no output dir specified
            return image_url
            
    except Exception as e:
        logger.warning(f"Could not optimize image {image_url}: {e}")
        return image_url


def should_optimize_image(image_url: str) -> bool:
    """Check if image should be optimized (not already optimized)"""
    # Skip if already a local file or data URI
    if image_url.startswith('/') or image_url.startswith('data:'):
        return False
    # Skip if already WebP
    if image_url.lower().endswith('.webp'):
        return False
    return True


def create_thumbnail(image_url: str, size_name: str, output_dir: Optional[Path] = None) -> Optional[str]:
    """
    Create a thumbnail of specified size for an image URL.

    Args:
        image_url: URL of the image to thumbnail
        size_name: Size name ('small', 'medium', 'large')
        output_dir: Directory to save thumbnail in

    Returns:
        Path to thumbnail file relative to output_dir, or None if failed
    """
    if not PIL_AVAILABLE:
        logger.debug(f"PIL not available, skipping thumbnail creation for {image_url}")
        return None

    if size_name not in THUMBNAIL_SIZES:
        logger.warning(f"Unknown thumbnail size: {size_name}")
        return None

    if not output_dir:
        logger.debug("No output directory specified for thumbnail")
        return None

    try:
        # Download image with timeout
        response = requests.get(image_url, timeout=15, stream=True, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        if response.status_code != 200:
            logger.debug(f"Failed to download image {image_url}: HTTP {response.status_code}")
            return None

        # Check content type
        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            logger.debug(f"URL does not contain an image: {image_url} (content-type: {content_type})")
            return None

        # Load image
        img = Image.open(io.BytesIO(response.content))

        # Convert to RGB if necessary (for JPEG compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background

        # Get target size
        target_size = THUMBNAIL_SIZES[size_name]

        # Create thumbnail (maintains aspect ratio)
        img.thumbnail(target_size, Image.Resampling.LANCZOS)

        # Generate filename using hash of original URL + size
        import hashlib
        url_hash = hashlib.md5(f"{image_url}_{size_name}".encode()).hexdigest()[:12]
        output_path = output_dir / f"{url_hash}.webp"

        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save as WebP with optimization
        img.save(output_path, 'WEBP', quality=80, optimize=True)

        # Return relative path from output_dir parent (to match website structure)
        return str(output_path.relative_to(output_dir.parent.parent))

    except Exception as e:
        logger.warning(f"Could not create {size_name} thumbnail for {image_url}: {e}")
        return None


def get_thumbnail_path(image_url: str, size_name: str, base_dir: Path) -> Optional[str]:
    """
    Get the cached thumbnail path for an image URL and size.
    Returns None if thumbnail doesn't exist.
    """
    if size_name not in THUMBNAIL_SIZES:
        return None

    import hashlib
    url_hash = hashlib.md5(f"{image_url}_{size_name}".encode()).hexdigest()[:12]
    thumb_path = base_dir / 'images' / 'thumbnails' / size_name / f"{url_hash}.webp"

    if thumb_path.exists():
        return str(thumb_path.relative_to(base_dir))

    return None

