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

