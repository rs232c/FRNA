#!/usr/bin/env python3
"""
CrimeRadar ingestor for Fall River incident reports
Scrapes real-time dispatch alerts and safety statistics
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from ingestors.news_ingestor import NewsIngestor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CrimeRadarIngestor(NewsIngestor):
    """Ingestor for CrimeRadar Fall River incident reports"""

    def __init__(self, source_config: Dict):
        super().__init__(source_config)
        self.base_url = "https://www.crimeradar.us/fall-river-ma"
        self.source_name = "CrimeRadar Fall River"
        self.source_type = "scanner"

    async def fetch_articles_async(self) -> List[Dict]:
        """Fetch incident reports from CrimeRadar"""
        articles = []

        try:
            session = await self._get_aiohttp_session()
            async with session.get(self.base_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    html = await response.text()
                    incidents = self._parse_incidents(html)

                    for incident in incidents:
                        # Convert to article format
                        article = {
                            "title": incident["title"],
                            "url": self.base_url,  # Link to main page since individual incidents don't have URLs
                            "published": incident["published"],
                            "summary": incident["description"],
                            "content": incident["full_description"],
                            "source": self.source_name,
                            "source_type": self.source_type,
                            "image_url": None,
                            "ingested_at": datetime.now().isoformat(),
                            "category": "scanner",
                            "incident_type": incident["type"],
                            "location": incident["location"]
                        }
                        articles.append(article)

                    logger.info(f"✅ Fetched {len(articles)} incidents from CrimeRadar")
                else:
                    logger.warning(f"❌ CrimeRadar request failed with status {response.status}")

        except Exception as e:
            logger.error(f"❌ Error fetching CrimeRadar incidents: {e}")
        finally:
            await self._close_session()

        return articles[:50]  # Limit to 50 most recent incidents

    def _parse_incidents(self, html: str) -> List[Dict]:
        """Parse incident reports from CrimeRadar HTML"""
        incidents = []

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Look for h3 elements that contain incident titles
            incident_headers = soup.find_all('h3', class_=['font-semibold', 'text-xl', 'mb-4', 'block', 'hover:underline'])

            for header in incident_headers:
                try:
                    title_text = header.get_text().strip()

                    # Skip if this doesn't look like an incident
                    if not any(keyword in title_text.lower() for keyword in [
                        'medical', 'emergency', 'fire', 'police', 'traffic', 'accident',
                        'vandalism', 'burglary', 'alarm', 'suspicious', 'investigation'
                    ]):
                        continue

                    # Look for the parent container that might have more details
                    container = header.parent
                    if container:
                        # Look for incident type (might be in a span or nearby element)
                        incident_type_elem = container.find('span', string=re.compile(r'Medical Emergency|Fire|Police|Traffic|Vandalism|Burglary', re.IGNORECASE))
                        incident_type = 'other'
                        if incident_type_elem:
                            type_text = incident_type_elem.get_text().strip()
                            incident_type = self._classify_incident(type_text)

                        # Look for timestamp and location in the container
                        container_text = container.get_text()

                        # Extract timestamp
                        timestamp_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+(?:AM|PM))', container_text)
                        timestamp_str = timestamp_match.group(1) if timestamp_match else None

                        published = None
                        if timestamp_str:
                            published = self._parse_timestamp(timestamp_str)

                        # For location, look for address patterns
                        location_match = re.search(r'([A-Za-z\s]+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Ct|Court|Pl|Place|Way|Terrace|Circle|Sq|Square|Pkwy|Parkway| Hwy|Highway)(?:,?\s*[A-Za-z\s,]+)?)', container_text)
                        location = location_match.group(1).strip() if location_match else "Fall River, MA"

                        # Create the incident entry
                        incidents.append({
                            "title": self._create_incident_title(title_text, incident_type),
                            "description": title_text,
                            "full_description": container_text,
                            "published": published.isoformat() if published else datetime.now().isoformat(),
                            "type": incident_type,
                            "location": location,
                            "timestamp": timestamp_str or "Unknown"
                        })

                except Exception as e:
                    logger.debug(f"Error parsing incident header {header}: {e}")
                    continue

            # Alternative approach: parse from the raw text content if HTML parsing fails
            if not incidents:
                logger.info("No incidents found via HTML parsing, trying text parsing...")
                text_content = soup.get_text()

                # Look for incident blocks in the text
                # Pattern: "Description...Incident Type...Date Time...Location"
                incident_blocks = re.findall(
                    r'([A-Z][^.!?]*?(?:medical|emergency|fire|police|traffic|accident|vandalism|burglary|alarm|suspicious|investigation)[^.!?]*?)(?:Incident Type:\s*([^.!?]*?))?(?:(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+(?:AM|PM)))([^.!?\n]*?)(?:\n|$)',
                    text_content,
                    re.IGNORECASE | re.MULTILINE
                )

                for block in incident_blocks[:20]:  # Limit to first 20
                    try:
                        description = block[0].strip()
                        incident_type_text = block[1].strip() if block[1] else ""
                        timestamp_str = block[2].strip()
                        location = block[3].strip() or "Fall River, MA"

                        # Parse timestamp
                        published = self._parse_timestamp(timestamp_str)
                        if not published:
                            continue

                        # Determine incident type
                        incident_type = self._classify_incident(incident_type_text or description)

                        incidents.append({
                            "title": self._create_incident_title(description, incident_type),
                            "description": description,
                            "full_description": f"{description} - {location}",
                            "published": published.isoformat(),
                            "type": incident_type,
                            "location": location,
                            "timestamp": timestamp_str
                        })

                    except Exception as e:
                        logger.debug(f"Error parsing incident block {block}: {e}")
                        continue

            # Remove duplicates
            unique_incidents = []
            seen = set()
            for incident in incidents:
                key = f"{incident['description']}_{incident['timestamp']}"
                if key not in seen:
                    unique_incidents.append(incident)
                    seen.add(key)

            logger.info(f"Parsed {len(unique_incidents)} unique incidents from CrimeRadar")

        except Exception as e:
            logger.error(f"Error parsing CrimeRadar HTML: {e}")

        return unique_incidents[:50]

    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """Parse timestamp from CrimeRadar format like '12/13/2025 08:20 AM'"""
        try:
            # CrimeRadar uses MM/DD/YYYY HH:MM AM/PM format
            dt = datetime.strptime(timestamp_str, '%m/%d/%Y %I:%M %p')
            return dt
        except ValueError:
            try:
                # Fallback: try without seconds
                dt = datetime.strptime(timestamp_str, '%m/%d/%Y %I:%M %p')
                return dt
            except ValueError:
                logger.warning(f"Could not parse timestamp: {timestamp_str}")
                return None

    def _classify_incident(self, description: str) -> str:
        """Classify incident type based on description keywords"""
        desc_lower = description.lower()

        # Emergency medical
        if any(word in desc_lower for word in ['medical emergency', 'patient', 'discomfort', 'suicide', 'overdose']):
            return 'medical'

        # Fire/rescue
        elif any(word in desc_lower for word in ['fire', 'smoke', 'alarm', 'rescue', 'arson']):
            return 'fire'

        # Police/law enforcement
        elif any(word in desc_lower for word in ['police', 'suspicious', 'burglary', 'theft', 'assault', 'domestic', 'warrant', 'arrest']):
            return 'police'

        # Traffic/accidents
        elif any(word in desc_lower for word in ['traffic', 'accident', 'collision', 'vehicle', 'crash', 'wreck']):
            return 'traffic'

        # Vandalism/property
        elif any(word in desc_lower for word in ['vandalism', 'damage', 'break-in', 'trespass']):
            return 'vandalism'

        # Family/disputes
        elif any(word in desc_lower for word in ['dispute', 'domestic', 'family', 'restraining', 'order']):
            return 'family'

        # General disturbance
        elif any(word in desc_lower for word in ['disturbance', 'noise', 'complaint', 'harass']):
            return 'disorderly'

        # Investigation
        elif any(word in desc_lower for word in ['investigation', 'odor', 'gas', 'unknown']):
            return 'investigation'

        else:
            return 'other'

    def _create_incident_title(self, description: str, incident_type: str) -> str:
        """Create a concise title for the incident"""
        # Clean up the description and make it title case
        title = description.strip()

        # Remove common prefixes that make titles too long
        prefixes_to_remove = [
            'investigation of', 'possible', 'reported', 'call for', 'check on',
            'complaint of', 'report of', 'suspicious', 'unknown'
        ]

        title_lower = title.lower()
        for prefix in prefixes_to_remove:
            if title_lower.startswith(prefix):
                title = title[len(prefix):].strip()
                break

        # Capitalize properly
        if title:
            title = title[0].upper() + title[1:]

        # Limit length
        if len(title) > 80:
            title = title[:77] + "..."

        # Add incident type prefix for clarity
        type_prefixes = {
            'medical': '🚑',
            'fire': '🔥',
            'police': '🚔',
            'traffic': '🚗',
            'vandalism': '💥',
            'family': '👨‍👩‍👧‍👦',
            'disorderly': '📢',
            'investigation': '🔍',
            'other': '📋'
        }

        prefix = type_prefixes.get(incident_type, '📋')
        return f"{prefix} {title}"

    async def fetch_articles(self) -> List[Dict]:
        """Synchronous wrapper for async method"""
        return await self.fetch_articles_async()