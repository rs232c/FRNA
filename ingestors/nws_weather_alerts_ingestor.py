"""
National Weather Service Weather Alerts Ingestor
Pulls official weather alerts from forecast.weather.gov for Fall River area
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from ingestors.news_ingestor import NewsIngestor

logger = logging.getLogger(__name__)


class NWSWeatherAlertsIngestor(NewsIngestor):
    """Ingests official weather alerts from National Weather Service"""

    def __init__(self, source_config: Dict):
        super().__init__(source_config)
        # Try the alerts page instead of forecast page
        self.nws_url = "https://forecast.weather.gov/MapClick.php?lat=41.7199586&lon=-71.139299"
        self.alerts_url = "https://alerts.weather.gov/cap/us.php?x=1"  # National alerts page
        self.source_name = "National Weather Service"
        self.source_type = "weather_alert"

    async def fetch_articles_async(self) -> List[Dict]:
        """Fetch current weather alerts from NWS"""
        articles = []

        try:
            session = await self._get_aiohttp_session()
            async with session.get(self.nws_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    html = await response.text()
                    alerts = self._parse_weather_alerts(html)

                    for alert in alerts:
                        articles.append({
                            "title": alert["title"],
                            "url": self.nws_url,
                            "published": alert["published"],
                            "summary": alert["description"],
                            "content": alert["description"],
                            "source": self.source_name,
                            "source_type": self.source_type,
                            "image_url": None,
                            "ingested_at": datetime.now().isoformat(),
                            "is_alert": True,
                            "alert_type": "weather",
                            "alert_priority": alert["priority"],
                            "alert_start_time": alert.get("alert_start_time"),
                            "alert_end_time": alert.get("alert_end_time")
                        })

                    logger.info(f"✅ Fetched {len(articles)} weather alerts from NWS")
                else:
                    logger.warning(f"❌ NWS request failed with status {response.status}")

        except Exception as e:
            logger.error(f"❌ Error fetching weather alerts: {e}")
        finally:
            await self._close_session()

        return articles

    def _parse_weather_alerts(self, html: str) -> List[Dict]:
        """Parse weather alerts from NWS HTML"""
        alerts = []

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Look for various alert sections with broader search
            alert_selectors = [
                ('div', {'class': 'hazards'}),
                ('div', {'id': 'hazards'}),
                ('div', {'class': lambda x: x and 'alert' in x.lower()}),
                ('div', {'class': lambda x: x and 'warning' in x.lower()}),
                ('div', {'class': lambda x: x and 'hazard' in x.lower()}),
                ('div', {'class': lambda x: x and any(word in (x or '').lower() for word in ['alert', 'warning', 'hazard'])}),
                ('td', {'class': lambda x: x and any(word in (x or '').lower() for word in ['alert', 'warning'])}),
                ('span', {'class': lambda x: x and any(word in (x or '').lower() for word in ['alert', 'warning'])}),
            ]

            for selector in alert_selectors:
                sections = soup.find_all(*selector)
                for section in sections:
                    # Look for alert content within the section
                    alert_items = section.find_all(['li', 'div', 'p', 'td', 'span'])

                    for item in alert_items:
                        alert_text = item.get_text().strip()
                        if alert_text and len(alert_text) > 15 and any(word in alert_text.lower() for word in ['warning', 'advisory', 'watch', 'alert', 'hazard']):
                            # Extract date/time information from alert text
                            date_time_info = self._extract_date_time_info(alert_text)

                            alerts.append({
                                "title": self._create_alert_title(alert_text),
                                "description": alert_text,
                                "published": datetime.now().isoformat(),
                                "priority": self._determine_alert_priority(alert_text),
                                "alert_dates": date_time_info.get('dates', []),
                                "alert_times": date_time_info.get('times', []),
                                "alert_start_time": date_time_info.get('alert_start_time'),
                                "alert_end_time": date_time_info.get('alert_end_time')
                            })

            # If no alerts found, look for general weather information that might be relevant
            if not alerts:
                # Search all text content for weather alerts
                all_text = soup.get_text()

                # Look for patterns that indicate weather alerts
                alert_patterns = [
                    r'(?:Winter|Snow|Ice|Wind|Flood|Severe|Heavy)\s+(?:Weather\s+)?(?:Warning|Advisory|Watch|Alert)',
                    r'(?:Warning|Advisory|Watch|Alert).*(?:snow|ice|wind|flood|severe|heavy)',
                    r'Hazardous\s+weather\s+conditions?',
                ]

                for pattern in alert_patterns:
                    matches = re.finditer(pattern, all_text, re.IGNORECASE)
                    for match in matches:
                        # Get surrounding context (up to 200 chars before and after)
                        start = max(0, match.start() - 100)
                        end = min(len(all_text), match.end() + 100)
                        context = all_text[start:end].strip()

                        # Clean up the context to get a meaningful alert
                        sentences = re.split(r'[.!?]+', context)
                        alert_text = ""
                        for sentence in sentences:
                            if any(word in sentence.lower() for word in ['warning', 'advisory', 'watch', 'alert', 'hazard']):
                                alert_text = sentence.strip()
                                break

                        if alert_text and len(alert_text) > 15:
                            date_time_info = self._extract_date_time_info(alert_text)
                            alerts.append({
                                "title": self._create_alert_title(alert_text),
                                "description": alert_text,
                                "published": datetime.now().isoformat(),
                                "priority": self._determine_alert_priority(alert_text),
                                "alert_dates": date_time_info.get('dates', []),
                                "alert_times": date_time_info.get('times', []),
                                "alert_start_time": date_time_info.get('alert_start_time'),
                                "alert_end_time": date_time_info.get('alert_end_time')
                            })

                # If still no alerts, create a fallback alert with current weather conditions
                # that might indicate potential issues
                if not alerts:
                    # Look for current weather conditions that might warrant attention
                    weather_indicators = [
                        r'(?:snow|ice|wind|flood|severe|heavy rain|thunderstorm|freezing)',
                        r'(?:below freezing|cold snap|wind chill)',
                        r'(?:adverse|hazardous|dangerous)\s+conditions?'
                    ]

                    for pattern in weather_indicators:
                        matches = re.finditer(pattern, all_text, re.IGNORECASE)
                        for match in matches:
                            start = max(0, match.start() - 50)
                            end = min(len(all_text), match.end() + 50)
                            context = all_text[start:end].strip()

                            # Extract date/time from the broader context
                            date_time_info = self._extract_date_time_info(context)

                            if date_time_info.get('dates') or date_time_info.get('times'):
                                alert_text = f"Weather conditions of note: {context[:100]}"
                                alerts.append({
                                    "title": self._create_alert_title(alert_text),
                                    "description": alert_text,
                                    "published": datetime.now().isoformat(),
                                    "priority": "info",
                                    "alert_dates": date_time_info.get('dates', []),
                                    "alert_times": date_time_info.get('times', []),
                                    "alert_start_time": date_time_info.get('alert_start_time'),
                                    "alert_end_time": date_time_info.get('alert_end_time')
                                })
                                break  # Only add one fallback alert

        except Exception as e:
            logger.error(f"Error parsing weather alerts: {e}")

        # Remove duplicates
        unique_alerts = []
        seen_descriptions = set()
        for alert in alerts:
            if alert['description'] not in seen_descriptions:
                unique_alerts.append(alert)
                seen_descriptions.add(alert['description'])

        return unique_alerts[:10]  # Limit to 10 alerts max

    def _extract_date_time_info(self, text: str) -> Dict:
        """Extract date and time information from alert text"""
        dates = []
        times = []

        # Date patterns
        date_patterns = [
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?\b',
            r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b',
            r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*\s+\d{1,2}(?:st|nd|rd|th)?\b',
        ]

        # Time patterns
        time_patterns = [
            r'\b\d{1,2}:\d{2}\s*(?:AM|PM|am|pm|a\.m\.|p\.m\.)\b',
            r'\b\d{1,2}\s*(?:AM|PM|am|pm|a\.m\.|p\.m\.)\b',
            r'\b\d{1,2}:\d{2}\b',  # 24-hour format
        ]

        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)

        for pattern in time_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            times.extend(matches)

        # Extract alert duration information
        duration_info = self._parse_alert_duration(text)

        return {
            'dates': list(set(dates)),  # Remove duplicates
            'times': list(set(times)),   # Remove duplicates
            'alert_start_time': duration_info.get('start_time'),
            'alert_end_time': duration_info.get('end_time')
        }

    def _parse_alert_duration(self, text: str) -> Dict:
        """Parse alert duration from text patterns like 'from X until Y'"""
        from datetime import datetime, timezone, timedelta

        # Find all complete date/time expressions in the text
        datetime_patterns = [
            r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?(?:,?\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))?(?:\s*(?:EST|EDT|ET))?',
            r'\d{1,2}/\d{1,2}(?:/\d{2,4})?(?:,?\s*\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))?(?:\s*(?:EST|EDT|ET))?',
            r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)(?:\s*(?:EST|EDT|ET))?',
        ]

        all_datetimes = []
        for pattern in datetime_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    dt = self._parse_datetime_string_with_context(match, text)
                    if dt:
                        # Store both the parsed datetime and the original string
                        all_datetimes.append((dt, match))
                except Exception as e:
                    continue

        # Remove duplicates and sort by position in text
        seen = set()
        unique_datetimes = []
        for dt, match_str in all_datetimes:
            if match_str not in seen:
                unique_datetimes.append((dt, match_str))
                seen.add(match_str)

        unique_datetimes.sort(key=lambda x: text.find(x[1]))

        # Look for duration indicators
        duration_keywords = ['from', 'until', 'to', 'through', 'thru']

        # If we have exactly 2 datetime expressions, assume first is start, second is end
        if len(unique_datetimes) == 2:
            start_time, end_time = unique_datetimes[0][0], unique_datetimes[1][0]

            # If end time is before start time, it might be the next day
            if end_time < start_time:
                # Check if the end time should be the next day
                end_time_next_day = end_time + timedelta(days=1)
                # Only adjust if it makes sense (end time becomes after start time)
                if end_time_next_day > start_time:
                    end_time = end_time_next_day

            return {
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat()
            }

        # If we have more than 2, try to find ones associated with duration keywords
        elif len(unique_datetimes) > 2:
            # Find datetimes near duration keywords
            start_candidates = []
            end_candidates = []

            for dt, match_str in unique_datetimes:
                pos = text.lower().find(match_str.lower())
                if pos >= 0:
                    # Find the positions of duration keywords
                    from_pos = text.lower().find('from')
                    until_pos = text.lower().find('until')
                    to_pos = text.lower().find('to')

                    # Check if this datetime appears after 'from' and before 'until'
                    if from_pos >= 0 and pos > from_pos and (until_pos < 0 or pos < until_pos):
                        start_candidates.append(dt)
                    # Check if this datetime appears after 'until' or 'to'
                    elif (until_pos >= 0 and pos > until_pos) or (to_pos >= 0 and pos > to_pos):
                        end_candidates.append(dt)

            if start_candidates and end_candidates:
                start_time = min(start_candidates)  # Earliest start time
                end_time = max(end_candidates)    # Latest end time
                return {
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat()
                }

        return {}

    def _parse_datetime_string(self, datetime_str: str) -> datetime:
        """Parse a datetime string with various formats and timezones"""
        import dateutil.parser
        from datetime import datetime, timezone

        # Clean up the string
        datetime_str = datetime_str.strip()

        # Add current year if not present (for relative dates)
        current_year = datetime.now().year
        if not re.search(r'\b20\d{2}\b', datetime_str):
            # Look for month/day patterns and add year
            month_day_match = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}', datetime_str, re.IGNORECASE)
            if month_day_match:
                datetime_str = f"{datetime_str}, {current_year}"

        try:
            # Try to parse with dateutil (handles various formats)
            dt = dateutil.parser.parse(datetime_str, fuzzy=True)

            # If no timezone specified, assume EST (Eastern Standard Time)
            if dt.tzinfo is None:
                # EST is UTC-5, EDT is UTC-4 - we'll assume EST for winter alerts
                from datetime import timezone, timedelta
                est_tz = timezone(timedelta(hours=-5))
                dt = dt.replace(tzinfo=est_tz)

            return dt
        except Exception as e:
            logger.warning(f"Failed to parse datetime '{datetime_str}': {e}")
            return None

    def _parse_datetime_string_with_context(self, datetime_str: str, full_text: str) -> datetime:
        """Parse a datetime string using full text context for better accuracy"""
        import dateutil.parser
        from datetime import datetime, timezone

        # Clean up the string
        datetime_str = datetime_str.strip()

        # Extract year from full text if available
        year_match = re.search(r'\b(20\d{2})\b', full_text)
        year = year_match.group(1) if year_match else str(datetime.now().year)

        # If datetime_str doesn't have a year, try to find it in the full text
        if not re.search(r'\b20\d{2}\b', datetime_str):
            # Look for month patterns and add year
            month_patterns = [
                r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}',
                r'\b\d{1,2}/\d{1,2}',
            ]
            for pattern in month_patterns:
                if re.search(pattern, datetime_str, re.IGNORECASE):
                    # Check if there's a year nearby in the full text
                    text_around = full_text[max(0, full_text.find(datetime_str) - 50):full_text.find(datetime_str) + len(datetime_str) + 50]
                    year_in_context = re.search(r'\b(20\d{2})\b', text_around)
                    if year_in_context:
                        year = year_in_context.group(1)
                    datetime_str = f"{datetime_str}, {year}"
                    break

        # Handle "today" references
        if 'today' in datetime_str.lower():
            today = datetime.now()
            datetime_str = datetime_str.lower().replace('today', f'{today.month}/{today.day}/{today.year}')

        try:
            # Try to parse with dateutil (handles various formats)
            dt = dateutil.parser.parse(datetime_str, fuzzy=True)

            # If no timezone specified, assume EST (Eastern Standard Time)
            if dt.tzinfo is None:
                from datetime import timezone, timedelta
                est_tz = timezone(timedelta(hours=-5))
                dt = dt.replace(tzinfo=est_tz)

            return dt
        except Exception as e:
            logger.warning(f"Failed to parse datetime '{datetime_str}' with context: {e}")
            # Fall back to original method
            return self._parse_datetime_string(datetime_str)

    def _create_alert_title(self, alert_text: str) -> str:
        """Create a concise title from alert text"""
        # Extract the alert type and key information
        alert_type = "Weather Alert"

        # Look for common alert types
        text_lower = alert_text.lower()
        if "warning" in text_lower:
            alert_type = "Warning"
        elif "advisory" in text_lower:
            alert_type = "Advisory"
        elif "watch" in text_lower:
            alert_type = "Watch"

        # Get first meaningful sentence or phrase
        first_part = alert_text.split('.')[0].split('...')[0].strip()

        # Limit length
        if len(first_part) > 80:
            first_part = first_part[:77] + "..."

        return f"{alert_type}: {first_part}"

    def _determine_alert_priority(self, alert_text: str) -> str:
        """Determine alert priority based on content"""
        text_lower = alert_text.lower()

        # Critical alerts
        if any(word in text_lower for word in ['tornado warning', 'flash flood warning', 'severe thunderstorm warning']):
            return 'critical'

        # Warning alerts
        if any(word in text_lower for word in ['warning', 'emergency', 'life-threatening', 'evacuation']):
            return 'warning'

        # Advisory alerts
        if any(word in text_lower for word in ['advisory', 'watch', 'hazard']):
            return 'warning'

        # Info alerts (default)
        return 'info'