"""
News ingestion module for scraping and parsing news articles
"""
import requests
from bs4 import BeautifulSoup
import feedparser
from datetime import datetime
from typing import List, Dict, Optional
import logging
from urllib.parse import urljoin, urlparse
import time
import asyncio
import aiohttp
from aiohttp import ClientTimeout
from cache import get_cache
from utils.retry import retry_async

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NewsIngestor:
    """Base class for news ingestion"""
    
    def __init__(self, source_config: Dict):
        self.source_config = source_config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self._aiohttp_session = None
        self._headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/rss+xml,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.google.com/',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        }
    
    def fetch_articles(self) -> List[Dict]:
        """Fetch articles from the news source (synchronous wrapper)
        
        Note: This method creates a new event loop. For better performance,
        use fetch_articles_async() directly if you're already in an async context.
        """
        try:
            return asyncio.run(self.fetch_articles_async())
        except RuntimeError as e:
            # If there's already a running event loop, this is a programming error
            # The aggregator should call fetch_articles_async() directly
            logger.error(f"Cannot run async method: {e}. Use fetch_articles_async() in async context.")
            raise
    
    async def fetch_articles_async(self) -> List[Dict]:
        """Fetch articles from the news source (async)"""
        articles = []
        
        try:
            if self.source_config.get("rss"):
                articles.extend(await self._fetch_from_rss_async())
            else:
                articles.extend(await self._fetch_from_web_async())
        finally:
            # Ensure session is closed after fetching
            await self._close_session()
        
        return articles
    
    async def _get_aiohttp_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._aiohttp_session is None or self._aiohttp_session.closed:
            timeout = ClientTimeout(total=30, connect=10)
            self._aiohttp_session = aiohttp.ClientSession(
                headers=self._headers,
                timeout=timeout
            )
        return self._aiohttp_session
    
    async def _close_session(self):
        """Close aiohttp session"""
        if self._aiohttp_session and not self._aiohttp_session.closed:
            await self._aiohttp_session.close()
    
    def _fetch_from_rss(self) -> List[Dict]:
        """Fetch articles from RSS feed (synchronous)
        
        Note: Use _fetch_from_rss_async() directly in async contexts.
        """
        try:
            return asyncio.run(self._fetch_from_rss_async())
        except RuntimeError as e:
            logger.error(f"Cannot run async method: {e}. Use _fetch_from_rss_async() in async context.")
            raise
    
    async def _fetch_from_rss_async(self) -> List[Dict]:
        """Fetch articles from RSS feed (async) with retry logic"""
        articles = []
        cache = get_cache()
        rss_url = self.source_config["rss"]
        source_name = self.source_config["name"]
        # Get source key from config (passed during setup)
        source_key = getattr(self, '_source_key', source_name.lower().replace(" ", "_"))
        
        # Check cache first
        cached_data = cache.get("rss", rss_url)
        if cached_data:
            logger.debug(f"Using cached RSS for {source_name}")
            return cached_data
        
        async def fetch_rss():
            logger.info(f"  → Fetching RSS feed: {rss_url}")
            session = await self._get_aiohttp_session()
            async with session.get(rss_url) as response:
                if response.status == 200:
                    content = await response.text()
                    feed = feedparser.parse(content)
                    logger.info(f"  ✓ Successfully fetched {len(feed.entries)} entries from {source_name} RSS")
                    # Fetch more entries to get past month of data
                    for entry in feed.entries[:50]:  # Get 50 entries to cover past month
                        # Use feedparser's parsed date tuple first (most reliable - feedparser already parsed it)
                        # published_parsed is a tuple: (year, month, day, hour, minute, second, weekday, yearday, dst)
                        published_date = None
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            try:
                                published_date = datetime(*entry.published_parsed[:6]).isoformat()
                            except:
                                published_date = None
                        elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                            try:
                                published_date = datetime(*entry.updated_parsed[:6]).isoformat()
                            except:
                                published_date = None
                        else:
                            # Fallback to parsing the string if parsed tuple not available
                            published_date_str = entry.get("published") or entry.get("pubDate") or entry.get("updated") or ""
                            published_date = self._parse_date(published_date_str) if published_date_str else None
                        
                        # Get content - prefer full content, fallback to summary
                        content_text = ""
                        if entry.get("content"):
                            # Try to get full content
                            if isinstance(entry.content, list) and len(entry.content) > 0:
                                content_text = entry.content[0].get("value", "")
                            elif isinstance(entry.content, str):
                                content_text = entry.content
                        
                        # If no content, use summary (but for Fall River Reporter, we'll scrape full content)
                        if not content_text:
                            content_text = entry.get("summary", "")
                        
                        # Extract image_url from RSS entry
                        image_url = None
                        # Try Media RSS (media:content or media:thumbnail)
                        if hasattr(entry, 'media_content') and entry.media_content:
                            for media in entry.media_content:
                                if media.get('type', '').startswith('image/'):
                                    image_url = media.get('url')
                                    break
                        # Try media:thumbnail
                        if not image_url and hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                            image_url = entry.media_thumbnail[0].get('url')
                        # Try enclosure (for images)
                        if not image_url and hasattr(entry, 'enclosures') and entry.enclosures:
                            for enc in entry.enclosures:
                                if enc.get('type', '').startswith('image/'):
                                    image_url = enc.get('href')
                                    break
                        # Try extracting from summary/content HTML
                        if not image_url:
                            html_content = entry.get("summary", "") or content_text
                            if html_content and "<img" in html_content:
                                try:
                                    soup = BeautifulSoup(html_content, 'html.parser')
                                    img = soup.find('img')
                                    if img and img.get('src'):
                                        image_url = img['src']
                                        # Make absolute URL if relative
                                        if image_url and not image_url.startswith(('http://', 'https://')):
                                            image_url = urljoin(entry.get("link", ""), image_url)
                                except:
                                    pass
                        
                        article = {
                            "title": entry.get("title", ""),
                            "url": entry.get("link", ""),
                            "published": published_date,  # Use actual publication date from feed, or None
                            "summary": entry.get("summary", ""),
                            "source": source_name,
                            "source_type": "news",
                            "content": content_text,
                            "image_url": image_url,  # Add image_url if found
                            "ingested_at": datetime.now().isoformat()
                        }
                        # #region agent log
                        try:
                            import json
                            import time
                            with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"G","location":"ingestors/news_ingestor.py:183","message":"RSS article extracted","data":{"title":(article.get('title') or '')[:50],"has_image_url":bool(image_url),"image_url":(image_url or '')[:80] if image_url else None,"source":source_name},"timestamp":int(time.time()*1000)})+'\n')
                        except: pass
                        # #endregion
                        articles.append(article)
                    return articles
                elif response.status == 403:
                    raise Exception(f"HTTP 403 Forbidden")
                else:
                    raise Exception(f"HTTP {response.status}")
        
        try:
            # Use retry logic with circuit breaker
            articles = await retry_async(
                fetch_rss,
                max_retries=1,  # 1 initial attempt + 1 retry = 2 total attempts
                initial_delay=1.0,
                exceptions=(aiohttp.ClientError, Exception),
                circuit_breaker_key=f"rss:{source_key}"
            )
            
            # Cache the results
            if articles:
                cache.set("rss", rss_url, articles)
        except Exception as e:
            logger.error(f"Error fetching RSS from {source_name}: {e}")
        
        return articles
    
    def _fetch_from_web(self) -> List[Dict]:
        """Scrape articles from website (synchronous)
        
        Note: Use _fetch_from_web_async() directly in async contexts.
        """
        try:
            return asyncio.run(self._fetch_from_web_async())
        except RuntimeError as e:
            logger.error(f"Cannot run async method: {e}. Use _fetch_from_web_async() in async context.")
            raise
    
    async def _fetch_from_web_async(self) -> List[Dict]:
        """Scrape articles from website (async)"""
        articles = []
        try:
            session = await self._get_aiohttp_session()
            async with session.get(self.source_config["url"]) as response:
                if response.status == 200:
                    content = await response.text()
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Common article selectors - may need customization per site
                    article_links = soup.find_all('a', href=True)
                    
                    # Collect URLs first, then fetch in parallel (with limit)
                    urls_to_fetch = []
                    for link in article_links[:100]:  # Increased to get more historical data
                        href = link.get('href', '')
                        if not href or href.startswith('#'):
                            continue
                        
                        # Make absolute URL
                        full_url = urljoin(self.source_config["url"], href)
                        
                        # Check if it looks like an article link
                        if self._is_article_link(full_url, link):
                            urls_to_fetch.append(full_url)
                    
                    # Fetch articles in parallel (limit concurrency)
                    semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
                    tasks = [self._scrape_article_async(url, semaphore) for url in urls_to_fetch[:30]]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for result in results:
                        if isinstance(result, dict) and result:
                            result["source"] = self.source_config["name"]
                            result["source_type"] = "news"
                            result["ingested_at"] = datetime.now().isoformat()
                            articles.append(result)
                        elif isinstance(result, Exception):
                            logger.debug(f"Error scraping article: {result}")
        
        except Exception as e:
            logger.error(f"Error scraping {self.source_config['name']}: {e}")
        
        return articles
    
    def _is_article_link(self, url: str, link_element) -> bool:
        """Determine if a link is likely an article"""
        # Check URL patterns
        article_patterns = ['/news/', '/article/', '/story/', '/2024/', '/2023/', '/2025/']
        if any(pattern in url.lower() for pattern in article_patterns):
            # Make sure it's not an external link or non-article page
            if 'heraldnews.com' in url or url.startswith('/'):
                return True
        
        # Check link text length (articles usually have longer titles)
        link_text = link_element.get_text(strip=True)
        if len(link_text) > 20 and not any(skip in url.lower() for skip in ['/tag/', '/author/', '/category/', '/page/']):
            return True
        
        return False
    
    def _scrape_article(self, url: str) -> Optional[Dict]:
        """Scrape individual article content (synchronous)
        
        Note: Use _scrape_article_async() directly in async contexts.
        """
        try:
            return asyncio.run(self._scrape_article_async(url))
        except RuntimeError as e:
            logger.error(f"Cannot run async method: {e}. Use _scrape_article_async() in async context.")
            raise
    
    async def _scrape_article_async(self, url: str, semaphore: Optional[asyncio.Semaphore] = None) -> Optional[Dict]:
        """Scrape individual article content (async)"""
        if semaphore:
            async with semaphore:
                return await self._do_scrape_article(url)
        else:
            return await self._do_scrape_article(url)
    
    async def _do_scrape_article(self, url: str) -> Optional[Dict]:
        """Internal async article scraping"""
        try:
            session = await self._get_aiohttp_session()
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                content = await response.text()
                soup = BeautifulSoup(content, 'html.parser')
            
                # Try to find title
                title = ""
                title_selectors = ['h1', '.article-title', '.headline', 'title']
                for selector in title_selectors:
                    title_elem = soup.select_one(selector)
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        break
                
                # Try to find article content
                content = ""
                content_selectors = [
                    'article', '.article-content', '.story-body', 
                    '.post-content', '[itemprop="articleBody"]'
                ]
                for selector in content_selectors:
                    content_elem = soup.select_one(selector)
                    if content_elem:
                        # Remove script and style elements
                        for script in content_elem(["script", "style"]):
                            script.decompose()
                        content = content_elem.get_text(separator=' ', strip=True)
                        break
                
                # Try to find publish date
                published = None
                date_selectors = [
                    'time[datetime]', '.published-date', '.date',
                    '[itemprop="datePublished"]'
                ]
                for selector in date_selectors:
                    date_elem = soup.select_one(selector)
                    if date_elem:
                        published = date_elem.get('datetime') or date_elem.get_text(strip=True)
                        break
                
                # Extract image_url from article page
                image_url = None
                # Try Open Graph image first (most reliable)
                og_image = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'og:image'})
                if og_image:
                    image_url = og_image.get('content')
                # Try Twitter card image
                if not image_url:
                    twitter_image = soup.find('meta', attrs={'name': 'twitter:image'}) or soup.find('meta', attrs={'property': 'twitter:image'})
                    if twitter_image:
                        image_url = twitter_image.get('content')
                # Try article image selectors
                if not image_url:
                    image_selectors = [
                        'article img', '.article-image img', '.story-image img',
                        '.featured-image img', '[itemprop="image"] img', '.hero-image img'
                    ]
                    for selector in image_selectors:
                        img_elem = soup.select_one(selector)
                        if img_elem and img_elem.get('src'):
                            image_url = img_elem.get('src')
                            break
                # Try first image in article content
                if not image_url and content_elem:
                    first_img = content_elem.find('img')
                    if first_img and first_img.get('src'):
                        image_url = first_img.get('src')
                # Make absolute URL if relative
                if image_url and not image_url.startswith(('http://', 'https://')):
                    image_url = urljoin(url, image_url)
                
                if title and len(content) > 100:  # Only return if we got meaningful content
                    # Parse published date if found, otherwise leave as None (don't use today's date)
                    parsed_published = self._parse_date(published) if published else None
                    return {
                        "title": title,
                        "url": url,
                        "published": parsed_published,  # None if no date found, not today's date
                        "summary": content[:500] + "..." if len(content) > 500 else content,
                        "content": content,
                        "image_url": image_url  # Add extracted image URL
                    }
        
        except Exception as e:
            logger.debug(f"Error scraping article {url}: {e}")
        
        return None
    
    def _parse_date(self, date_string: str) -> str:
        """Parse various date formats - returns None if parsing fails (don't default to today)"""
        if not date_string:
            return None  # Don't default to today - let it be None
        
        # First try ISO format (most common from feeds)
        try:
            # Handle ISO format with or without timezone
            date_str_clean = date_string.replace('Z', '+00:00').split('+')[0].split('.')[0]
            dt = datetime.fromisoformat(date_str_clean)
            return dt.isoformat()
        except:
            pass
        
        # Try feedparser's date parsing (handles RSS date formats)
        try:
            parsed = feedparser._parse_date(date_string)
            return datetime(*parsed[:6]).isoformat()
        except:
            pass
        
        # Try dateutil parser (handles many formats)
        try:
            from dateutil import parser
            return parser.parse(date_string).isoformat()
        except:
            pass
        
        # If all parsing fails, return None (don't default to today)
        return None


class HeraldNewsIngestor(NewsIngestor):
    """Specialized ingestor for Herald News"""
    
    async def _fetch_from_web_async(self) -> List[Dict]:
        """Custom scraping for Herald News (async)"""
        articles = []
        seen_urls = set()
        
        try:
            # Herald News uses /story/ URLs - scrape from homepage
            session = await self._get_aiohttp_session()
            async with session.get(self.source_config["url"]) as response:
                if response.status == 200:
                    content = await response.text()
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Find all links that match article patterns
                    all_links = soup.find_all('a', href=True)
                    
                    # Collect URLs first
                    urls_to_fetch = []
                    for link in all_links:
                        href = link.get('href', '')
                        if not href:
                            continue
                        
                        # Make absolute URL
                        if href.startswith('/'):
                            full_url = urljoin(self.source_config["url"], href)
                        elif 'heraldnews.com' in href:
                            full_url = href
                        else:
                            continue
                        
                        # Check if it's a story/article URL
                        if '/story/' in full_url.lower() and full_url not in seen_urls:
                            seen_urls.add(full_url)
                            urls_to_fetch.append(full_url)
                            
                            if len(urls_to_fetch) >= 30:  # Reasonable limit for scraping
                                break
                    
                    # Fetch articles in parallel
                    semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
                    tasks = [self._scrape_article_async(url, semaphore) for url in urls_to_fetch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for result in results:
                        if isinstance(result, dict) and result and len(result.get("content", "")) > 100:
                            result["source"] = self.source_config["name"]
                            result["source_type"] = "news"
                            result["ingested_at"] = datetime.now().isoformat()
                            articles.append(result)
        
        except Exception as e:
            logger.error(f"Error fetching from Herald News: {e}")
        
        return articles


class FallRiverReporterIngestor(NewsIngestor):
    """Specialized ingestor for Fall River Reporter"""
    
    async def fetch_articles_async(self) -> List[Dict]:
        """Fetch articles from Fall River Reporter - use RSS but scrape full content"""
        articles = []
        
        # First get articles from RSS (for URLs and metadata)
        rss_articles = await self._fetch_from_rss_async()
        
        # Then scrape full content for each article URL
        if rss_articles:
            logger.info(f"Found {len(rss_articles)} articles from RSS, fetching full content...")
            semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
            tasks = [self._scrape_article_async(article.get("url", ""), semaphore) for article in rss_articles if article.get("url")]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Merge RSS metadata with scraped content
            for i, (rss_article, scraped_result) in enumerate(zip(rss_articles, results)):
                if isinstance(scraped_result, dict) and scraped_result:
                    # Use scraped content if available, otherwise use RSS summary
                    final_article = {
                        "title": rss_article.get("title", scraped_result.get("title", "")),
                        "url": rss_article.get("url", ""),
                        "published": rss_article.get("published") or scraped_result.get("published"),
                        "summary": rss_article.get("summary", ""),
                        "source": self.source_config["name"],
                        "source_type": "news",
                        "content": scraped_result.get("content", rss_article.get("content", rss_article.get("summary", ""))),
                        "ingested_at": datetime.now().isoformat()
                    }
                    articles.append(final_article)
                else:
                    # If scraping failed, use RSS article as-is
                    articles.append(rss_article)
        
        return articles

