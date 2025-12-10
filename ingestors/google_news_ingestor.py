"""
Google News RSS ingestor - fetches news from Google News RSS based on city/state
"""
import feedparser
from datetime import datetime
from typing import List, Dict
import logging
import urllib.parse
from ingestors.news_ingestor import NewsIngestor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GoogleNewsIngestor(NewsIngestor):
    """Ingestor for Google News RSS feeds"""
    
    def __init__(self, city: str, state: str, zip_code: str = None):
        """
        Initialize Google News ingestor
        
        Args:
            city: City name (e.g., "Fall River")
            state: State abbreviation (e.g., "MA")
            zip_code: Optional zip code for tagging articles
        """
        # Build RSS URL
        query = f"when:7d {city} {state}"
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        
        # Create a minimal source_config for compatibility with base class
        source_config = {
            "name": f"Google News ({city}, {state})",
            "url": f"https://news.google.com",
            "rss": rss_url,  # Set RSS URL for base class
            "category": "news",
            "enabled": True
        }
        super().__init__(source_config)
        self.city = city
        self.state = state
        self.zip_code = zip_code
        self._rss_url = rss_url
    
    def _build_rss_url(self) -> str:
        """Build Google News RSS URL for city/state"""
        # Google News RSS format: q=when:7d+{city}+{state}
        query = f"when:7d {self.city} {self.state}"
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        return rss_url
    
    async def fetch_articles_async(self) -> List[Dict]:
        """Fetch articles from Google News RSS"""
        articles = []
        
        if not self._rss_url:
            self._rss_url = self._build_rss_url()
        
        logger.info(f"Fetching Google News for {self.city}, {self.state}")
        
        try:
            # Use the base class RSS fetching method
            rss_articles = await self._fetch_from_rss_async()
            
            # Tag articles with zip_code if provided
            for article in rss_articles:
                article["source"] = f"Google News ({self.city}, {self.state})"
                if self.zip_code:
                    article["zip_code"] = self.zip_code
                # Google News articles typically don't have images in RSS
                # But we'll try to extract from content if available
                if not article.get("image_url"):
                    # Try to extract image from summary/content if available
                    summary = article.get("summary", "")
                    if summary and "<img" in summary:
                        # Basic image extraction from HTML summary
                        from bs4 import BeautifulSoup
                        try:
                            soup = BeautifulSoup(summary, 'html.parser')
                            img = soup.find('img')
                            if img and img.get('src'):
                                article["image_url"] = img['src']
                        except:
                            pass
            
            articles.extend(rss_articles)
            logger.info(f"Fetched {len(articles)} articles from Google News for {self.city}, {self.state}")
            
        except Exception as e:
            logger.error(f"Error fetching Google News for {self.city}, {self.state}: {e}")
        
        return articles
    
    async def _fetch_from_rss_async(self) -> List[Dict]:
        """Override to use our custom RSS URL"""
        articles = []
        rss_url = self._build_rss_url()
        source_name = self.source_config["name"]
        
        try:
            session = await self._get_aiohttp_session()
            async with session.get(rss_url) as response:
                if response.status == 200:
                    content = await response.text()
                    feed = feedparser.parse(content)
                    
                    for entry in feed.entries[:50]:  # Get up to 50 articles
                        # Parse published date
                        published_date = None
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            try:
                                published_date = datetime(*entry.published_parsed[:6]).isoformat()
                            except:
                                pass
                        
                        if not published_date and hasattr(entry, 'published'):
                            try:
                                # Try parsing the published string (simple format)
                                # Google News typically uses RFC 822 format
                                try:
                                    from dateutil import parser
                                    dt = parser.parse(entry.published)
                                    published_date = dt.isoformat()
                                except ImportError:
                                    # Fallback: try basic parsing
                                    published_date = datetime.now().isoformat()
                            except:
                                published_date = datetime.now().isoformat()
                        
                        if not published_date:
                            published_date = datetime.now().isoformat()
                        
                        # Get content
                        content_text = ""
                        if entry.get("content"):
                            if isinstance(entry.content, list) and len(entry.content) > 0:
                                content_text = entry.content[0].get("value", "")
                            elif isinstance(entry.content, str):
                                content_text = entry.content
                        
                        if not content_text:
                            content_text = entry.get("summary", "")
                        
                        article = {
                            "title": entry.get("title", ""),
                            "url": entry.get("link", ""),
                            "published": published_date,
                            "summary": entry.get("summary", ""),
                            "source": source_name,
                            "source_type": "news",
                            "content": content_text,
                            "ingested_at": datetime.now().isoformat(),
                            "category": "news"  # Default category
                        }
                        
                        # Add zip_code if available
                        if self.zip_code:
                            article["zip_code"] = self.zip_code
                        
                        articles.append(article)
                else:
                    logger.warning(f"Google News RSS returned status {response.status} for {self.city}, {self.state}")
        except Exception as e:
            logger.error(f"Error fetching Google News RSS: {e}")
        
        return articles

