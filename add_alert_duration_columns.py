#!/usr/bin/env python3
"""
Add alert_start_time and alert_end_time columns to the articles table
for automatic alert expiration based on duration
"""

import sqlite3
import logging
from config import DATABASE_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_alert_duration_columns():
    """Add alert duration columns to articles table"""
    try:
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        cursor = conn.cursor()

        # Check if columns already exist
        cursor.execute("PRAGMA table_info(articles)")
        columns = [row[1] for row in cursor.fetchall()]

        # Add alert_start_time column if it doesn't exist
        if 'alert_start_time' not in columns:
            logger.info("Adding alert_start_time column...")
            cursor.execute('''
                ALTER TABLE articles ADD COLUMN alert_start_time TEXT
            ''')
            logger.info("✅ Added alert_start_time column")
        else:
            logger.info("alert_start_time column already exists")

        # Add alert_end_time column if it doesn't exist
        if 'alert_end_time' not in columns:
            logger.info("Adding alert_end_time column...")
            cursor.execute('''
                ALTER TABLE articles ADD COLUMN alert_end_time TEXT
            ''')
            logger.info("✅ Added alert_end_time column")
        else:
            logger.info("alert_end_time column already exists")

        conn.commit()
        conn.close()

        logger.info("✅ Database schema updated successfully")

    except Exception as e:
        logger.error(f"❌ Error updating database schema: {e}")
        raise

if __name__ == "__main__":
    add_alert_duration_columns()