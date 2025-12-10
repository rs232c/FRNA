"""Force reingest articles with fixed date parsing"""
import asyncio
import logging
from aggregator import NewsAggregator
from database import ArticleDatabase
from website_generator import WebsiteGenerator
from ingestors.weather_ingestor import WeatherIngestor
from cache import get_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("=" * 60)
    logger.info("Force Reingest with Fixed Date Parsing")
    logger.info("=" * 60)
    
    # Clear cache to force fresh fetch
    logger.info("Clearing cache...")
    cache = get_cache()
    cache.clear_all()
    logger.info("Cache cleared")
    
    # Initialize components
    aggregator = NewsAggregator()
    database = ArticleDatabase()
    website_generator = WebsiteGenerator()
    weather_ingestor = WeatherIngestor()
    
    # Force refresh - fetch all sources regardless of last fetch time
    logger.info("Fetching articles with force_refresh=True...")
    articles = await aggregator.aggregate_async(force_refresh=True)
    logger.info(f"Collected {len(articles)} articles")
    
    if articles:
        # Show sample dates
        logger.info("\nSample article dates:")
        for article in articles[:5]:
            logger.info(f"  - {article.get('title', 'N/A')[:50]}")
            logger.info(f"    Published: {article.get('published', 'N/A')}")
        
        # Save to database
        logger.info("\nSaving articles to database...")
        new_ids = database.save_articles(articles)
        logger.info(f"Saved {len(new_ids)} articles")
        
        # Get all articles from database and enrich
        logger.info("\nEnriching articles...")
        db_articles = database.get_all_articles(limit=500)
        enriched_articles = aggregator.enrich_articles(db_articles)
        logger.info(f"Enriched {len(enriched_articles)} articles")
        
        # Show sample enriched dates
        logger.info("\nSample enriched article dates:")
        for article in enriched_articles[:5]:
            logger.info(f"  - {article.get('title', 'N/A')[:50]}")
            logger.info(f"    Published: {article.get('published', 'N/A')}")
            logger.info(f"    Formatted: {article.get('formatted_date', 'N/A')}")
        
        # Generate website
        logger.info("\nGenerating website...")
        website_generator.generate(enriched_articles)
        logger.info("Website generated successfully")
        
        logger.info("\n" + "=" * 60)
        logger.info("Reingest complete!")
        logger.info(f"  Articles: {len(enriched_articles)}")
        logger.info("=" * 60)
    else:
        logger.warning("No articles collected")

if __name__ == '__main__':
    asyncio.run(main())

