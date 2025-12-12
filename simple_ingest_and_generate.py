#!/usr/bin/env python3
"""
Simple ingestion + website generation script
"""
import asyncio
import logging
from aggregator import NewsAggregator
from database import ArticleDatabase
from website_generator import WebsiteGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting simple ingestion + generation...")

    # Create components
    aggregator = NewsAggregator()
    database = ArticleDatabase()
    generator = WebsiteGenerator()

    # Collect articles (force refresh)
    logger.info("Collecting articles...")
    articles = await aggregator.collect_all_articles_async(force_refresh=True)
    logger.info(f"Collected {len(articles)} articles")

    # Process and save articles
    if articles:
        logger.info("Processing articles...")
        # Filter and enrich
        filtered = aggregator.filter_relevant_articles(articles)
        enriched = aggregator.enrich_articles(filtered)

        logger.info("Saving to database...")
        database.save_articles(enriched)
        logger.info(f"Saved {len(enriched)} articles to database")

        # Generate website (skip meetings to avoid the bug)
        logger.info("Generating website...")
        try:
            generator.generate(enriched)
            logger.info("Website generated successfully!")
        except Exception as e:
            logger.error(f"Error generating website: {e}")
            logger.info("Continuing anyway...")

    logger.info("Complete!")

if __name__ == "__main__":
    asyncio.run(main())