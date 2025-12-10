"""
Web server that serves the static website and triggers regeneration if needed
"""
import os
import sqlite3
import time
import subprocess
import sys
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
import logging
import urllib.request
import urllib.error

from config import DATABASE_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global flag to prevent concurrent regenerations
_regenerating = False
_regeneration_lock = threading.Lock()


class RegeneratingHTTPRequestHandler(SimpleHTTPRequestHandler):
    """HTTP handler that checks if regeneration is needed before serving pages"""
    
    def do_GET(self):
        """Handle GET requests - check if regeneration needed"""
        # Handle API proxy endpoint
        if self.path.startswith('/api/proxy-rss'):
            self._handle_rss_proxy()
            return
        
        # Check if we need to regenerate
        if self._should_regenerate():
            # Trigger regeneration and wait for it to complete
            self._trigger_regeneration()
        
        # Serve the file normally
        return super().do_GET()
    
    def _handle_rss_proxy(self):
        """Proxy RSS feeds to avoid CORS issues"""
        try:
            # Parse query parameters
            parsed_path = urlparse(self.path)
            query_params = parse_qs(parsed_path.query)
            rss_url = query_params.get('url', [None])[0]
            
            if not rss_url:
                self.send_response(400)
                self.send_header('Content-type', 'text/plain')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'Missing url parameter')
                return
            
            # Fetch RSS feed
            req = urllib.request.Request(rss_url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    rss_data = response.read()
                    
                    # Send response
                    self.send_response(200)
                    self.send_header('Content-type', 'application/rss+xml; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Access-Control-Allow-Methods', 'GET')
                    self.end_headers()
                    self.wfile.write(rss_data)
            except urllib.error.HTTPError as e:
                logger.error(f"HTTP error fetching RSS: {e}")
                self.send_response(e.code)
                self.send_header('Content-type', 'text/plain')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f'Error fetching RSS: {e}'.encode())
            except Exception as e:
                logger.error(f"Error fetching RSS: {e}")
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(f'Error: {str(e)}'.encode())
                
        except Exception as e:
            logger.error(f"Error in RSS proxy: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(f'Internal server error: {str(e)}'.encode())
    
    def _should_regenerate(self):
        """Check if website needs regeneration based on admin settings"""
        try:
            # Get the parent directory (we're serving from website_output)
            parent_dir = os.path.dirname(os.path.abspath(os.getcwd()))
            if not parent_dir:
                parent_dir = os.path.join(os.getcwd(), '..')
            
            db_path = os.path.join(parent_dir, DATABASE_CONFIG.get("path", "fallriver_news.db"))
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Get regenerate settings
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('auto_regenerate',))
            row = cursor.fetchone()
            auto_regenerate = row[0] == '1' if row else True
            
            if not auto_regenerate:
                conn.close()
                return False
            
            # Get regenerate interval
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('regenerate_interval',))
            row = cursor.fetchone()
            interval_minutes = int(row[0]) if row and row[0] else 10
            
            # Get regenerate_on_load setting
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('regenerate_on_load',))
            row = cursor.fetchone()
            regenerate_on_load = row[0] == '1' if row else False
            
            # Check last regeneration time
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            row = cursor.fetchone()
            
            if regenerate_on_load:
                # Always regenerate if this setting is enabled
                conn.close()
                return True
            
            if not row or not row[0]:
                # Never regenerated, do it now
                conn.close()
                return True
            
            # Check if enough time has passed
            last_time = datetime.fromisoformat(row[0])
            next_time = last_time + timedelta(minutes=interval_minutes)
            
            conn.close()
            
            if datetime.now() >= next_time:
                logger.info(f"Website is out of date (last: {last_time}, interval: {interval_minutes} min)")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking regeneration status: {e}")
            return False
    
    def _trigger_regeneration(self):
        """Trigger website regeneration - wait for it to complete"""
        global _regenerating
        
        with _regeneration_lock:
            if _regenerating:
                logger.info("Regeneration already in progress, serving current page...")
                return
            
            _regenerating = True
        
        try:
            logger.info("=" * 60)
            logger.info("Website is out of date - triggering regeneration before serving page")
            logger.info("=" * 60)
            
            # Get the parent directory (we're serving from website_output)
            parent_dir = os.path.dirname(os.path.abspath(os.getcwd()))
            if not parent_dir:
                parent_dir = os.path.join(os.getcwd(), '..')
            
            # Run main.py --once to regenerate (synchronously so page is fresh)
            result = subprocess.run(
                [sys.executable, 'main.py', '--once'],
                cwd=parent_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                # Update last regeneration time
                conn = sqlite3.connect(os.path.join(parent_dir, DATABASE_CONFIG.get("path", "fallriver_news.db")))
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO admin_settings (key, value)
                    VALUES ('last_regeneration_time', ?)
                ''', (datetime.now().isoformat(),))
                conn.commit()
                conn.close()
                
                logger.info("✓ Website regenerated successfully - serving fresh content")
            else:
                logger.error(f"✗ Regeneration failed: {result.stderr}")
                logger.info("Serving existing content despite regeneration failure")
                
        except subprocess.TimeoutExpired:
            logger.error("Regeneration timed out after 5 minutes - serving existing content")
        except Exception as e:
            logger.error(f"Error during regeneration: {e} - serving existing content")
        finally:
            _regenerating = False
    
    def log_message(self, format, *args):
        """Override to use our logger"""
        logger.info(f"{self.address_string()} - {format % args}")


def serve(port=8000, directory="website_output"):
    """Serve the website with auto-regeneration"""
    # Store original directory
    original_dir = os.getcwd()
    
    # Change to output directory for serving
    if not os.path.isabs(directory):
        directory = os.path.join(original_dir, directory)
    
    os.chdir(directory)
    
    server_address = ('', port)
    httpd = HTTPServer(server_address, RegeneratingHTTPRequestHandler)
    
    logger.info("=" * 60)
    logger.info(f"Serving website on http://localhost:{port}")
    logger.info("Website will auto-regenerate when out of date on page load")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down server...")
        httpd.shutdown()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Serve website with auto-regeneration")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve on")
    parser.add_argument("--dir", type=str, default="website_output", help="Directory to serve")
    args = parser.parse_args()
    
    serve(port=args.port, directory=args.dir)

