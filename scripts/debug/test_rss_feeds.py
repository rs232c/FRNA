"""
Test RSS feed URLs to find working alternatives
"""
import sys
import feedparser
import requests
from typing import Dict, List, Tuple
import json
from config import NEWS_SOURCES

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def test_rss_url(url: str, timeout: int = 10) -> Tuple[bool, int, str]:
    """
    Test an RSS feed URL
    
    Returns:
        (is_valid, status_code, error_message)
    """
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
        status_code = response.status_code
        
        if status_code == 200:
            # Try to parse as RSS
            feed = feedparser.parse(response.content)
            if feed.bozo:
                return (False, status_code, f"Invalid RSS format: {feed.bozo_exception}")
            if len(feed.entries) == 0:
                return (False, status_code, "RSS feed has no entries")
            return (True, status_code, f"Valid RSS feed with {len(feed.entries)} entries")
        elif status_code == 403:
            return (False, status_code, "Forbidden - server blocking requests")
        elif status_code == 404:
            return (False, status_code, "Not Found - URL doesn't exist")
        else:
            return (False, status_code, f"HTTP {status_code}")
    except requests.exceptions.Timeout:
        return (False, 0, "Timeout")
    except requests.exceptions.ConnectionError:
        return (False, 0, "Connection error")
    except Exception as e:
        return (False, 0, str(e))

# Alternative URLs to test for each source
ALTERNATIVE_URLS = {
    "herald_news": [
        "https://www.heraldnews.com/feed/",
        "https://www.heraldnews.com/rss",
        "https://www.heraldnews.com/rss.xml",
    ],
    "herald_news_obituaries": [
        "https://www.heraldnews.com/obituaries/feed/",
        "https://www.heraldnews.com/feed/?section=obituaries",
    ],
    "taunton_gazette": [
        "https://www.tauntongazette.com/feed/",
        "https://www.tauntongazette.com/rss",
    ],
    "masslive": [
        "https://www.masslive.com/search/?q=Fall+River&f=rss",
        "https://www.masslive.com/feed/",
    ],
    "abc6": [
        "https://www.abc6.com/rss-feeds/",
        "https://www.abc6.com/feed/",
    ],
    "nbc10": [
        "https://turnto10.com/station/rss-feeds",
        "https://turnto10.com/feed/",
    ],
    "southcoast_today": [
        "https://www.southcoasttoday.com/feed/",
        "https://www.southcoasttoday.com/news/rss",
    ],
    "patch_fall_river": [
        "https://patch.com/massachusetts/fallriver/feed/",
        "https://fallriver.patch.com/rss.xml",
    ],
    "southcoast_funeral_service": [
        "https://www.southcoastchapel.com/feed/",
        "https://www.southcoastchapel.com/obituaries/feed/",
    ],
    "waring_sullivan": [
        "https://www.dignitymemorial.com/obituaries/massachusetts/fall-river-ma/rss",
    ],
    "oliveira_funeral_homes": [
        "https://www.oliveirafuneralhomes.com/feed/",
        "https://www.oliveirafuneralhomes.com/obituaries/feed/",
    ],
}

def main():
    print("=" * 80)
    print("RSS Feed Testing Script")
    print("=" * 80)
    print()
    
    results = {}
    
    for source_key, source_config in NEWS_SOURCES.items():
        if not source_config.get("enabled"):
            continue
        
        rss_url = source_config.get("rss")
        if not rss_url:
            continue
        
        source_name = source_config.get("name", source_key)
        print(f"Testing: {source_name}")
        print(f"  Current URL: {rss_url}")
        
        # Test current URL
        is_valid, status_code, message = test_rss_url(rss_url)
        results[source_key] = {
            "name": source_name,
            "current_url": rss_url,
            "current_status": status_code,
            "current_valid": is_valid,
            "current_message": message,
            "alternatives": []
        }
        
        if is_valid:
            print(f"  [OK] Current URL works! ({message})")
        else:
            print(f"  [FAIL] Current URL failed: {message}")
            
            # Test alternatives
            alternatives = ALTERNATIVE_URLS.get(source_key, [])
            if alternatives:
                print(f"  Testing {len(alternatives)} alternatives...")
                for alt_url in alternatives:
                    alt_valid, alt_status, alt_message = test_rss_url(alt_url)
                    results[source_key]["alternatives"].append({
                        "url": alt_url,
                        "status": alt_status,
                        "valid": alt_valid,
                        "message": alt_message
                    })
                    
                    if alt_valid:
                        print(f"    [OK] {alt_url} - {alt_message}")
                    else:
                        print(f"    [FAIL] {alt_url} - {alt_message}")
            else:
                print(f"  No alternatives configured")
        
        print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    working = [k for k, v in results.items() if v["current_valid"]]
    broken = [k for k, v in results.items() if not v["current_valid"]]
    has_working_alt = [k for k, v in results.items() if not v["current_valid"] and any(alt["valid"] for alt in v["alternatives"])]
    
    print(f"Working feeds: {len(working)}/{len(results)}")
    print(f"Broken feeds: {len(broken)}/{len(results)}")
    print(f"Broken feeds with working alternatives: {len(has_working_alt)}")
    print()
    
    if broken:
        print("BROKEN FEEDS:")
        for source_key in broken:
            result = results[source_key]
            print(f"  - {result['name']}: {result['current_message']}")
            if result['alternatives']:
                working_alts = [alt for alt in result['alternatives'] if alt['valid']]
                if working_alts:
                    print(f"    → Working alternative: {working_alts[0]['url']}")
        print()
    
    # Save results to JSON
    with open("rss_test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Results saved to rss_test_results.json")

if __name__ == "__main__":
    main()

