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

    # #region agent log
    import socket
    try:
        with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
            import json
            hostname = socket.gethostname()
            localhost_ip = socket.gethostbyname('localhost')
            try:
                all_interfaces = [str(addr[4][0]) for addr in socket.getaddrinfo(hostname, None)]
            except:
                all_interfaces = []
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "A",
                "location": "server.py:49",
                "message": "Server startup - checking network configuration",
                "data": {
                    "host": "0.0.0.0",
                    "port": 8000,
                    "threaded": True,
                    "hostname": hostname,
                    "localhost_ip": localhost_ip,
                    "all_interfaces": all_interfaces
                },
                "timestamp": int(time.time() * 1000)
            }
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        pass
    # #endregion agent log

    print("=" * 60)
    print("Fall River News Aggregator - Unified Server")
    print("=" * 60)
    print("Starting server on http://0.0.0.0:8000 (all interfaces)")
    print("Access via:")
    print("  - http://127.0.0.1:8000")
    print("  - http://localhost:8000")
    print("  - http://192.168.1.33:8000 (if on local network)")
    print("Website: http://127.0.0.1:8000")
    print("Admin Panel: http://127.0.0.1:8000/admin")
    print("Admin credentials configured via environment variables")
    print("Automatic regeneration enabled for website pages")

    # #region agent log
    try:
        with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
            import json
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "B",
                "location": "server.py:66",
                "message": "About to start Flask server",
                "data": {
                    "host": "0.0.0.0",
                    "port": 8000,
                    "threaded": True,
                    "debug": False
                },
                "timestamp": int(time.time() * 1000)
            }
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        pass
    # #endregion agent log

    app.run(host='0.0.0.0', port=8000, debug=False, threaded=True)

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
    # NO CACHE for HTML files during development/debugging
    elif path.endswith('.html'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['Last-Modified'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
        response.headers['ETag'] = f'no-cache-{int(datetime.now().timestamp())}'
    # Cache JS, CSS, images for 1 hour (static assets)
    elif any(path.endswith(ext) for ext in ['.js', '.css', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.webp']):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    # Default: no cache for unknown types
    else:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'

    return response

# Duplicate if __name__ == '__main__' block removed - server starts in first block above