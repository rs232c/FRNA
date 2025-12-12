#!/usr/bin/env python3
"""
Unified server entry point for Fall River News Aggregator
"""
import os
import sqlite3
import time
import subprocess
import sys
import json
import threading
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

from flask import Flask, request, send_from_directory, jsonify
from dotenv import load_dotenv

from admin.routes import app
from admin.services import init_admin_db, get_db
from config import DATABASE_CONFIG

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global flag to prevent concurrent regenerations
_regenerating = False
_regeneration_lock = threading.Lock()
_last_regeneration_start = None

# The admin/routes.py already handles static file serving, so we don't need to duplicate it here

if __name__ == '__main__':
    # Initialize admin database
    init_admin_db()

    print("=" * 60)
    print("Fall River News Aggregator - Unified Server")
    print("=" * 60)
    print("Starting server on http://127.0.0.1:8000")
    print("Website: http://127.0.0.1:8000")
    print("Admin Panel: http://127.0.0.1:8000/admin")
    print("Admin credentials configured via environment variables")
    print("Automatic regeneration enabled for website pages")

    app.run(host='127.0.0.1', port=8000, debug=False)

def _should_regenerate():
    """Check if website regeneration is needed"""
    global _last_regeneration_start

    try:
        # Don't check too frequently (prevent rapid-fire regenerations)
        if _last_regeneration_start and (datetime.now() - _last_regeneration_start).seconds < 30:
            return False

        with get_db() as conn:
            cursor = conn.cursor()

            # Check if regeneration is enabled in settings
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('regenerate_on_load',))
            row = cursor.fetchone()
            if not row or row[0] != '1':
                return False

            # Check last regeneration time
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            row = cursor.fetchone()
            if not row:
                return True

            try:
                last_regen = datetime.fromisoformat(row[0])
                # Regenerate if it's been more than 10 minutes since last regeneration
                return (datetime.now() - last_regen).seconds > 600
            except (ValueError, TypeError):
                return True

    except Exception as e:
        logger.warning(f"Error checking regeneration need: {e}")
        return False

def _trigger_regeneration():
    """Trigger website regeneration in background"""
    global _regenerating, _last_regeneration_start

    with _regeneration_lock:
        if _regenerating:
            return  # Already regenerating

        _regenerating = True
        _last_regeneration_start = datetime.now()

        def regenerate():
            global _regenerating
            try:
                logger.info("=" * 60)
                logger.info("Website is out of date - triggering QUICK regeneration in background")
                logger.info("Page served immediately - regeneration happening asynchronously")
                logger.info("=" * 60)

                # Run quick_regenerate.py
                result = subprocess.run([
                    sys.executable, 'scripts/deployment/quick_regenerate.py'
                ], capture_output=True, text=True, timeout=300)

                if result.returncode == 0:
                    logger.info("Background regeneration completed successfully")
                else:
                    logger.error(f"Background regeneration failed: {result.stderr}")

            except subprocess.TimeoutExpired:
                logger.error("Background regeneration timed out")
            except Exception as e:
                logger.error(f"Error during background regeneration: {e}")
            finally:
                _regenerating = False

        # Start regeneration in background thread
        thread = threading.Thread(target=regenerate, daemon=True)
        thread.start()

# Add cache control headers
@app.after_request
def add_cache_headers(response):
    """Add appropriate cache headers"""
    path = request.path.lower()

    # No cache for root redirect and API endpoints
    if request.path == '/' or request.path == '' or request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    # Cache HTML files for 5 minutes (content changes frequently)
    elif path.endswith('.html'):
        response.headers['Cache-Control'] = 'public, max-age=300'
    # Cache JS, CSS, images for 1 hour (static assets)
    elif any(path.endswith(ext) for ext in ['.js', '.css', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.webp']):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    # Default: no cache for unknown types
    else:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'

    return response

if __name__ == '__main__':
    # Initialize admin database
    init_admin_db()

    print("=" * 60)
    print("Fall River News Aggregator - Unified Server")
    print("=" * 60)
    print("Starting server on http://127.0.0.1:8000")
    print("Website: http://127.0.0.1:8000")
    print("Admin Panel: http://127.0.0.1:8000/admin")
    print("Admin credentials configured via environment variables")
    print("Automatic regeneration enabled for website pages")

    app.run(host='127.0.0.1', port=8000, debug=False)