"""Force refresh both news and meetings"""
import asyncio
import logging
from cache import get_cache
from aggregator import NewsAggregator
from database import ArticleDatabase
from website_generator import WebsiteGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("=" * 60)
    logger.info("Force Refresh: News & Meetings")
    logger.info("=" * 60)
    
    # Clear relevant caches
    cache = get_cache()
    logger.info("Clearing news and meetings caches...")
    cache.invalidate("rss")  # Clear RSS feed cache
    cache.invalidate("scraped")  # Clear scraped content cache
    cache.invalidate("meetings", "fall_river")  # Clear meetings cache
    cache.invalidate("agendas", "agenda_urls:fall_river")  # Clear agenda URLs cache
    cache.invalidate("agendas", "agenda_pdfs:fall_river")  # Clear agenda PDFs cache
    logger.info("✓ Caches cleared")
    
    # Force refresh news
    logger.info("\nFetching fresh news articles...")
    aggregator = NewsAggregator()
    articles = await aggregator.aggregate_async(force_refresh=True)
    logger.info(f"✓ Collected {len(articles)} articles")
    
    # Save articles
    if articles:
        logger.info("\nSaving articles to database...")
        database = ArticleDatabase()
        database.save_articles(articles)
        logger.info("✓ Articles saved")
    
    # Get all articles for website generation
    logger.info("\nRetrieving articles from database...")
    database = ArticleDatabase()
    db_articles = database.get_all_articles(limit=500)
    enriched_articles = aggregator.enrich_articles(db_articles)
    logger.info(f"✓ Retrieved {len(enriched_articles)} articles")
    
    # Generate website (this will fetch fresh meetings)
    logger.info("\nGenerating website (fetching fresh meetings)...")
    generator = WebsiteGenerator()
    generator.generate(enriched_articles)
    logger.info("✓ Website generated")
    
    logger.info("\n" + "=" * 60)
    logger.info("Force refresh complete!")
    logger.info("=" * 60)

if __name__ == '__main__':
    asyncio.run(main())

