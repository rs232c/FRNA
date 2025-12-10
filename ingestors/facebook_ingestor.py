"""
Facebook ingestion module for fetching posts from city pages and local columnists
"""
import requests
import logging
from datetime import datetime
from typing import List, Dict, Optional
import os
from config import FACEBOOK_CONFIG

try:
    from facebook import GraphAPI
    FACEBOOK_AVAILABLE = True
except ImportError:
    FACEBOOK_AVAILABLE = False
    logging.warning("facebook-sdk not installed. Facebook ingestion will be limited.")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FacebookIngestor:
    """Ingest posts from Facebook pages"""
    
    def __init__(self):
        self.access_token = FACEBOOK_CONFIG.get("page_access_token") or FACEBOOK_CONFIG.get("city_page_token")
        if self.access_token and FACEBOOK_AVAILABLE:
            self.graph = GraphAPI(access_token=self.access_token)
        else:
            self.graph = None
            if not FACEBOOK_AVAILABLE:
                logger.warning("facebook-sdk not installed. Install with: pip install facebook-sdk")
            elif not self.access_token:
                logger.warning("No Facebook access token provided. Facebook ingestion will be limited.")
    
    def fetch_city_posts(self, limit: int = 25) -> List[Dict]:
        """Fetch posts from the city's Facebook page"""
        posts = []
        
        page_id = FACEBOOK_CONFIG.get("city_page") or FACEBOOK_CONFIG.get("page_id")
        if not page_id:
            logger.error("No Facebook page ID configured")
            return posts
        
        try:
            if self.graph:
                # Use Graph API
                feed = self.graph.get_connections(
                    id=page_id,
                    connection_name='posts',
                    fields='id,message,created_time,link,full_picture,permalink_url',
                    limit=limit
                )
                
                for post in feed.get('data', []):
                    posts.append({
                        "title": post.get("message", "")[:200] or "Facebook Post",
                        "url": post.get("permalink_url", post.get("link", "")),
                        "published": post.get("created_time", datetime.now().isoformat()),
                        "summary": post.get("message", "")[:500],
                        "content": post.get("message", ""),
                        "source": "City of Fall River (Facebook)",
                        "source_type": "social_media",
                        "image_url": post.get("full_picture"),
                        "post_id": post.get("id"),
                        "ingested_at": datetime.now().isoformat()
                    })
            else:
                # Fallback: web scraping (less reliable, may violate ToS)
                logger.warning("Using web scraping fallback for Facebook (not recommended)")
                posts.extend(self._scrape_facebook_page(page_id, limit))
        
        except Exception as e:
            logger.error(f"Error fetching city Facebook posts: {e}")
        
        return posts
    
    def fetch_columnist_posts(self, limit_per_columnist: int = 10) -> List[Dict]:
        """Fetch posts from local columnists' Facebook pages"""
        all_posts = []
        
        columnist_ids = FACEBOOK_CONFIG.get("local_columnists", [])
        if not columnist_ids:
            logger.warning("No local columnist Facebook IDs configured")
            return all_posts
        
        for columnist_id in columnist_ids:
            if not columnist_id:
                continue
            
            try:
                if self.graph:
                    feed = self.graph.get_connections(
                        id=columnist_id,
                        connection_name='posts',
                        fields='id,message,created_time,link,full_picture,permalink_url',
                        limit=limit_per_columnist
                    )
                    
                    for post in feed.get('data', []):
                        # Filter for relevant content
                        message = post.get("message", "")
                        if self._is_relevant_post(message):
                            all_posts.append({
                                "title": message[:200] or "Columnist Post",
                                "url": post.get("permalink_url", post.get("link", "")),
                                "published": post.get("created_time", datetime.now().isoformat()),
                                "summary": message[:500],
                                "content": message,
                                "source": f"Local Columnist (Facebook)",
                                "source_type": "social_media",
                                "image_url": post.get("full_picture"),
                                "post_id": post.get("id"),
                                "ingested_at": datetime.now().isoformat()
                            })
                else:
                    logger.warning(f"Cannot fetch posts from columnist {columnist_id} without access token")
            
            except Exception as e:
                logger.error(f"Error fetching posts from columnist {columnist_id}: {e}")
        
        return all_posts
    
    def _is_relevant_post(self, message: str) -> bool:
        """Check if a post is relevant to Fall River"""
        if not message:
            return False
        
        message_lower = message.lower()
        relevant_keywords = [
            "fall river",
            "fall river, ma",
            "fall river, massachusetts",
            "local",
            "community"
        ]
        
        return any(keyword in message_lower for keyword in relevant_keywords)
    
    def _scrape_facebook_page(self, page_id: str, limit: int) -> List[Dict]:
        """Fallback web scraping method (use with caution - may violate ToS)"""
        posts = []
        # Note: Facebook's HTML structure changes frequently
        # This is a placeholder - actual implementation would need Selenium
        # and careful handling of Facebook's dynamic content
        logger.warning("Web scraping Facebook is not implemented. Please use Graph API.")
        return posts
    
    def fetch_all_facebook_content(self) -> List[Dict]:
        """Fetch all Facebook content (city + columnists)"""
        all_content = []
        
        # Fetch city posts
        city_posts = self.fetch_city_posts()
        all_content.extend(city_posts)
        
        # Fetch columnist posts
        columnist_posts = self.fetch_columnist_posts()
        all_content.extend(columnist_posts)
        
        return all_content

