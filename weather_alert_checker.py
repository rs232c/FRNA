#!/usr/bin/env python3
"""
Weather Alert Status Checker
Checks NWS website for active weather alerts and updates system status
"""

import sqlite3
import asyncio
import aiohttp
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

class WeatherAlertChecker:
    """Checks NWS for active weather alerts and manages alert status"""

    def __init__(self):
        self.nws_url = "https://forecast.weather.gov/MapClick.php?lat=41.7199586&lon=-71.139299"
        self.db_path = "fallriver_news.db"

    async def check_alerts_async(self) -> dict:
        """Check NWS website for active weather alerts"""
        alerts = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.nws_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        html = await response.text()
                        alerts = self._parse_alerts(html)
                    else:
                        logger.warning(f"NWS request failed with status {response.status}")

        except Exception as e:
            logger.error(f"Error checking weather alerts: {e}")

        # Determine overall alert status
        has_active_alerts = len(alerts) > 0
        highest_priority = 'info'

        if has_active_alerts:
            priorities = [alert['priority'] for alert in alerts]
            if 'critical' in priorities:
                highest_priority = 'critical'
            elif 'warning' in priorities:
                highest_priority = 'warning'

        return {
            'has_alerts': has_active_alerts,
            'alert_count': len(alerts),
            'highest_priority': highest_priority,
            'alerts': alerts,
            'checked_at': datetime.now().isoformat(),
            'source': 'NWS'
        }

    def _parse_alerts(self, html: str) -> list:
        """Parse weather alerts from NWS HTML"""
        alerts = []

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Look for hazardous weather conditions
            hazardous_sections = soup.find_all(['div', 'section'], class_=lambda x: x and any(term in ' '.join(x).lower() for term in ['hazard', 'alert', 'warning']))

            for section in hazardous_sections:
                # Look for alert items within the section
                alert_items = section.find_all(['li', 'div', 'p'], class_=lambda x: x and any(term in ' '.join(x).lower() for term in ['alert', 'warning', 'hazard']))

                for item in alert_items:
                    text = item.get_text().strip()
                    if text and len(text) > 10:  # Filter very short items
                        # Skip if it looks like general information
                        if not any(skip in text.lower() for skip in ['forecast', 'outlook', 'probability', 'chance']):
                            alerts.append({
                                'title': text[:100],
                                'description': text,
                                'priority': self._determine_priority(text),
                                'type': 'weather'
                            })

            # Also check for specific hazard boxes
            hazard_boxes = soup.find_all('div', class_=lambda x: x and 'hazard' in x.lower())
            for box in hazard_boxes:
                box_text = box.get_text().strip()
                if box_text and len(box_text) > 15 and box_text not in [a['description'] for a in alerts]:
                    alerts.append({
                        'title': box_text[:100],
                        'description': box_text,
                        'priority': self._determine_priority(box_text),
                        'type': 'weather'
                    })

        except Exception as e:
            logger.error(f"Error parsing alerts: {e}")

        return alerts[:10]  # Limit to 10 alerts

    def _determine_priority(self, text: str) -> str:
        """Determine alert priority from text"""
        text_lower = text.lower()

        # Critical alerts
        if any(word in text_lower for word in [
            'tornado warning', 'flash flood warning', 'severe thunderstorm warning',
            'hurricane warning', 'evacuation', 'life-threatening', 'immediate danger'
        ]):
            return 'critical'

        # Warning alerts
        if any(word in text_lower for word in [
            'warning', 'emergency', 'severe', 'dangerous', 'hazardous conditions',
            'travel ban', 'road closure', 'shelter in place'
        ]):
            return 'warning'

        # Watch alerts
        if any(word in text_lower for word in [
            'watch', 'advisory', 'alert', 'hazard', 'caution'
        ]):
            return 'warning'

        return 'info'

    def update_alert_status(self, alert_status: dict):
        """Update the alert status in the database"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Store current alert status
            cursor.execute('''
                INSERT OR REPLACE INTO admin_settings (key, value)
                VALUES (?, ?)
            ''', ('weather_alert_status', str(alert_status['has_alerts'])))

            cursor.execute('''
                INSERT OR REPLACE INTO admin_settings (key, value)
                VALUES (?, ?)
            ''', ('weather_alert_count', str(alert_status['alert_count'])))

            cursor.execute('''
                INSERT OR REPLACE INTO admin_settings (key, value)
                VALUES (?, ?)
            ''', ('weather_alert_priority', alert_status['highest_priority']))

            cursor.execute('''
                INSERT OR REPLACE INTO admin_settings (key, value)
                VALUES (?, ?)
            ''', ('weather_alert_last_checked', alert_status['checked_at']))

            # Store alert details as JSON
            import json
            cursor.execute('''
                INSERT OR REPLACE INTO admin_settings (key, value)
                VALUES (?, ?)
            ''', ('weather_alert_details', json.dumps(alert_status['alerts'])))

            conn.commit()
            conn.close()

            logger.info(f"Updated weather alert status: {alert_status['has_alerts']} alerts, priority: {alert_status['highest_priority']}")

        except Exception as e:
            logger.error(f"Error updating alert status: {e}")

    def get_current_alert_status(self) -> dict:
        """Get current alert status from database"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT key, value FROM admin_settings WHERE key LIKE "weather_alert_%"')

            status = {
                'has_alerts': False,
                'alert_count': 0,
                'highest_priority': 'info',
                'last_checked': None,
                'alerts': []
            }

            for row in cursor.fetchall():
                key = row['key']
                value = row['value']

                if key == 'weather_alert_status':
                    status['has_alerts'] = value == 'True'
                elif key == 'weather_alert_count':
                    status['alert_count'] = int(value) if value.isdigit() else 0
                elif key == 'weather_alert_priority':
                    status['highest_priority'] = value
                elif key == 'weather_alert_last_checked':
                    status['last_checked'] = value
                elif key == 'weather_alert_details':
                    try:
                        import json
                        status['alerts'] = json.loads(value)
                    except:
                        status['alerts'] = []

            conn.close()
            return status

        except Exception as e:
            logger.error(f"Error getting alert status: {e}")
            return {
                'has_alerts': False,
                'alert_count': 0,
                'highest_priority': 'info',
                'last_checked': None,
                'alerts': []
            }

    async def check_and_update_async(self):
        """Check alerts and update status"""
        logger.info("Checking NWS for active weather alerts...")
        alert_status = await self.check_alerts_async()
        self.update_alert_status(alert_status)
        return alert_status


async def main():
    """Main function for testing"""
    checker = WeatherAlertChecker()

    print("Checking weather alerts...")
    status = await checker.check_and_update_async()

    print(f"Active alerts: {status['has_alerts']}")
    print(f"Alert count: {status['alert_count']}")
    print(f"Highest priority: {status['highest_priority']}")
    print(f"Alerts found: {len(status['alerts'])}")

    for alert in status['alerts'][:3]:  # Show first 3
        print(f"  - {alert['title']} (priority: {alert['priority']})")


if __name__ == "__main__":
    asyncio.run(main())