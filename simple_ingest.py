#!/usr/bin/env python3
"""
Simple ingestion script - just fetches articles without website generation
"""
import asyncio
import logging
from aggregator import NewsAggregator
from database import ArticleDatabase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting simple ingestion...")

    # Create aggregator
    aggregator = NewsAggregator()

    # Collect articles
    logger.info("Collecting articles...")
    articles = await aggregator.collect_all_articles_async()

    logger.info(f"Collected {len(articles)} articles")

    # Save to database
    if articles:
        logger.info("Saving to database...")
        db = ArticleDatabase()
        db.save_articles(articles)
        logger.info("Articles saved!")

    logger.info("Simple ingestion complete!")

if __name__ == "__main__":
    asyncio.run(main())