"""
Show live aggregation with detailed output
"""
import sys
from aggregator import NewsAggregator
from website_generator import WebsiteGenerator
from datetime import datetime

def print_header(text):
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)

def print_section(text):
    print(f"\n{'─'*70}")
    print(f"  {text}")
    print(f"{'─'*70}")

def main():
    print_header("FALL RIVER NEWS AGGREGATOR - LIVE RUN")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Initialize components
    print_section("Initializing Components")
    aggregator = NewsAggregator()
    website_generator = WebsiteGenerator()
    
    # Run aggregation
    print_section("Starting Aggregation")
    articles = aggregator.aggregate()
    
    # Show results
    print_section("Aggregation Results")
    print(f"✓ Total articles collected: {len(articles)}")
    
    if articles:
        print(f"\n📰 Articles Found:")
        for i, article in enumerate(articles, 1):
            print(f"\n  {i}. {article.get('title', 'No title')}")
            print(f"     Source: {article.get('source', 'Unknown')}")
            print(f"     URL: {article.get('url', 'N/A')[:70]}...")
            print(f"     Hashtags: {', '.join(article.get('hashtags', [])[:3])}")
    
    # Generate website
    if articles:
        print_section("Generating Website")
        website_generator.generate(articles)
        print(f"✓ Website generated in 'website_output/' directory")
        print(f"  - index.html (main page)")
        print(f"  - {len(articles)} article pages")
        print(f"  - CSS and JavaScript files")
    
    print_section("Summary")
    print(f"✓ Aggregation complete")
    print(f"✓ {len(articles)} articles ready for distribution")
    print(f"✓ Website ready for deployment")
    print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_header("DONE")

if __name__ == "__main__":
    main()

