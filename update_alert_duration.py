#!/usr/bin/env python3
import sqlite3
import sys
sys.path.append('.')
from ingestors.nws_weather_alerts_ingestor import NWSWeatherAlertsIngestor

# Get the existing alert content and parse its duration
conn = sqlite3.connect('fallriver_news.db')
cursor = conn.cursor()

cursor.execute('SELECT id, content FROM articles WHERE id = 5335')
row = cursor.fetchone()

if row:
    alert_id = row[0]
    content = row[1]

    print(f"Alert content: {content[:200]}...")

    # Parse duration from content
    ingestor = NWSWeatherAlertsIngestor({})
    duration_info = ingestor._parse_alert_duration(content)

    print(f"Parsed duration: {duration_info}")

    if duration_info.get('start_time') and duration_info.get('end_time'):
        # Update the database
        cursor.execute('''
            UPDATE articles
            SET alert_start_time = ?, alert_end_time = ?
            WHERE id = ?
        ''', (duration_info['start_time'], duration_info['end_time'], alert_id))

        conn.commit()
        print(f"Updated alert {alert_id} with duration information")
    else:
        print("Could not parse duration from alert content")

conn.close()