"""
Test script to check news source URLs and accessibility
"""
import requests
from bs4 import BeautifulSoup
import feedparser
from config import NEWS_SOURCES

def test_rss_feed(url, name):
    """Test if RSS feed is accessible"""
    print(f"\n{'='*60}")
    print(f"Testing RSS Feed: {name}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    try:
        feed = feedparser.parse(url)
        print(f"✓ Feed accessible")
        print(f"  Feed title: {feed.feed.get('title', 'N/A')}")
        print(f"  Feed link: {feed.feed.get('link', 'N/A')}")
        print(f"  Number of entries: {len(feed.entries)}")
        
        if feed.entries:
            print(f"\n  First 3 entries:")
            for i, entry in enumerate(feed.entries[:3], 1):
                print(f"    {i}. {entry.get('title', 'No title')[:60]}")
                print(f"       Link: {entry.get('link', 'N/A')[:80]}")
        
        return True, len(feed.entries)
    except Exception as e:
        print(f"✗ Error accessing RSS feed: {e}")
        return False, 0

def test_website(url, name):
    """Test if website is accessible and find article links"""
    print(f"\n{'='*60}")
    print(f"Testing Website: {name}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        response = session.get(url, timeout=10)
        response.raise_for_status()
        print(f"✓ Website accessible (Status: {response.status_code})")
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for RSS feed links
        rss_links = soup.find_all('link', type='application/rss+xml')
        if rss_links:
            print(f"\n  Found RSS feed links:")
            for rss_link in rss_links:
                href = rss_link.get('href', '')
                title = rss_link.get('title', 'RSS Feed')
                print(f"    - {title}: {href}")
        
        # Look for article links
        article_links = soup.find_all('a', href=True)
        article_urls = []
        for link in article_links[:50]:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            if href and text and len(text) > 20:
                # Check if it looks like an article
                if any(pattern in href.lower() for pattern in ['/news/', '/article/', '/story/', '/2024/', '/2025/']):
                    article_urls.append((href, text[:60]))
        
        if article_urls:
            print(f"\n  Found {len(article_urls)} potential article links:")
            for href, text in article_urls[:10]:
                print(f"    - {text}")
                print(f"      {href[:80]}")
        else:
            print(f"\n  No obvious article links found")
            print(f"  Total links on page: {len(article_links)}")
        
        # Look for common article containers
        article_containers = soup.find_all(['article', 'div'], class_=lambda x: x and ('article' in str(x).lower() or 'story' in str(x).lower() or 'post' in str(x).lower()))
        print(f"\n  Found {len(article_containers)} potential article containers")
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Error accessing website: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def test_news_path(url, name):
    """Test /news path specifically"""
    news_url = url.rstrip('/') + '/news'
    print(f"\n{'='*60}")
    print(f"Testing /news path: {name}")
    print(f"URL: {news_url}")
    print(f"{'='*60}")
    
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        response = session.get(news_url, timeout=10)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            print(f"✓ /news path accessible")
            soup = BeautifulSoup(response.content, 'html.parser')
            article_containers = soup.find_all(['article', 'div'], class_=lambda x: x and ('article' in str(x).lower() or 'story' in str(x).lower()))
            print(f"  Found {len(article_containers)} potential article containers")
            return True
        else:
            print(f"✗ /news path returned status {response.status_code}")
            return False
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def main():
    print("="*60)
    print("News Source URL Testing")
    print("="*60)
    
    for source_key, source_config in NEWS_SOURCES.items():
        if not source_config.get("enabled", True):
            continue
        
        name = source_config["name"]
        base_url = source_config["url"]
        rss_url = source_config.get("rss")
        
        # Test RSS feed if available
        if rss_url:
            test_rss_feed(rss_url, name)
        else:
            print(f"\n{name}: No RSS feed configured")
        
        # Test main website
        test_website(base_url, name)
        
        # Test /news path
        test_news_path(base_url, name)
    
    print(f"\n{'='*60}")
    print("Testing Complete")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()

