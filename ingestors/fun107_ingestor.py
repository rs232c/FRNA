"""
Fun107 ingestion module
"""
import requests
from bs4 import BeautifulSoup
import feedparser
from datetime import datetime
from typing import List, Dict, Optional
import logging
from urllib.parse import urljoin
import time
import asyncio
import aiohttp
from ingestors.news_ingestor import NewsIngestor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Fun107Ingestor(NewsIngestor):
    """Specialized ingestor for Fun107"""
    
    async def fetch_articles_async(self) -> List[Dict]:
        """Fetch articles from Fun107 (async)"""
        articles = []
        
        # Try RSS first
        if self.source_config.get("rss"):
            try:
                rss_url = self.source_config["rss"]
                session = await self._get_aiohttp_session()
                async with session.get(rss_url) as response:
                    if response.status == 200:
                        content = await response.text()
                        feed = feedparser.parse(content)
                        for entry in feed.entries[:30]:
                            # Filter for Fall River content
                            title = entry.get("title", "")
                            summary = entry.get("summary", "")
                            content_text = entry.get("content", [{}])[0].get("value", "") if entry.get("content") else summary
                            
                            # Check if it mentions Fall River
                            combined = f"{title} {summary} {content_text}".lower()
                            if "fall river" in combined or "fallriver" in combined:
                                article = {
                                    "title": title,
                                    "url": entry.get("link", ""),
                                    "published": self._parse_date(entry.get("published", "")),
                                    "summary": summary[:500],
                                    "content": content_text,
                                    "source": self.source_config["name"],
                                    "source_type": "news",
                                    "category": "entertainment",  # Fun107 is entertainment
                                    "ingested_at": datetime.now().isoformat()
                                }
                                articles.append(article)
            except Exception as e:
                logger.error(f"Error fetching Fun107 RSS: {e}")
        
        # Also try web scraping
        try:
            session = await self._get_aiohttp_session()
            async with session.get(self.source_config["url"]) as response:
                if response.status == 200:
                    content = await response.text()
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Look for article links
                    article_links = soup.find_all('a', href=True)
                    seen_urls = set()
                    urls_to_fetch = []
                    
                    for link in article_links[:50]:
                        href = link.get('href', '')
                        text = link.get_text(strip=True)
                        
                        if not href or not text or len(text) < 20:
                            continue
                        
                        # Check if it's an article link
                        if any(pattern in href.lower() for pattern in ['/news/', '/article/', '/story/', '/2024/', '/2025/']):
                            full_url = urljoin(self.source_config["url"], href)
                            
                            if full_url not in seen_urls and "fall river" in (text + href).lower():
                                seen_urls.add(full_url)
                                urls_to_fetch.append(full_url)
                                
                                if len(urls_to_fetch) >= 20:
                                    break
                    
                    # Fetch articles in parallel
                    semaphore = asyncio.Semaphore(5)
                    tasks = [self._scrape_article_async(url, semaphore) for url in urls_to_fetch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for result in results:
                        if isinstance(result, dict) and result:
                            result["source"] = self.source_config["name"]
                            result["source_type"] = "news"
                            result["category"] = "entertainment"
                            result["ingested_at"] = datetime.now().isoformat()
                            articles.append(result)
        except Exception as e:
            logger.error(f"Error scraping Fun107: {e}")
        
        return articles



