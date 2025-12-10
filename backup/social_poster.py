"""
Social media posting module for Facebook, Instagram, and TikTok
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime
from config import (
    FACEBOOK_CONFIG, INSTAGRAM_CONFIG, TIKTOK_CONFIG,
    LOCALE_HASHTAG, HASHTAGS, POSTING_SCHEDULE
)
from database import ArticleDatabase
import requests

try:
    from facebook import GraphAPI
    FACEBOOK_SDK_AVAILABLE = True
except ImportError:
    FACEBOOK_SDK_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SocialPoster:
    """Handle posting to various social media platforms"""
    
    def __init__(self):
        self.facebook_enabled = bool(FACEBOOK_CONFIG.get("page_access_token"))
        self.instagram_enabled = INSTAGRAM_CONFIG.get("enabled", False) and bool(INSTAGRAM_CONFIG.get("username"))
        self.tiktok_enabled = TIKTOK_CONFIG.get("enabled", False) and bool(TIKTOK_CONFIG.get("access_token"))
        self.database = ArticleDatabase()
    
    def format_post_content(self, article: Dict, platform: str) -> str:
        """Format article content for social media post"""
        title = article.get("title", "")
        summary = article.get("summary", "")
        url = article.get("url", "")
        hashtags = " ".join(article.get("hashtags", [])[:5])  # Limit hashtags
        
        # Platform-specific formatting
        if platform == "facebook":
            # Facebook allows longer posts
            content = f"{title}\n\n{summary[:300]}...\n\nRead more: {url}\n\n{hashtags}"
        elif platform == "instagram":
            # Instagram caption format
            content = f"{title}\n\n{summary[:200]}...\n\n{hashtags}\n\nLink in bio: {url}"
        elif platform == "tiktok":
            # TikTok description format
            content = f"{title} {hashtags}\n\nFull story: {url}"
        else:
            content = f"{title}\n\n{summary}\n\n{url}\n\n{hashtags}"
        
        return content
    
    def post_to_facebook(self, article: Dict) -> bool:
        """Post article to Facebook page"""
        if not self.facebook_enabled:
            logger.warning("Facebook posting not enabled or configured")
            return False
        
        if not FACEBOOK_SDK_AVAILABLE:
            logger.warning("facebook-sdk not installed. Install with: pip install facebook-sdk")
            return False
        
        try:
            graph = GraphAPI(access_token=FACEBOOK_CONFIG["page_access_token"])
            
            message = self.format_post_content(article, "facebook")
            
            # Prepare post data
            post_data = {
                "message": message
            }
            
            # Add link if available
            if article.get("url"):
                post_data["link"] = article["url"]
            
            # Add image if available
            if article.get("image_url"):
                post_data["picture"] = article["image_url"]
            
            # Post to page
            page_id = FACEBOOK_CONFIG.get("page_id")
            response = graph.put_object(
                parent_object=page_id,
                connection_name='feed',
                **post_data
            )
            
            logger.info(f"Posted to Facebook: {article.get('title', '')[:50]}...")
            # Mark as posted in database if article has ID
            if article.get("id"):
                self.database.mark_as_posted(article["id"], "facebook", True)
            return True
        
        except Exception as e:
            logger.error(f"Error posting to Facebook: {e}")
            return False
    
    def post_to_instagram(self, article: Dict) -> bool:
        """Post article to Instagram"""
        if not self.instagram_enabled:
            logger.warning("Instagram posting not enabled or configured")
            return False
        
        try:
            try:
                from instagrapi import Client
            except ImportError:
                logger.warning("instagrapi not installed. Install with: pip install instagrapi")
                return False
            
            cl = Client()
            cl.login(INSTAGRAM_CONFIG["username"], INSTAGRAM_CONFIG["password"])
            
            caption = self.format_post_content(article, "instagram")
            
            # Instagram requires an image
            image_url = article.get("image_url")
            if not image_url:
                logger.warning("Instagram post skipped - no image available")
                return False
            
            # Download image
            import requests
            from io import BytesIO
            from PIL import Image
            
            img_response = requests.get(image_url)
            img = Image.open(BytesIO(img_response.content))
            
            # Save temporarily
            temp_path = "temp_instagram_image.jpg"
            img.save(temp_path)
            
            # Upload to Instagram
            cl.photo_upload(
                path=temp_path,
                caption=caption
            )
            
            # Clean up
            import os
            os.remove(temp_path)
            
            logger.info(f"Posted to Instagram: {article.get('title', '')[:50]}...")
            # Mark as posted in database if article has ID
            if article.get("id"):
                self.database.mark_as_posted(article["id"], "instagram", True)
            return True
        
        except Exception as e:
            logger.error(f"Error posting to Instagram: {e}")
            return False
    
    def post_to_tiktok(self, article: Dict) -> bool:
        """Post article to TikTok (Note: Requires TikTok Business API)"""
        if not self.tiktok_enabled:
            logger.warning("TikTok posting not enabled or configured")
            return False
        
        try:
            # TikTok API requires video content, not just text
            # This is a placeholder - actual implementation would need video creation
            logger.warning("TikTok posting requires video content. Text-only posts not supported via API.")
            return False
        
        except Exception as e:
            logger.error(f"Error posting to TikTok: {e}")
            return False
    
    def post_to_all_platforms(self, article: Dict) -> Dict[str, bool]:
        """Post article to all enabled platforms"""
        results = {
            "facebook": False,
            "instagram": False,
            "tiktok": False
        }
        
        if self.facebook_enabled:
            results["facebook"] = self.post_to_facebook(article)
        
        if self.instagram_enabled:
            results["instagram"] = self.post_to_instagram(article)
        
        if self.tiktok_enabled:
            results["tiktok"] = self.post_to_tiktok(article)
        
        return results
    
    def post_articles(self, articles: List[Dict], max_posts: Optional[int] = None) -> Dict:
        """Post multiple articles to social media"""
        if max_posts is None:
            max_posts = POSTING_SCHEDULE.get("max_posts_per_day", 10)
        
        results = {
            "total": len(articles[:max_posts]),
            "posted": 0,
            "failed": 0,
            "platform_results": {
                "facebook": {"success": 0, "failed": 0},
                "instagram": {"success": 0, "failed": 0},
                "tiktok": {"success": 0, "failed": 0}
            }
        }
        
        for article in articles[:max_posts]:
            # Check if already posted (by URL)
            article_url = article.get("url", "")
            if not article_url:
                continue
            
            platform_results = {}
            
            # Check each platform
            if self.facebook_enabled and not self.database.is_posted(article_url, "facebook"):
                platform_results["facebook"] = self.post_to_facebook(article)
            else:
                platform_results["facebook"] = False
            
            if self.instagram_enabled and not self.database.is_posted(article_url, "instagram"):
                platform_results["instagram"] = self.post_to_instagram(article)
            else:
                platform_results["instagram"] = False
            
            if self.tiktok_enabled and not self.database.is_posted(article_url, "tiktok"):
                platform_results["tiktok"] = self.post_to_tiktok(article)
            else:
                platform_results["tiktok"] = False
            
            for platform, success in platform_results.items():
                if success:
                    results["platform_results"][platform]["success"] += 1
                    results["posted"] += 1
                else:
                    if platform_results.get(platform) is not False:  # Only count as failed if we tried
                        results["platform_results"][platform]["failed"] += 1
                        results["failed"] += 1
        
        return results

