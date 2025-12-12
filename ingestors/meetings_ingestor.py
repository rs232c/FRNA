"""
Meetings ingestion module for Fall River, MA
Reads from local iCal file or downloads from official city calendar
"""
import requests
import logging
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, List
from icalendar import Calendar
from cache import get_cache
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, quote
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Local calendar file path (user-provided)
LOCAL_CALENDAR_PATH = Path("C:/FRNA/calendar_import/Official Meetings.ics")

# Fall River official calendar iCal URL (for future automation)
# The calendar is loaded via JavaScript from revizeCalendar plugin
MEETINGS_ICAL_URL = "https://www.fallriverma.gov/_assets_/plugins/revizeCalendar/cache/calendarimport.ics"

# Alternative URLs to try if primary fails
ALTERNATIVE_ICAL_URLS = [
    "https://www.fallriverma.gov/sites/g/files/vyhlif6061/f/calendars/full_calendar.ics",
    "https://www.fallriverma.gov/sites/default/files/calendars/full_calendar.ics",
    "https://www.fallriverma.gov/calendar/export.ics",
]


class MeetingsIngestor:
    """Fetch and parse city meetings from official iCal export"""
    
    def __init__(self):
        self.ical_url = MEETINGS_ICAL_URL
        self._agenda_cache = {}  # Cache for scraped agenda URLs
    
    def fetch_meetings(self) -> List[Dict]:
        """Fetch upcoming meetings from iCal file
        
        Returns:
            List of meeting dictionaries with keys:
            - id: Unique identifier (UID from iCal)
            - title: Meeting title/board name
            - date: ISO format date string
            - time: Time string (HH:MM AM/PM format)
            - datetime: Full datetime object
            - location: Meeting location
            - description: Optional description
        """
        cache = get_cache()
        cache_key = "meetings:fall_river"
        
        # Check cache first (24 hour TTL - once per day)
        cached_meetings = cache.get("meetings", cache_key)
        if cached_meetings:
            logger.debug("Using cached meetings data")
            # Load both agenda caches if available (scraped URLs and probed PDFs)
            agenda_cache_key = "agenda_urls:fall_river"
            pdf_cache_key = "agenda_pdfs:fall_river"
            cached_agendas = cache.get("agendas", agenda_cache_key) or {}
            cached_pdfs = cache.get("agendas", pdf_cache_key) or {}
            # Merge both caches into in-memory cache
            self._agenda_cache = {**cached_agendas, **cached_pdfs}
            # Apply agenda URLs to cached meetings (including PDF probing)
            # This ensures agenda URLs are always up-to-date even for cached meetings
            self._apply_agenda_urls_to_meetings(cached_meetings)
            return cached_meetings
        
        # Scrape agenda URLs first (before parsing) so they're available during parsing
        # This allows _get_agenda_url() to use scraped URLs immediately
        self._scrape_agenda_urls([])  # Pass empty list - we'll apply after parsing
        
        # Try local file first (user-provided)
        if LOCAL_CALENDAR_PATH.exists():
            try:
                logger.info(f"Reading calendar from local file: {LOCAL_CALENDAR_PATH}")
                with open(LOCAL_CALENDAR_PATH, 'rb') as f:
                    ical_content = f.read()
                
                meetings = self._parse_ical_content(ical_content)
                if meetings:
                    # Apply scraped agenda URLs to meetings (scraped earlier in fetch_meetings)
                    self._apply_agenda_urls_to_meetings(meetings)
                    # Cache for 24 hours
                    cache.set("meetings", cache_key, meetings, ttl=86400)
                    logger.info(f"Successfully loaded {len(meetings)} meetings from local file")
                    return meetings
            except Exception as e:
                logger.warning(f"Error reading local calendar file: {e}")
                logger.info("Falling back to web download...")
        else:
            logger.info(f"Local calendar file not found at {LOCAL_CALENDAR_PATH}, trying web download...")
        
        # Try primary URL first, then alternatives
        urls_to_try = [self.ical_url] + ALTERNATIVE_ICAL_URLS
        
        for url in urls_to_try:
            try:
                # Download iCal file
                logger.info(f"Attempting to download meetings calendar from {url}")
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/calendar,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Referer': 'https://www.fallriverma.gov/calendar',
                    'Connection': 'keep-alive',
                }
                response = requests.get(url, timeout=30, headers=headers)
                
                # Check if we got HTML instead of iCal (404 page, redirect, etc.)
                content_type = response.headers.get('Content-Type', '').lower()
                content_start = response.text.strip()[:50] if response.text else ''
                
                if response.status_code == 404:
                    logger.warning(f"URL returned 404: {url}")
                    logger.warning("Calendar may not be available at this URL. Please verify the URL on the Fall River website.")
                    continue  # Try next URL
                
                if 'html' in content_type or content_start.startswith('<!DOCTYPE') or content_start.startswith('<html'):
                    logger.warning(f"Received HTML instead of iCal file from {url}. Status: {response.status_code}")
                    logger.warning("This usually means the URL is incorrect or the calendar export is not available.")
                    continue  # Try next URL
                
                response.raise_for_status()
                
                # Verify it's actually iCal content
                if b'BEGIN:VCALENDAR' not in response.content[:200]:
                    logger.warning(f"Response from {url} doesn't appear to be iCal format")
                    continue  # Try next URL
                
                # Parse iCal content
                meetings = self._parse_ical_content(response.content)
                if meetings:
                    # Apply scraped agenda URLs to meetings (scraped earlier in fetch_meetings)
                    self._apply_agenda_urls_to_meetings(meetings)
                    # Cache for 24 hours (86400 seconds) - once per day
                    cache.set("meetings", cache_key, meetings, ttl=86400)
                    logger.info(f"Successfully fetched {len(meetings)} upcoming meetings from {url}")
                    return meetings
                
            except requests.exceptions.HTTPError as e:
                logger.warning(f"HTTP error from {url}: {e.response.status_code if hasattr(e, 'response') else 'unknown'}")
                continue  # Try next URL
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error from {url}: {e}")
                continue  # Try next URL
            except Exception as e:
                logger.warning(f"Error processing {url}: {e}")
                continue  # Try next URL
        
        # If we get here, all URLs failed
        logger.error("Failed to fetch meetings calendar from all attempted URLs")
        logger.info("Attempting to use Selenium as fallback to extract calendar from page...")
        
        # Try using Selenium to load the page and extract calendar data
        try:
            meetings = self._fetch_with_selenium()
            if meetings:
                # Apply scraped agenda URLs to meetings (scraped earlier in fetch_meetings)
                self._apply_agenda_urls_to_meetings(meetings)
                logger.info(f"Successfully fetched {len(meetings)} meetings using Selenium")
                # Cache for 24 hours
                cache.set("meetings", cache_key, meetings, ttl=86400)
                return meetings
        except ImportError:
            logger.warning("Selenium not available - install with: pip install selenium")
        except Exception as e:
            logger.warning(f"Selenium fallback failed: {e}")
        
        return []
    
    def _fetch_with_selenium(self) -> List[Dict]:
        """Fallback method to fetch calendar using Selenium (requires JavaScript execution)"""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            import time
            import re
        except ImportError:
            raise ImportError("Selenium is required for JavaScript-based calendar extraction")
        
        logger.info("Loading calendar page with Selenium...")
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        # Enable logging to capture console messages (Selenium 4+ syntax)
        chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
        
        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.get("https://www.fallriverma.gov/calendar")
            
            # Wait for calendar to load and JavaScript to execute
            logger.info("Waiting for calendar to load...")
            time.sleep(5)  # Initial wait
            
            # Try to find and click export button if it exists
            try:
                export_selectors = [
                    'button[data-export]',
                    '.export-button',
                    'a[href*=".ics"]',
                    '[onclick*="export"]',
                    '[onclick*="calendar"]',
                    'button:contains("Export")',
                    'a:contains("Export")',
                    'a:contains("iCal")',
                    'a:contains("Calendar")',
                ]
                for selector in export_selectors:
                    try:
                        # Try CSS selector first
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if not elements:
                            # Try XPath for text-based selectors
                            if ':contains(' in selector:
                                text = selector.split(':contains(')[1].rstrip(')').strip('"\'')
                                xpath = f"//*[contains(text(), '{text}')]"
                                elements = driver.find_elements(By.XPATH, xpath)
                        if elements:
                            logger.info(f"Found export button with selector: {selector}")
                            elements[0].click()
                            time.sleep(3)  # Wait for export to trigger
                            break
                    except Exception as e:
                        logger.debug(f"Selector {selector} failed: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Could not click export button: {e}")
            
            time.sleep(5)  # Additional wait for calendar data to load
            
            # Check page source first
            page_source = driver.page_source
            ical_content = None
            
            # Look for iCal data in page source
            if 'BEGIN:VCALENDAR' in page_source:
                logger.info("Found iCal data in page source")
                start_idx = page_source.find('BEGIN:VCALENDAR')
                # Find the end - look for END:VCALENDAR
                end_match = re.search(r'END:VCALENDAR', page_source[start_idx:])
                if end_match:
                    end_idx = start_idx + end_match.end()
                    ical_content = page_source[start_idx:end_idx]
            
            # If not in page source, check console logs for iCal data
            if not ical_content:
                logger.info("Checking browser console logs for calendar data...")
                logs = driver.get_log('browser')
                for log in logs:
                    message = log.get('message', '')
                    if 'BEGIN:VCALENDAR' in message:
                        logger.info("Found iCal data in console logs")
                        # Extract iCal content from log message
                        start_idx = message.find('BEGIN:VCALENDAR')
                        end_match = re.search(r'END:VCALENDAR', message[start_idx:])
                        if end_match:
                            end_idx = start_idx + end_match.end()
                            ical_content = message[start_idx:end_idx]
                            break
            
            # Try executing JavaScript to get calendar data
            if not ical_content:
                logger.info("Trying to extract calendar via JavaScript...")
                try:
                    # Try multiple JavaScript approaches to get calendar data
                    js_attempts = [
                        # Try to get from window object
                        "return window.calendarData || window.calendar || null;",
                        # Try to find and click export button, then capture data
                        """
                        var exportBtn = document.querySelector('[data-export], .export, [onclick*="export"], [onclick*="calendar"]');
                        if (exportBtn) {
                            exportBtn.click();
                            return 'clicked';
                        }
                        return null;
                        """,
                        # Try to intercept console.log calls
                        """
                        var originalLog = console.log;
                        var captured = [];
                        console.log = function(...args) {
                            captured.push(args.join(' '));
                            originalLog.apply(console, args);
                        };
                        // Trigger calendar load if needed
                        setTimeout(function() {
                            console.log = originalLog;
                        }, 2000);
                        return captured.join('\\n');
                        """,
                        # Try to get calendar from revizeCalendar plugin
                        """
                        if (window.revizeCalendar || window.RevizeCalendar) {
                            var cal = window.revizeCalendar || window.RevizeCalendar;
                            if (cal && cal.getEvents) {
                                return cal.getEvents();
                            }
                            if (cal && cal.export) {
                                return cal.export();
                            }
                        }
                        return null;
                        """,
                        # Try to find calendar data in script tags
                        """
                        var scripts = document.getElementsByTagName('script');
                        for (var i = 0; i < scripts.length; i++) {
                            var content = scripts[i].innerHTML || scripts[i].textContent || '';
                            if (content.indexOf('BEGIN:VCALENDAR') !== -1) {
                                var start = content.indexOf('BEGIN:VCALENDAR');
                                var end = content.indexOf('END:VCALENDAR', start) + 'END:VCALENDAR'.length;
                                return content.substring(start, end);
                            }
                        }
                        return null;
                        """
                    ]
                    
                    for i, js_code in enumerate(js_attempts):
                        try:
                            js_result = driver.execute_script(js_code)
                            if js_result:
                                result_str = str(js_result)
                                if 'BEGIN:VCALENDAR' in result_str:
                                    logger.info(f"Found iCal data via JavaScript method {i+1}")
                                    # Extract just the iCal portion
                                    start_idx = result_str.find('BEGIN:VCALENDAR')
                                    end_match = re.search(r'END:VCALENDAR', result_str[start_idx:])
                                    if end_match:
                                        end_idx = start_idx + end_match.end()
                                        ical_content = result_str[start_idx:end_idx]
                                        break
                        except Exception as e:
                            logger.debug(f"JavaScript attempt {i+1} failed: {e}")
                            continue
                            
                except Exception as e:
                    logger.debug(f"JavaScript extraction failed: {e}")
            
            # Try to intercept network requests for .ics files
            if not ical_content:
                logger.info("Checking network requests for calendar data...")
                try:
                    # Get performance logs (network requests)
                    performance_logs = driver.get_log('performance')
                    for log in performance_logs:
                        message = log.get('message', '')
                        if '.ics' in message.lower() or 'calendar' in message.lower():
                            logger.debug(f"Found calendar-related network request: {message[:200]}")
                except Exception as e:
                    logger.debug(f"Could not check network logs: {e}")
            
            # Parse the iCal content if found
            if ical_content:
                logger.info("Parsing iCal content...")
                try:
                    cal = Calendar.from_ical(ical_content.encode('utf-8'))
                    meetings = []
                    now = datetime.now(timezone.utc)
                    
                    for component in cal.walk():
                        if component.name == "VEVENT":
                            meeting = self._parse_event(component)
                            if meeting and meeting['datetime'] and meeting['datetime'] >= now:
                                meetings.append(meeting)
                    
                    meetings.sort(key=lambda x: x['datetime'] if x['datetime'] else datetime.max.replace(tzinfo=timezone.utc))
                    logger.info(f"Successfully parsed {len(meetings)} upcoming meetings from calendar")
                    return meetings
                except Exception as e:
                    logger.warning(f"Error parsing iCal content: {e}")
                    logger.debug(f"iCal content preview: {ical_content[:500]}")
            else:
                logger.warning("Could not find iCal data in page source, console logs, or via JavaScript")
                # Log page source snippet for debugging
                if 'revizeCalendar' in page_source.lower():
                    logger.debug("Page contains revizeCalendar references but no iCal data found")
                return []
                
        finally:
            if driver:
                driver.quit()
    
    def _parse_ical_content(self, ical_content: bytes) -> List[Dict]:
        """Parse iCal content and return list of upcoming meetings
        
        Args:
            ical_content: Raw bytes of iCal file content
            
        Returns:
            List of meeting dictionaries
        """
        try:
            cal = Calendar.from_ical(ical_content)
            meetings = []
            now = datetime.now(timezone.utc)
            
            for component in cal.walk():
                if component.name == "VEVENT":
                    meeting = self._parse_event(component)
                    if meeting:
                        # Only include upcoming meetings
                        if meeting['datetime'] and meeting['datetime'] >= now:
                            meetings.append(meeting)
            
            # Sort by datetime
            meetings.sort(key=lambda x: x['datetime'] if x['datetime'] else datetime.max.replace(tzinfo=timezone.utc))
            
            return meetings
        except Exception as e:
            logger.error(f"Error parsing iCal content: {e}", exc_info=True)
            return []
    
    def _parse_event(self, event) -> Optional[Dict]:
        """Parse a single iCal event into a meeting dictionary"""
        try:
            # Get UID for unique identifier
            uid = str(event.get('UID', ''))
            if not uid:
                # Generate a fallback ID from title and date
                title = str(event.get('SUMMARY', ''))
                dt = event.get('DTSTART')
                if dt:
                    dt_val = dt.dt
                    uid = f"{title}_{dt_val.isoformat()}"
                else:
                    uid = f"meeting_{hash(str(event))}"
            
            # Get title (board/committee name)
            title = str(event.get('SUMMARY', 'Untitled Meeting')).strip()
            
            # Get datetime
            dt_start = event.get('DTSTART')
            if not dt_start:
                return None
            
            dt_val = dt_start.dt
            if isinstance(dt_val, datetime):
                meeting_datetime = dt_val
                if meeting_datetime.tzinfo is None:
                    # Assume local time if no timezone
                    meeting_datetime = meeting_datetime.replace(tzinfo=timezone.utc)
            else:
                # Date-only (all-day event)
                meeting_datetime = datetime.combine(dt_val, datetime.min.time())
                meeting_datetime = meeting_datetime.replace(tzinfo=timezone.utc)
            
            # Format date and time (keep as strings for display)
            date_str = meeting_datetime.strftime('%Y-%m-%d')
            time_str = meeting_datetime.strftime('%I:%M %p').lstrip('0')
            
            # Get location
            location = str(event.get('LOCATION', '')).strip()
            
            # Get description
            description = str(event.get('DESCRIPTION', '')).strip()
            
            # Try to extract agenda URL from description first
            agenda_url = None
            # Look for URLs in description (agenda links are sometimes embedded)
            agenda_match = re.search(r'https?://[^\s"\'<>\)]+', description)
            if agenda_match:
                agenda_url = agenda_match.group(0).rstrip('.,;:)')
            
            # If no URL in description, try to construct based on meeting type
            if not agenda_url:
                agenda_url = self._get_agenda_url(title, meeting_datetime, description)
            
            return {
                'id': uid,
                'title': title,
                'date': date_str,
                'time': time_str,
                'datetime': meeting_datetime,  # Keep as datetime object for comparison/sorting
                'location': location,
                'description': description,
                'agenda_url': agenda_url
            }
        
        except Exception as e:
            logger.warning(f"Error parsing event: {e}")
            return None
    
    def _scrape_agenda_urls(self, meetings: List[Dict]):
        """Scrape agenda URLs from the city calendar page and match them to meetings
        
        Args:
            meetings: List of meeting dictionaries to update with agenda URLs
        """
        cache = get_cache()
        cache_key = "agenda_urls:fall_river"
        
        # Check cache first (24 hour TTL)
        cached_agendas = cache.get("agendas", cache_key)
        # Also check PDF cache
        pdf_cache_key = "agenda_pdfs:fall_river"
        cached_pdfs = cache.get("agendas", pdf_cache_key) or {}
        
        if cached_agendas:
            logger.debug("Using cached agenda URLs")
            # Merge both caches (scraped URLs + probed PDFs)
            self._agenda_cache = {**(cached_agendas or {}), **cached_pdfs}
            # Update meetings with cached agenda URLs
            self._apply_agenda_urls_to_meetings(meetings)
            # Still probe for PDFs even if cache exists - PDF probing is the most reliable method
            # and will update any missing agenda URLs
            if meetings:
                self._probe_agenda_pdfs(meetings)
            return
        elif cached_pdfs:
            # If we have PDF cache but no scraped cache, use PDF cache
            self._agenda_cache = cached_pdfs
            self._apply_agenda_urls_to_meetings(meetings)
            if meetings:
                self._probe_agenda_pdfs(meetings)
            return
        
        logger.info("Scraping agenda URLs from city calendar page...")
        agenda_map = {}
        
        # Try HTML scraping first
        try:
            agenda_map = self._scrape_agenda_urls_html()
        except Exception as e:
            logger.debug(f"HTML scraping failed: {e}, trying Selenium...")
        
        # If HTML scraping didn't find much, try Selenium (for JavaScript-rendered content)
        if len(agenda_map) < 3:
            try:
                selenium_agendas = self._scrape_agenda_urls_selenium()
                if selenium_agendas:
                    agenda_map.update(selenium_agendas)
            except Exception as e:
                logger.debug(f"Selenium scraping failed: {e}")
        
        # Cache the results
        if agenda_map:
            cache.set("agendas", cache_key, agenda_map, ttl=86400)
            # Merge with any existing PDF cache
            pdf_cache_key = "agenda_pdfs:fall_river"
            cached_pdfs = cache.get("agendas", pdf_cache_key) or {}
            self._agenda_cache = {**agenda_map, **cached_pdfs}
            logger.info(f"Scraped {len(agenda_map)} agenda URLs from calendar page")
        else:
            logger.warning("No agenda URLs found on calendar page")
        
        # Apply scraped agenda URLs to meetings (this will also probe for PDFs)
        self._apply_agenda_urls_to_meetings(meetings)
    
    def _scrape_agenda_urls_html(self) -> Dict[str, str]:
        """Scrape agenda URLs using HTML parsing (faster, works for static content)
        
        Returns:
            Dictionary mapping cache keys to agenda URLs
        """
        agenda_map = {}
        calendar_url = "https://www.fallriverma.gov/calendar.php"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        response = requests.get(calendar_url, timeout=30, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all links that might be agendas
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            href = link.get('href', '')
            link_text = link.get_text(strip=True).lower()
            href_lower = href.lower()
            
            # Check if this looks like an agenda link
            is_agenda_link = False
            if href.endswith('.pdf') and ('agenda' in href_lower or 'agenda' in link_text):
                is_agenda_link = True
            elif 'agenda' in link_text and ('view' in link_text or 'download' in link_text or href.endswith('.pdf')):
                is_agenda_link = True
            elif 'agenda' in href_lower and href.endswith('.pdf'):
                is_agenda_link = True
            
            if is_agenda_link:
                # Make absolute URL
                agenda_url = urljoin(calendar_url, href)
                
                # Try to extract date and meeting info from surrounding context
                parent = link.parent
                date_match = None
                meeting_title = None
                
                # Look for date patterns in parent/sibling elements (check up to 3 levels up)
                elements_to_check = [link, parent]
                if parent:
                    elements_to_check.append(parent.parent)
                    if parent.parent:
                        elements_to_check.append(parent.parent.parent)
                
                for elem in elements_to_check:
                    if not elem:
                        continue
                    text = elem.get_text() if hasattr(elem, 'get_text') else str(elem)
                    
                    # Try to find date patterns
                    date_patterns = [
                        r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})',  # MM-DD-YYYY or MM/DD/YYYY
                        r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})',  # YYYY-MM-DD or YYYY/MM/DD
                    ]
                    for pattern in date_patterns:
                        match = re.search(pattern, text)
                        if match:
                            try:
                                date_str = match.group(0).replace('/', '-')
                                if len(match.group(1)) == 4:  # YYYY-MM-DD format
                                    date_match = datetime.strptime(date_str, '%Y-%m-%d')
                                else:  # MM-DD-YYYY format
                                    date_match = datetime.strptime(date_str, '%m-%d-%Y')
                                break
                            except:
                                continue
                    
                    # Try to extract meeting title
                    if not meeting_title:
                        title_keywords = ['city council', 'zoning board', 'planning board', 'board of health',
                                       'licensing board', 'school committee', 'finance committee', 'cda',
                                       'community development', 'dpu', 'tif board', 'tax increment']
                        text_lower = text.lower()
                        for keyword in title_keywords:
                            if keyword in text_lower:
                                meeting_title = keyword
                                break
                    
                    if date_match:
                        break
                
                # If we found date info, create cache keys
                if date_match:
                    date_key = date_match.strftime('%Y-%m-%d')
                    if meeting_title:
                        cache_key_meeting = f"{date_key}:{meeting_title}"
                        agenda_map[cache_key_meeting] = agenda_url
                    # Also add date-only key for broader matching
                    if date_key not in agenda_map:  # Don't overwrite more specific matches
                        agenda_map[date_key] = agenda_url
        
        return agenda_map
    
    def _scrape_agenda_urls_selenium(self) -> Dict[str, str]:
        """Scrape agenda URLs using Selenium (for JavaScript-rendered content)
        
        Returns:
            Dictionary mapping cache keys to agenda URLs
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            import time
        except ImportError:
            logger.debug("Selenium not available for agenda scraping")
            return {}
        
        agenda_map = {}
        driver = None
        
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            driver = webdriver.Chrome(options=chrome_options)
            driver.get("https://www.fallriverma.gov/calendar.php")
            
            # Wait for page to load
            time.sleep(3)
            
            # Find all links
            links = driver.find_elements(By.TAG_NAME, 'a')
            
            for link in links:
                try:
                    href = link.get_attribute('href') or ''
                    link_text = link.text.lower()
                    href_lower = href.lower()
                    
                    # Check if this looks like an agenda link
                    is_agenda_link = False
                    if href.endswith('.pdf') and ('agenda' in href_lower or 'agenda' in link_text):
                        is_agenda_link = True
                    elif 'agenda' in link_text and ('view' in link_text or 'download' in link_text or href.endswith('.pdf')):
                        is_agenda_link = True
                    elif 'agenda' in href_lower and href.endswith('.pdf'):
                        is_agenda_link = True
                    
                    if is_agenda_link:
                        # Try to find date and meeting info from surrounding elements
                        try:
                            parent = link.find_element(By.XPATH, './..')
                            parent_text = parent.text if parent else ''
                            
                            # Extract date
                            date_match = None
                            date_patterns = [
                                r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})',
                                r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})',
                            ]
                            for pattern in date_patterns:
                                match = re.search(pattern, parent_text)
                                if match:
                                    try:
                                        date_str = match.group(0).replace('/', '-')
                                        if len(match.group(1)) == 4:
                                            date_match = datetime.strptime(date_str, '%Y-%m-%d')
                                        else:
                                            date_match = datetime.strptime(date_str, '%m-%d-%Y')
                                        break
                                    except:
                                        continue
                            
                            if date_match:
                                date_key = date_match.strftime('%Y-%m-%d')
                                agenda_map[date_key] = href
                        except:
                            pass
                except:
                    continue
            
        except Exception as e:
            logger.debug(f"Selenium agenda scraping error: {e}")
        finally:
            if driver:
                driver.quit()
        
        return agenda_map
    
    def _apply_agenda_urls_to_meetings(self, meetings: List[Dict]):
        """Apply scraped agenda URLs to meeting dictionaries
        
        Args:
            meetings: List of meeting dictionaries to update
        """
        for meeting in meetings:
            dt = meeting.get('datetime')
            if not dt:
                continue
            
            if isinstance(dt, datetime):
                meeting_date = dt.date()
            elif isinstance(dt, str):
                try:
                    meeting_date = datetime.fromisoformat(dt.replace('Z', '+00:00')).date()
                except:
                    continue
            else:
                continue
            
            date_key = meeting_date.strftime('%Y-%m-%d')
            title = meeting.get('title', '').lower()
            
            # Try exact match first: date + title keywords
            matched_url = None
            
            # Try matching by date + title keywords
            title_keywords = ['city council', 'zoning board', 'planning board', 'board of health',
                            'licensing board', 'school committee', 'finance committee', 'cda',
                            'community development', 'dpu', 'tif board', 'tax increment']
            for keyword in title_keywords:
                if keyword in title:
                    cache_key = f"{date_key}:{keyword}"
                    if cache_key in self._agenda_cache:
                        matched_url = self._agenda_cache[cache_key]
                        break
            
            # Fallback: try date-only match
            if not matched_url and date_key in self._agenda_cache:
                matched_url = self._agenda_cache[date_key]
            
            # Update meeting with scraped URL if found
            if matched_url:
                meeting['agenda_url'] = matched_url
                logger.debug(f"Matched agenda URL for {meeting.get('title')} on {date_key}")

        # Second pass: probe for exact agenda PDFs at site root (most reliable)
        # This is necessary because many agenda PDFs are published as:
        # https://www.fallriverma.gov/AGENDA-Fall%20River%20<MeetingName>%20MM-DD-YYYY.pdf
        self._probe_agenda_pdfs(meetings)

    def _probe_agenda_pdfs(self, meetings: List[Dict]):
        """Probe for agenda PDFs published directly under fallriverma.gov/ and cache results.

        The city site frequently publishes agenda PDFs at the site root with predictable names.
        We only accept URLs that actually exist (HTTP 200/301/302), otherwise we keep existing links.
        """
        if not meetings:
            return

        cache = get_cache()
        cache_key = "agenda_pdfs:fall_river"
        cached = cache.get("agendas", cache_key) or {}

        # Prime in-memory cache
        if cached:
            for k, v in cached.items():
                self._agenda_cache.setdefault(k, v)

        # Get timezone for date formatting (fallback to UTC if tzdata not available)
        try:
            tz = ZoneInfo("America/New_York")
        except Exception:
            # Fallback to UTC if timezone data not available
            tz = timezone.utc
        base = "https://www.fallriverma.gov/"

        # Limit probing to avoid excessive requests in one run
        # (we run at most once/day due to meetings cache TTL)
        max_meetings = 40
        max_candidates_per_meeting = 6

        def _clean_title(raw: str) -> str:
            t = (raw or "").strip()
            # Remove trailing time portions like "@6:00 PM" or " @ 2:00 p.m."
            t = re.sub(r'\s*@\s*.*$', '', t).strip()
            # Collapse whitespace
            t = re.sub(r'\s+', ' ', t).strip()
            return t

        def _date_mdy(dt: datetime) -> str:
            # Convert to local date for filename matching
            try:
                local_dt = dt.astimezone(tz)
            except Exception:
                local_dt = dt
            return local_dt.strftime("%m-%d-%Y")

        def _url_exists(url: str) -> bool:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                }

                # Try HEAD first (fast), but many sites treat HEAD differently
                r = requests.head(url, timeout=10, allow_redirects=True, headers=headers)
                if r.status_code in (200, 301, 302):
                    return True

                # Fallback: tiny GET (more reliable than HEAD on some CMS/CDNs)
                rg = requests.get(
                    url,
                    timeout=15,
                    stream=True,
                    allow_redirects=True,
                    headers={**headers, "Range": "bytes=0-0"},
                )
                return rg.status_code in (200, 206)
            except Exception:
                return False

        updated_cache = dict(cached)

        for meeting in meetings[:max_meetings]:
            dt = meeting.get("datetime")
            if not isinstance(dt, datetime):
                continue

            date_str = _date_mdy(dt)
            title_clean = _clean_title(meeting.get("title", ""))
            if not title_clean:
                continue

            # Cache keys for matching
            key_exact = f"{dt.strftime('%Y-%m-%d')}:{title_clean.lower()}"
            key_date = dt.strftime('%Y-%m-%d')

            # If we already have a known-good PDF URL cached, use it
            cached_url = self._agenda_cache.get(key_exact) or self._agenda_cache.get(key_date)
            if cached_url and cached_url.lower().endswith(".pdf"):
                meeting["agenda_url"] = cached_url
                continue

            # Generate candidate filenames that match observed city pattern
            # Example:
            # AGENDA-Fall River Zoning Board of Appeals 12-18-2025.pdf
            candidates = []
            base_name = f"Fall River {title_clean} {date_str}"

            # Common prefixes
            for prefix in ("AGENDA-", "ADA AGENDA-", "ADA-AGENDA-"):
                candidates.append(f"{prefix}{base_name}.pdf")

            # Also try without "Fall River " prefix (sometimes omitted)
            base_name2 = f"{title_clean} {date_str}"
            for prefix in ("AGENDA-", "ADA AGENDA-", "ADA-AGENDA-"):
                candidates.append(f"{prefix}{base_name2}.pdf")

            # De-dup while preserving order
            seen = set()
            ordered = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    ordered.append(c)

            found = None
            for filename in ordered[:max_candidates_per_meeting]:
                # Quote path portion but keep slashes
                url = base + quote(filename)
                if _url_exists(url):
                    found = url
                    break

            if found:
                meeting["agenda_url"] = found
                self._agenda_cache[key_exact] = found
                # Keep a date-only fallback too
                self._agenda_cache.setdefault(key_date, found)
                updated_cache[key_exact] = found
                updated_cache.setdefault(key_date, found)

        # Persist cache (24h)
        if updated_cache != cached:
            cache.set("agendas", cache_key, updated_cache, ttl=86400)
    
    def _get_agenda_url(self, title: str, meeting_datetime: datetime, description: str = "") -> Optional[str]:
        """Get agenda URL for a meeting based on title, date, and description
        
        Args:
            title: Meeting title/board name
            meeting_datetime: Meeting datetime
            description: Meeting description (may contain agenda info)
            
        Returns:
            Agenda URL if found, None otherwise
        """
        # First check if we have a scraped/probed agenda URL in cache
        date_key = meeting_datetime.strftime('%Y-%m-%d')
        title_lower = (title or "").lower().strip()

        # Try exact title key first (probed PDF resolver uses this)
        exact_key = f"{date_key}:{re.sub(r'\\s*@\\s*.*$', '', title_lower).strip()}"
        if exact_key in self._agenda_cache:
            return self._agenda_cache[exact_key]
        
        # Try to match from scraped agenda cache
        title_keywords = ['city council', 'zoning board', 'planning board', 'board of health',
                         'licensing board', 'school committee', 'finance committee', 'cda',
                         'community development', 'dpu', 'tif board', 'tax increment']
        for keyword in title_keywords:
            if keyword in title_lower:
                cache_key = f"{date_key}:{keyword}"
                if cache_key in self._agenda_cache:
                    return self._agenda_cache[cache_key]
        
        # Fallback: date-only match
        if date_key in self._agenda_cache:
            return self._agenda_cache[date_key]
        
        # If no scraped URL found, use pattern-based construction
        # Base URL for agendas on city website
        base_url = "https://www.fallriverma.gov/sites/g/files/vyhlif6061/f/agendas"
        
        # Format date in multiple formats for different URL patterns
        date_str_iso = meeting_datetime.strftime('%Y-%m-%d')  # YYYY-MM-DD
        date_str_mdy = meeting_datetime.strftime('%m-%d-%Y')  # MM-DD-YYYY
        date_str_mdy_short = meeting_datetime.strftime('%m-%d-%y')  # MM-DD-YY
        
        # Normalize title and description for matching
        title_lower = title.lower()
        desc_lower = description.lower()
        combined_text = f"{title_lower} {desc_lower}"
        
        # Mapping of meeting types to agenda filename patterns (try multiple date formats)
        agenda_patterns = {
            'zoning board': [
                f"{date_str_iso}_zoning_board_agenda.pdf",
                f"{date_str_mdy}_zoning_board_agenda.pdf",
                f"zoning_board_{date_str_iso}_agenda.pdf"
            ],
            'licensing board': [
                f"{date_str_iso}_licensing_board_agenda.pdf",
                f"{date_str_mdy}_licensing_board_agenda.pdf",
                f"licensing_board_{date_str_iso}_agenda.pdf"
            ],
            'city council': [
                f"{date_str_iso}_city_council_agenda_packet.pdf",
                f"{date_str_mdy}_city_council_agenda_packet.pdf",
                f"city_council_{date_str_iso}_agenda.pdf",
                f"city_council_agenda_{date_str_mdy}.pdf"
            ],
            'community development': [
                f"{date_str_iso}_cda_agenda.pdf",
                f"{date_str_mdy}_cda_agenda.pdf",
                f"cda_{date_str_iso}_agenda.pdf"
            ],
            'cda': [
                f"{date_str_iso}_cda_agenda.pdf",
                f"{date_str_mdy}_cda_agenda.pdf",
                f"cda_{date_str_iso}_agenda.pdf"
            ],
            'dpu public hearing': [
                f"{date_str_iso}_dpu_hearing_agenda.pdf",
                f"{date_str_mdy}_dpu_hearing_agenda.pdf",
                f"dpu_hearing_{date_str_iso}_agenda.pdf"
            ],
            'dpu': [
                f"{date_str_iso}_dpu_hearing_agenda.pdf",
                f"{date_str_mdy}_dpu_hearing_agenda.pdf",
                f"dpu_hearing_{date_str_iso}_agenda.pdf"
            ],
            'planning board': [
                f"{date_str_iso}_planning_board_agenda.pdf",
                f"{date_str_mdy}_planning_board_agenda.pdf",
                f"planning_board_{date_str_iso}_agenda.pdf"
            ],
            'board of health': [
                f"{date_str_iso}_board_of_health_agenda.pdf",
                f"{date_str_mdy}_board_of_health_agenda.pdf",
                f"board_of_health_{date_str_iso}_agenda.pdf"
            ],
            'school committee': [
                f"{date_str_iso}_school_committee_agenda.pdf",
                f"{date_str_mdy}_school_committee_agenda.pdf",
                f"school_committee_{date_str_iso}_agenda.pdf"
            ],
            'finance committee': [
                f"{date_str_iso}_finance_committee_agenda.pdf",
                f"{date_str_mdy}_finance_committee_agenda.pdf",
                f"finance_committee_{date_str_iso}_agenda.pdf"
            ],
            'redevelopment authority': [
                f"{date_str_iso}_redevelopment_authority_agenda.pdf",
                f"{date_str_mdy}_redevelopment_authority_agenda.pdf",
                f"redevelopment_authority_{date_str_iso}_agenda.pdf"
            ],
            'tif board': [
                f"{date_str_iso}_tif_board_agenda.pdf",
                f"{date_str_mdy}_tif_board_agenda.pdf",
                f"tif_board_{date_str_iso}_agenda.pdf"
            ],
            'tax increment financing': [
                f"{date_str_iso}_tif_board_agenda.pdf",
                f"{date_str_mdy}_tif_board_agenda.pdf",
                f"tif_board_{date_str_iso}_agenda.pdf"
            ],
        }
        
        # Try to match meeting type and return first pattern (most common format)
        for key, patterns in agenda_patterns.items():
            if key in combined_text:
                # Return the first (most common) pattern
                return f"{base_url}/{patterns[0]}"
        
        # Fallback: try generic pattern with sanitized board name
        # Extract board name (before @ symbol if present)
        board_name = title.split('@')[0].strip().lower()
        # Remove common words
        board_name = board_name.replace('fall river', '').replace('board', '').replace('committee', '').replace('meeting', '').strip()
        # Create slug
        board_slug = board_name.replace(' ', '_').replace('-', '_').replace("'", '').replace('.', '')
        if board_slug and len(board_slug) > 2:
            # Try most common format first
            generic_url = f"{base_url}/{date_str_iso}_{board_slug}_agenda.pdf"
            return generic_url
        
        # Final fallback: link to calendar page with date filter
        # This ensures users can find the agenda even if PDF URL construction fails
        date_param = meeting_datetime.strftime('%Y-%m-%d')
        return f"https://www.fallriverma.gov/calendar.php?date={date_param}#calendar"
    
    def generate_ics_file(self, meeting: Dict) -> str:
        """Generate an .ics file content for a single meeting
        
        Args:
            meeting: Meeting dictionary
            
        Returns:
            String content of .ics file
        """
        from icalendar import Event
        
        cal = Calendar()
        cal.add('prodid', '-//Fall River News Aggregator//Meetings Calendar//EN')
        cal.add('version', '2.0')
        
        event = Event()
        event.add('uid', meeting['id'])
        event.add('summary', meeting['title'])
        
        # Add datetime - ensure it has timezone info
        dt = meeting.get('datetime')
        if dt:
            # Handle string datetime
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
                except:
                    try:
                        dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
                    except:
                        logger.warning(f"Could not parse datetime string: {dt}")
                        dt = None
            
            if dt:
                # If datetime doesn't have timezone, assume UTC
                if isinstance(dt, datetime) and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                event.add('dtstart', dt)
                # Set end time to 1 hour after start (typical meeting duration)
                from datetime import timedelta
                dt_end = dt + timedelta(hours=1)
                event.add('dtend', dt_end)
        else:
            # Fallback to date-only if no datetime
            date_str = meeting.get('date', '')
            if date_str:
                try:
                    dt_start = datetime.strptime(date_str, '%Y-%m-%d').date()
                    event.add('dtstart', dt_start)
                    event.add('dtend', dt_start)
                except:
                    pass
        
        if meeting.get('location'):
            event.add('location', meeting['location'])
        
        if meeting.get('description'):
            event.add('description', meeting['description'])
        
        cal.add_component(event)
        
        return cal.to_ical().decode('utf-8')

