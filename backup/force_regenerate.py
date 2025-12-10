"""Force regenerate website with current code - no aiohttp dependency"""
import sys
from database import ArticleDatabase
from website_generator import WebsiteGenerator
from config import ARTICLE_CATEGORIES
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def enrich_articles_simple(articles):
    """Enrich articles with category info without full aggregator"""
    from datetime import datetime
    
    enriched = []
    for article in articles:
        # Detect/assign category if missing
        if not article.get("category"):
            # Simple category detection
            title_lower = (article.get("title", "") or "").lower()
            source_lower = (article.get("source", "") or "").lower()
            
            if "sport" in title_lower or "sport" in source_lower:
                article["category"] = "sports"
            elif "entertain" in title_lower or "fun" in source_lower:
                article["category"] = "entertainment"
            elif "local" in title_lower or "local" in source_lower:
                article["category"] = "local"
            elif "media" in source_lower or "tv" in source_lower:
                article["category"] = "media"
            else:
                article["category"] = "news"
        
        # Add category info
        category_info = ARTICLE_CATEGORIES.get(article["category"], ARTICLE_CATEGORIES["news"])
        article["category_name"] = category_info["name"]
        article["category_icon"] = category_info["icon"]
        article["category_color"] = category_info["color"]
        
        # Add formatted date
        pub_date = None
        published_str = article.get("published")
        
        if published_str:
            try:
                pub_str_clean = published_str.replace('Z', '+00:00').split('+')[0].split('.')[0]
                pub_date = datetime.fromisoformat(pub_str_clean)
            except:
                try:
                    pub_date = datetime.fromisoformat(published_str.split('T')[0])
                except:
                    pass
        
        if pub_date:
            article["formatted_date"] = pub_date.strftime("%B %d, %Y at %I:%M %p")
            article["date_sort"] = pub_date.isoformat()
        else:
            created_at_str = article.get("created_at") or article.get("ingested_at")
            if created_at_str:
                try:
                    pub_date = datetime.fromisoformat(created_at_str.replace('Z', '+00:00').split('+')[0])
                    article["formatted_date"] = pub_date.strftime("%B %d, %Y at %I:%M %p")
                except:
                    article["formatted_date"] = "Date N/A"
            else:
                article["formatted_date"] = "Date N/A"
        
        # Add source_display
        article["source_display"] = article.get("source", "Unknown Source")
        
        enriched.append(article)
    
    # Sort by published date
    enriched.sort(key=lambda x: x.get("published") or x.get("date_sort") or x.get("created_at") or "1900-01-01", reverse=True)
    
    return enriched

def main():
    logger.info("Starting forced website regeneration...")
    
    # Initialize components
    database = ArticleDatabase()
    website_generator = WebsiteGenerator()
    
    # Get articles from database
    logger.info("Fetching articles from database...")
    db_articles = database.get_all_articles(limit=500)
    logger.info(f"Retrieved {len(db_articles)} articles from database")
    
    # Enrich articles with category icons and metadata
    logger.info("Enriching articles with metadata...")
    enriched_articles = enrich_articles_simple(db_articles)
    logger.info(f"Enriched {len(enriched_articles)} articles")
    
    # Verify articles have category_icon
    missing_icons = [a for a in enriched_articles if not a.get('category_icon')]
    if missing_icons:
        logger.warning(f"{len(missing_icons)} articles missing category_icon")
    
    # Show sample
    logger.info("\nSample of enriched articles:")
    for article in enriched_articles[:3]:
        logger.info(f"  - {article.get('title', 'No title')[:50]}")
        logger.info(f"    Category: {article.get('category')} | Icon: {article.get('category_icon')} | Color: {article.get('category_color')}")
    
    # Generate website
    logger.info("\nGenerating website...")
    website_generator.generate(enriched_articles)
    logger.info("Website regenerated successfully!")

if __name__ == '__main__':
    main()
