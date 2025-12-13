#!/usr/bin/env python3
import asyncio
import sys
sys.path.append('.')
from aggregator import NewsAggregator

async def test_integration():
    print("Testing CrimeRadar integration...")
    aggregator = NewsAggregator()

    try:
        # Test CrimeRadar specifically
        incidents = await aggregator.crime_radar_ingestor.fetch_articles_async()
        print(f"✅ CrimeRadar fetched {len(incidents)} incidents")

        if incidents:
            # Show sample without emojis
            incident = incidents[0]
            title_clean = incident['title'].encode('ascii', 'ignore').decode('ascii')
            print(f"Sample incident: {title_clean}")
            print(f"Type: {incident.get('incident_type', 'unknown')}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_integration())