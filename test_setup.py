"""
Test script to verify Fall River News Aggregator setup
"""
import sys
import os

def test_imports():
    """Test if all required modules can be imported"""
    print("Testing imports...")
    try:
        import requests
        import bs4
        import feedparser
        import jinja2
        from dotenv import load_dotenv
        print("✓ All core dependencies imported successfully")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        print("  Run: pip install -r requirements.txt")
        return False

def test_config():
    """Test if config can be loaded"""
    print("\nTesting configuration...")
    try:
        from config import NEWS_SOURCES, LOCALE, LOCALE_HASHTAG
        print(f"✓ Configuration loaded")
        print(f"  Locale: {LOCALE}")
        print(f"  Hashtag: {LOCALE_HASHTAG}")
        print(f"  News sources: {len(NEWS_SOURCES)}")
        return True
    except Exception as e:
        print(f"✗ Config error: {e}")
        return False

def test_database():
    """Test database initialization"""
    print("\nTesting database...")
    try:
        from database import ArticleDatabase
        db = ArticleDatabase()
        print("✓ Database initialized successfully")
        return True
    except Exception as e:
        print(f"✗ Database error: {e}")
        return False

def test_ingestors():
    """Test ingestor initialization"""
    print("\nTesting ingestors...")
    try:
        from ingestors.news_ingestor import NewsIngestor
        from ingestors.facebook_ingestor import FacebookIngestor
        from config import NEWS_SOURCES
        
        # Test news ingestor
        if NEWS_SOURCES:
            first_source = list(NEWS_SOURCES.values())[0]
            ingestor = NewsIngestor(first_source)
            print("✓ News ingestor initialized")
        
        # Test Facebook ingestor
        fb_ingestor = FacebookIngestor()
        print("✓ Facebook ingestor initialized")
        return True
    except Exception as e:
        print(f"✗ Ingestor error: {e}")
        return False

def test_aggregator():
    """Test aggregator initialization"""
    print("\nTesting aggregator...")
    try:
        from aggregator import NewsAggregator
        agg = NewsAggregator()
        print("✓ Aggregator initialized successfully")
        return True
    except Exception as e:
        print(f"✗ Aggregator error: {e}")
        return False

def test_website_generator():
    """Test website generator"""
    print("\nTesting website generator...")
    try:
        from website_generator import WebsiteGenerator
        gen = WebsiteGenerator()
        print("✓ Website generator initialized successfully")
        return True
    except Exception as e:
        print(f"✗ Website generator error: {e}")
        return False

def test_social_poster():
    """Test social poster"""
    print("\nTesting social poster...")
    try:
        from social_poster import SocialPoster
        poster = SocialPoster()
        print("✓ Social poster initialized successfully")
        print(f"  Facebook enabled: {poster.facebook_enabled}")
        print(f"  Instagram enabled: {poster.instagram_enabled}")
        print(f"  TikTok enabled: {poster.tiktok_enabled}")
        return True
    except Exception as e:
        print(f"✗ Social poster error: {e}")
        return False

def check_env_file():
    """Check if .env file exists"""
    print("\nChecking environment file...")
    if os.path.exists(".env"):
        print("✓ .env file exists")
        return True
    else:
        print("⚠ .env file not found")
        print("  Create it from .env.example and add your API credentials")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Fall River News Aggregator - Setup Test")
    print("=" * 60)
    print()
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("Configuration", test_config()))
    results.append(("Database", test_database()))
    results.append(("Ingestors", test_ingestors()))
    results.append(("Aggregator", test_aggregator()))
    results.append(("Website Generator", test_website_generator()))
    results.append(("Social Poster", test_social_poster()))
    results.append(("Environment File", check_env_file()))
    
    print()
    print("=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {name}")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed! System is ready to use.")
        print("  Run: python main.py --once (to test)")
    else:
        print("\n⚠ Some tests failed. Please fix the issues above.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

