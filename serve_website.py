"""
Web server that serves the static website and triggers regeneration if needed
"""
import os
import sqlite3
import time
import subprocess
import sys
import json
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
_last_regeneration_start = None  # Track when regen started to prevent rapid-fire triggers


class RegeneratingHTTPRequestHandler(SimpleHTTPRequestHandler):
    """HTTP handler that checks if regeneration is needed before serving pages"""
    
    def end_headers(self):
        """Override to add cache headers for static files"""
        # Add cache headers for static files (frontend caching enabled)
        path = self.path.lower()
        
        # No cache for root redirect and API endpoints
        if self.path == '/' or self.path == '' or self.path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        # Cache HTML files for 5 minutes (content changes frequently)
        elif path.endswith('.html'):
            self.send_header('Cache-Control', 'public, max-age=300')
        # Cache JS, CSS, images for 1 hour (static assets)
        elif any(path.endswith(ext) for ext in ['.js', '.css', '.jpg', '.jpeg', '.png', '.gif', '.svg', '.ico', '.webp']):
            self.send_header('Cache-Control', 'public, max-age=3600')
        # Default: no cache for unknown types
        else:
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        
        super().end_headers()
    
    def do_GET(self):
        """Handle GET requests - check if regeneration needed"""
        # Handle root path - serve main index.html
        if self.path == '/' or self.path == '':
            self.path = '/index.html'

        # Handle API proxy endpoint
        if self.path.startswith('/api/proxy-rss'):
            self._handle_rss_proxy()
            return

        # For any other path that doesn't exist, serve the main index.html
        # This handles /02720 and any other zip codes by serving the single page
        requested_path = os.path.join(self.directory, self.path.lstrip('/'))
        if not os.path.exists(requested_path):
            self.path = '/index.html'

        # Check if we need to regenerate (non-blocking)
        if self._should_regenerate():
            # Trigger regeneration asynchronously - don't wait!
            self._trigger_regeneration_async()

        # Serve the file immediately (don't wait for regeneration)
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
            # Get the parent directory (we're serving from build)
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
            logger.info(f"Auto-regenerate flag is {'enabled' if auto_regenerate else 'disabled'}")
            
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
            logger.info(f"Regenerate interval: {interval_minutes} min, regenerate_on_load: {regenerate_on_load}")
            
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
            
            # Check if regeneration is already running (prevent duplicate triggers)
            global _regenerating
            if _regenerating:
                logger.info("Regeneration already in progress, skipping check")
                return False
            
            if datetime.now() >= next_time:
                logger.info(f"Website is out of date (last: {last_time}, interval: {interval_minutes} min) - will trigger quick regen")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking regeneration status: {e}")
            return False
    
    def _trigger_regeneration_async(self):
        """Trigger website regeneration asynchronously - returns immediately, doesn't block"""
        global _regenerating, _last_regeneration_start
        
        with _regeneration_lock:
            # Check if regeneration is already running
            if _regenerating:
                logger.info("Regeneration already in progress, serving current page immediately...")
                return
            
            # Prevent rapid-fire regenerations (wait at least 30 seconds between triggers)
            if _last_regeneration_start:
                time_since_start = (datetime.now() - _last_regeneration_start).total_seconds()
                if time_since_start < 30:
                    logger.info(f"Regeneration started {time_since_start:.0f}s ago, skipping duplicate trigger")
                    return
            
            _regenerating = True
            _last_regeneration_start = datetime.now()
        
        # Start regeneration in background thread - don't block!
        def regenerate_in_background():
            global _regenerating, _last_regeneration_start
            try:
                logger.info("=" * 60)
                logger.info("Website is out of date - triggering QUICK regeneration in background")
                logger.info("Page served immediately - regeneration happening asynchronously")
                logger.info("=" * 60)

                # Get the parent directory (we're serving from build)
                parent_dir = os.path.dirname(os.path.abspath(os.getcwd()))
                if not parent_dir:
                    parent_dir = os.path.join(os.getcwd(), '..')
                
                logger.info(f"Starting quick regeneration in directory: {parent_dir}")
                logger.info(f"Running command: {sys.executable} quick_regenerate.py")
                
                # Use quick_regenerate.py instead of main.py --once for fast regeneration
                # This skips fetching new articles and just regenerates HTML/CSS/JS
                import subprocess as sp
                process = sp.Popen(
                    [sys.executable, 'quick_regenerate.py'],
                    cwd=parent_dir,
                    stdout=sp.PIPE,
                    stderr=sp.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                # Stream output line by line
                logger.info("--- Quick Regeneration Output (Background) ---")
                output_lines = []
                start_time = time.time()
                
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        logger.info(f"  {line}")
                        output_lines.append(line)
                        sys.stdout.flush()
                
                process.wait()
                elapsed_time = time.time() - start_time
                
                logger.info("--- End Quick Regeneration Output ---")
                
                if process.returncode == 0:
                    # Update last regeneration time
                    conn = sqlite3.connect(os.path.join(parent_dir, DATABASE_CONFIG.get("path", "fallriver_news.db")))
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR REPLACE INTO admin_settings (key, value)
                        VALUES ('last_regeneration_time', ?)
                    ''', (datetime.now().isoformat(),))
                    conn.commit()
                    conn.close()
                    
                    logger.info(f"✓ Quick regeneration completed successfully in {elapsed_time:.1f}s")
                else:
                    logger.error(f"✗ Quick regeneration failed with exit code {process.returncode}")
                    logger.error("Last 10 lines of output:")
                    for line in output_lines[-10:]:
                        logger.error(f"  {line}")
                    
            except Exception as e:
                logger.error(f"Error during background regeneration: {e}", exc_info=True)
            finally:
                with _regeneration_lock:
                    _regenerating = False
                    _last_regeneration_start = None
        
        # Start background thread - returns immediately!
        thread = threading.Thread(target=regenerate_in_background, daemon=True)
        thread.start()
        logger.info("Background regeneration thread started - page served immediately")
    
    def log_message(self, format, *args):
        """Override to use our logger"""
        logger.info(f"{self.address_string()} - {format % args}")


def serve(port=8000, directory="build"):
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
    parser.add_argument("--dir", type=str, default="build", help="Directory to serve")
    args = parser.parse_args()
    
    serve(port=args.port, directory=args.dir)

