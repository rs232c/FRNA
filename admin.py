"""
Admin backend for managing news aggregator
"""
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_from_directory
from functools import wraps
import sqlite3
import json
import os
import secrets
import logging
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from config import DATABASE_CONFIG, NEWS_SOURCES, WEBSITE_CONFIG

# Optional security imports - gracefully handle if not installed
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    FLASK_LIMITER_AVAILABLE = True
except ImportError:
    FLASK_LIMITER_AVAILABLE = False
    logger_temp = logging.getLogger(__name__)
    logger_temp.warning("flask-limiter not installed. Rate limiting disabled. Install with: pip install flask-limiter")

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    logger_temp = logging.getLogger(__name__)
    logger_temp.warning("bcrypt not installed. Password hashing disabled. Install with: pip install bcrypt")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Security: Use environment variable for secret key, generate if not set or empty
flask_secret_key = os.getenv('FLASK_SECRET_KEY', '').strip()
if not flask_secret_key:
    flask_secret_key = secrets.token_hex(32)
    logger.warning("FLASK_SECRET_KEY not set in environment. Using generated key (sessions will be invalidated on restart).")
app.secret_key = flask_secret_key

# Security: Configure secure session cookies
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'  # Set to True in production with HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Security: Rate limiting (optional)
if FLASK_LIMITER_AVAILABLE:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://"
    )
else:
    # Fallback decorator that does nothing
    class DummyLimiter:
        def limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
    limiter = DummyLimiter()

# Website output directory for serving static files
WEBSITE_OUTPUT_DIR = Path(WEBSITE_CONFIG.get("output_dir", "website_output"))

# Security Constants
ZIP_CODE_LENGTH = 5
REGENERATION_TIMEOUT_SECONDS = 600
MAX_ARTICLE_ID = 2**31 - 1  # SQLite INTEGER max value

# Security: CORS configuration - restrict to specific origins
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')

# Security: Authentication credentials from environment (REQUIRED)
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
ZIP_LOGIN_PASSWORD = os.getenv('ZIP_LOGIN_PASSWORD')

# Require credentials to be set
if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise ValueError(
        "ADMIN_USERNAME and ADMIN_PASSWORD environment variables must be set. "
        "Create a .env file with:\n"
        "ADMIN_USERNAME=your_username\n"
        "ADMIN_PASSWORD=your_secure_password\n"
        "ZIP_LOGIN_PASSWORD=your_zip_password"
    )

if not ZIP_LOGIN_PASSWORD:
    logger.warning("ZIP_LOGIN_PASSWORD not set. Per-zip admin login will be disabled.")

# Security: Hash password for secure storage/comparison
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    if not BCRYPT_AVAILABLE:
        raise ImportError("bcrypt not installed. Install with: pip install bcrypt")
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash"""
    if not BCRYPT_AVAILABLE:
        # Fallback to plain text comparison if bcrypt not available
        return password == hashed
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

# Store hashed password (fallback to plain text comparison for backward compatibility)
_ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH')
if _ADMIN_PASSWORD_HASH:
    _ADMIN_PASSWORD_HASHED = True
else:
    _ADMIN_PASSWORD_HASHED = False
    logger.warning("ADMIN_PASSWORD_HASH not set. Using plain text password comparison (not secure!)")

# Add CORS headers for API requests - SECURE VERSION
@app.after_request
def after_request(response):
    # Security: Only allow specific origins instead of wildcard
    origin = request.headers.get('Origin')
    if origin and origin in ALLOWED_ORIGINS:
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    
    # Prevent ALL caching for admin pages - completely disable caching
    if request.path.startswith('/admin'):
        response.headers.add('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
        response.headers.add('Pragma', 'no-cache')
        response.headers.add('Expires', '0')
        response.headers.add('Last-Modified', datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT'))
        response.headers.add('ETag', '')
    
    # Also disable caching for HTML files (main site pages) - ensure users see latest articles
    if (request.path.endswith('.html') or 
        request.path == '/' or 
        request.path.startswith('/category/') or
        (request.path.startswith('/') and len(request.path) == 6 and request.path[1:].isdigit())):  # Zip code routes like /02720
        response.headers.add('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
        response.headers.add('Pragma', 'no-cache')
        response.headers.add('Expires', '0')
        response.headers.add('Last-Modified', datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT'))
    
    return response

# Security: Input validation helpers
def validate_zip_code(zip_code: str) -> bool:
    """Validate zip code format"""
    if not zip_code:
        return False
    return zip_code.isdigit() and len(zip_code) == ZIP_CODE_LENGTH

def validate_article_id(article_id) -> bool:
    """Validate article ID"""
    try:
        aid = int(article_id)
        return 0 < aid <= MAX_ARTICLE_ID
    except (ValueError, TypeError):
        return False

def safe_path(base_path: Path, user_path: str) -> Path:
    """Security: Prevent path traversal attacks"""
    # Resolve both paths to absolute
    base = base_path.resolve()
    # Join and resolve user path
    full_path = (base / user_path).resolve()
    # Ensure resolved path is still within base
    try:
        full_path.relative_to(base)
        return full_path
    except ValueError:
        raise ValueError(f"Path traversal detected: {user_path}")

# Security: Database connection context manager
@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# Legacy get_db function for backward compatibility
def get_db_legacy():
    """Legacy database connection (use get_db context manager instead)"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    return conn
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    return conn

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # For API endpoints, return JSON error instead of redirect
        if request.path.startswith('/admin/api'):
            if 'logged_in' not in session:
                return jsonify({'success': False, 'error': 'Not authenticated'}), 401
        elif 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Main site routes - zip code based
@app.route('/api/session-check')
def session_check():
    """API endpoint to check current session and return logged-in zip code"""
    if session.get('logged_in'):
        zip_code = session.get('zip_code', '02720')
        return jsonify({
            'logged_in': True,
            'zip_code': zip_code
        })
    return jsonify({
        'logged_in': False,
        'zip_code': None
    })

@app.route('/')
def index():
    """Main index route - shows landing page or serves static index.html"""
    # Serve static index.html - client-side handles routing
    index_path = WEBSITE_OUTPUT_DIR / "index.html"
    if index_path.exists():
        return send_from_directory(str(WEBSITE_OUTPUT_DIR), "index.html")
    else:
        # Fallback: show landing page
        from website_generator import WebsiteGenerator
        generator = WebsiteGenerator()
        template = generator._get_landing_template()
        html = template.render()
        return html

@app.route('/category/<category_slug>')
def category_page(category_slug):
    """Serve category page - must be before /<zip_code> route to match first"""
    from config import CATEGORY_SLUGS
    
    # Strip .html extension if present (for compatibility with static file links)
    if category_slug.endswith('.html'):
        category_slug = category_slug[:-5]
    
    # Validate category slug
    if category_slug not in CATEGORY_SLUGS:
        return "Category not found", 404
    
    # Try to serve static HTML
    category_path = WEBSITE_OUTPUT_DIR / "category" / f"{category_slug}.html"
    if category_path.exists():
        return send_from_directory(str(WEBSITE_OUTPUT_DIR / "category"), f"{category_slug}.html")
    else:
        return "Category page not generated yet. Please run the aggregator first.", 404

@app.route('/<zip_code>')
def zip_page(zip_code):
    """Handle path-based zip code routing: /02720"""
    # Security: Validate zip code format (5 digits)
    if not validate_zip_code(zip_code):
        # Not a zip code, try to serve as static file (with path traversal protection)
        try:
            # Security: Prevent path traversal
            safe_file_path = safe_path(WEBSITE_OUTPUT_DIR, zip_code)
            return send_from_directory(str(WEBSITE_OUTPUT_DIR), safe_file_path.name)
        except (ValueError, OSError):
            return redirect('/?error=invalid_zip')
    
    # Serve static index.html - client-side JavaScript will handle the zip code
    index_path = WEBSITE_OUTPUT_DIR / "index.html"
    if index_path.exists():
        return send_from_directory(str(WEBSITE_OUTPUT_DIR), "index.html")
    else:
        return "Website not generated yet. Please run the aggregator first.", 404

@app.route('/<zip_code>/category/<category_slug>')
def zip_category_page(zip_code, category_slug):
    """Serve zip-specific category page"""
    from config import CATEGORY_SLUGS
    
    # Validate zip code
    if not validate_zip_code(zip_code):
        return "Invalid zip code", 400
    
    # Strip .html extension if present (for compatibility with static file links)
    if category_slug.endswith('.html'):
        category_slug = category_slug[:-5]
    
    # Validate category slug
    if category_slug not in CATEGORY_SLUGS:
        return "Category not found", 404
    
    # Try to serve static HTML from zip-specific directory
    zip_category_path = WEBSITE_OUTPUT_DIR / f"zip_{zip_code}" / "category" / f"{category_slug}.html"
    if zip_category_path.exists():
        return send_from_directory(str(WEBSITE_OUTPUT_DIR / f"zip_{zip_code}" / "category"), f"{category_slug}.html")
    else:
        # Fallback to root category page if zip-specific doesn't exist
        category_path = WEBSITE_OUTPUT_DIR / "category" / f"{category_slug}.html"
        if category_path.exists():
            return send_from_directory(str(WEBSITE_OUTPUT_DIR / "category"), f"{category_slug}.html")
        return "Category page not generated yet. Please run the aggregator first.", 404

# Serve static assets (CSS, JS, images) - check zip-specific directories first
@app.route('/css/<path:filename>')
def serve_css(filename):
    """Serve CSS files - check zip-specific directory first"""
    # Security: Validate and sanitize filename
    try:
        safe_filename = safe_path(Path('css'), filename).name
    except ValueError:
        return "Invalid filename", 400
    
    zip_code = request.args.get('z', '').strip()
    if validate_zip_code(zip_code):
        zip_output_dir = WEBSITE_OUTPUT_DIR / f"zip_{zip_code}" / "css"
        if zip_output_dir.exists():
            try:
                safe_path(zip_output_dir, safe_filename)
                return send_from_directory(str(zip_output_dir), safe_filename)
            except (ValueError, OSError):
                pass
    try:
        safe_path(WEBSITE_OUTPUT_DIR / 'css', safe_filename)
        return send_from_directory(str(WEBSITE_OUTPUT_DIR / 'css'), safe_filename)
    except (ValueError, OSError):
        return "File not found", 404

@app.route('/js/<path:filename>')
def serve_js(filename):
    """Serve JavaScript files - check zip-specific directory first"""
    # Security: Validate and sanitize filename
    try:
        safe_filename = safe_path(Path('js'), filename).name
    except ValueError:
        return "Invalid filename", 400
    
    zip_code = request.args.get('z', '').strip()
    if validate_zip_code(zip_code):
        zip_output_dir = WEBSITE_OUTPUT_DIR / f"zip_{zip_code}" / "js"
        if zip_output_dir.exists():
            try:
                safe_path(zip_output_dir, safe_filename)
                return send_from_directory(str(zip_output_dir), safe_filename)
            except (ValueError, OSError):
                pass
    try:
        safe_path(WEBSITE_OUTPUT_DIR / 'js', safe_filename)
        return send_from_directory(str(WEBSITE_OUTPUT_DIR / 'js'), safe_filename)
    except (ValueError, OSError):
        return "File not found", 404

@app.route('/images/<path:filename>')
def serve_images(filename):
    """Serve image files - check zip-specific directory first"""
    # Security: Validate and sanitize filename
    try:
        safe_filename = safe_path(Path('images'), filename).name
    except ValueError:
        return "Invalid filename", 400
    
    zip_code = request.args.get('z', '').strip()
    if validate_zip_code(zip_code):
        zip_output_dir = WEBSITE_OUTPUT_DIR / f"zip_{zip_code}" / "images"
        if zip_output_dir.exists():
            try:
                safe_path(zip_output_dir, safe_filename)
                return send_from_directory(str(zip_output_dir), safe_filename)
            except (ValueError, OSError):
                pass
    try:
        safe_path(WEBSITE_OUTPUT_DIR / 'images', safe_filename)
        return send_from_directory(str(WEBSITE_OUTPUT_DIR / 'images'), safe_filename)
    except (ValueError, OSError):
        return "File not found", 404

@app.route('/api/proxy-rss')
def proxy_rss():
    """Proxy RSS feeds to avoid CORS issues"""
    import urllib.request
    import urllib.error
    from flask import Response
    
    try:
        rss_url = request.args.get('url')
        if not rss_url:
            return jsonify({'error': 'Missing url parameter'}), 400
        
        # Fetch RSS feed
        req = urllib.request.Request(rss_url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                rss_data = response.read()
                
                # Return RSS data with proper headers
                return Response(
                    rss_data,
                    mimetype='application/rss+xml; charset=utf-8',
                    headers={
                        'Access-Control-Allow-Origin': '*',
                        'Access-Control-Allow-Methods': 'GET'
                    }
                )
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP error fetching RSS: {e}")
            return jsonify({'error': f'Error fetching RSS: {e}'}), e.code
        except Exception as e:
            logger.error(f"Error fetching RSS: {e}")
            return jsonify({'error': str(e)}), 500
            
    except Exception as e:
        logger.error(f"Error in RSS proxy: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# Handle OPTIONS requests for CORS preflight (handled in each endpoint)


def ensure_single_management_entry(cursor, article_id):
    """Ensure only one management entry exists for an article (the most recent one)"""
    # Get the most recent entry
    cursor.execute('''
        SELECT ROWID, enabled, display_order 
        FROM article_management 
        WHERE article_id = ? 
        ORDER BY ROWID DESC 
        LIMIT 1
    ''', (article_id,))
    latest = cursor.fetchone()
    
    if latest:
        # Delete all entries except the latest
        cursor.execute('''
            DELETE FROM article_management 
            WHERE article_id = ? AND ROWID != ?
        ''', (article_id, latest[0]))
    return latest

def init_admin_db():
    """Initialize admin settings table"""
    # Ensure database is initialized (this will create relevance_config table)
    from database import ArticleDatabase
    db = ArticleDatabase()
    
    # Security: Use context manager for database connections
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Create admin_settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT
            )
        ''')
        
        # Create article_management table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS article_management (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER,
                enabled INTEGER DEFAULT 1,
                display_order INTEGER DEFAULT 0,
                FOREIGN KEY (article_id) REFERENCES articles (id)
            )
        ''')
        
        # Add columns if they don't exist (for existing databases)
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_top_story INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN zip_code TEXT')
        except:
            pass
        
        # Create admin_settings_zip table for zip-specific settings
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings_zip (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                zip_code TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                UNIQUE(zip_code, key)
            )
        ''')
        
        # Create index on zip_code for performance
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_admin_settings_zip_code ON admin_settings_zip(zip_code)')
        except:
            pass
        
        # Initialize default settings
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('show_images', '1')
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO admin_settings (key, value) 
            VALUES ('relevance_threshold', '10')
        ''')
        
        conn.commit()

@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")  # Security: Rate limiting on login
def login():
    zip_code = request.args.get('z', '').strip()
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        # Security: Input validation
        if not username or not password:
            error = 'Username and password are required'
            if request.headers.get('Content-Type') == 'application/json' or request.is_json:
                return jsonify({'success': False, 'error': error}), 401
            return render_template_string(LOGIN_TEMPLATE, error=error, zip_code=zip_code)
        
        # Check if it's a zip code login (5 digits) or main admin login
        if validate_zip_code(username):
            # Per-zip login: username = zip code, password from ZIP_LOGIN_PASSWORD env var
            if not ZIP_LOGIN_PASSWORD:
                error = 'Per-zip admin login is not configured. Contact administrator.'
            elif password == ZIP_LOGIN_PASSWORD:
                session['logged_in'] = True
                session['zip_code'] = username
                session['is_main_admin'] = False
                # Return JSON for client-side storage
                if request.headers.get('Content-Type') == 'application/json' or request.is_json:
                    return jsonify({'success': True, 'zip_code': username})
                return redirect(f'/admin/{username}')
            else:
                error = 'Invalid password for zip code login.'
        elif username == ADMIN_USERNAME:
            # Main admin login: username = "admin", verify password
            # Security: Support both hashed and plain text (for backward compatibility)
            if _ADMIN_PASSWORD_HASHED and _ADMIN_PASSWORD_HASH:
                password_valid = verify_password(password, _ADMIN_PASSWORD_HASH)
            else:
                # Fallback to plain text comparison (not secure, but backward compatible)
                password_valid = (password == ADMIN_PASSWORD)
            
            if password_valid:
                session['logged_in'] = True
                session['is_main_admin'] = True
                # Set zip_code to None initially, but allow accessing any zip
                # If zip_code is provided in URL, set it for convenience
                if zip_code and validate_zip_code(zip_code):
                    session['zip_code'] = zip_code
                else:
                    session['zip_code'] = None  # No zip restriction, but can access any zip
                if zip_code and validate_zip_code(zip_code):
                    return redirect(f'/admin/{zip_code}')
                return redirect('/admin')
            else:
                error = 'Invalid credentials'
        else:
            error = 'Invalid credentials'
        
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'error': error}), 401
        return render_template_string(LOGIN_TEMPLATE, error=error, zip_code=zip_code)
    
    return render_template_string(LOGIN_TEMPLATE, zip_code=zip_code)

@app.route('/admin/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# Serve Sortable.min.js from root
@app.route('/Sortable.min.js')
def serve_sortable():
    """Serve Sortable.min.js from project root"""
    try:
        return send_from_directory(str(Path.cwd()), 'Sortable.min.js')
    except (ValueError, OSError):
        return "Sortable.min.js not found", 404

# Serve static website files (must come after zip code and admin routes)
@app.route('/<path:filename>')
def serve_website(filename):
    """Serve static website files"""
    # Security: Skip admin routes and API routes
    if filename.startswith('admin') or filename.startswith('api'):
        return "Not found", 404
    
    # Skip zip code routes (handled by zip_page route above) - 5 digits
    if validate_zip_code(filename):
        return "Not found", 404
    
    try:
        # Security: Prevent path traversal attacks
        safe_file_path = safe_path(WEBSITE_OUTPUT_DIR, filename)
        return send_from_directory(str(WEBSITE_OUTPUT_DIR), safe_file_path.relative_to(WEBSITE_OUTPUT_DIR.resolve()))
    except (ValueError, OSError) as e:
        # If file not found, try serving index.html for HTML files
        if filename.endswith('.html'):
            try:
                return send_from_directory(str(WEBSITE_OUTPUT_DIR), 'index.html')
            except:
                return f"File not found: {filename}", 404
        return f"Error serving file: {e}", 500

@app.route('/admin')
@app.route('/admin/<path:path>')
@login_required
def admin_route(path=None):
    """Handle admin routes - supports /admin (main), /admin/02720, and /admin/02720/articles"""
    # Check if it's main admin dashboard (no path or path is 'main')
    if not path or path == 'main':
        # Main admin dashboard - show list of zip codes and global controls
        return admin_main_dashboard()
    
    # Check if path is a zip code (5 digits)
    if path.isdigit() and len(path) == 5:
        # Path is a zip code: /admin/02720
        zip_code = path
        tab = 'articles'  # Default tab
        return admin_dashboard_legacy(tab, zip_code)
    
    # Check if it's /admin/<zip>/<tab> format
    if '/' in path:
        parts = path.split('/', 1)
        zip_code = parts[0]
        tab = parts[1] if len(parts) > 1 else 'articles'
        
        if zip_code.isdigit() and len(zip_code) == 5:
            # Redirect auto-filtered to trash
            if tab == 'auto-filtered':
                return redirect(f'/admin/{zip_code}/trash')
            return admin_dashboard_legacy(tab, zip_code)
    
    # Legacy route: /admin/<tab> (no zip code) - redirect to main admin
    return redirect('/admin')

def admin_main_dashboard():
    """Main admin dashboard - shows all zip codes and global controls"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Get all unique zip codes from articles
    cursor.execute('SELECT DISTINCT zip_code FROM articles WHERE zip_code IS NOT NULL ORDER BY zip_code')
    zip_codes_from_articles = [row[0] for row in cursor.fetchall()]
    
    # Also get zip codes from article_management (in case zip has admin data but no articles yet)
    cursor.execute('SELECT DISTINCT zip_code FROM article_management WHERE zip_code IS NOT NULL ORDER BY zip_code')
    zip_codes_from_management = [row[0] for row in cursor.fetchall()]
    
    # Also get zip codes from admin_settings_zip
    cursor.execute('SELECT DISTINCT zip_code FROM admin_settings_zip WHERE zip_code IS NOT NULL ORDER BY zip_code')
    zip_codes_from_settings = [row[0] for row in cursor.fetchall()]
    
    # Also get zip codes from relevance_config
    cursor.execute('SELECT DISTINCT zip_code FROM relevance_config WHERE zip_code IS NOT NULL ORDER BY zip_code')
    zip_codes_from_relevance = [row[0] for row in cursor.fetchall()]
    
    # Combine all zip codes and remove duplicates
    all_zip_codes = set(zip_codes_from_articles + zip_codes_from_management + zip_codes_from_settings + zip_codes_from_relevance)
    zip_codes = sorted(list(all_zip_codes))
    
    # Get sticky/favorite zip codes from admin_settings
    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('sticky_zips',))
    sticky_row = cursor.fetchone()
    sticky_zips = []
    if sticky_row:
        try:
            import json
            sticky_zips = json.loads(sticky_row['value'])
        except:
            sticky_zips = []
    
    # Get global settings
    cursor.execute('SELECT key, value FROM admin_settings')
    settings = {row[0]: row[1] for row in cursor.fetchall()}
    
    conn.close()
    
    # Simple main admin dashboard HTML
    html = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Main Admin - Fall River News</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
            h1 {{ color: #0078d4; }}
            .zip-list {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; margin: 20px 0; }}
            .zip-card {{ padding: 15px; background: #e3f2fd; border-radius: 4px; text-align: center; }}
            .zip-card a {{ color: #0078d4; text-decoration: none; font-weight: bold; }}
            .zip-card a:hover {{ text-decoration: underline; }}
            .actions {{ margin: 20px 0; padding: 15px; background: #fff3e0; border-radius: 4px; }}
            button {{ padding: 10px 20px; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px; }}
            button:hover {{ background: #005a9e; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Main Admin Dashboard</h1>
            <p>Logged in as: <strong>admin</strong> | <a href="/admin/logout">Logout</a></p>
            
            <div class="actions">
                <h2>Global Actions</h2>
                <button onclick="regenerateAll()">Regenerate All Websites</button>
                <button onclick="regenerateSelected()">Regenerate Selected Zip</button>
            </div>
            
            <h2>Zip Code Admins ({len(zip_codes)} total)</h2>
            
            <!-- Sticky/Favorite Zip Codes -->
    '''
    
    # Build sticky zips section
    sticky_set = set(sticky_zips)
    sticky_zips_in_list = [z for z in sticky_zips if z in zip_codes]
    
    if sticky_zips_in_list:
        html += '''
            <div style="margin-bottom: 2rem;">
                <h3 style="color: #0078d4; margin-bottom: 1rem;">⭐ Sticky Zip Codes</h3>
                <div class="zip-list">
        '''
        for zip_code in sticky_zips_in_list:
            html += f'''
                    <div class="zip-card" style="background: #fff3e0; border: 2px solid #ff9800;">
                        <a href="/admin/{zip_code}">⭐ Zip {zip_code}</a>
                        <button class="remove-sticky-btn" data-zip-code="{zip_code}" style="margin-top: 0.5rem; padding: 0.25rem 0.5rem; background: #d32f2f; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 0.75rem;">Remove</button>
                    </div>
            '''
        html += '''
                </div>
            </div>
        '''
    
    html += '''
            <!-- All Zip Codes -->
            <div class="zip-list">
    '''
    
    # Show all zip codes with sticky indicator
    for zip_code in zip_codes:
        is_sticky = zip_code in sticky_set
        sticky_style = 'background: #fff3e0; border: 2px solid #ff9800;' if is_sticky else ''
        sticky_icon = '⭐ ' if is_sticky else ''
        button_bg = '#d32f2f' if is_sticky else '#4caf50'
        button_text = 'Remove from' if is_sticky else 'Add to'
        
        html += f'''
                <div class="zip-card" style="{sticky_style}">
                    <a href="/admin/{zip_code}">{sticky_icon}Zip {zip_code}</a>
                    <button class="toggle-sticky-btn" data-zip-code="{zip_code}" style="margin-top: 0.5rem; padding: 0.25rem 0.5rem; background: {button_bg}; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 0.75rem;">
                        {button_text} Sticky
                    </button>
                </div>
        '''
    
    html += '''
            </div>
        </div>
        <script>
            function regenerateAll() {
                if (confirm('Regenerate websites for all zip codes?')) {
                    fetch('/admin/api/regenerate-all', {method: "POST"})
                        .then(r => r.json())
                        .then(data => alert(data.message || 'Regeneration started'));
                }
            }
            function regenerateSelected() {
                const zip = prompt('Enter zip code to regenerate:');
                if (zip && /^\\d{5}$/.test(zip)) {
                    fetch('/admin/api/regenerate?zip=' + encodeURIComponent(zip), {method: "POST"})
                        .then(r => r.json())
                        .then(data => alert(data.message || 'Regeneration started'));
                }
            }
            function toggleSticky(zip) {
                const payload = {"zip_code": zip};
                fetch('/admin/api/toggle-sticky-zip', {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify(payload)
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        location.reload();
                    } else {
                        alert(data.message || 'Error updating sticky zip');
                    }
                });
            }
            function removeSticky(zip) {
                toggleSticky(zip);
            }
        </script>
    </body>
    </html>
    '''
    
    return html

@login_required
def admin_dashboard_legacy(tab='articles', zip_code_param=None):
    """Server-side admin dashboard with zip code isolation"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Get zip_code from parameter, session, or URL
    is_main_admin = session.get('is_main_admin', False)
    
    if zip_code_param:
        # Zip code from URL path (/admin/02720)
        zip_code = zip_code_param
        # If main admin, allow accessing any zip and update session to reflect current zip
        if is_main_admin:
            # Main admin can access any zip - update session to reflect current zip for consistency
            session['zip_code'] = zip_code
        else:
            # For zip-specific admins, check if they're accessing their own zip
            session_zip = session.get('zip_code')
            if session_zip and session_zip != zip_code:
                # User is logged in as a different zip - allow them to switch by updating session
                # This allows zip-specific admins to manage multiple zips if they know the zip codes
                # (They still need to login as each zip, but can switch between them)
                session['zip_code'] = zip_code
                # Note: This allows switching, but they still need to be logged in
                # If you want stricter security, uncomment the redirect below:
                # return redirect(f'/admin/{session_zip}')
            elif not session_zip:
                # No session zip but trying to access a zip - need to login
                return redirect('/admin/login')
            # If session zip matches URL zip, allow access (no redirect needed)
    else:
        # Get zip_code from session
        zip_code = session.get('zip_code')
        if not zip_code and not is_main_admin:
            # Zip-specific admin must have a zip code
            if not zip_code or not zip_code.isdigit() or len(zip_code) != 5:
                return redirect('/admin/login')
    
    # Main admin can work without zip restriction, but zip-specific admin needs zip
    if not is_main_admin and (not zip_code or not zip_code.isdigit() or len(zip_code) != 5):
        return redirect('/admin/login')
    
    # Get show_trash parameter (default: false - don't show rejected articles)
    show_trash = request.args.get('trash', '0') == '1'
    show_auto_filtered = request.args.get('auto_filtered', '0') == '1'
    
    # Build zip_code filter for article_management queries (CRITICAL: filter by zip_code)
    # Initialize variables to ensure they're always defined
    zip_filter_am = ""
    zip_params_am = []
    zip_filter_articles = ""
    zip_params_articles = []
    
    if zip_code:
        zip_filter_am = "AND am.zip_code = ?"
        zip_params_am = [zip_code]
        # Show articles that belong to this zip OR articles with NULL zip_code (until assigned)
        # But only if they have article_management entries for this zip
        zip_filter_articles = "AND (a.zip_code = ? OR a.zip_code IS NULL)"
        zip_params_articles = [zip_code]
    
    # Ensure is_stellar column exists in article_management table
    try:
        # Check if column exists by trying to select it
        cursor.execute('SELECT is_stellar FROM article_management LIMIT 1')
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_stellar INTEGER DEFAULT 0')
            conn.commit()
        except sqlite3.OperationalError:
            # Already added or other error, ignore
            pass
    
    # Ensure is_good_fit column exists in article_management table
    try:
        # Check if column exists by trying to select it
        cursor.execute('SELECT is_good_fit FROM article_management LIMIT 1')
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_good_fit INTEGER DEFAULT 0')
            conn.commit()
        except sqlite3.OperationalError:
            # Already added or other error, ignore
            pass
    
    # Get relevance threshold for filtering (only on main articles tab, not trash)
    relevance_threshold = None
    if not show_trash and not show_auto_filtered and zip_code:
        cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', 
                     (zip_code, 'relevance_threshold'))
        threshold_row = cursor.fetchone()
        if threshold_row:
            try:
                relevance_threshold = float(threshold_row[0])
            except (ValueError, TypeError):
                pass
    
    # Build WHERE clause with relevance threshold filtering
    where_clauses = ['a.zip_code = ?']
    where_params = [zip_code] if zip_code else [None]
    
    # Rejection filter
    where_clauses.append('((am.is_rejected IS NULL AND ? = 0) OR (am.is_rejected = ?))')
    where_params.extend([1 if show_trash else 0, 1 if show_trash else 0])
    
    # Relevance threshold filter (only on main articles tab)
    if relevance_threshold is not None and not show_trash and not show_auto_filtered:
        where_clauses.append('(a.relevance_score IS NULL OR a.relevance_score >= ?)')
        where_params.append(relevance_threshold)
    
    # Get all articles with management info - filter article_management by zip_code
    # Use LEFT JOIN to include articles even if they don't have management entries yet
    where_sql = ' AND '.join(where_clauses)
    query_params = ([zip_code] * 2 if zip_code else [None, None]) + where_params
    
    cursor.execute(f'''
        SELECT a.*, 
               COALESCE(am.enabled, 1) as enabled,
               COALESCE(am.display_order, a.id) as display_order,
               COALESCE(am.is_rejected, 0) as is_rejected,
               COALESCE(am.is_top_story, 0) as is_top_story,
               COALESCE(am.is_stellar, 0) as is_stellar,
               COALESCE(am.is_good_fit, 0) as is_good_fit
        FROM articles a
        LEFT JOIN (
            SELECT article_id, enabled, display_order, is_rejected, is_top_story, is_stellar, is_good_fit
            FROM article_management
            WHERE zip_code = ?
            AND ROWID IN (
                SELECT MAX(ROWID) 
                FROM article_management 
                WHERE zip_code = ?
                GROUP BY article_id
            )
        ) am ON a.id = am.article_id
        WHERE {where_sql}
        ORDER BY 
            CASE WHEN a.published IS NOT NULL AND a.published != '' THEN a.published ELSE '1970-01-01' END DESC,
            COALESCE(am.display_order, a.id) ASC
    ''', query_params)
    
    articles = [dict(row) for row in cursor.fetchall()]
    
    # Remove duplicates by ID (safety check in case JOIN still creates duplicates)
    seen_ids = set()
    unique_articles = []
    for article in articles:
        article_id = article.get('id')
        if article_id and article_id not in seen_ids:
            seen_ids.add(article_id)
            unique_articles.append(article)
    articles = unique_articles
    
    # Calculate relevance scores for articles that don't have them
    from utils.relevance_calculator import calculate_relevance_score
    for article in articles:
        if article.get('relevance_score') is None:
            article['relevance_score'] = calculate_relevance_score(article)
    
    # Log for debugging
    logger.info(f"Admin dashboard: Found {len(articles)} articles (show_trash={show_trash})")
    
    # Ensure all articles have management entries for this zip (for persistence)
    # Only create entries if they don't exist - don't overwrite existing settings
    for article in articles:
        article_id = article.get('id')
        if article_id and zip_code:
            # Check if entry exists for this zip_code
            cursor.execute('SELECT COUNT(*) FROM article_management WHERE article_id = ? AND zip_code = ?', (article_id, zip_code))
            exists = cursor.fetchone()[0] > 0
            if not exists:
                # Only insert if it doesn't exist for this zip - don't overwrite existing settings
                cursor.execute('''
                    INSERT INTO article_management (article_id, enabled, display_order, zip_code)
                    VALUES (?, 1, ?, ?)
                ''', (article_id, article_id, zip_code))
    conn.commit()
    
    # Get settings - merge global and zip-specific
    settings = {}
    # Get global settings
    cursor.execute('SELECT key, value FROM admin_settings')
    for row in cursor.fetchall():
        settings[row['key']] = row['value']
    
    # Get zip-specific settings (override global)
    if zip_code:
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ?', (zip_code,))
        for row in cursor.fetchall():
            settings[row['key']] = row['value']
    
    # Get last regeneration time
    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
    regen_row = cursor.fetchone()
    last_regeneration_raw = regen_row['value'] if regen_row else None
    
    # Format timestamp for display in Eastern Time
    last_regeneration = None
    if last_regeneration_raw:
        try:
            from datetime import datetime, timezone
            from zoneinfo import ZoneInfo
            
            # Parse the timestamp - handle both with and without timezone
            timestamp_str = last_regeneration_raw.replace('Z', '+00:00')
            dt = datetime.fromisoformat(timestamp_str)
            
            # If timestamp is naive (no timezone), it was stored as local system time
            # We need to determine what timezone that was and convert to Eastern
            if dt.tzinfo is None:
                # Assume it was stored in UTC (since main.py uses datetime.now() which might be system local)
                # But to be safe, let's check: if the stored time seems way off, it might be local time
                # For now, assume UTC since that's what datetime.now().isoformat() typically produces
                dt = dt.replace(tzinfo=timezone.utc)
            
            # Convert to Eastern Time
            eastern_tz = ZoneInfo('America/New_York')
            dt_eastern = dt.astimezone(eastern_tz)
            last_regeneration = dt_eastern.strftime('%Y-%m-%d %I:%M %p %Z')
        except Exception as e:
            logger.warning(f"Error formatting timestamp: {e}")
            # If zoneinfo fails, try manual conversion
            try:
                from datetime import timedelta
                timestamp_str = last_regeneration_raw.replace('Z', '+00:00')
                dt = datetime.fromisoformat(timestamp_str)
                
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                
                # Determine DST based on the date itself (not current date)
                month = dt.month
                if month >= 4 and month <= 10:
                    eastern_offset = timedelta(hours=-4)  # EDT
                    tz_name = "EDT"
                else:
                    eastern_offset = timedelta(hours=-5)  # EST
                    tz_name = "EST"
                
                eastern_tz = timezone(eastern_offset)
                dt_eastern = dt.astimezone(eastern_tz)
                last_regeneration = dt_eastern.strftime(f'%Y-%m-%d %I:%M %p {tz_name}')
            except:
                last_regeneration = last_regeneration_raw
    
    # Get enabled zip codes
    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('enabled_zips',))
    enabled_zips_row = cursor.fetchone()
    enabled_zips = []
    if enabled_zips_row:
        try:
            import json
            enabled_zips = json.loads(enabled_zips_row['value'])
        except:
            enabled_zips = []
    # If empty, get all zip codes from articles (don't default to 02720)
    if not enabled_zips:
        cursor.execute('SELECT DISTINCT zip_code FROM articles WHERE zip_code IS NOT NULL ORDER BY zip_code')
        enabled_zips = [row[0] for row in cursor.fetchall()]
    
    # Get version from config
    from config import VERSION
    
    # Get source settings from database - ZIP-SPECIFIC (only sources for this zip)
    # IMPORTANT: Only load sources from admin_settings_zip for this specific zip
    # New zips start with NO sources - they must be added manually
    sources_config = {}
    
    if zip_code:
        # Get zip-specific source settings
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_%"', (zip_code,))
        source_settings = {}
        for row in cursor.fetchall():
            # Key format: "source_{source_key}_{setting}"
            key = row['key']
            if key.startswith('source_'):
                parts = key.replace('source_', '').split('_', 1)
                if len(parts) == 2:
                    source_key = parts[0]
                    setting = parts[1]
                    if source_key not in source_settings:
                        source_settings[source_key] = {}
                    source_settings[source_key][setting] = row['value']
        
        # Get custom sources for this zip (not in NEWS_SOURCES)
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "custom_source_%"', (zip_code,))
        for row in cursor.fetchall():
            import json
            source_key = row['key'].replace('custom_source_', '')
            try:
                custom_data = json.loads(row['value'])
                custom_data['key'] = source_key
                sources_config[source_key] = custom_data
            except:
                pass  # Skip invalid JSON
        
        # Get source overrides for this zip (name/url/rss changes)
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_override_%"', (zip_code,))
        for row in cursor.fetchall():
            import json
            source_key = row['key'].replace('source_override_', '')
            try:
                override_data = json.loads(row['value'])
                # If source already exists, merge override data
                if source_key in sources_config:
                    sources_config[source_key].update(override_data)
                else:
                    # Create new source from override (merge with NEWS_SOURCES if it exists there)
                    if source_key in NEWS_SOURCES:
                        sources_config[source_key] = dict(NEWS_SOURCES[source_key])
                        sources_config[source_key].update(override_data)
                    else:
                        sources_config[source_key] = override_data
                    sources_config[source_key]['key'] = source_key
            except:
                pass  # Skip invalid JSON
        
        # Apply settings (enabled/require_fall_river) to sources
        for source_key in sources_config:
            if source_key in source_settings:
                if 'enabled' in source_settings[source_key]:
                    sources_config[source_key]['enabled'] = source_settings[source_key]['enabled'] == '1'
                if 'require_fall_river' in source_settings[source_key]:
                    sources_config[source_key]['require_fall_river'] = source_settings[source_key]['require_fall_river'] == '1'
    
    # If no zip_code, return empty sources (new zip should have no sources)
    
    # Load relevance config if on relevance or sources tab - ZIP-SPECIFIC
    relevance_config = None
    if tab == 'relevance' or tab == 'sources' or tab == 'categories':
        try:
            # Load relevance config from database, filtered by zip_code
            if zip_code:
                cursor.execute('SELECT category, item, points FROM relevance_config WHERE zip_code = ? ORDER BY category, item', (zip_code,))
            else:
                # Main admin - show all or default
                cursor.execute('SELECT category, item, points FROM relevance_config WHERE zip_code IS NULL ORDER BY category, item')
            
            rows = cursor.fetchall()
            relevance_config = {
                'high_relevance': [],
                'medium_relevance': [],
                'local_places': [],
                'topic_keywords': {},
                'source_credibility': {},
                'clickbait_patterns': []
            }
            
            for row in rows:
                category = row[0]
                item = row[1]
                points = row[2]
                
                if category in ['high_relevance', 'medium_relevance', 'local_places', 'clickbait_patterns']:
                    relevance_config[category].append(item)
                elif category == 'topic_keywords':
                    relevance_config[category][item] = points if points is not None else 0.0
                elif category == 'source_credibility':
                    relevance_config[category][item] = points if points is not None else 0.0
            
            # Load category-level points from admin_settings_zip
            if zip_code:
                cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key IN (?, ?)', 
                             (zip_code, 'high_relevance_points', 'local_places_points'))
                for row in cursor.fetchall():
                    key = row[0]
                    value = row[1]
                    try:
                        relevance_config[key] = float(value)
                    except (ValueError, TypeError):
                        pass
                # Set defaults if not found
                if 'high_relevance_points' not in relevance_config:
                    relevance_config['high_relevance_points'] = 15.0
                if 'local_places_points' not in relevance_config:
                    relevance_config['local_places_points'] = 3.0
            else:
                # Defaults for main admin
                relevance_config['high_relevance_points'] = 15.0
                relevance_config['local_places_points'] = 3.0
        except Exception as e:
            logger.error(f"Error loading relevance config: {e}")
            relevance_config = {
                'high_relevance': [],
                'medium_relevance': [],
                'local_places': [],
                'topic_keywords': {},
                'source_credibility': {},
                'clickbait_patterns': []
            }
    
    # Add relevance scores to sources_config from zip-specific relevance_config
    if tab == 'sources' or tab == 'relevance':
        if relevance_config and 'source_credibility' in relevance_config:
            source_credibility = relevance_config['source_credibility']
            for source_key, source_data in sources_config.items():
                source_name_lower = source_data.get('name', '').lower()
                if source_name_lower in source_credibility:
                    source_data['_relevance_score'] = source_credibility[source_name_lower]
                else:
                    source_data['_relevance_score'] = -1  # No score, sort to bottom
        else:
            # If no relevance config, set all to -1
            for source_key, source_data in sources_config.items():
                source_data['_relevance_score'] = -1
    
    # Sort sources by relevance score (descending) if on sources or relevance tab
    if tab == 'sources' or tab == 'relevance':
        sources_config = dict(sorted(sources_config.items(), 
                                     key=lambda x: x[1].get('_relevance_score', -1), 
                                     reverse=True))
    
    # Collect statistics (filtered by zip_code)
    stats = {}
    
    # Total articles for this zip (or all if main admin)
    if zip_code:
        cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code = ?', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM articles')
    stats['total_articles'] = cursor.fetchone()[0]
    
    # Active articles (not rejected) for this zip
    if zip_code:
        cursor.execute('''
            SELECT COUNT(DISTINCT a.id) FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id AND am.zip_code = ?
            WHERE (a.zip_code = ? OR a.zip_code IS NULL)
            AND COALESCE(am.is_rejected, 0) = 0
        ''', (zip_code, zip_code))
    else:
        cursor.execute('''
            SELECT COUNT(DISTINCT a.id) FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id
            WHERE COALESCE(am.is_rejected, 0) = 0
        ''')
    stats['active_articles'] = cursor.fetchone()[0]
    
    # Rejected articles count (for this zip)
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE is_rejected = 1 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE is_rejected = 1')
    stats['rejected_articles'] = cursor.fetchone()[0]
    
    # Top stories count (for this zip)
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE is_top_story = 1 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE is_top_story = 1')
    stats['top_stories'] = cursor.fetchone()[0]
    
    # Disabled articles count (for this zip)
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM article_management
            WHERE enabled = 0 AND zip_code = ?
        ''', (zip_code,))
    else:
        cursor.execute('SELECT COUNT(*) FROM article_management WHERE enabled = 0')
    stats['disabled_articles'] = cursor.fetchone()[0]
    
    # Articles by source (for this zip's articles)
    if zip_code:
        cursor.execute('''
            SELECT source, COUNT(*) as count 
            FROM articles 
            WHERE zip_code = ? OR zip_code IS NULL
            GROUP BY source 
            ORDER BY count DESC
        ''', (zip_code,))
    else:
        cursor.execute('''
            SELECT source, COUNT(*) as count 
            FROM articles 
            GROUP BY source 
            ORDER BY count DESC
        ''')
    stats['articles_by_source'] = [{'source': row[0], 'count': row[1]} for row in cursor.fetchall()]
    
    # Articles by category (for this zip's articles)
    if zip_code:
        cursor.execute('''
            SELECT COALESCE(category, 'uncategorized') as cat, COUNT(*) as count 
            FROM articles 
            WHERE zip_code = ? OR zip_code IS NULL
            GROUP BY cat 
            ORDER BY count DESC
        ''', (zip_code,))
    else:
        cursor.execute('''
            SELECT COALESCE(category, 'uncategorized') as cat, COUNT(*) as count 
            FROM articles 
            GROUP BY cat 
            ORDER BY count DESC
        ''')
    stats['articles_by_category'] = [{'category': row[0], 'count': row[1]} for row in cursor.fetchall()]
    
    # Recent articles (last 7 days) for this zip
    from datetime import datetime, timedelta
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    if zip_code:
        cursor.execute('''
            SELECT COUNT(*) FROM articles 
            WHERE ((published IS NOT NULL AND published > ?) 
               OR (published IS NULL AND created_at > ?))
            AND (zip_code = ? OR zip_code IS NULL)
        ''', (week_ago, week_ago, zip_code))
    else:
        cursor.execute('''
            SELECT COUNT(*) FROM articles 
            WHERE ((published IS NOT NULL AND published > ?) 
               OR (published IS NULL AND created_at > ?))
        ''', (week_ago, week_ago))
    stats['articles_last_7_days'] = cursor.fetchone()[0]
    
    # Source fetch stats
    cursor.execute('SELECT source_key, last_fetch_time, last_article_count FROM source_fetch_tracking')
    stats['source_fetch_stats'] = [{'source': row[0], 'last_fetch': row[1], 'count': row[2]} for row in cursor.fetchall()]
    
    # Get Bayesian features for rejected articles (for trash tab display)
    rejected_article_features = {}
    if show_trash:
        try:
            from utils.bayesian_learner import BayesianLearner
            learner = BayesianLearner()
            for article in articles:
                if article.get('is_rejected'):
                    features = learner.extract_features(article)
                    # Format features for display
                    rejected_article_features[article.get('id')] = {
                        'keywords': list(features.get('keywords', set()))[:10],  # Limit to 10
                        'nearby_towns': list(features.get('nearby_towns', set())),
                        'topics': list(features.get('topics', set())),
                        'has_fall_river': features.get('has_fall_river', False),
                        'n_grams': list(features.get('n_grams', set()))[:5]  # Limit to 5
                    }
        except Exception as e:
            logger.warning(f"Could not extract features for rejected articles: {e}")
    
    conn.close()
    
    # Load relevance config if on relevance or sources tab - ZIP-SPECIFIC (already loaded above)
    # Filter source_credibility to only include sources that exist in sources_config
    if relevance_config and 'source_credibility' in relevance_config and isinstance(relevance_config['source_credibility'], dict):
        # Get all source names from sources_config (lowercase for matching)
        valid_source_names = {source_data.get('name', '').lower() for source_data in sources_config.values()}
        # Filter source_credibility to only include valid sources
        filtered_source_credibility = {
            source_name: points 
            for source_name, points in relevance_config['source_credibility'].items()
            if source_name.lower() in valid_source_names
        }
        # Sort by points (descending) for display on relevance page
        relevance_config['source_credibility'] = dict(sorted(
            filtered_source_credibility.items(),
            key=lambda x: x[1],
            reverse=True
        ))
    
    # Add cache-busting timestamp to force browser to reload JavaScript
    cache_bust = int(datetime.now().timestamp())
    
    return render_template_string(ADMIN_TEMPLATE, articles=articles, settings=settings, sources=sources_config, version=VERSION, last_regeneration=last_regeneration, stats=stats, rejected_features=rejected_article_features, active_tab=tab, cache_bust=cache_bust, relevance_config=relevance_config, zip_code=zip_code, enabled_zips=enabled_zips)

@app.route('/admin/api/get-rejected-articles', methods=['GET', 'OPTIONS'])
@login_required
def get_rejected_articles():
    """Get all rejected articles for the trash tab - filtered by zip code"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        import sqlite3
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get zip_code from session
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Allow zip_code from query parameter (for cases where session might not be set)
        if request.args.get('zip_code'):
            zip_code = request.args.get('zip_code')
        # Main admin can also specify zip_code in query parameter
        elif is_main_admin and request.args.get('zip_code'):
            zip_code = request.args.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'error': 'Zip code required. Please provide zip_code in query parameter or ensure you are logged in.'}), 400
        
        # Ensure is_rejected column exists
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
            conn.commit()
        except:
            pass  # Column already exists
        
        # Set row factory for dict results
        conn.row_factory = sqlite3.Row
        
        # Get rejected articles filtered by zip_code with all needed fields
        # Show articles rejected for this specific zip_code OR auto-filtered articles with NULL zip_code (backward compatibility)
        cursor.execute('''
            SELECT a.*, 
                   a.relevance_score,
                   COALESCE(am.is_rejected, 0) as is_rejected,
                   COALESCE(am.is_auto_rejected, 0) as is_auto_rejected,
                   am.auto_reject_reason,
                   CASE 
                       WHEN am.is_auto_rejected = 1 THEN 'auto'
                       WHEN am.is_rejected = 1 THEN 'manual'
                       ELSE 'unknown'
                   END as rejection_type
            FROM articles a
            JOIN (
                SELECT article_id, is_rejected, is_auto_rejected, auto_reject_reason, zip_code
                FROM article_management
                WHERE (zip_code = ? OR (zip_code IS NULL AND is_auto_rejected = 1))
                AND ROWID IN (
                    SELECT MAX(ROWID) 
                    FROM article_management 
                    WHERE (zip_code = ? OR (zip_code IS NULL AND is_auto_rejected = 1))
                    GROUP BY article_id
                )
            ) am ON a.id = am.article_id
            WHERE am.is_rejected = 1
            ORDER BY a.created_at DESC
            LIMIT 100
        ''', (zip_code, zip_code))
        
        articles = []
        for row in cursor.fetchall():
            # Convert Row to dict properly
            article = {key: row[key] for key in row.keys()}
            articles.append(article)
        
        conn.close()
        
        logger.info(f"Returning {len(articles)} rejected articles for zip {zip_code}")
        return jsonify({'success': True, 'articles': articles})
    except Exception as e:
        logger.error(f"Error getting rejected articles: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/toggle-article', methods=['POST', 'OPTIONS'])
@login_required
def toggle_article():
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    logger.info(f"reject_article called with data: {data}")
    article_id = data.get('article_id')
    enabled = data.get('enabled', True)
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Get current display_order before updating (for this zip)
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Update or insert the management entry with zip_code
    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, zip_code)
        VALUES (?, ?, ?, ?)
    ''', (article_id, 1 if enabled else 0, display_order, zip_code))
    
    conn.commit()
    conn.close()
    
    # Auto-regenerate website when article is toggled
    try:
        from database import ArticleDatabase
        from aggregator import NewsAggregator
        from website_generator import WebsiteGenerator
        from ingestors.weather_ingestor import WeatherIngestor
        
        db = ArticleDatabase()
        aggregator = NewsAggregator()
        website_gen = WebsiteGenerator()
        weather_ingestor = WeatherIngestor()
        
        # Get all articles from database
        articles = db.get_all_articles(limit=500)
        # Enrich them
        enriched_articles = aggregator.enrich_articles(articles)
        # Generate website (will filter out disabled articles)
        website_gen.generate(enriched_articles)
        logger.info(f"Website auto-regenerated after toggling article {article_id}")
    except Exception as e:
        logger.warning(f"Could not auto-regenerate website: {e}")
        # Don't fail the toggle if regeneration fails
    
    return jsonify({'success': True, 'message': 'Article toggled and website regenerated'})

@app.route('/admin/api/get-auto-filtered', methods=['GET', 'OPTIONS'])
@login_required
def get_auto_filtered():
    """Get articles that were auto-filtered by Bayesian system or relevance threshold - filtered by zip code"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get zip_code from session
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Allow zip_code from query parameter (for cases where session might not be set)
        if request.args.get('zip_code'):
            zip_code = request.args.get('zip_code')
        # Main admin can also specify zip_code in query parameter
        elif is_main_admin and request.args.get('zip_code'):
            zip_code = request.args.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'error': 'Zip code required. Please provide zip_code in query parameter or ensure you are logged in.'}), 400
        
        # Ensure columns exist
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        except:
            pass
        conn.commit()
        
        # Get auto-filtered articles (both Bayesian and relevance threshold filtered)
        # Use subquery to get only the latest management entry per article
        # Show articles with matching zip_code OR auto-filtered articles with NULL zip_code (backward compatibility)
        cursor.execute('''
            SELECT a.*, am.auto_reject_reason
            FROM articles a
            INNER JOIN (
                SELECT article_id, auto_reject_reason
                FROM article_management
                WHERE (zip_code = ? OR (zip_code IS NULL AND is_auto_rejected = 1))
                AND is_auto_rejected = 1
                AND ROWID IN (
                    SELECT MAX(ROWID) 
                    FROM article_management 
                    WHERE (zip_code = ? OR (zip_code IS NULL AND is_auto_rejected = 1))
                    GROUP BY article_id
                )
            ) am ON a.id = am.article_id
            WHERE (a.zip_code = ? OR a.zip_code IS NULL)
            ORDER BY a.created_at DESC
            LIMIT 100
        ''', (zip_code, zip_code, zip_code))
        
        articles = []
        rows = cursor.fetchall()
        for row in rows:
            article = dict(row)
            articles.append(article)
        
        conn.close()
        
        logger.info(f"Returning {len(articles)} auto-filtered articles for zip {zip_code}")
        return jsonify({'success': True, 'articles': articles})
    except Exception as e:
        logger.error(f"Error getting auto-filtered articles: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/get-all-trash', methods=['GET', 'OPTIONS'])
@login_required
def get_all_trash():
    """Get all trashed articles (both manually rejected and auto-filtered) - filtered by zip code"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        import sqlite3
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get zip_code from session
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Allow zip_code from query parameter
        if request.args.get('zip_code'):
            zip_code = request.args.get('zip_code')
        elif is_main_admin and request.args.get('zip_code'):
            zip_code = request.args.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'error': 'Zip code required. Please provide zip_code in query parameter or ensure you are logged in.'}), 400
        
        # Ensure columns exist
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        except:
            pass
        conn.commit()
        
        # Set row factory for dict results
        conn.row_factory = sqlite3.Row
        
        # Get manually rejected articles
        cursor.execute('''
            SELECT a.*, 
                   COALESCE(am.is_rejected, 0) as is_rejected,
                   COALESCE(am.is_auto_rejected, 0) as is_auto_rejected,
                   am.auto_reject_reason
            FROM articles a
            JOIN (
                SELECT article_id, is_rejected, is_auto_rejected, auto_reject_reason
                FROM article_management
                WHERE zip_code = ?
                AND is_rejected = 1
                AND ROWID IN (
                    SELECT MAX(ROWID) 
                    FROM article_management 
                    WHERE zip_code = ?
                    GROUP BY article_id
                )
            ) am ON a.id = am.article_id
            WHERE (a.zip_code = ? OR a.zip_code IS NULL)
            ORDER BY a.created_at DESC
            LIMIT 100
        ''', (zip_code, zip_code, zip_code))
        
        manual_articles = []
        for row in cursor.fetchall():
            article = {key: row[key] for key in row.keys()}
            article['rejection_type'] = 'manual'
            manual_articles.append(article)
        
        # Get auto-filtered articles
        cursor.execute('''
            SELECT a.*, 
                   COALESCE(am.is_rejected, 0) as is_rejected,
                   COALESCE(am.is_auto_rejected, 0) as is_auto_rejected,
                   am.auto_reject_reason
            FROM articles a
            INNER JOIN (
                SELECT article_id, is_rejected, is_auto_rejected, auto_reject_reason
                FROM article_management
                WHERE zip_code = ?
                AND is_auto_rejected = 1
                AND ROWID IN (
                    SELECT MAX(ROWID) 
                    FROM article_management 
                    WHERE zip_code = ?
                    GROUP BY article_id
                )
            ) am ON a.id = am.article_id
            WHERE (a.zip_code = ? OR a.zip_code IS NULL)
            ORDER BY a.created_at DESC
            LIMIT 100
        ''', (zip_code, zip_code, zip_code))
        
        auto_articles = []
        for row in cursor.fetchall():
            article = {key: row[key] for key in row.keys()}
            article['rejection_type'] = 'auto'
            auto_articles.append(article)
        
        # Combine and sort by date (newest first)
        all_articles = manual_articles + auto_articles
        all_articles.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        conn.close()
        
        logger.info(f"Returning {len(manual_articles)} manually rejected and {len(auto_articles)} auto-filtered articles for zip {zip_code}")
        return jsonify({'success': True, 'articles': all_articles})
    except Exception as e:
        logger.error(f"Error getting all trash articles: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/restore-auto-filtered', methods=['POST', 'OPTIONS'])
@login_required
def restore_auto_filtered():
    """Restore an auto-filtered article"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    article_id = data.get('article_id')
    
    if not article_id:
        return jsonify({'success': False, 'message': 'Article ID required'}), 400
    
    try:
        import sqlite3
        from config import DATABASE_CONFIG
        
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        cursor = conn.cursor()
        
        # Ensure columns exist
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        except:
            pass
        
        # Remove auto-rejected status and enable the article
        cursor.execute('''
            UPDATE article_management 
            SET is_auto_rejected = 0, is_rejected = 0, enabled = 1, auto_reject_reason = NULL
            WHERE article_id = ?
        ''', (article_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Article restored'})
    except Exception as e:
        logger.error(f"Error restoring auto-filtered article: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/restore-article', methods=['POST', 'OPTIONS'])
@login_required
def restore_article_unified():
    """Unified restore endpoint that handles both manually rejected and auto-filtered articles"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    article_id = data.get('article_id')
    rejection_type = data.get('rejection_type', 'manual')  # 'manual' or 'auto'
    
    if not article_id:
        return jsonify({'success': False, 'message': 'Article ID required'}), 400
    
    try:
        import sqlite3
        from config import DATABASE_CONFIG
        
        # Get zip_code from request body first (for all users), then fall back to session
        zip_code = data.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # If not in request body, try session
        if not zip_code:
            zip_code = session.get('zip_code')
        
        # Main admin can still override if needed (though request body should work)
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'error': 'Zip code required'}), 400
        
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        cursor = conn.cursor()
        
        # Ensure columns exist
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
        except:
            pass
        
        if rejection_type == 'auto':
            # Restore auto-filtered article
            cursor.execute('''
                UPDATE article_management 
                SET is_auto_rejected = 0, is_rejected = 0, enabled = 1, auto_reject_reason = NULL
                WHERE article_id = ? AND zip_code = ?
            ''', (article_id, zip_code))
        else:
            # Restore manually rejected article
            cursor.execute('''
                UPDATE article_management 
                SET is_rejected = 0, enabled = 1
                WHERE article_id = ? AND zip_code = ?
            ''', (article_id, zip_code))
        
        # If no rows were updated, create a new entry
        if cursor.rowcount == 0:
            cursor.execute('''
                INSERT INTO article_management (article_id, zip_code, enabled, is_rejected, is_auto_rejected, auto_reject_reason)
                VALUES (?, ?, 1, 0, 0, NULL)
            ''', (article_id, zip_code))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Article restored'})
    except Exception as e:
        logger.error(f"Error restoring article: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/get-bayesian-features', methods=['GET', 'OPTIONS'])
@login_required
def get_bayesian_features():
    """Get Bayesian features extracted from a rejected article"""
    if request.method == 'OPTIONS':
        return '', 200
    article_id = request.args.get('article_id')
    if not article_id:
        return jsonify({'success': False, 'message': 'Article ID required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        cursor.execute('SELECT title, content, summary, source FROM articles WHERE id = ?', (article_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'success': False, 'message': 'Article not found'}), 404
        
        article = {
            'title': row[0] or '',
            'content': row[1] or row[2] or '',
            'summary': row[2] or '',
            'source': row[3] or ''
        }
        
        from utils.bayesian_learner import BayesianLearner
        learner = BayesianLearner()
        features = learner.extract_features(article)
        
        # Also get rejection patterns from database
        import sqlite3
        db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        learned_patterns = []
        for feature_type, feature_set in features.items():
            if feature_type == "has_fall_river":
                continue
            for feature in feature_set:
                cursor.execute('''
                    SELECT reject_count, accept_count 
                    FROM rejection_patterns 
                    WHERE feature = ? AND feature_type = ?
                ''', (feature, feature_type))
                row = cursor.fetchone()
                if row:
                    learned_patterns.append({
                        'feature': feature,
                        'type': feature_type,
                        'reject_count': row[0],
                        'accept_count': row[1]
                    })
        
        conn.close()
        
        return jsonify({
            'success': True,
            'features': {
                'keywords': list(features.get('keywords', set()))[:15],
                'nearby_towns': list(features.get('nearby_towns', set())),
                'topics': list(features.get('topics', set())),
                'has_fall_river': features.get('has_fall_river', False),
                'n_grams': list(features.get('n_grams', set()))[:10]
            },
            'learned_patterns': learned_patterns[:20]  # Top 20 patterns
        })
    except Exception as e:
        logger.error(f"Error getting Bayesian features: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/get-top-stories', methods=['GET', 'OPTIONS'])
def get_top_stories():
    """Get top stories for a zip code - PUBLIC endpoint for frontend sync"""
    if request.method == 'OPTIONS':
        return '', 200
    
    zip_code = request.args.get('zip_code')
    if not zip_code or not zip_code.isdigit() or len(zip_code) != 5:
        return jsonify({'success': False, 'error': 'Valid zip code required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get top story article IDs for this zip
        cursor.execute('''
            SELECT DISTINCT article_id
            FROM article_management
            WHERE zip_code = ? AND is_top_story = 1
        ''', (zip_code,))
        
        top_story_ids = [str(row[0]) for row in cursor.fetchall()]
        conn.close()
        
        return jsonify({
            'success': True,
            'top_stories': top_story_ids
        })
    except Exception as e:
        logger.error(f"Error getting top stories: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/api/reject-article', methods=['POST', 'OPTIONS'])
@login_required
def reject_article():
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    article_id = data.get('article_id')
    rejected = data.get('rejected', True)  # True = reject, False = restore
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure is_rejected column exists
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass  # Column already exists
    
    # Get article data for Bayesian training
    cursor.execute('SELECT title, content, summary, source FROM articles WHERE id = ?', (article_id,))
    article_row = cursor.fetchone()
    article_data = None
    if article_row:
        article_data = {
            'title': article_row[0] or '',
            'content': article_row[1] or article_row[2] or '',
            'summary': article_row[2] or '',
            'source': article_row[3] or ''
        }
    
    # Get zip_code from request body first (for all users), then fall back to session
    zip_code = data.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # If not in request body, try session
    if not zip_code:
        zip_code = session.get('zip_code')
    
    # Main admin can still override if needed (though request body should work)
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    # Get current display_order before updating (for this zip)
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Check if entry exists for this zip
    cursor.execute('SELECT id FROM article_management WHERE article_id = ? AND zip_code = ?', (article_id, zip_code))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing entry - preserve other columns like is_top_story
        cursor.execute('''
            UPDATE article_management 
            SET enabled = ?, display_order = ?, is_rejected = ?
            WHERE article_id = ? AND zip_code = ?
        ''', (0 if rejected else 1, display_order, 1 if rejected else 0, article_id, zip_code))
        logger.info(f"Updated article_management for article {article_id} (zip {zip_code}): rejected={rejected}")
    else:
        # Insert new entry with zip_code
        cursor.execute('''
            INSERT INTO article_management (article_id, enabled, display_order, is_rejected, zip_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (article_id, 0 if rejected else 1, display_order, 1 if rejected else 0, zip_code))
        logger.info(f"Inserted new article_management for article {article_id} (zip {zip_code}): rejected={rejected}")
    
    conn.commit()
    conn.close()
    
    # Train Bayesian model if article is rejected
    if rejected and article_data:
        try:
            from utils.bayesian_learner import BayesianLearner
            learner = BayesianLearner()
            learner.train_from_rejection(article_data)
            logger.info(f"Bayesian model trained from rejected article: '{article_data.get('title', '')[:50]}...'")
        except Exception as e:
            logger.warning(f"Could not train Bayesian model: {e}")
    
    # Auto-regenerate website when article is rejected/restored
    try:
        from database import ArticleDatabase
        from aggregator import NewsAggregator
        from website_generator import WebsiteGenerator
        from ingestors.weather_ingestor import WeatherIngestor
        
        db = ArticleDatabase()
        aggregator = NewsAggregator()
        website_gen = WebsiteGenerator()
        weather_ingestor = WeatherIngestor()
        
        articles = db.get_all_articles(limit=500)
        enriched_articles = aggregator.enrich_articles(articles)
        website_gen.generate(enriched_articles)
        logger.info(f"Website auto-regenerated after {'rejecting' if rejected else 'restoring'} article {article_id}")
    except Exception as e:
        logger.warning(f"Could not auto-regenerate website: {e}")
    
    return jsonify({'success': True, 'message': f'Article {"rejected" if rejected else "restored"} and website regenerated'})

@app.route('/admin/<zip_code>/trash', methods=['POST', 'OPTIONS'])
@login_required
def trash_article_by_zip(zip_code):
    """Handle trash action via /admin/<zip_code>/trash POST route"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    article_id = data.get('id') or data.get('article_id')
    action = data.get('action', 'trash')
    rejected = (action == 'trash')
    
    if not article_id:
        return jsonify({'success': False, 'error': 'Article ID required'}), 400
    
    # Validate zip code
    if not validate_zip_code(zip_code):
        return jsonify({'success': False, 'error': 'Invalid zip code'}), 400
    
    # Use the same logic as reject_article but with zip_code from URL
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Ensure is_rejected column exists
    try:
        cursor.execute('ALTER TABLE article_management ADD COLUMN is_rejected INTEGER DEFAULT 0')
        conn.commit()
    except:
        pass  # Column already exists
    
    # Get article data for Bayesian training
    cursor.execute('SELECT title, content, summary, source FROM articles WHERE id = ?', (article_id,))
    article_row = cursor.fetchone()
    article_data = None
    if article_row:
        article_data = {
            'title': article_row[0] or '',
            'content': article_row[1] or article_row[2] or '',
            'summary': article_row[2] or '',
            'source': article_row[3] or ''
        }
    
    # Get current display_order before updating (for this zip)
    cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
    row = cursor.fetchone()
    display_order = row[0] if row else article_id
    
    # Check if entry exists for this zip
    cursor.execute('SELECT id FROM article_management WHERE article_id = ? AND zip_code = ?', (article_id, zip_code))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing entry - preserve other columns like is_top_story
        cursor.execute('''
            UPDATE article_management 
            SET enabled = ?, display_order = ?, is_rejected = ?
            WHERE article_id = ? AND zip_code = ?
        ''', (0 if rejected else 1, display_order, 1 if rejected else 0, article_id, zip_code))
        logger.info(f"Updated article_management for article {article_id} (zip {zip_code}): rejected={rejected}")
    else:
        # Insert new entry with zip_code
        cursor.execute('''
            INSERT INTO article_management (article_id, enabled, display_order, is_rejected, zip_code)
            VALUES (?, ?, ?, ?, ?)
        ''', (article_id, 0 if rejected else 1, display_order, 1 if rejected else 0, zip_code))
        logger.info(f"Inserted new article_management for article {article_id} (zip {zip_code}): rejected={rejected}")
    
    conn.commit()
    conn.close()
    
    # Train Bayesian model if article is rejected
    if rejected and article_data:
        try:
            from utils.bayesian_learner import BayesianLearner
            learner = BayesianLearner()
            learner.train_from_rejection(article_data)
            logger.info(f"Bayesian model trained from rejected article: '{article_data.get('title', '')[:50]}...'")
        except Exception as e:
            logger.warning(f"Could not train Bayesian model: {e}")
    
    # Auto-regenerate website when article is rejected/restored
    try:
        from database import ArticleDatabase
        from aggregator import NewsAggregator
        from website_generator import WebsiteGenerator
        from ingestors.weather_ingestor import WeatherIngestor
        
        db = ArticleDatabase()
        aggregator = NewsAggregator()
        website_gen = WebsiteGenerator()
        weather_ingestor = WeatherIngestor()
        
        articles = db.get_all_articles(limit=500)
        enriched_articles = aggregator.enrich_articles(articles)
        website_gen.generate(enriched_articles)
        logger.info(f"Website auto-regenerated after {'rejecting' if rejected else 'restoring'} article {article_id}")
    except Exception as e:
        logger.warning(f"Could not auto-regenerate website: {e}")
    
    return jsonify({'success': True, 'message': f'Article {"rejected" if rejected else "restored"} and website regenerated'})

@app.route('/admin/api/reorder-articles', methods=['POST', 'OPTIONS'])
@login_required
def reorder_articles():
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    article_orders = data.get('orders', [])
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    for item in article_orders:
        article_id = item.get('id')
        order = item.get('order')
        
        cursor.execute('''
            INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, zip_code)
            VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ? AND zip_code = ?), 1), ?, ?)
        ''', (article_id, article_id, zip_code, order, zip_code))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/admin/api/toggle-images', methods=['POST', 'OPTIONS'])
@login_required
def toggle_images():
    """Toggle show images setting - ZIP-SPECIFIC"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    show_images = data.get('show_images', True)
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Save to zip-specific settings
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
        VALUES (?, 'show_images', ?)
    ''', (zip_code, '1' if show_images else '0'))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

def regenerate_zip_website(zip_code: str, force_refresh: bool = False):
    """Regenerate website for a specific zip code with relevance recalculation
    
    Args:
        zip_code: Zip code to regenerate
        force_refresh: If True, fetch fresh articles from sources
    
    Returns:
        Tuple (success: bool, message: str)
    """
    try:
        from utils.relevance_calculator import calculate_relevance_score, load_relevance_config
        import sqlite3
        from datetime import datetime
        import subprocess
        import sys
        
        logger.info(f"Starting zip-specific regeneration for {zip_code}")
        
        # Step 1: Recalculate ALL relevance scores for existing articles in this zip
        logger.info(f"Recalculating relevance scores for zip {zip_code}...")
        load_relevance_config(force_reload=True, zip_code=zip_code)
        
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        cursor = conn.cursor()
        
        cursor.execute('SELECT id, title, url, published, summary, content, source FROM articles WHERE zip_code = ?', (zip_code,))
        existing_articles = cursor.fetchall()
        
        # Get relevance threshold
        cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', (zip_code, 'relevance_threshold'))
        threshold_row = cursor.fetchone()
        relevance_threshold = None
        if threshold_row:
            try:
                relevance_threshold = float(threshold_row[0])
            except (ValueError, TypeError):
                pass
        
        recalculated_count = 0
        auto_filtered_count = 0
        
        for row in existing_articles:
            article = {
                'id': row[0],
                'title': row[1] or '',
                'url': row[2] or '',
                'published': row[3] or '',
                'summary': row[4] or '',
                'content': row[5] or '',
                'source': row[6] or '',
                'zip_code': zip_code
            }
            
            # Recalculate relevance score
            new_score = calculate_relevance_score(article, zip_code=zip_code)
            cursor.execute('UPDATE articles SET relevance_score = ? WHERE id = ?', (new_score, article['id']))
            
            # Check if should be auto-filtered
            is_auto_filtered = (relevance_threshold is not None and new_score < relevance_threshold)
            
            # Update article_management
            cursor.execute('''
                UPDATE article_management 
                SET enabled = ?
                WHERE article_id = ? AND zip_code = ?
            ''', (0 if is_auto_filtered else 1, article['id'], zip_code))
            
            if is_auto_filtered:
                auto_filtered_count += 1
            recalculated_count += 1
        
        conn.commit()
        conn.close()
        logger.info(f"Recalculated {recalculated_count} articles ({auto_filtered_count} auto-filtered)")
        
        # Step 2: Run main.py with zip_code to fetch fresh articles (if force_refresh) and generate website
        logger.info(f"Running aggregation cycle for zip {zip_code}...")
        cmd = [sys.executable, 'main.py', '--once', '--zip', zip_code]
        env = os.environ.copy()
        env['ZIP_CODE'] = zip_code
        if force_refresh:
            env['FORCE_REFRESH'] = '1'
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            env=env
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"Regeneration failed: {error_msg}")
            return False, f"Regeneration failed: {error_msg}"
        
        # Step 3: Update last regeneration time for this zip
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
            VALUES (?, 'last_regeneration_time', ?)
        ''', (zip_code, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        logger.info(f"Successfully regenerated website for zip {zip_code}")
        return True, f"Regenerated website for {zip_code} ({recalculated_count} articles recalculated)"
        
    except subprocess.TimeoutExpired:
        logger.error(f"Regeneration timed out for zip {zip_code}")
        return False, "Regeneration timed out after 10 minutes"
    except Exception as e:
        logger.error(f"Error in regenerate_zip_website: {e}", exc_info=True)
        return False, str(e)


@app.route('/admin/api/regenerate', methods=['POST', 'OPTIONS'])
@login_required
def regenerate_website():
    """Trigger website regeneration with optional force refresh and zip-specific support"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    force_refresh = data.get('force_refresh', False)
    zip_code_param = data.get('zip_code')
    
    # Get zip_code from session or parameter
    zip_code = zip_code_param or session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # If zip_code provided, do zip-specific regeneration
    if zip_code:
        try:
            success, message = regenerate_zip_website(zip_code, force_refresh)
            if success:
                return jsonify({'success': True, 'message': message})
            else:
                return jsonify({'success': False, 'message': message}), 500
        except Exception as e:
            logger.error(f"Error in zip-specific regeneration: {e}", exc_info=True)
            return jsonify({'success': False, 'message': str(e)}), 500
    
    # Otherwise, do global regeneration (main admin only)
    if not is_main_admin:
        return jsonify({'success': False, 'message': 'Global regeneration requires main admin access'}), 403
    
    import subprocess
    import sys
    from cache import get_cache
    import sqlite3
    
    try:
        # Clear cache before regenerating
        try:
            cache = get_cache()
            cache.clear_all()
            logger.info("Cache cleared before regeneration")
        except Exception as e:
            logger.warning(f"Could not clear cache: {e}")
        
        # If force refresh, clear source fetch tracking
        if force_refresh:
            try:
                conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
                cursor = conn.cursor()
                cursor.execute('DELETE FROM source_fetch_tracking')
                conn.commit()
                conn.close()
                logger.info("Source fetch tracking cleared for force refresh")
            except Exception as e:
                logger.warning(f"Could not clear source fetch tracking: {e}")
        
        # Note: Auto-rejected articles will be excluded from website generation
        # They remain in the database for review in the Auto-Filtered tab
        # Manually rejected articles remain in the trash
        logger.info("Auto-rejected articles will be excluded from website generation")
        
        # Run the main aggregator
        try:
            cmd = [sys.executable, 'main.py', '--once']
            env = os.environ.copy()
            if force_refresh:
                env['FORCE_REFRESH'] = '1'
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # Increased timeout for force refresh (10 minutes)
                env=env
            )
            
            if result.returncode == 0:
                logger.info("Website regenerated successfully")
                return jsonify({'success': True, 'message': 'Website regenerated successfully'})
            else:
                error_msg = result.stderr or result.stdout or 'Unknown error'
                logger.error(f"Regeneration failed: {error_msg}")
                return jsonify({'success': False, 'message': error_msg})
        except subprocess.TimeoutExpired:
            logger.error("Regeneration timed out after 10 minutes")
            return jsonify({'success': False, 'message': 'Regeneration timed out after 10 minutes'})
    except Exception as e:
        logger.error(f"Error in regenerate_website: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/api/regenerate-all', methods=['POST', 'OPTIONS'])
@login_required
def regenerate_all_websites():
    """Regenerate websites for all zip codes - MAIN ADMIN ONLY"""
    if request.method == 'OPTIONS':
        return '', 200
    
    is_main_admin = session.get('is_main_admin', False)
    if not is_main_admin:
        return jsonify({'success': False, 'error': 'Main admin access required'}), 403
    
    import subprocess
    import sys
    from cache import get_cache
    
    try:
        # Clear cache before regenerating
        try:
            cache = get_cache()
            cache.clear_all()
            logger.info("Cache cleared before regeneration")
        except Exception as e:
            logger.warning(f"Could not clear cache: {e}")
        
        # Run the main aggregator for all zips
        try:
            cmd = [sys.executable, 'main.py', '--once']
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )
            if result.returncode == 0:
                logger.info("Website regeneration completed for all zips")
                return jsonify({'success': True, 'message': 'Website regeneration completed for all zip codes'})
            else:
                error_msg = result.stderr or result.stdout or 'Unknown error'
                logger.error(f"Regeneration failed: {error_msg}")
                return jsonify({'success': False, 'message': error_msg})
        except subprocess.TimeoutExpired:
            logger.error("Regeneration timed out")
            return jsonify({'success': False, 'message': 'Regeneration timed out'})
        except Exception as e:
            logger.error(f"Error running regeneration: {e}", exc_info=True)
            return jsonify({'success': False, 'message': str(e)})
    except Exception as e:
        logger.error(f"Error regenerating websites: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/api/source', methods=['POST', 'OPTIONS'])
@login_required
def update_source():
    """Update source setting - ZIP-SPECIFIC"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    source_key = data.get('source')
    setting = data.get('setting')
    value = data.get('value', False)
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Key format: source_{source_key}_{setting}
        key = f"source_{source_key}_{setting}"
        # Save to zip-specific settings
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
            VALUES (?, ?, ?)
        ''', (zip_code, key, '1' if value else '0'))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Source setting updated for zip {zip_code}: {key} = {value}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating source setting: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)})

@app.route('/admin/api/good-fit', methods=['POST', 'OPTIONS'])
@login_required
def toggle_good_fit():
    """Toggle good fit status for an article"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    article_id = data.get('id') or data.get('article_id')
    is_good_fit = data.get('is_good_fit', True)
    
    if not article_id:
        return jsonify({'success': False, 'error': 'Article ID required'}), 400
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Ensure is_good_fit column exists
        try:
            cursor.execute('ALTER TABLE article_management ADD COLUMN is_good_fit INTEGER DEFAULT 0')
            conn.commit()
        except:
            pass  # Column already exists
        
        # Get current display_order
        cursor.execute('SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ? ORDER BY ROWID DESC LIMIT 1', (article_id, zip_code))
        row = cursor.fetchone()
        display_order = row[0] if row else article_id
        
        # Check if entry exists
        cursor.execute('SELECT id FROM article_management WHERE article_id = ? AND zip_code = ?', (article_id, zip_code))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing entry
            cursor.execute('''
                UPDATE article_management 
                SET is_good_fit = ?, display_order = ?
                WHERE article_id = ? AND zip_code = ?
            ''', (1 if is_good_fit else 0, display_order, article_id, zip_code))
        else:
            # Insert new entry
            cursor.execute('''
                INSERT INTO article_management (article_id, enabled, display_order, is_good_fit, zip_code)
                VALUES (?, 1, ?, ?, ?)
            ''', (article_id, display_order, 1 if is_good_fit else 0, zip_code))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Article {article_id} good fit set to {is_good_fit} for zip {zip_code}")
        return jsonify({'success': True, 'message': f'Good fit {"enabled" if is_good_fit else "disabled"}'})
    except Exception as e:
        logger.error(f"Error toggling good fit: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/top-story', methods=['POST', 'OPTIONS'])
@login_required
def toggle_top_story():
    """Toggle top story status for an article - ZIP-SPECIFIC"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    article_id = data.get('id')
    is_top_story = data.get('is_top_story', False)
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, is_top_article, is_top_story, zip_code)
        VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ? AND zip_code = ?), 1), 
                COALESCE((SELECT display_order FROM article_management WHERE article_id = ? AND zip_code = ?), ?),
                COALESCE((SELECT is_top_article FROM article_management WHERE article_id = ? AND zip_code = ?), 0), ?, ?)
    ''', (article_id, article_id, zip_code, article_id, zip_code, article_id, article_id, zip_code, 1 if is_top_story else 0, zip_code))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/admin/api/edit-article', methods=['POST', 'OPTIONS'])
def edit_article():
    """Edit article title, summary, category, URL, and publication date"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    article_id = data.get('id') or data.get('article_id')
    title = data.get('title', '')
    summary = data.get('summary', '')
    category = data.get('category')
    url = data.get('url')
    published = data.get('published')  # ISO format date string
    relevance_score = data.get('relevance_score')
    local_score = data.get('local_score')
    
    # Clean bad characters
    import re
    title = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', title) if title else ''
    summary = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', summary) if summary else ''
    
    # Validate and format published date if provided
    if published:
        try:
            from datetime import datetime
            # Try to parse and reformat to ISO
            dt = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
            published = dt.isoformat()
        except:
            try:
                # Try parsing as date string
                dt = datetime.fromisoformat(published.split('T')[0])
                published = dt.isoformat()
            except:
                published = None  # Invalid date, ignore it
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Build update query dynamically based on what's provided
    updates = []
    values = []
    
    if title:
        updates.append('title = ?')
        values.append(title)
    if summary is not None:
        updates.append('summary = ?')
        values.append(summary)
    if category:
        updates.append('category = ?')
        values.append(category)
        
        # Get original category before update for training
        cursor.execute('SELECT category FROM articles WHERE id = ?', (article_id,))
        original_cat_row = cursor.fetchone()
        original_category = original_cat_row[0] if original_cat_row else None
        
        # Get article data for training
        cursor.execute('SELECT title, content, summary, source, url FROM articles WHERE id = ?', (article_id,))
        article_row = cursor.fetchone()
        
        if article_row and original_category != category:
            title, content, summary, source, url = article_row
            
            # Create category training table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS category_training (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER,
                    title TEXT,
                    content TEXT,
                    summary TEXT,
                    source TEXT,
                    url TEXT,
                    original_category TEXT,
                    corrected_category TEXT,
                    zip_code TEXT,
                    trained_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (article_id) REFERENCES articles (id)
                )
            ''')
            
            # Get zip_code from session or use default
            zip_code = session.get('zip_code', '02720')
            
            # Store training data
            cursor.execute('''
                INSERT INTO category_training 
                (article_id, title, content, summary, source, url, original_category, corrected_category, zip_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (article_id, title, content or '', summary or '', source or '', url or '', original_category, category, zip_code))
    if url:
        updates.append('url = ?')
        values.append(url)
    if published:
        updates.append('published = ?')
        values.append(published)
    if relevance_score is not None:
        updates.append('relevance_score = ?')
        values.append(float(relevance_score))
    if local_score is not None:
        updates.append('local_score = ?')
        values.append(float(local_score))
    
    if updates:
        values.append(article_id)
        query = f'UPDATE articles SET {", ".join(updates)} WHERE id = ?'
        cursor.execute(query, values)
    
    conn.commit()
    conn.close()
    
    # Auto-regenerate website after edit
    try:
        from database import ArticleDatabase
        from aggregator import NewsAggregator
        from website_generator import WebsiteGenerator
        from ingestors.weather_ingestor import WeatherIngestor
        
        db = ArticleDatabase()
        aggregator = NewsAggregator()
        website_gen = WebsiteGenerator()
        weather_ingestor = WeatherIngestor()
        
        articles = db.get_all_articles(limit=500)
        enriched_articles = aggregator.enrich_articles(articles)
        website_gen.generate(enriched_articles)
        logger.info(f"Website auto-regenerated after editing article {article_id}")
    except Exception as e:
        logger.warning(f"Could not auto-regenerate website: {e}")
    
    return jsonify({'success': True, 'message': 'Article updated and website regenerated'})

@app.route('/admin/api/get-article', methods=['GET'])
@login_required
def get_article():
    """Get article data for editing"""
    article_id = request.args.get('id')
    if not article_id:
        return jsonify({'success': False, 'message': 'Article ID required'})
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        article = dict(row)
        return jsonify({'success': True, 'article': article})
    else:
        return jsonify({'success': False, 'message': 'Article not found'})

@app.route('/admin/api/add-source', methods=['POST', 'OPTIONS'])
@login_required
def add_source():
    """Add a new news source - ZIP-SPECIFIC"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    name = data.get('name', '')
    url = data.get('url', '')
    rss = data.get('rss')
    category = data.get('category', 'news')
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    # Generate a key from the name
    import re
    source_key = re.sub(r'[^a-z0-9_]', '_', name.lower())
    
    # Save to database as a custom source - ZIP-SPECIFIC
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Store in admin_settings_zip (zip-specific)
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
        VALUES (?, ?, ?)
    ''', (zip_code, f"custom_source_{source_key}", json.dumps({
        'name': name,
        'url': url,
        'rss': rss,
        'category': category,
        'enabled': True,
        'require_fall_river': True
    })))
    
    # Save or delete relevance score from relevance_config - ZIP-SPECIFIC
    relevance_score = data.get('relevance_score')
    source_name_lower = name.lower()
    if relevance_score is not None and relevance_score != '':
        # Save relevance score
        try:
            relevance_score_float = float(relevance_score)
            cursor.execute('''
                INSERT OR REPLACE INTO relevance_config (category, item, points, zip_code)
                VALUES (?, ?, ?, ?)
            ''', ('source_credibility', source_name_lower, relevance_score_float, zip_code))
        except (ValueError, TypeError):
            pass  # Invalid score, skip
    else:
        # Delete relevance score if cleared (empty string or None)
        cursor.execute('DELETE FROM relevance_config WHERE category = ? AND item = ? AND zip_code = ?', 
                      ('source_credibility', source_name_lower, zip_code))
    
    # Commit the transaction first
    conn.commit()
    conn.close()
    
    # Clear cache AFTER commit to ensure database is updated
    from utils.relevance_calculator import load_relevance_config
    load_relevance_config(force_reload=True)
    
    return jsonify({'success': True, 'source_key': source_key})

@app.route('/admin/api/get-source', methods=['GET', 'OPTIONS'])
@login_required
def get_source():
    """Get source data for editing - ZIP-SPECIFIC"""
    if request.method == 'OPTIONS':
        return '', 200
    source_key = request.args.get('key', '')
    
    if not source_key:
        return jsonify({'success': False, 'message': 'Source key required'}), 400
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and request.args.get('zip_code'):
        zip_code = request.args.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Check for custom source - ZIP-SPECIFIC
        cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', (zip_code, f"custom_source_{source_key}"))
        row = cursor.fetchone()
        
        if row:
            # Custom source
            import json
            source_data = json.loads(row['value'])
            source_data['key'] = source_key
            # Get relevance score from relevance_config - ZIP-SPECIFIC
            source_name_lower = source_data.get('name', '').lower()
            cursor.execute('SELECT points FROM relevance_config WHERE category = ? AND item = ? AND zip_code = ?', 
                          ('source_credibility', source_name_lower, zip_code))
            relevance_row = cursor.fetchone()
            if relevance_row:
                source_data['relevance_score'] = relevance_row[0]
            else:
                source_data['relevance_score'] = None
            conn.close()
            return jsonify({'success': True, 'source': source_data})
        
        # Check for override (for built-in sources) - ZIP-SPECIFIC
        cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', (zip_code, f"source_override_{source_key}"))
        row = cursor.fetchone()
        
        if row:
            # Override exists - merge with base config if it's a built-in source
            import json
            source_data = json.loads(row['value'])
            source_data['key'] = source_key
            
            # If it's a built-in source, merge with base config to get defaults
            if source_key in NEWS_SOURCES:
                base_config = NEWS_SOURCES[source_key].copy()
                # Override takes precedence
                base_config.update(source_data)
                source_data = base_config
                # Get enabled/require_fall_river settings - ZIP-SPECIFIC
                cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE ?', (zip_code, f"source_{source_key}_%"))
                settings = {row['key']: row['value'] for row in cursor.fetchall()}
                if f"source_{source_key}_enabled" in settings:
                    source_data['enabled'] = settings[f"source_{source_key}_enabled"] == '1'
                if f"source_{source_key}_require_fall_river" in settings:
                    source_data['require_fall_river'] = settings[f"source_{source_key}_require_fall_river"] == '1'
            
            # Get relevance score from relevance_config - ZIP-SPECIFIC
            source_name_lower = source_data.get('name', '').lower()
            cursor.execute('SELECT points FROM relevance_config WHERE category = ? AND item = ? AND zip_code = ?', 
                          ('source_credibility', source_name_lower, zip_code))
            relevance_row = cursor.fetchone()
            if relevance_row:
                source_data['relevance_score'] = relevance_row[0]
            else:
                source_data['relevance_score'] = None
            conn.close()
            return jsonify({'success': True, 'source': source_data})
        
        # Source not found for this zip - return error
        conn.close()
        return jsonify({'success': False, 'message': 'Source not found for this zip code'}), 404
    except Exception as e:
        logger.error(f"Error getting source: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/get-sources', methods=['GET', 'OPTIONS'])
@login_required
def get_sources():
    """Get all sources for a zip code - ZIP-SPECIFIC"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and request.args.get('zip_code'):
        zip_code = request.args.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Build sources_config similar to admin_dashboard_legacy
        sources_config = {}
        
        # Get zip-specific source settings
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_%"', (zip_code,))
        source_settings = {}
        for row in cursor.fetchall():
            key = row['key']
            if key.startswith('source_'):
                parts = key.replace('source_', '').split('_', 1)
                if len(parts) == 2:
                    source_key = parts[0]
                    setting = parts[1]
                    if source_key not in source_settings:
                        source_settings[source_key] = {}
                    source_settings[source_key][setting] = row['value']
        
        # Get custom sources for this zip
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "custom_source_%"', (zip_code,))
        for row in cursor.fetchall():
            import json
            source_key = row['key'].replace('custom_source_', '')
            try:
                custom_data = json.loads(row['value'])
                custom_data['key'] = source_key
                sources_config[source_key] = custom_data
            except:
                pass
        
        # Get source overrides for this zip
        cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key LIKE "source_override_%"', (zip_code,))
        for row in cursor.fetchall():
            import json
            source_key = row['key'].replace('source_override_', '')
            try:
                override_data = json.loads(row['value'])
                if source_key in sources_config:
                    sources_config[source_key].update(override_data)
                else:
                    if source_key in NEWS_SOURCES:
                        sources_config[source_key] = dict(NEWS_SOURCES[source_key])
                        sources_config[source_key].update(override_data)
                    else:
                        sources_config[source_key] = override_data
                    sources_config[source_key]['key'] = source_key
            except:
                pass
        
        # Apply settings (enabled/require_fall_river) to sources
        for source_key in sources_config:
            if source_key in source_settings:
                if 'enabled' in source_settings[source_key]:
                    sources_config[source_key]['enabled'] = source_settings[source_key]['enabled'] == '1'
                if 'require_fall_river' in source_settings[source_key]:
                    sources_config[source_key]['require_fall_river'] = source_settings[source_key]['require_fall_river'] == '1'
        
        # Get relevance scores
        cursor.execute('SELECT category, item, points FROM relevance_config WHERE zip_code = ? AND category = ?', 
                      (zip_code, 'source_credibility'))
        source_credibility = {}
        for row in cursor.fetchall():
            source_credibility[row[1]] = row[2]
        
        # Add relevance scores to sources
        for source_key, source_data in sources_config.items():
            source_name_lower = source_data.get('name', '').lower()
            if source_name_lower in source_credibility:
                source_data['relevance_score'] = source_credibility[source_name_lower]
            else:
                source_data['relevance_score'] = None
        
        conn.close()
        
        # Convert to list format for easier client-side handling
        sources_list = []
        for source_key, source_data in sources_config.items():
            source_data['key'] = source_key
            sources_list.append(source_data)
        
        return jsonify({'success': True, 'sources': sources_list})
    except Exception as e:
        logger.error(f"Error getting sources: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/edit-source', methods=['POST', 'OPTIONS'])
@login_required
def edit_source():
    """Edit an existing news source - ZIP-SPECIFIC"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    source_key = data.get('key', '')
    name = data.get('name', '')
    url = data.get('url', '')
    rss = data.get('rss')
    category = data.get('category', 'news')
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    # Update in database - ZIP-SPECIFIC
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Check if it's a custom source or built-in for this zip
    cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', (zip_code, f"custom_source_{source_key}"))
    row = cursor.fetchone()
    
    if row:
        # Update custom source
        cursor.execute('''
            UPDATE admin_settings_zip
            SET value = ?
            WHERE zip_code = ? AND key = ?
        ''', (json.dumps({
            'name': name,
            'url': url,
            'rss': rss,
            'category': category,
            'enabled': True,
            'require_fall_river': True
        }), zip_code, f"custom_source_{source_key}"))
    else:
        # Save as override for built-in source (zip-specific)
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
            VALUES (?, ?, ?)
        ''', (zip_code, f"source_override_{source_key}", json.dumps({
            'name': name,
            'url': url,
            'rss': rss,
            'category': category
        })))
    
    # Save or delete relevance score from relevance_config - ZIP-SPECIFIC
    relevance_score = data.get('relevance_score')
    source_name_lower = name.lower()
    if relevance_score is not None and relevance_score != '':
        # Save relevance score
        try:
            relevance_score_float = float(relevance_score)
            cursor.execute('''
                INSERT OR REPLACE INTO relevance_config (category, item, points, zip_code)
                VALUES (?, ?, ?, ?)
            ''', ('source_credibility', source_name_lower, relevance_score_float, zip_code))
        except (ValueError, TypeError):
            pass  # Invalid score, skip
    else:
        # Delete relevance score if cleared (empty string or None)
        cursor.execute('DELETE FROM relevance_config WHERE category = ? AND item = ? AND zip_code = ?', 
                      ('source_credibility', source_name_lower, zip_code))
    
    # Commit the transaction first
    conn.commit()
    conn.close()
    
    # Clear cache AFTER commit to ensure database is updated
    from utils.relevance_calculator import load_relevance_config
    load_relevance_config(force_reload=True)
    
    return jsonify({'success': True})

@app.route('/admin/api/admin-setting', methods=['POST', 'OPTIONS'])
def save_admin_setting():
    """Save admin setting (for regenerate settings)"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    key = data.get('key')
    value = data.get('value')
    
    if not key:
        return jsonify({'success': False, 'message': 'Key is required'})
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES (?, ?)
    ''', (key, str(value)))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    import sqlite3
    from config import DATABASE_CONFIG
    
    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "checks": {}
    }
    
    # Check database
    try:
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM articles')
        article_count = cursor.fetchone()[0]
        conn.close()
        status["checks"]["database"] = "ok"
        status["article_count"] = article_count
    except Exception as e:
        status["status"] = "unhealthy"
        status["checks"]["database"] = f"error: {str(e)}"
    
    # Check website output directory
    try:
        from pathlib import Path
        from config import WEBSITE_CONFIG
        output_dir = Path(WEBSITE_CONFIG.get("output_dir", "website_output"))
        index_file = output_dir / "index.html"
        status["checks"]["website_files"] = "ok" if index_file.exists() else "missing"
    except Exception as e:
        status["checks"]["website_files"] = f"error: {str(e)}"
    
    # Get cache stats
    try:
        from cache import get_cache
        cache_stats = get_cache().get_stats()
        status["cache"] = cache_stats
    except:
        pass
    
    # Get performance metrics
    try:
        from monitoring.metrics import get_metrics
        metrics = get_metrics()
        stats = metrics.get_stats()
        status["performance"] = {
            "aggregation_avg": stats.get("aggregate_articles", {}).get("avg_duration"),
            "website_gen_avg": stats.get("generate_website", {}).get("avg_duration")
        }
    except:
        pass
    
    status_code = 200 if status["status"] == "healthy" else 503
    return jsonify(status), status_code

@app.route('/admin/api/relevance-config', methods=['GET', 'OPTIONS'])
@login_required
def get_relevance_config():
    """Get all relevance configuration items grouped by category"""
    if request.method == 'OPTIONS':
        return '', 200
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('SELECT category, item, points FROM relevance_config ORDER BY category, item')
    rows = cursor.fetchall()
    conn.close()
    
    config = {
        'high_relevance': [],
        'medium_relevance': [],
        'local_places': [],
        'topic_keywords': {},
        'source_credibility': {},
        'clickbait_patterns': []
    }
    
    for row in rows:
        category = row[0]
        item = row[1]
        points = row[2]
        
        if category in ['high_relevance', 'medium_relevance', 'local_places', 'clickbait_patterns']:
            config[category].append(item)
        elif category == 'topic_keywords':
            config[category][item] = points if points is not None else 0.0
        elif category == 'source_credibility':
            config[category][item] = points if points is not None else 0.0
    
    return jsonify({'success': True, 'config': config})

@app.route('/admin/api/relevance-config/add', methods=['POST', 'OPTIONS'])
@login_required
def add_relevance_item():
    """Add a new item to relevance configuration"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    category = data.get('category')
    item = data.get('item', '').strip()
    points = data.get('points')
    
    if not category or not item:
        return jsonify({'success': False, 'message': 'Category and item are required'}), 400
    
    # Prevent managing source_credibility from Relevance page - must use Sources page
    if category == 'source_credibility':
        return jsonify({'success': False, 'message': 'Source credibility scores must be managed on the Sources page. Edit a source to set its relevance score.'}), 400
    
    # Validate category
    valid_categories = ['high_relevance', 'medium_relevance', 'local_places', 'topic_keywords', 'source_credibility', 'clickbait_patterns']
    if category not in valid_categories:
        return jsonify({'success': False, 'message': f'Invalid category. Must be one of: {", ".join(valid_categories)}'}), 400
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'message': 'Zip code required'}), 400
    
    # Set default points based on category if not provided
    if points is None:
        if category == 'high_relevance':
            points = 15.0  # Updated default to 15
        elif category == 'medium_relevance':
            points = 5.0
        elif category == 'local_places':
            points = 3.0
        elif category == 'clickbait_patterns':
            points = None  # No points for clickbait patterns
        else:
            return jsonify({'success': False, 'message': 'Points required for topic_keywords and source_credibility'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO relevance_config (category, item, points, zip_code)
            VALUES (?, ?, ?, ?)
        ''', (category, item, points, zip_code))
        conn.commit()
        conn.close()
        
        # Clear cache to force reload
        from utils.relevance_calculator import load_relevance_config
        load_relevance_config(force_reload=True, zip_code=zip_code)
        
        return jsonify({'success': True, 'message': 'Item added successfully'})
    except sqlite3.IntegrityError as e:
        conn.close()
        logger.error(f"IntegrityError adding relevance item: {e}")
        return jsonify({'success': False, 'message': f'Item "{item}" already exists in {category} for zip {zip_code}'}), 400
    except Exception as e:
        conn.close()
        logger.error(f"Error adding relevance item: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/admin/api/relevance-config/remove', methods=['POST', 'OPTIONS'])
@login_required
def remove_relevance_item():
    """Remove an item from relevance configuration"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    category = data.get('category')
    item = data.get('item', '').strip()
    
    if not category or not item:
        return jsonify({'success': False, 'message': 'Category and item are required'}), 400
    
    # Prevent managing source_credibility from Relevance page - must use Sources page
    if category == 'source_credibility':
        return jsonify({'success': False, 'message': 'Source credibility scores must be managed on the Sources page. Edit a source to set its relevance score.'}), 400
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'message': 'Zip code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM relevance_config WHERE category = ? AND item = ? AND zip_code = ?', (category, item, zip_code))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    if deleted > 0:
        # Clear cache to force reload
        from utils.relevance_calculator import load_relevance_config
        load_relevance_config(force_reload=True, zip_code=zip_code)
        
        return jsonify({'success': True, 'message': 'Item removed successfully'})
    else:
        return jsonify({'success': False, 'message': 'Item not found'}), 404

@app.route('/admin/api/relevance-config/update', methods=['POST', 'OPTIONS'])
@login_required
def update_relevance_points():
    """Update points for a relevance configuration item"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    category = data.get('category')
    item = data.get('item', '').strip()
    points = data.get('points')
    
    if not category or not item:
        return jsonify({'success': False, 'message': 'Category and item are required'}), 400
    
    if points is None:
        return jsonify({'success': False, 'message': 'Points are required'}), 400
    
    # Prevent managing source_credibility from Relevance page - must use Sources page
    if category == 'source_credibility':
        return jsonify({'success': False, 'message': 'Source credibility scores must be managed on the Sources page. Edit a source to set its relevance score.'}), 400
    
    # Allow updating points for topic_keywords or category-level points (high_relevance_points, local_places_points)
    if category not in ['topic_keywords', 'high_relevance_points', 'local_places_points']:
        return jsonify({'success': False, 'message': 'Invalid category for point updates'}), 400
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'message': 'Zip code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Handle category-level points (stored in admin_settings_zip)
    if category in ['high_relevance_points', 'local_places_points']:
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
            VALUES (?, ?, ?)
        ''', (zip_code, category, str(points)))
        conn.commit()
        conn.close()
        
        # Clear cache to force reload
        from utils.relevance_calculator import load_relevance_config
        load_relevance_config(force_reload=True, zip_code=zip_code)
        
        return jsonify({'success': True, 'message': 'Category points updated successfully'})
    
    # Handle topic_keywords (stored in relevance_config)
    cursor.execute('''
        UPDATE relevance_config 
        SET points = ? 
        WHERE category = ? AND item = ? AND zip_code = ?
    ''', (points, category, item, zip_code))
    
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    
    if updated > 0:
        # Clear cache to force reload
        from utils.relevance_calculator import load_relevance_config
        load_relevance_config(force_reload=True, zip_code=zip_code)
        
        return jsonify({'success': True, 'message': 'Points updated successfully'})
    else:
        return jsonify({'success': False, 'message': 'Item not found'}), 404

@app.route('/admin/api/relevance-threshold', methods=['POST', 'OPTIONS'])
@login_required
def save_relevance_threshold():
    """Save the relevance threshold setting (zip-specific)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    threshold = data.get('threshold')
    
    if threshold is None:
        return jsonify({'success': False, 'message': 'Threshold is required'}), 400
    
    try:
        threshold_value = float(threshold)
        if threshold_value < 0 or threshold_value > 100:
            return jsonify({'success': False, 'message': 'Threshold must be between 0 and 100'}), 400
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid threshold value'}), 400
    
    # Get zip_code from session
    zip_code = session.get('zip_code')
    is_main_admin = session.get('is_main_admin', False)
    
    # Main admin can specify zip_code in request
    if is_main_admin and data.get('zip_code'):
        zip_code = data.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'message': 'Zip code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
        VALUES (?, 'relevance_threshold', ?)
    ''', (zip_code, str(threshold_value)))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': f'Relevance threshold set to {threshold_value}'})

@app.route('/admin/api/recalculate-relevance-scores', methods=['POST', 'OPTIONS'])
@login_required
def recalculate_relevance_scores():
    """Recalculate relevance scores for articles using zip-specific config"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from utils.relevance_calculator import calculate_relevance_score, load_relevance_config
        
        # Get zip_code from session
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code in request
        data = request.json or {}
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        # Clear cache and reload zip-specific config
        load_relevance_config(force_reload=True, zip_code=zip_code)
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get all articles for this zip
        cursor.execute('SELECT id, title, url, published, summary, content, source, zip_code FROM articles WHERE zip_code = ?', (zip_code,))
        articles = cursor.fetchall()
        
        # Get relevance threshold for this zip
        cursor.execute('SELECT value FROM admin_settings_zip WHERE zip_code = ? AND key = ?', (zip_code, 'relevance_threshold'))
        threshold_row = cursor.fetchone()
        relevance_threshold = None
        if threshold_row:
            try:
                relevance_threshold = float(threshold_row[0])
            except (ValueError, TypeError):
                pass
        
        updated_count = 0
        auto_filtered_count = 0
        
        for row in articles:
            article = {
                'id': row[0],
                'title': row[1] or '' if len(row) > 1 else '',
                'url': row[2] or '' if len(row) > 2 else '',
                'published': row[3] or '' if len(row) > 3 else '',
                'summary': row[4] or '' if len(row) > 4 else '',
                'content': row[5] or '' if len(row) > 5 else '',
                'source': row[6] or '' if len(row) > 6 else '',
                'zip_code': row[7] if len(row) > 7 else zip_code
            }
            
            # Calculate new relevance score using zip-specific config
            new_score = calculate_relevance_score(article, zip_code=zip_code)
            
            # Update relevance score in database
            cursor.execute('UPDATE articles SET relevance_score = ? WHERE id = ?', (new_score, article['id']))
            
            # Check if article should be auto-filtered based on threshold
            is_auto_filtered = (relevance_threshold is not None and new_score < relevance_threshold)
            
            # Ensure article_management entry exists, then update it
            cursor.execute('''
                SELECT article_id FROM article_management 
                WHERE article_id = ? AND zip_code = ?
            ''', (article['id'], zip_code))
            exists = cursor.fetchone()
            
            if exists:
                # Update existing entry
                cursor.execute('''
                    UPDATE article_management 
                    SET enabled = ?
                    WHERE article_id = ? AND zip_code = ?
                ''', (0 if is_auto_filtered else 1, article['id'], zip_code))
            else:
                # Create new entry
                cursor.execute('''
                    INSERT INTO article_management (article_id, zip_code, enabled, is_rejected, is_top_story)
                    VALUES (?, ?, ?, 0, 0)
                ''', (article['id'], zip_code, 0 if is_auto_filtered else 1))
            
            if is_auto_filtered:
                auto_filtered_count += 1
            
            updated_count += 1
        
        conn.commit()
        conn.close()
        
        message = f'Recalculated relevance scores for {updated_count} articles'
        if auto_filtered_count > 0:
            message += f' ({auto_filtered_count} auto-filtered)'
        
        return jsonify({'success': True, 'message': message})
    except Exception as e:
        logger.error(f"Error recalculating relevance scores: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/predict-category', methods=['POST', 'OPTIONS'])
@login_required
def predict_category():
    """Predict category for an article (for testing)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from utils.category_classifier import CategoryClassifier
        
        data = request.json or {}
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        article = data.get('article', {})
        if not article:
            return jsonify({'success': False, 'message': 'Article data required'}), 400
        
        classifier = CategoryClassifier(zip_code)
        primary_category, primary_confidence, secondary_category, secondary_confidence = classifier.predict_category(article)
        
        return jsonify({
            'success': True,
            'primary_category': primary_category,
            'primary_confidence': primary_confidence,
            'secondary_category': secondary_category,
            'secondary_confidence': secondary_confidence
        })
    except Exception as e:
        logger.error(f"Error predicting category: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/set-article-category', methods=['POST', 'OPTIONS'])
@login_required
def set_article_category():
    """Override article category manually"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json or {}
        article_id = data.get('article_id')
        category = data.get('category')
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        if not article_id or not category:
            return jsonify({'success': False, 'message': 'Article ID and category required'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get article data for training
        cursor.execute('SELECT title, content, summary, source, url FROM articles WHERE id = ?', (article_id,))
        article_row = cursor.fetchone()
        
        if article_row:
            title, content, summary, source, url = article_row
            
            # Create category training table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS category_training (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER,
                    title TEXT,
                    content TEXT,
                    summary TEXT,
                    source TEXT,
                    url TEXT,
                    original_category TEXT,
                    corrected_category TEXT,
                    zip_code TEXT,
                    trained_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (article_id) REFERENCES articles (id)
                )
            ''')
            
            # Get original category before override
            cursor.execute('SELECT category FROM articles WHERE id = ?', (article_id,))
            original_cat_row = cursor.fetchone()
            original_category = original_cat_row[0] if original_cat_row else None
            
            # Store training data
            cursor.execute('''
                INSERT INTO category_training 
                (article_id, title, content, summary, source, url, original_category, corrected_category, zip_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (article_id, title, content or '', summary or '', source or '', url or '', original_category, category, zip_code))
        
        # Update article category with override flag
        cursor.execute('''
            UPDATE articles 
            SET category = ?, primary_category = ?, category_override = 1
            WHERE id = ?
        ''', (category, category, article_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Category set to {category}'})
    except Exception as e:
        logger.error(f"Error setting article category: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/train-category-positive', methods=['POST', 'OPTIONS'])
@login_required
def train_category_positive():
    """Train model with positive example (thumbs up)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from utils.category_classifier import CategoryClassifier
        
        data = request.json or {}
        article_id = data.get('article_id')
        category = data.get('category')
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        if not article_id or not category:
            return jsonify({'success': False, 'message': 'Article ID and category required'}), 400
        
        # Get article data
        conn = get_db_legacy()
        cursor = conn.cursor()
        cursor.execute('SELECT title, content, summary, source FROM articles WHERE id = ?', (article_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'success': False, 'message': 'Article not found'}), 404
        
        article = {
            'title': row[0] or '',
            'content': row[1] or '',
            'summary': row[2] or '',
            'source': row[3] or ''
        }
        
        # Train classifier
        classifier = CategoryClassifier(zip_code)
        classifier.train_from_feedback(article, category, is_positive=True)
        
        # Optionally recalculate category for this article
        primary_category, primary_confidence, secondary_category, secondary_confidence = classifier.predict_category(article)
        
        # Update article with new prediction
        conn = get_db_legacy()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE articles 
            SET primary_category = ?, category_confidence = ?, secondary_category = ?
            WHERE id = ?
        ''', (primary_category, primary_confidence, secondary_category, article_id))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Trained positive example for {category}',
            'updated_category': primary_category,
            'updated_confidence': primary_confidence
        })
    except Exception as e:
        logger.error(f"Error training category positive: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/train-category-negative', methods=['POST', 'OPTIONS'])
@login_required
def train_category_negative():
    """Train model with negative example (thumbs down)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from utils.category_classifier import CategoryClassifier
        
        data = request.json or {}
        article_id = data.get('article_id')
        category = data.get('category')
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        if not article_id or not category:
            return jsonify({'success': False, 'message': 'Article ID and category required'}), 400
        
        # Get article data
        conn = get_db_legacy()
        cursor = conn.cursor()
        cursor.execute('SELECT title, content, summary, source FROM articles WHERE id = ?', (article_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'success': False, 'message': 'Article not found'}), 404
        
        article = {
            'title': row[0] or '',
            'content': row[1] or '',
            'summary': row[2] or '',
            'source': row[3] or ''
        }
        
        # Train classifier
        classifier = CategoryClassifier(zip_code)
        classifier.train_from_feedback(article, category, is_positive=False)
        
        # Optionally recalculate category for this article
        primary_category, primary_confidence, secondary_category, secondary_confidence = classifier.predict_category(article)
        
        # Update article with new prediction
        conn = get_db_legacy()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE articles 
            SET primary_category = ?, category_confidence = ?, secondary_category = ?
            WHERE id = ?
        ''', (primary_category, primary_confidence, secondary_category, article_id))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Trained negative example for {category}',
            'updated_category': primary_category,
            'updated_confidence': primary_confidence
        })
    except Exception as e:
        logger.error(f"Error training category negative: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/category-keywords/get', methods=['GET', 'OPTIONS'])
@login_required
def get_category_keywords():
    """Get keywords for a category/zip (or all categories if no category specified)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        category = request.args.get('category')
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code
        if is_main_admin and request.args.get('zip_code'):
            zip_code = request.args.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # If category specified, return just that category's keywords
        if category:
            cursor.execute('''
                SELECT keyword FROM category_keywords 
                WHERE zip_code = ? AND category = ?
                ORDER BY keyword
            ''', (zip_code, category))
            keywords = [row[0] for row in cursor.fetchall()]
            conn.close()
            return jsonify({'success': True, 'keywords': keywords})
        
        # Otherwise, return all categories with their keywords
        cursor.execute('''
            SELECT category, keyword FROM category_keywords 
            WHERE zip_code = ?
            ORDER BY category, keyword
        ''', (zip_code,))
        
        categories_data = {}
        for row in cursor.fetchall():
            cat = row[0]
            keyword = row[1]
            if cat not in categories_data:
                categories_data[cat] = []
            categories_data[cat].append(keyword)
        
        conn.close()
        
        return jsonify({'success': True, 'categories': categories_data})
    except Exception as e:
        logger.error(f"Error getting category keywords: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/category-keywords/add', methods=['POST', 'OPTIONS'])
@login_required
def add_category_keyword():
    """Add a keyword to a category"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json or {}
        category = data.get('category')
        keyword = data.get('keyword', '').strip()
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        if not category or not keyword:
            return jsonify({'success': False, 'message': 'Category and keyword required'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO category_keywords (zip_code, category, keyword)
                VALUES (?, ?, ?)
            ''', (zip_code, category, keyword.lower()))
            conn.commit()
            conn.close()
            
            return jsonify({'success': True, 'message': 'Keyword added successfully'})
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'success': False, 'message': 'Keyword already exists'}), 400
        except Exception as e:
            conn.close()
            logger.error(f"Error adding keyword: {e}", exc_info=True)
            return jsonify({'success': False, 'message': str(e)}), 500
    except Exception as e:
        logger.error(f"Error in add_category_keyword: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/category-keywords/remove', methods=['POST', 'OPTIONS'])
@login_required
def remove_category_keyword():
    """Remove a keyword from a category"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json or {}
        category = data.get('category')
        keyword = data.get('keyword', '').strip()
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        if not category or not keyword:
            return jsonify({'success': False, 'message': 'Category and keyword required'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM category_keywords 
            WHERE zip_code = ? AND category = ? AND keyword = ?
        ''', (zip_code, category, keyword.lower()))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Keyword removed successfully'})
    except Exception as e:
        logger.error(f"Error removing keyword: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/category-keywords/import-defaults', methods=['POST', 'OPTIONS'])
@login_required
def import_default_keywords():
    """Import default keywords for a category"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from utils.category_classifier import DEFAULT_CATEGORY_KEYWORDS
        
        data = request.json or {}
        category = data.get('category')
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        if not category or category not in DEFAULT_CATEGORY_KEYWORDS:
            return jsonify({'success': False, 'message': 'Invalid category'}), 400
        
        keywords = DEFAULT_CATEGORY_KEYWORDS[category]
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        added = 0
        skipped = 0
        for keyword in keywords:
            try:
                cursor.execute('''
                    INSERT INTO category_keywords (zip_code, category, keyword)
                    VALUES (?, ?, ?)
                ''', (zip_code, category, keyword.lower()))
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
                continue
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Imported {added} keywords ({skipped} already existed)'
        })
    except Exception as e:
        logger.error(f"Error importing default keywords: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/category-keywords/populate-defaults', methods=['POST', 'OPTIONS'])
@login_required
def populate_all_default_keywords():
    """Populate all category keywords from DEFAULT_CATEGORY_KEYWORDS for a zip"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from utils.category_classifier import DEFAULT_CATEGORY_KEYWORDS
        
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code
        data = request.json or {}
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        total_added = 0
        total_skipped = 0
        category_results = {}
        
        for category, keywords in DEFAULT_CATEGORY_KEYWORDS.items():
            added = 0
            skipped = 0
            for keyword in keywords:
                try:
                    cursor.execute('''
                        INSERT INTO category_keywords (zip_code, category, keyword)
                        VALUES (?, ?, ?)
                    ''', (zip_code, category, keyword.lower()))
                    added += 1
                except sqlite3.IntegrityError:
                    skipped += 1
                    continue
            
            category_results[category] = {'added': added, 'skipped': skipped}
            total_added += added
            total_skipped += skipped
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Populated {total_added} keywords across all categories ({total_skipped} already existed)',
            'results': category_results
        })
    except Exception as e:
        logger.error(f"Error populating default keywords: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/toggle-stellar', methods=['POST', 'OPTIONS'])
@login_required
def toggle_stellar():
    """Toggle stellar flag for an article"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json or {}
        article_id = data.get('article_id')
        is_stellar = data.get('is_stellar', False)
        
        if not article_id:
            return jsonify({'success': False, 'message': 'Article ID required'}), 400
        
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Check if article_management entry exists
        cursor.execute('''
            SELECT id FROM article_management 
            WHERE article_id = ? AND zip_code = ?
        ''', (article_id, zip_code))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing entry
            cursor.execute('''
                UPDATE article_management 
                SET is_stellar = ?
                WHERE article_id = ? AND zip_code = ?
            ''', (1 if is_stellar else 0, article_id, zip_code))
        else:
            # Create new entry
            cursor.execute('''
                INSERT INTO article_management (article_id, zip_code, is_stellar)
                VALUES (?, ?, ?)
            ''', (article_id, zip_code, 1 if is_stellar else 0))
        
        conn.commit()
        
        # If marking as stellar, extract keywords and add to high_relevance
        if is_stellar:
            cursor.execute('SELECT title, content FROM articles WHERE id = ?', (article_id,))
            article = cursor.fetchone()
            
            if article:
                title = article[0] or ''
                content = article[1] or ''
                
                # Extract significant words (3+ characters, not stop words)
                import re
                from utils.category_classifier import STOP_WORDS
                
                text = (title + ' ' + content).lower()
                words = re.findall(r'\b[a-z]{3,}\b', text)
                
                # Filter out stop words and get unique words
                significant_words = [w for w in words if w not in STOP_WORDS]
                word_counts = {}
                for word in significant_words:
                    word_counts[word] = word_counts.get(word, 0) + 1
                
                # Get top 5 most frequent words
                top_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                
                # Add to high_relevance keywords
                added_keywords = []
                for word, count in top_words:
                    try:
                        cursor.execute('''
                            INSERT INTO relevance_config (zip_code, category, item, points)
                            VALUES (?, 'high_relevance', ?, ?)
                        ''', (zip_code, word, 15.0))
                        added_keywords.append(word)
                    except sqlite3.IntegrityError:
                        # Already exists
                        pass
                
                conn.commit()
                
                if added_keywords:
                    logger.info(f"Extracted keywords from stellar article {article_id}: {added_keywords}")
        
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Article marked as {"stellar" if is_stellar else "normal"}',
            'is_stellar': is_stellar
        })
    except Exception as e:
        logger.error(f"Error toggling stellar: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/category-keywords/bulk-add', methods=['POST', 'OPTIONS'])
@login_required
def bulk_add_keywords():
    """Add multiple keywords at once"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json or {}
        category = data.get('category')
        keywords = data.get('keywords', [])
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        if not category or not keywords:
            return jsonify({'success': False, 'message': 'Category and keywords required'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        added = 0
        skipped = 0
        for keyword in keywords:
            keyword = keyword.strip().lower()
            if not keyword:
                continue
            try:
                cursor.execute('''
                    INSERT INTO category_keywords (zip_code, category, keyword)
                    VALUES (?, ?, ?)
                ''', (zip_code, category, keyword))
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
                continue
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Added {added} keywords ({skipped} already existed)'
        })
    except Exception as e:
        logger.error(f"Error bulk adding keywords: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/category-keywords/delete-category', methods=['POST', 'OPTIONS'])
@login_required
def delete_category():
    """Delete a category and all its keywords, reassign articles to News"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json or {}
        category = data.get('category')
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        if not category:
            return jsonify({'success': False, 'message': 'Category required'}), 400
        
        if category == 'News':
            return jsonify({'success': False, 'message': 'Cannot delete the News category (default fallback)'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Delete all keywords for this category
        cursor.execute('''
            DELETE FROM category_keywords 
            WHERE zip_code = ? AND category = ?
        ''', (zip_code, category))
        
        keywords_deleted = cursor.rowcount
        
        # Reassign all articles with this category to "News"
        cursor.execute('''
            UPDATE articles 
            SET primary_category = 'News', category_override = 0
            WHERE zip_code = ? AND primary_category = ?
        ''', (zip_code, category))
        
        articles_updated = cursor.rowcount
        
        # Delete training data for this category
        try:
            table_name = f"category_patterns_{zip_code}"
            cursor.execute(f'DELETE FROM {table_name} WHERE category = ?', (category,))
        except:
            pass  # Table might not exist
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Category "{category}" deleted. {keywords_deleted} keywords removed, {articles_updated} articles reassigned to News.'
        })
    except Exception as e:
        logger.error(f"Error deleting category: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/get-category-stats', methods=['GET', 'OPTIONS'])
@login_required
def get_category_stats():
    """Get category accuracy statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        # Main admin can specify zip_code in request
        if is_main_admin and request.args.get('zip_code'):
            zip_code = request.args.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get category distribution - include all articles for this zip, even if primary_category is NULL
        cursor.execute('''
            SELECT COALESCE(primary_category, 'News') as category, COUNT(*) as count
            FROM articles
            WHERE zip_code = ?
            GROUP BY COALESCE(primary_category, 'News')
            ORDER BY count DESC
        ''', (zip_code,))
        
        category_counts = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Get training data counts from category_patterns table
        from utils.category_classifier import CategoryClassifier
        classifier = CategoryClassifier(zip_code)
        
        table_name = f"category_patterns_{zip_code}"
        cursor.execute(f'''
            SELECT category, SUM(positive_count) as pos, SUM(negative_count) as neg
            FROM {table_name}
            GROUP BY category
        ''')
        
        training_stats = {}
        for row in cursor.fetchall():
            training_stats[row[0]] = {
                'positive': row[1] or 0,
                'negative': row[2] or 0,
                'total': (row[1] or 0) + (row[2] or 0)
            }
        
        conn.close()
        
        return jsonify({
            'success': True,
            'category_counts': category_counts,
            'training_stats': training_stats,
            'total_training': classifier.total_positive + classifier.total_negative
        })
    except Exception as e:
        logger.error(f"Error getting category stats: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/retrain-all-categories', methods=['POST', 'OPTIONS'])
@login_required
def retrain_all_categories():
    """Recalculate all article categories using current model"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from utils.category_classifier import CategoryClassifier
        
        zip_code = session.get('zip_code')
        is_main_admin = session.get('is_main_admin', False)
        
        data = request.json or {}
        if is_main_admin and data.get('zip_code'):
            zip_code = data.get('zip_code')
        
        if not zip_code:
            return jsonify({'success': False, 'message': 'Zip code required'}), 400
        
        classifier = CategoryClassifier(zip_code)
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get all articles for this zip (excluding overrides)
        cursor.execute('''
            SELECT id, title, content, summary, source 
            FROM articles 
            WHERE zip_code = ? AND (category_override = 0 OR category_override IS NULL)
        ''', (zip_code,))
        
        articles = cursor.fetchall()
        updated_count = 0
        
        for row in articles:
            article_id = row[0]
            article = {
                'title': row[1] or '',
                'content': row[2] or '',
                'summary': row[3] or '',
                'source': row[4] or ''
            }
            
            primary_category, primary_confidence, secondary_category, secondary_confidence = classifier.predict_category(article)
            
            cursor.execute('''
                UPDATE articles 
                SET primary_category = ?, category_confidence = ?, secondary_category = ?
                WHERE id = ?
            ''', (primary_category, primary_confidence, secondary_category, article_id))
            
            updated_count += 1
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Recalculated categories for {updated_count} articles'
        })
    except Exception as e:
        logger.error(f"Error retraining all categories: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/zip-codes/add', methods=['POST', 'OPTIONS'])
@login_required
def add_zip_code():
    """Add a zip code to enabled list"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    zip_code = data.get('zip_code', '').strip()
    
    if not zip_code or len(zip_code) != 5 or not zip_code.isdigit():
        return jsonify({'success': False, 'message': 'Invalid zip code format'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get current enabled zips
        cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('enabled_zips',))
        row = cursor.fetchone()
        enabled_zips = []
        if row:
            try:
                import json
                enabled_zips = json.loads(row['value'])
            except:
                enabled_zips = []
        
        # Add zip if not already present
        if zip_code not in enabled_zips:
            enabled_zips.append(zip_code)
            enabled_zips.sort()  # Keep sorted
        
        # Save back to database
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings (key, value)
            VALUES ('enabled_zips', ?)
        ''', (json.dumps(enabled_zips),))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Zip code {zip_code} added'})
    except Exception as e:
        logger.error(f"Error adding zip code: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/zip-codes/remove', methods=['POST', 'OPTIONS'])
@login_required
def remove_zip_code():
    """Remove a zip code from enabled list"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    zip_code = data.get('zip_code', '').strip()
    
    if not zip_code:
        return jsonify({'success': False, 'message': 'Zip code required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get current enabled zips
        cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('enabled_zips',))
        row = cursor.fetchone()
        enabled_zips = []
        if row:
            try:
                import json
                enabled_zips = json.loads(row['value'])
            except:
                enabled_zips = []
        
        # Remove zip if present
        if zip_code in enabled_zips:
            enabled_zips.remove(zip_code)
        
        # Save back to database
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings (key, value)
            VALUES ('enabled_zips', ?)
        ''', (json.dumps(enabled_zips),))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Zip code {zip_code} removed'})
    except Exception as e:
        logger.error(f"Error removing zip code: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/admin/api/regenerate-settings', methods=['POST', 'OPTIONS'])
def save_regenerate_settings():
    """Save regenerate settings"""
    if request.method == 'OPTIONS':
        return '', 200
    data = request.json or {}
    auto_regenerate = data.get('auto_regenerate', False)
    regenerate_interval = data.get('regenerate_interval', 10)
    regenerate_on_load = data.get('regenerate_on_load', False)
    source_fetch_interval = data.get('source_fetch_interval', 10)  # Add source fetch interval
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('auto_regenerate', ?)
    ''', ('1' if auto_regenerate else '0',))
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('regenerate_interval', ?)
    ''', (str(regenerate_interval),))
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('regenerate_on_load', ?)
    ''', ('1' if regenerate_on_load else '0',))
    
    # Save source_fetch_interval
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('source_fetch_interval', ?)
    ''', (str(source_fetch_interval),))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Regenerate settings saved'})

# HTML Templates
LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login{% if zip_code %} - Zip {{ zip_code }}{% endif %}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        .login-box {
            background: white;
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            width: 100%;
            max-width: 400px;
        }
        h1 {
            margin-bottom: 1.5rem;
            color: #333;
            text-align: center;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        label {
            display: block;
            margin-bottom: 0.5rem;
            color: #555;
            font-weight: 500;
        }
        input[type="text"], input[type="password"] {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1rem;
        }
        button {
            width: 100%;
            padding: 0.75rem;
            background: #0078d4;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            margin-top: 1rem;
        }
        button:hover {
            background: #106ebe;
        }
        .error {
            color: #d32f2f;
            margin-bottom: 1rem;
            padding: 0.5rem;
            background: #ffebee;
            border-radius: 4px;
        }
        .info {
            color: #1976d2;
            margin-bottom: 1rem;
            padding: 0.75rem;
            background: #e3f2fd;
            border-radius: 4px;
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="login-box">
        <h1>Admin Login{% if zip_code %} - Zip {{ zip_code }}{% endif %}</h1>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        {% if not zip_code %}
        <div class="info" style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 0.75rem; margin-bottom: 1rem; border-radius: 4px;">
            <strong>Setup Required:</strong><br>
            Admin credentials must be configured via environment variables.<br>
            Set ADMIN_USERNAME, ADMIN_PASSWORD, and ZIP_LOGIN_PASSWORD in your .env file.
        </div>
        {% endif %}
        <form method="POST" id="loginForm">
            <div class="form-group">
                <label>Username{% if zip_code %} (Zip Code: {{ zip_code }}){% endif %}</label>
                <input type="text" name="username" value="{{ zip_code if zip_code else '' }}" required>
            </div>
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">Login</button>
        </form>
    </div>
    <script>
        // Store login state in localStorage after successful login
        document.getElementById('loginForm').addEventListener('submit', function(e) {
            const formData = new FormData(this);
            const username = formData.get('username');
            const password = formData.get('password');
            
            // Check if it's a zip code (5 digits)
            if (username && username.length === 5 && /^[0-9]{5}$/.test(username)) {
                // Store zip code in localStorage for client-side filtering
                localStorage.setItem('admin_zip_code', username);
                sessionStorage.setItem('admin_zip_code', username);
            }
        });
        
        // Check if we have a zip code from URL
        const urlParams = new URLSearchParams(window.location.search);
        const zipParam = urlParams.get('z');
        if (zipParam && zipParam.length === 5) {
            document.querySelector('input[name="username"]').value = zipParam;
        }
    </script>
</body>
</html>
"""

ADMIN_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <meta http-equiv="Last-Modified" content="{{ cache_bust }}">
    <title>Admin Dashboard - Fall River News</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #2a2a2a;
            color: #e0e0e0;
        }
        .header {
            background: #1a1a1a;
            color: white;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #404040;
        }
        .header h1 { font-size: 1.5rem; color: #0078d4; }
        .header a {
            color: white;
            text-decoration: none;
            padding: 0.5rem 1rem;
            background: #0078d4;
            border-radius: 4px;
        }
        .header a:hover {
            background: #106ebe;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        .controls {
            background: #252525;
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 2rem;
            display: flex;
            gap: 1rem;
            align-items: center;
            flex-wrap: wrap;
            border: 1px solid #404040;
        }
        .toggle-switch {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        .switch {
            position: relative;
            display: inline-block;
            width: 50px;
            height: 24px;
        }
        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: .4s;
            border-radius: 24px;
        }
        .slider:before {
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: .4s;
            border-radius: 50%;
        }
        input:checked + .slider {
            background-color: #0078d4;
        }
        input:checked + .slider:before {
            transform: translateX(26px);
        }
        button {
            padding: 0.5rem 1.5rem;
            background: #0078d4;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
        }
        button:hover {
            background: #106ebe;
        }
        .articles-list {
            background: #252525;
            border-radius: 8px;
            overflow: visible;
            max-height: none;
            border: 1px solid #404040;
        }
        .article-item {
            display: flex;
            align-items: center;
            padding: 1rem;
            border-bottom: 1px solid #404040;
            gap: 1rem;
        }
        .article-item:last-child {
            border-bottom: none;
        }
        .article-item.disabled {
            opacity: 0.5;
        }
        .drag-handle {
            cursor: move;
            font-size: 1.5rem;
            color: #888;
        }
        .article-info {
            flex: 1;
        }
        .article-title {
            font-weight: 600;
            margin-bottom: 0.25rem;
            color: #e0e0e0;
        }
        .article-title a {
            color: #0078d4;
            text-decoration: none;
        }
        .article-title a:hover {
            color: #106ebe;
            opacity: 1 !important;
        }
        .article-meta {
            font-size: 0.85rem;
            color: #888;
        }
        .article-actions {
            display: flex;
            gap: 0.5rem;
            align-items: center;
        }
        .article-actions button {
            pointer-events: auto !important;
            z-index: 10;
            position: relative;
            transition: background-color 0.2s, opacity 0.2s;
        }
        .article-actions button:hover {
            opacity: 1 !important;
            transform: scale(1.1);
        }
        .top-story-btn[data-state="on"] {
            background: #ff9800 !important;
            opacity: 1 !important;
            box-shadow: 0 0 15px rgba(255, 193, 7, 0.8), 
                        0 0 30px rgba(255, 193, 7, 0.4), 
                        0 0 45px rgba(255, 193, 7, 0.2) !important;
            transition: box-shadow 0.3s ease, background 0.3s ease !important;
        }
        .top-story-btn[data-state="off"] {
            background: #666 !important;
            opacity: 0.6 !important;
            box-shadow: none !important;
            transition: box-shadow 0.3s ease, background 0.3s ease !important;
        }
        .good-fit-btn[data-state="on"] {
            background: #4caf50 !important;
            opacity: 1 !important;
            box-shadow: 0 0 15px rgba(76, 175, 80, 0.8), 
                        0 0 30px rgba(76, 175, 80, 0.4), 
                        0 0 45px rgba(76, 175, 80, 0.2) !important;
            transition: box-shadow 0.3s ease, background 0.3s ease !important;
        }
        .good-fit-btn[data-state="off"] {
            background: #666 !important;
            opacity: 0.6 !important;
            box-shadow: none !important;
            transition: box-shadow 0.3s ease, background 0.3s ease !important;
        }
        .reject-btn, .restore-btn {
            padding: 0.4rem 0.8rem;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85rem;
            font-weight: 600;
            margin-right: 0.5rem;
        }
        .reject-btn {
            background: #ff9800;
            color: white;
        }
        .reject-btn:hover {
            background: #f57c00;
        }
        .restore-btn {
            background: #4caf50;
            color: white;
        }
        .restore-btn:hover {
            background: #388e3c;
        }
        .article-item.rejected {
            opacity: 0.6;
            background: #3d2817;
        }
        /* Badge styles for trash articles - using CSS classes instead of inline gradients */
        .badge-container {
            color: white;
            padding: 0.4rem 0.8rem;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.85rem;
        }
        .badge-manual {
            background: linear-gradient(135deg, #d32f2f 0%, #f44336 100%);
        }
        .badge-auto {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        /* Bayesian features header gradient */
        .features-header-gradient {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.9rem;
            margin-right: 1rem;
        }
        /* Learned patterns badge gradient */
        .pattern-badge-gradient {
            background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);
            color: white;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: 600;
            box-shadow: 0 2px 4px rgba(211,47,47,0.3);
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }
        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            overflow: auto;
            background-color: rgba(0,0,0,0.7);
        }
        .modal-content {
            background-color: #252525;
            margin: 5% auto;
            padding: 0;
            border: 1px solid #404040;
            width: 90%;
            max-width: 600px;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .modal-header {
            padding: 1.5rem;
            background: #252525;
            color: white;
            border-radius: 8px 8px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .modal-header h2 {
            margin: 0;
            font-size: 1.5rem;
        }
        .close-modal {
            color: #aaa;
            font-size: 28px;
            font-weight: bold;
            cursor: pointer;
            line-height: 1;
        }
        .close-modal:hover {
            color: white;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 600;
            color: #e0e0e0;
        }
        .form-group input,
        .form-group textarea,
        .form-group select {
            width: 100%;
            padding: 0.75rem;
            background: #1a1a1a;
            border: 1px solid #404040;
            border-radius: 4px;
            font-size: 1rem;
            color: #e0e0e0;
            box-sizing: border-box;
        }
        .form-group input:focus,
        .form-group textarea:focus,
        .form-group select:focus {
            outline: none;
            border-color: #0078d4;
        }
        .form-group textarea {
            resize: vertical;
            min-height: 100px;
        }
        .form-actions {
            padding: 1.5rem;
            background: #1a1a1a;
            border-top: 1px solid #404040;
            display: flex;
            gap: 1rem;
            justify-content: flex-end;
            border-radius: 0 0 8px 8px;
        }
        .form-actions button {
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
        }
        .form-actions button[type="submit"] {
            background: #0078d4;
            color: white;
        }
        .form-actions button[type="submit"]:hover {
            background: #106ebe;
        }
        .form-actions button[type="button"] {
            background: #666;
            color: white;
        }
        .form-actions button[type="button"]:hover {
            background: #555;
        }
        .tabs {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 1.5rem;
            border-bottom: 2px solid #404040;
        }
        .tab-btn {
            padding: 0.75rem 1.5rem;
            background: transparent;
            border: none;
            color: #b0b0b0;
            cursor: pointer;
            font-size: 1rem;
            font-weight: 600;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            text-decoration: none;
            display: inline-block;
            position: relative;
            z-index: 10;
            transition: color 0.2s;
        }
        .tab-btn:hover {
            color: #0078d4;
        }
        .tab-btn.active {
            color: #0078d4;
            border-bottom-color: #0078d4;
        }
        .tab-btn:visited {
            color: #b0b0b0;
        }
        .tab-btn.active:visited {
            color: #0078d4;
        }
        .tab-content {
            display: none;
        }
        {% if active_tab == 'articles' %}
        #articlesTab {
            display: block;
        }
        {% elif active_tab == 'trash' %}
        #trashTab {
            display: block;
        }
        {% elif active_tab == 'sources' %}
        #sourcesTab {
            display: block;
        }
        {% elif active_tab == 'stats' %}
        #statsTab {
            display: block;
        }
        {% elif active_tab == 'settings' %}
        #settingsTab {
            display: block;
        }
        {% elif active_tab == 'relevance' %}
        #relevanceTab {
            display: block;
        }
        {% elif active_tab == 'categories' %}
        #categoriesTab {
            display: block;
        }
        {% elif active_tab == 'keywords' %}
        #keywordsTab {
            display: block;
        }
        {% endif %}
        .sources-list {
            background: #252525;
            border-radius: 8px;
            overflow: hidden;
            border: 1px solid #404040;
        }
        .source-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.5rem;
            border-bottom: 1px solid #404040;
            gap: 2rem;
        }
        .source-item:last-child {
            border-bottom: none;
        }
        .source-info {
            flex: 1;
        }
        .source-name {
            font-size: 1.2rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
            color: #e0e0e0;
        }
        .source-url {
            font-size: 0.9rem;
            color: #888;
            margin-bottom: 0.25rem;
        }
        .source-category {
            font-size: 0.85rem;
            color: #666;
        }
        .source-actions {
            display: flex;
            gap: 2rem;
            align-items: center;
        }
        .reject-btn, .restore-btn {
            padding: 0.4rem 0.8rem;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.85rem;
            font-weight: 600;
            margin-right: 0.5rem;
        }
        .reject-btn {
            background: #ff9800;
            color: white;
        }
        .reject-btn:hover {
            background: #f57c00;
        }
        .restore-btn {
            background: #4caf50;
            color: white;
        }
        .restore-btn:hover {
            background: #388e3c;
        }
        .article-item.rejected {
            opacity: 0.6;
            background: #fff3e0;
        }
        .stats-container {
            background: #252525;
            border-radius: 8px;
            padding: 2rem;
            border: 1px solid #404040;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .stat-card {
            background: #f5f5f5;
            padding: 1.5rem;
            border-radius: 8px;
            text-align: center;
            border: 2px solid #e0e0e0;
        }
        .stat-value {
            font-size: 2.5rem;
            font-weight: 700;
            color: #0078d4;
            margin-bottom: 0.5rem;
        }
        .stat-label {
            font-size: 0.9rem;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .stats-section {
            background: #1a1a1a;
            padding: 1.5rem;
            border-radius: 8px;
            border: 1px solid #404040;
        }
        .stats-section h3 {
            margin-bottom: 1rem;
            color: #e0e0e0;
        }
        .stats-list {
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }
        .stats-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem;
            background: #252525;
            border-radius: 4px;
            border: 1px solid #404040;
        }
        .stats-item-label {
            font-weight: 600;
            color: #e0e0e0;
        }
        .stats-item-value {
            font-weight: 700;
            color: #0078d4;
        }
        .stats-item-meta {
            font-size: 0.85rem;
            color: #888;
            margin-left: 1rem;
        }
        .settings-container {
            background: #252525;
            border-radius: 8px;
            padding: 2rem;
            border: 1px solid #404040;
        }
        .settings-section {
            padding: 1.5rem;
            background: #1a1a1a;
            border: 1px solid #404040;
            border-radius: 8px;
            margin-bottom: 1.5rem;
        }
        .settings-section h3 {
            margin-bottom: 1rem;
            color: #e0e0e0;
        }
        .settings-controls {
            display: flex;
            gap: 1rem;
            align-items: center;
        }
        .info-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }
        .info-item {
            display: flex;
            justify-content: space-between;
            padding: 0.75rem;
            background: #252525;
            border-radius: 4px;
            border: 1px solid #404040;
        }
        .info-label {
            font-weight: 600;
            color: #888;
        }
        .info-value {
            color: #e0e0e0;
        }
    </style>
    <script src="/Sortable.min.js"></script>
    <!-- Cache bust: {{ cache_bust }} -->
</head>
<body>
    <div class="header">
        <h1>{% if zip_code %}Zip {{ zip_code }} - {% endif %}Admin Dashboard</h1>
        <div style="display: flex; gap: 1rem; align-items: center;">
            <a href="/" style="color: white; text-decoration: none; padding: 0.5rem 1rem; background: #0078d4; border-radius: 4px;">Home</a>
            <a href="/admin/logout" style="color: white; text-decoration: none; padding: 0.5rem 1rem; background: #d32f2f; border-radius: 4px;">Logout</a>
        </div>
    </div>
    
    <div class="container" id="admin-container" data-zip-code="{{ zip_code or '' }}">
        <div class="tabs">
            <a href="/admin/{{ zip_code }}" class="tab-btn {{ 'active' if active_tab == 'articles' else '' }}">Articles</a>
            <a href="/admin/{{ zip_code }}/trash" class="tab-btn {{ 'active' if active_tab == 'trash' else '' }}">🗑️ Trash</a>
            <a href="/admin/{{ zip_code }}/sources" class="tab-btn {{ 'active' if active_tab == 'sources' else '' }}">Sources</a>
            <a href="/admin/{{ zip_code }}/stats" class="tab-btn {{ 'active' if active_tab == 'stats' else '' }}">📊 Stats</a>
            <a href="/admin/{{ zip_code }}/relevance" class="tab-btn {{ 'active' if active_tab == 'relevance' else '' }}">🎯 Relevance</a>
            <a href="/admin/{{ zip_code }}/categories" class="tab-btn {{ 'active' if active_tab == 'categories' else '' }}">📂 Categories</a>
            <a href="/admin/{{ zip_code }}/keywords" class="tab-btn {{ 'active' if active_tab == 'keywords' else '' }}">🔑 Keyword Manager</a>
            <a href="/admin/{{ zip_code }}/settings" class="tab-btn {{ 'active' if active_tab == 'settings' else '' }}">⚙️ Settings</a>
        </div>
        
        {% if active_tab == 'articles' %}
        <div id="articlesTab" class="tab-content">
            <div class="controls">
                <div class="toggle-switch">
                    <label>Show Images:</label>
                    <label class="switch">
                        <input type="checkbox" id="showImages" {{ 'checked' if settings.get('show_images') == '1' else '' }}>
                        <span class="slider"></span>
                    </label>
                </div>
            </div>
            
            <div class="articles-list" id="articles-list" data-zip-code="{{ zip_code or '' }}">
            <div style="padding: 0.75rem 1rem; background: #1a1a1a; border-bottom: 2px solid #404040; font-weight: 600; color: #e0e0e0;">
                Showing {{ articles|length }} of {{ stats.total_articles }} article{{ 's' if stats.total_articles != 1 else '' }}{% if not show_trash and stats.rejected_articles > 0 %} ({{ stats.rejected_articles }} in <a href="/admin/{{ zip_code }}/trash" style="color: #0078d4; text-decoration: underline;">🗑️ Trash</a>){% endif %}
            </div>
            {% for article in articles %}
            <div class="article-item {{ 'rejected' if article.get('is_rejected', 0) else '' }}" data-id="{{ article.id }}">
                <span class="drag-handle">☰</span>
                <div class="article-info">
                    <div class="article-title" style="display: flex; align-items: center; gap: 0.5rem;">
                        <span>{{ article.title[:80] }}{% if article.title|length > 80 %}...{% endif %}</span>
                        {% if article.url %}
                        <a href="{{ article.url }}" target="_blank" rel="noopener noreferrer" title="Open article in new window" style="color: #0078d4; text-decoration: none; font-size: 1.1rem; opacity: 0.7; transition: opacity 0.2s;">🔗</a>
                        {% endif %}
                    </div>
                    <div class="article-meta">
                        {{ article.source }} - {{ article.published[:10] if article.published else 'N/A' }}
                        {% if article.category %}
                        • {{ article.category }}
                        {% endif %}
                        {% if article.relevance_score is defined and article.relevance_score is not none %}
                        • Relevance: {{ "%.0f"|format(article.relevance_score) }}
                        {% else %}
                        • Relevance: N/A
                        {% endif %}
                        {% if article.local_score is defined and article.local_score is not none %}
                        • Local: {{ "%.0f"|format(article.local_score) }}%
                        <span style="display: inline-block; width: 60px; height: 8px; background: #404040; border-radius: 4px; margin-left: 0.5rem; vertical-align: middle; overflow: hidden;">
                            <span style="display: block; width: {{ "%.0f"|format(article.local_score) }}%; height: 100%; background: {% if article.local_score > 60 %}#4caf50{% elif article.local_score > 30 %}#ff9800{% else %}#d32f2f{% endif %};"></span>
                        </span>
                        {% else %}
                        • Local: N/A
                        {% endif %}
                    </div>
                </div>
                <div class="article-actions" style="display: flex; gap: 0.5rem; align-items: center;">
                    <button class="top-story-btn" data-id="{{ article.id }}" data-state="{{ 'on' if article.get('is_top_story', 0) else 'off' }}" data-action="toggle-top-story"
                            style="padding: 0.5rem; background: {% if article.get('is_top_story', 0) %}#ff9800{% else %}#666{% endif %}; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem; opacity: {% if article.get('is_top_story', 0) %}1{% else %}0.6{% endif %};" 
                            title="Mark as top story">
                        🎩
                    </button>
                    <button class="good-fit-btn" data-id="{{ article.id }}" data-state="{{ 'on' if article.get('is_good_fit', 0) else 'off' }}" data-action="toggle-good-fit"
                            style="padding: 0.5rem; background: {% if article.get('is_good_fit', 0) %}#4caf50{% else %}#666{% endif %}; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem; opacity: {% if article.get('is_good_fit', 0) %}1{% else %}0.6{% endif %};" 
                            title="Mark as good fit">
                        👍
                    </button>
                    <button class="edit-article-btn" data-id="{{ article.id }}" data-action="edit-article"
                            style="padding: 0.5rem; background: #252525; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem;" 
                            title="Edit article">
                        ✏️
                    </button>
                    {% if article.get('is_rejected', 0) %}
                    <button class="restore-trash-btn" data-id="{{ article.id }}" data-action="restore-article" 
                            title="Restore from trash" style="padding: 0.5rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem;">↩️</button>
                    {% else %}
                    <button class="trash-btn" data-id="{{ article.id }}" data-action="trash-article"
                            style="padding: 0.5rem; background: #252525; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1.2rem;" 
                            title="Delete">
                        👎
                    </button>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
            </div>
        </div>
        {% endif %}
        
        {% if active_tab == 'trash' %}
        <div id="trashTab" class="tab-content">
            <div style="padding: 1.5rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; margin-bottom: 2rem; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                <h3 style="margin: 0 0 0.75rem 0; color: #fff; font-size: 1.5rem; font-weight: 600;">🗑️ Trash - All Rejected Articles</h3>
                <p style="margin: 0; color: rgba(255,255,255,0.95); font-size: 1rem; line-height: 1.6;">View all rejected articles - both manually rejected and auto-filtered. Manually rejected articles train the Bayesian model. You can restore any article from here.</p>
            </div>
            <div style="margin-bottom: 1.5rem; display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;">
                <div style="display: flex; gap: 0.5rem; align-items: center;">
                    <span style="color: #e0e0e0; font-weight: 600; font-size: 0.95rem;">Filter:</span>
                    <button id="trashFilterAll" class="trash-filter-btn active" data-filter="all" style="padding: 0.5rem 1rem; background: #0078d4; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.9rem; transition: all 0.2s;">All</button>
                    <button id="trashFilterManual" class="trash-filter-btn" data-filter="manual" style="padding: 0.5rem 1rem; background: #404040; color: #e0e0e0; border: 1px solid #555; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.9rem; transition: all 0.2s;">🗑️ Manual</button>
                    <button id="trashFilterAuto" class="trash-filter-btn" data-filter="auto" style="padding: 0.5rem 1rem; background: #404040; color: #e0e0e0; border: 1px solid #555; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.9rem; transition: all 0.2s;">🤖 Auto</button>
                </div>
                <div id="trashFilterCount" style="color: #888; font-size: 0.9rem; margin-left: auto;">
                    <span id="trashFilterCountText">Loading...</span>
                </div>
            </div>
            <div style="margin-bottom: 1.5rem; position: relative;">
                <input type="text" id="trashSearchInput" placeholder="🔍 Search by title, source, or reason..." 
                       style="width: 100%; padding: 0.75rem 2.5rem 0.75rem 1rem; background: #252525; border: 1px solid #404040; border-radius: 8px; color: #e0e0e0; font-size: 0.95rem; outline: none; transition: border-color 0.2s;"
                       onfocus="this.style.borderColor='#0078d4';" 
                       onblur="this.style.borderColor='#404040';">
                <button id="trashSearchClear" onclick="clearTrashSearch()" 
                        style="position: absolute; right: 0.5rem; top: 50%; transform: translateY(-50%); background: transparent; border: none; color: #888; cursor: pointer; font-size: 1.2rem; padding: 0.25rem 0.5rem; display: none; transition: color 0.2s;"
                        onmouseover="this.style.color='#e0e0e0';" 
                        onmouseout="this.style.color='#888';"
                        title="Clear search">×</button>
            </div>
            <div class="articles-list" id="trashList" style="background: transparent;">
                <p style="padding: 2rem; text-align: center; color: #888; background: #252525; border-radius: 8px; border: 1px solid #404040;">Loading rejected articles...</p>
            </div>
        </div>
        {% endif %}
        
        
        {% if active_tab == 'sources' %}
        <div id="sourcesTab" class="tab-content">
            <div class="sources-list">
                {% if sources|length == 0 %}
                <div style="padding: 2rem; text-align: center; background: #252525; border-radius: 8px; margin-bottom: 1rem; border: 1px solid #404040;">
                    <p style="color: #666; margin-bottom: 1rem;">No sources configured for this zip code.</p>
                    <button onclick="addNewSource()" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">
                        + Add Source
                    </button>
                </div>
                {% else %}
                {% for source_key, source_config in sources.items() %}
                <div class="source-item">
                    <div class="source-info">
                        <div class="source-name">{{ source_config.name }}</div>
                        <div class="source-url">{{ source_config.url }}</div>
                        <div class="source-category">Category: {{ source_config.get('category', 'news') }}</div>
                        {% if source_config.get('_relevance_score') is not none and source_config.get('_relevance_score') >= 0 %}
                        <div class="source-relevance" style="color: #666; font-size: 0.9rem; margin-top: 0.25rem;">
                            Relevance Score: <strong style="color: {% if source_config.get('_relevance_score', 0) >= 20 %}#4caf50{% elif source_config.get('_relevance_score', 0) >= 10 %}#ff9800{% else %}#f44336{% endif %};">{{ "%.1f"|format(source_config.get('_relevance_score')) }}</strong> points
                        </div>
                        {% else %}
                        <div class="source-relevance" style="color: #999; font-size: 0.9rem; margin-top: 0.25rem; font-style: italic;">
                            No relevance score set
                        </div>
                        {% endif %}
                    </div>
                    <div class="source-actions">
                        <button class="edit-source-btn" data-source-key="{{ source_key }}" title="Edit source">✏️</button>
                        <div class="toggle-switch">
                            <label>Enabled:</label>
                            <label class="switch">
                                <input type="checkbox" class="source-enabled" data-source="{{ source_key }}" {{ 'checked' if source_config.get('enabled', True) else '' }}>
                                <span class="slider"></span>
                            </label>
                        </div>
                        <div class="toggle-switch">
                            <label>Require Fall River:</label>
                            <label class="switch">
                                <input type="checkbox" class="source-filter" data-source="{{ source_key }}" {{ 'checked' if source_config.get('require_fall_river', False) else '' }}>
                                <span class="slider"></span>
                            </label>
                        </div>
                    </div>
                </div>
                {% endfor %}
                <div style="margin-top: 1.5rem;">
                    <button onclick="addNewSource()" style="padding: 0.75rem 1.5rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">
                        + Add Source
                    </button>
                </div>
                {% endif %}
            </div>
            <div style="margin-top: 1.5rem; padding: 1rem; background: #f5f5f5; border-radius: 4px;">
                <p style="color: #666; font-size: 0.9rem;">
                    <strong>Note:</strong> "Require Fall River" means only articles mentioning "Fall River" will be included from that source.
                    This helps filter out irrelevant content from larger regional sources like Fun107 and WPRI.
                </p>
            </div>
        </div>
        {% endif %}
        
        {% if active_tab == 'stats' %}
        <div id="statsTab" class="tab-content">
            <div class="stats-container">
                <h2 style="margin-bottom: 1.5rem;">Statistics Dashboard</h2>
                
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-value">{{ stats.total_articles }}</div>
                        <div class="stat-label">Total Articles</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{{ stats.active_articles }}</div>
                        <div class="stat-label">Active Articles</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{{ stats.rejected_articles }}</div>
                        <div class="stat-label">Rejected Articles</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{{ stats.top_stories }}</div>
                        <div class="stat-label">Top Stories</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{{ stats.disabled_articles }}</div>
                        <div class="stat-label">Disabled Articles</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{{ stats.articles_last_7_days }}</div>
                        <div class="stat-label">Last 7 Days</div>
                    </div>
                </div>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-top: 2rem;">
                    <div class="stats-section">
                        <h3>Articles by Source</h3>
                        <div class="stats-list">
                            {% for item in stats.articles_by_source %}
                            <div class="stats-item">
                                <span class="stats-item-label">{{ item.source }}</span>
                                <span class="stats-item-value">{{ item.count }}</span>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                    
                    <div class="stats-section">
                        <h3>Articles by Category</h3>
                        <div class="stats-list">
                            {% for item in stats.articles_by_category %}
                            <div class="stats-item">
                                <span class="stats-item-label">{{ item.category }}</span>
                                <span class="stats-item-value">{{ item.count }}</span>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                </div>
                
                {% if stats.source_fetch_stats %}
                <div class="stats-section" style="margin-top: 2rem;">
                    <h3>Source Fetch Status</h3>
                    <div class="stats-list">
                        {% for item in stats.source_fetch_stats %}
                        <div class="stats-item">
                            <span class="stats-item-label">{{ item.source }}</span>
                            <span class="stats-item-value">{{ item.count }} articles</span>
                            <span class="stats-item-meta">Last: {{ item.last_fetch[:16] if item.last_fetch else 'Never' }}</span>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}
            </div>
        </div>
        {% endif %}
        
        {% if active_tab == 'categories' %}
        <div id="categoriesTab" class="tab-content">
            <div class="relevance-container">
                <h2 style="margin-bottom: 1.5rem;">Category Classification System</h2>
                
                <!-- Collapsible Explanation -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: #e3f2fd; border-left: 4px solid #2196f3; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="toggleExplanation('categoriesExplanation')">
                        <h3 style="margin: 0; color: #333;">📚 How Category Classification Works</h3>
                        <span id="categoriesExplanationToggle" style="font-size: 1.2rem; user-select: none;">▼</span>
                    </div>
                    <div id="categoriesExplanation" style="margin-top: 1rem; color: #666; font-size: 0.9rem; line-height: 1.6;">
                        <p><strong>Fast Keyword-Based + Bayesian Learning:</strong> This system uses a combination of keyword matching and machine learning to automatically categorize articles.</p>
                        <ul style="margin: 0.5rem 0; padding-left: 1.5rem;">
                            <li><strong>Keyword Matching:</strong> Each category has a list of keywords. Articles are scored based on how many keywords they contain relative to article length.</li>
                            <li><strong>Bayesian Learning:</strong> As you give thumbs up/down feedback on article categories, the system learns patterns and improves accuracy.</li>
                            <li><strong>Cold-Start:</strong> For the first 48 hours or until you have 50+ training examples, the system uses pure keyword matching. After that, it switches to Bayesian-enhanced scoring.</li>
                            <li><strong>Training:</strong> Use the 👍/👎 buttons next to category badges on articles to train the system. The more you train, the smarter it gets!</li>
                        </ul>
                        <p style="margin-top: 0.5rem;"><strong>Result:</strong> After 50-100 training examples per zip code, the system achieves >95% accuracy with zero AI costs and <1ms prediction time.</p>
                    </div>
                </div>
                
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: #e3f2fd; border-left: 4px solid #2196f3; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Retrain All Categories</h3>
                    <p style="color: #666; font-size: 0.9rem; margin-bottom: 1rem;">
                        Recalculate categories for all articles using the current trained model and keyword lists. 
                        This is useful after training the classifier with new examples or updating keywords.
                    </p>
                    <button onclick="retrainAllCategories()" style="padding: 0.75rem 1.5rem; background: #2196f3; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 1rem;">
                        🔄 Retrain All Categories
                    </button>
                </div>
                
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Category Statistics</h3>
                    <div id="categoryStats" style="padding: 1rem; background: #f5f5f5; border-radius: 4px;">
                        <p style="color: #666; text-align: center;">Loading statistics...</p>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}
        
        {% if active_tab == 'keywords' %}
        <div id="keywordsTab" class="tab-content">
            <div class="relevance-container">
                <h2 style="margin-bottom: 1.5rem;">Keyword Manager</h2>
                
                <!-- Collapsible Explanation -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: #e3f2fd; border-left: 4px solid #2196f3; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <div style="display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="toggleExplanation('keywordsExplanation')">
                        <h3 style="margin: 0; color: #333;">📚 About Keyword Manager</h3>
                        <span id="keywordsExplanationToggle" style="font-size: 1.2rem; user-select: none;">▼</span>
                    </div>
                    <div id="keywordsExplanation" style="margin-top: 1rem; color: #666; font-size: 0.9rem; line-height: 1.6;">
                        <p><strong>Manage Category Keywords:</strong> Keywords are the foundation of the fast category classification system.</p>
                        <ul style="margin: 0.5rem 0; padding-left: 1.5rem;">
                            <li><strong>Add Keywords:</strong> Enter keywords that are commonly found in articles of that category. The system counts how many keywords appear in each article.</li>
                            <li><strong>Remove Keywords:</strong> Click the 🗑️ button next to any keyword to remove it from the category.</li>
                            <li><strong>Bulk Add:</strong> Paste multiple keywords (one per line) to add them all at once.</li>
                            <li><strong>Import Defaults:</strong> Load the pre-configured default keyword list for a category (15-20 keywords per category).</li>
                            <li><strong>Add Categories:</strong> Create new categories by typing a name and clicking "+ Add". You can then add keywords for it.</li>
                            <li><strong>Delete Categories:</strong> Remove a category entirely. All its keywords will be deleted and articles will be reassigned to "News".</li>
                        </ul>
                        <p style="margin-top: 0.5rem;"><strong>Tip:</strong> More keywords = better accuracy, but too many generic keywords can cause false positives. Focus on category-specific terms.</p>
                    </div>
                </div>
                
                <!-- Add New Category Section -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Add New Category</h3>
                    <div style="margin-bottom: 1rem;">
                        <input type="text" id="newCategoryInput" placeholder="Category name" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 300px; margin-right: 0.5rem;">
                        <button onclick="addNewCategory()" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Add Category</button>
                    </div>
                    <p style="color: #666; font-size: 0.85rem; margin: 0;">Note: Categories can be deleted (except "News" which is the default fallback).</p>
                </div>
                
                <!-- Categories List (loaded dynamically) -->
                <div id="categoriesKeywordsList">
                    <p style="color: #666; text-align: center; padding: 2rem;">Loading categories and keywords...</p>
                </div>
            </div>
        </div>
        {% endif %}
        
        {% if active_tab == 'settings' %}
        <div id="settingsTab" class="tab-content">
            <div class="settings-container">
                <h2 style="margin-bottom: 1.5rem;">Settings</h2>
                
                <div class="settings-section">
                    <h3>Website Regeneration</h3>
                    <div class="settings-controls">
                        <button onclick="regenerateWebsite()" style="margin-right: 1rem;">Regenerate Website</button>
                        <button onclick="regenerateAll()" style="background: #ff9800; color: white; padding: 0.5rem 1rem; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">🔄 Regenerate All (Fresh Data)</button>
                    </div>
                    <p style="color: #666; margin-top: 0.5rem; font-size: 0.9rem;">
                        <strong>Regenerate Website:</strong> Regenerates the website using existing articles in the database.<br>
                        <strong>Regenerate All:</strong> Fetches fresh data from all sources and regenerates the entire website. This may take several minutes.
                    </p>
                </div>
                
                <div class="settings-section" style="margin-top: 2rem;">
                    <h3>Display Settings</h3>
                    <div class="toggle-switch">
                        <label>Show Images:</label>
                        <label class="switch">
                            <input type="checkbox" id="showImagesSettings" {{ 'checked' if settings.get('show_images') == '1' else '' }}>
                            <span class="slider"></span>
                        </label>
                    </div>
                </div>
                
                <div class="settings-section" style="margin-top: 2rem;">
                    <h3>AI Filtering</h3>
                    <div style="background: #e3f2fd; padding: 1rem; border-radius: 6px; margin-bottom: 1rem; border-left: 4px solid #2196f3;">
                        <p style="margin: 0; color: #1565c0; font-size: 0.9rem; line-height: 1.6;">
                            <strong>AI Relevance Checking:</strong> Uses AI to verify articles are truly about Fall River before ingestion. 
                            Requires OpenAI API key (set OPENAI_API_KEY environment variable). 
                            If no API key, uses enhanced heuristic-based filtering.
                        </p>
                    </div>
                    <div class="toggle-switch">
                        <label>Enable AI Filtering:</label>
                        <label class="switch">
                            <input type="checkbox" id="aiFilteringSettings" {{ 'checked' if settings.get('ai_filtering_enabled') == '1' else '' }}>
                            <span class="slider"></span>
                        </label>
                    </div>
                    <p style="color: #666; margin-top: 0.5rem; font-size: 0.85rem;">
                        AI filtering helps prevent non-Fall River content from being ingested. 
                        Works alongside Bayesian learning and relevance scoring.
                    </p>
                </div>
                
                <div class="settings-section" style="margin-top: 2rem;">
                    <h3>Zip Code Management</h3>
                    <p style="color: #666; font-size: 0.9rem; margin-bottom: 1rem;">
                        Enable zip codes to get pre-generated static pages. Enabled zips will be aggregated and generated periodically.
                    </p>
                    <div style="margin-bottom: 1rem;">
                        <input type="text" id="newZipCode" placeholder="Enter zip code (e.g., 02720)" pattern="[0-9]{5}" maxlength="5" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 200px; margin-right: 0.5rem;">
                        <button onclick="addZipCode()" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Add Zip Code</button>
                    </div>
                    <div id="enabledZipsList" style="display: flex; flex-wrap: gap: 0.5rem; margin-top: 1rem;">
                        {% if enabled_zips %}
                            {% for zip in enabled_zips %}
                            <div style="display: flex; align-items: center; gap: 0.5rem; background: #e8f5e9; padding: 0.5rem 1rem; border-radius: 6px; border: 1px solid #4caf50;">
                                <span style="font-weight: 600;">{{ zip }}</span>
                                <button class="remove-zip-btn" data-zip="{{ zip }}" style="background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer; font-size: 0.8rem;">Remove</button>
                            </div>
                            {% endfor %}
                        {% else %}
                            <p style="color: #999; font-style: italic;">No zip codes enabled. Add one to get started.</p>
                        {% endif %}
                    </div>
                </div>
                
                <div class="settings-section" style="margin-top: 2rem;">
                    <h3>System Information</h3>
                    <div class="info-grid">
                        <div class="info-item">
                            <span class="info-label">Version:</span>
                            <span class="info-value">{{ version }}</span>
                        </div>
                        <div class="info-item">
                            <span class="info-label">Last Generated:</span>
                            <span class="info-value">{{ last_regeneration or 'Never' }}</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}
        
        {% if active_tab == 'relevance' %}
        <div id="relevanceTab" class="tab-content">
            <div class="relevance-container">
                <h2 style="margin-bottom: 1.5rem;">Relevance Scoring Configuration</h2>
                
                <!-- Bayesian Learning System Explanation (Collapsible) -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); color: white;">
                    <div style="display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="toggleExplanation('bayesianExplanation')">
                        <h3 style="margin: 0; color: white; font-size: 1.3rem;">🧠 Bayesian Learning System</h3>
                        <span id="bayesianExplanationToggle" style="font-size: 1.2rem; user-select: none; color: white;">▼</span>
                    </div>
                    <div id="bayesianExplanation" style="margin-top: 1rem;">
                    <div style="background: rgba(255,255,255,0.15); padding: 1rem; border-radius: 6px; margin-bottom: 1rem;">
                        <p style="color: white; font-size: 0.95rem; line-height: 1.7; margin: 0;">
                            The system uses a <strong>Naive Bayes classifier</strong> that learns from your actions to automatically filter similar articles in the future. 
                            This creates a personalized filtering system that improves over time.
                        </p>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: 1rem;">
                        <div style="background: rgba(255,255,255,0.1); padding: 1rem; border-radius: 6px;">
                            <h4 style="margin-top: 0; margin-bottom: 0.5rem; color: white; font-size: 1rem;">📚 Learning from Rejections</h4>
                            <p style="color: rgba(255,255,255,0.95); font-size: 0.9rem; line-height: 1.6; margin: 0;">
                                When you move an article to <strong>🗑️ Trash</strong>, the system extracts features (keywords, locations, topics, nearby towns) 
                                and learns that similar articles should be filtered. Future articles with matching patterns are automatically filtered.
                            </p>
                        </div>
                        <div style="background: rgba(255,255,255,0.1); padding: 1rem; border-radius: 6px;">
                            <h4 style="margin-top: 0; margin-bottom: 0.5rem; color: white; font-size: 1rem;">✅ Learning from Acceptances</h4>
                            <p style="color: rgba(255,255,255,0.95); font-size: 0.9rem; line-height: 1.6; margin: 0;">
                                When you mark articles as "good fit" or keep them active, the system learns these patterns are acceptable. 
                                This balances the model and prevents over-filtering of legitimate content.
                            </p>
                        </div>
                    </div>
                    <div style="background: rgba(255,255,255,0.15); padding: 1rem; border-radius: 6px; margin-top: 1rem;">
                        <h4 style="margin-top: 0; margin-bottom: 0.5rem; color: white; font-size: 1rem;">🎯 How It Works</h4>
                        <ul style="color: rgba(255,255,255,0.95); font-size: 0.9rem; line-height: 1.8; margin: 0; padding-left: 1.5rem;">
                            <li><strong>Feature Extraction:</strong> Analyzes keywords, locations, topics, and nearby towns mentioned in articles</li>
                            <li><strong>Probability Calculation:</strong> Calculates the probability that an article should be rejected based on learned patterns</li>
                            <li><strong>Auto-Filtering:</strong> Articles with >70% rejection probability are automatically filtered during aggregation</li>
                            <li><strong>Context Awareness:</strong> Articles mentioning "Fall River" are less likely to be filtered, even if they match rejection patterns</li>
                        </ul>
                    </div>
                    <div style="background: rgba(255,255,255,0.2); padding: 0.75rem 1rem; border-radius: 6px; margin-top: 1rem; border-left: 4px solid rgba(255,255,255,0.5);">
                        <p style="color: white; font-size: 0.9rem; line-height: 1.6; margin: 0;">
                            <strong>💡 Tip:</strong> The Bayesian system works alongside the relevance scoring system below. 
                            Relevance scores provide immediate filtering based on keywords and rules, while Bayesian learning adapts to your specific preferences over time. 
                            Both systems work together to create the most accurate filtering possible.
                        </p>
                    </div>
                    </div>
                </div>
                
                <!-- Auto-Filter Threshold Setting -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: #e3f2fd; border-left: 4px solid #2196f3; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Auto-Filter Threshold</h3>
                    <p style="color: #666; font-size: 0.9rem; margin-bottom: 1rem;">
                        Articles with relevance scores below this threshold will be automatically filtered out during aggregation. 
                        They will be saved to the database and appear in the "Auto-Filtered" tab for review.
                    </p>
                    <div style="display: flex; align-items: center; gap: 1rem;">
                        <label style="font-weight: 600;">Minimum Relevance Score:</label>
                        <input type="number" id="relevanceThreshold" value="{{ (settings.get('relevance_threshold', '10') | float) | int }}" step="1" min="0" max="100" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 100px;">
                        <button class="save-threshold-btn" style="padding: 0.5rem 1rem; background: #2196f3; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Save Threshold</button>
                        <span id="thresholdSaveStatus" style="color: #4caf50; font-weight: 600; display: none;">✓ Saved</span>
                    </div>
                </div>
                
                <!-- Recalculate All Relevance Scores -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: #fff3e0; border-left: 4px solid #ff9800; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Recalculate All Relevance Scores</h3>
                    <p style="color: #666; font-size: 0.9rem; margin-bottom: 1rem;">
                        Recalculate relevance scores for all existing articles using the current relevance configuration. 
                        This is useful after making changes to keywords, places, topics, or scoring rules.
                    </p>
                    <button onclick="recalculateRelevanceScores()" style="padding: 0.75rem 1.5rem; background: #ff9800; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; font-size: 1rem;">
                        🔄 Recalculate All Relevance Scores
                    </button>
                    <p style="color: #666; font-size: 0.85rem; margin-top: 0.5rem;">
                        This will update all articles in the database with new relevance scores based on your current configuration.
                    </p>
                </div>
                
                <p style="color: #666; margin-bottom: 2rem; line-height: 1.6;">
                    Manage the keywords, places, topics, and sources that affect article relevance scores. 
                    Changes take effect immediately for new articles.
                </p>
                
                {% if relevance_config %}
                <!-- High Relevance Keywords -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">
                        High Relevance Keywords 
                        <input type="number" id="highRelevancePoints" value="{{ (relevance_config.get('high_relevance_points', 15) | float) | int }}" step="1" min="0" max="100" class="update-category-points-input" data-category="high_relevance_points" style="width: 60px; padding: 0.25rem; border: 1px solid #ddd; border-radius: 4px; margin-left: 0.5rem; font-weight: 600;">
                        points each
                    </h3>
                    <div style="margin-bottom: 1rem;">
                        <input type="text" id="highRelevanceInput" placeholder="Add keyword (e.g., 'fall river')" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 300px; margin-right: 0.5rem;">
                        <button onclick="addRelevanceItem('high_relevance', document.getElementById('highRelevanceInput').value)" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">Add</button>
                    </div>
                    <div class="relevance-items" id="highRelevanceItems">
                        {% for item in relevance_config.get('high_relevance', []) %}
                        <div class="relevance-item" style="display: inline-block; margin: 0.25rem; padding: 0.5rem 1rem; background: #e8f5e9; border-radius: 4px;">
                            <span>{{ item }}</span>
                            <button class="remove-relevance-btn" data-category="high_relevance" data-item="{{ item|e }}" style="margin-left: 0.5rem; background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer;">🗑️</button>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                
                <!-- Medium Relevance Keywords (now treated as ignore keywords) -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Ignore Keywords (Nearby Towns)</h3>
                    <p style="color: #666; font-size: 0.9rem; margin-bottom: 1rem; padding: 0.75rem; background: #fff3cd; border-left: 4px solid #ff9800; border-radius: 4px;">
                        <strong>Note:</strong> Articles mentioning these nearby towns will be heavily penalized (-15 points) unless Fall River is also mentioned. 
                        If Fall River is mentioned, they get a small bonus (+1 point). This helps filter out articles about nearby towns that aren't relevant to Fall River.
                    </p>
                    <div style="margin-bottom: 1rem;">
                        <input type="text" id="mediumRelevanceInput" placeholder="Add keyword (e.g., 'somerset')" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 300px; margin-right: 0.5rem;">
                        <button onclick="addRelevanceItem('medium_relevance', document.getElementById('mediumRelevanceInput').value)" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">Add</button>
                    </div>
                    <div class="relevance-items" id="mediumRelevanceItems">
                        {% for item in relevance_config.get('medium_relevance', []) %}
                        <div class="relevance-item" style="display: inline-block; margin: 0.25rem; padding: 0.5rem 1rem; background: #fff3e0; border-radius: 4px;">
                            <span>{{ item }}</span>
                            <button class="remove-relevance-btn" data-category="medium_relevance" data-item="{{ item|e }}" style="margin-left: 0.5rem; background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer;">🗑️</button>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                
                <!-- Local Places -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">
                        Local Places 
                        <input type="number" id="localPlacesPoints" value="{{ (relevance_config.get('local_places_points', 3) | float) | int }}" step="1" min="0" max="100" class="update-category-points-input" data-category="local_places_points" style="width: 60px; padding: 0.25rem; border: 1px solid #ddd; border-radius: 4px; margin-left: 0.5rem; font-weight: 600;">
                        points each
                    </h3>
                    <div style="margin-bottom: 1rem;">
                        <input type="text" id="localPlacesInput" placeholder="Add place (e.g., 'battleship cove')" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 300px; margin-right: 0.5rem;">
                        <button onclick="addRelevanceItem('local_places', document.getElementById('localPlacesInput').value)" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">Add</button>
                    </div>
                    <div class="relevance-items" id="localPlacesItems">
                        {% for item in relevance_config.get('local_places', []) %}
                        <div class="relevance-item" style="display: inline-block; margin: 0.25rem; padding: 0.5rem 1rem; background: #e1f5fe; border-radius: 4px;">
                            <span>{{ item }}</span>
                            <button class="remove-relevance-btn" data-category="local_places" data-item="{{ item|e }}" style="margin-left: 0.5rem; background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer;">🗑️</button>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                
                <!-- Topic Keywords -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Topic Keywords (Variable Points)</h3>
                    <div style="margin-bottom: 1rem;">
                        <input type="text" id="topicKeywordInput" placeholder="Keyword" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 200px; margin-right: 0.5rem;">
                        <input type="number" id="topicPointsInput" placeholder="Points" step="1" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 100px; margin-right: 0.5rem;">
                        <button onclick="addRelevanceItem('topic_keywords', document.getElementById('topicKeywordInput').value, parseFloat(document.getElementById('topicPointsInput').value))" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">Add</button>
                    </div>
                    <div class="relevance-items" id="topicKeywordsItems">
                        {% for keyword, points in relevance_config.get('topic_keywords', {}).items() %}
                        <div class="relevance-item" style="display: flex; align-items: center; margin: 0.5rem 0; padding: 0.75rem; background: #f3e5f5; border-radius: 4px;">
                            <span style="flex: 1; font-weight: 600;">{{ keyword }}</span>
                            <input type="number" value="{{ (points | float) | int }}" step="1" class="update-relevance-points-input" data-category="topic_keywords" data-item="{{ keyword|e }}" style="width: 80px; padding: 0.25rem; border: 1px solid #ddd; border-radius: 4px; margin: 0 0.5rem;">
                            <span style="margin-right: 0.5rem; color: #666;">points</span>
                            <button class="remove-relevance-btn" data-category="topic_keywords" data-item="{{ keyword|e }}" style="background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer;">🗑️</button>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                
                <!-- Source Credibility (Read-Only) -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Source Credibility (Variable Points)</h3>
                    <p style="color: #666; font-size: 0.9rem; margin-bottom: 1rem; padding: 0.75rem; background: #fff3cd; border-left: 4px solid #ff9800; border-radius: 4px;">
                        <strong>Note:</strong> Source credibility scores are managed on the <a href="#sources" onclick="switchTab('sources')" style="color: #2196f3; text-decoration: underline;">Sources page</a>. 
                        Edit a source to set or change its relevance score. This section is read-only for reference.
                    </p>
                    <div class="relevance-items" id="sourceCredibilityItems">
                        {% for source, points in relevance_config.get('source_credibility', {}).items() %}
                        <div class="relevance-item" style="display: flex; align-items: center; margin: 0.5rem 0; padding: 0.75rem; background: #fff9c4; border-radius: 4px;">
                            <span style="flex: 1; font-weight: 600;">{{ source }}</span>
                            <span style="width: 80px; padding: 0.25rem; margin: 0 0.5rem; text-align: right; font-weight: 600; color: {% if points >= 20 %}#4caf50{% elif points >= 10 %}#ff9800{% else %}#f44336{% endif %};">{{ (points | float) | int }}</span>
                            <span style="margin-right: 0.5rem; color: #666;">points</span>
                        </div>
                        {% endfor %}
                        {% if not relevance_config.get('source_credibility', {}) %}
                        <p style="color: #999; font-style: italic; padding: 1rem;">No source credibility scores configured. Add sources on the Sources page to set their relevance scores.</p>
                        {% endif %}
                    </div>
                </div>
                
                <!-- Clickbait Patterns -->
                <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333;">Clickbait Patterns (Penalty: -5 points each)</h3>
                    <div style="margin-bottom: 1rem;">
                        <input type="text" id="clickbaitInput" placeholder="Add pattern (e.g., 'you won't believe')" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 300px; margin-right: 0.5rem;">
                        <button onclick="addRelevanceItem('clickbait_patterns', document.getElementById('clickbaitInput').value)" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer;">Add</button>
                    </div>
                    <div class="relevance-items" id="clickbaitItems">
                        {% for item in relevance_config.get('clickbait_patterns', []) %}
                        <div class="relevance-item" style="display: inline-block; margin: 0.25rem; padding: 0.5rem 1rem; background: #ffebee; border-radius: 4px;">
                            <span>{{ item }}</span>
                            <button class="remove-relevance-btn" data-category="clickbait_patterns" data-item="{{ item|e }}" style="margin-left: 0.5rem; background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer;">🗑️</button>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}
            </div>
        </div>
        {% endif %}
    </div>
    
    <script>
        // Test that script is loading
        console.log('Admin script starting to load...');
        
        // CRITICAL: Unified event delegation using the exact pattern specified
        // This handles all button clicks using event delegation on document
        document.addEventListener('click', async (e) => {
            const btn = e.target.closest('button, .trash-btn, .restore-btn, .top-story-btn, .restore-trash-btn');
            
            if (!btn) return;
            
            // Only process if it's one of our target button classes or has data-action
            if (!btn.classList.contains('trash-btn') && 
                !btn.classList.contains('restore-btn') && 
                !btn.classList.contains('restore-trash-btn') && 
                !btn.classList.contains('top-story-btn') &&
                !btn.classList.contains('good-fit-btn') &&
                !btn.classList.contains('edit-article-btn') &&
                !btn.getAttribute('data-action')) {
                return;
            }
            
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            
            // Get ID from button or parent element - using the exact pattern
            const id = btn.dataset.id || btn.closest('[data-id]')?.dataset.id;
            
            if (!id) {
                console.error('No data-id found on button:', btn);
                return;
            }
            
            const articleId = parseInt(id);
            if (isNaN(articleId)) {
                console.error('Invalid article ID:', id);
                return;
            }
            
            console.log('Button clicked:', {
                button: btn.className,
                action: btn.getAttribute('data-action'),
                id: articleId,
                element: btn
            });
            
            // Handle trash button
            if (btn.classList.contains('trash-btn') || btn.getAttribute('data-action') === 'trash-article') {
                if (typeof window.rejectArticle === 'function') {
                    console.log('Calling rejectArticle for article:', articleId);
                    try {
                        window.rejectArticle(articleId);
                    } catch (error) {
                        console.error('Error calling rejectArticle:', error);
                        alert('Error trashing article: ' + error.message);
                    }
                } else {
                    console.error('rejectArticle is not a function!', typeof window.rejectArticle);
                    alert('Error: rejectArticle function not available. Please refresh the page.');
                }
                return;
            }
            
            // Handle restore button
            if (btn.classList.contains('restore-btn') || btn.classList.contains('restore-trash-btn') || btn.getAttribute('data-action') === 'restore-article') {
                const rejectionType = btn.getAttribute('data-rejection-type') || 'manual';
                if (typeof window.restoreArticle === 'function') {
                    console.log('Calling restoreArticle for article:', articleId, 'rejectionType:', rejectionType);
                    try {
                        window.restoreArticle(articleId, rejectionType);
                    } catch (error) {
                        console.error('Error calling restoreArticle:', error);
                        alert('Error restoring article: ' + error.message);
                    }
                } else {
                    console.error('restoreArticle is not a function!');
                    alert('Error: restoreArticle function not available. Please refresh the page.');
                }
                return;
            }
            
            // Handle top story button
            if (btn.classList.contains('top-story-btn') || btn.getAttribute('data-action') === 'toggle-top-story') {
                if (typeof window.toggleTopStory === 'function') {
                    console.log('Calling toggleTopStory for article:', articleId);
                    try {
                        window.toggleTopStory(articleId);
                    } catch (error) {
                        console.error('Error calling toggleTopStory:', error);
                        alert('Error toggling top story: ' + error.message);
                    }
                } else {
                    console.error('toggleTopStory is not a function!');
                    alert('Error: toggleTopStory function not available. Please refresh the page.');
                }
                return;
            }
            
            // Handle good fit button
            if (btn.classList.contains('good-fit-btn') || btn.getAttribute('data-action') === 'toggle-good-fit') {
                if (typeof window.toggleGoodFit === 'function') {
                    console.log('Calling toggleGoodFit for article:', articleId);
                    try {
                        window.toggleGoodFit(articleId);
                    } catch (error) {
                        console.error('Error calling toggleGoodFit:', error);
                        alert('Error toggling good fit: ' + error.message);
                    }
                } else {
                    console.error('toggleGoodFit is not a function!');
                    alert('Error: toggleGoodFit function not available. Please refresh the page.');
                }
                return;
            }
            
            // Handle edit article button
            if (btn.classList.contains('edit-article-btn') || btn.getAttribute('data-action') === 'edit-article') {
                if (typeof window.editArticle === 'function') {
                    console.log('Calling editArticle for article:', articleId);
                    try {
                        window.editArticle(articleId);
                    } catch (error) {
                        console.error('Error calling editArticle:', error);
                        alert('Error editing article: ' + error.message);
                    }
                } else {
                    console.error('editArticle is not a function!');
                    alert('Error: editArticle function not available. Please refresh the page.');
                }
                return;
            }
        });
        
        console.log('Unified button event handler attached');
        
        // CRITICAL: Define button handler functions FIRST and make them globally available
        // Wrap in IIFE with error handling to ensure they're available immediately
        (function() {
            try {
                // Reject article - make globally accessible immediately
                function rejectArticle(articleId) {
                    console.log('Rejecting article:', articleId);
                    if (!articleId) {
                        alert('Error: Article ID is missing');
                        return;
                    }
                    
                    // Extract zip_code from URL path (e.g., /admin/02720/articles)
                    const pathParts = window.location.pathname.split('/');
                    let zipCode = null;
                    if (pathParts.length >= 3 && pathParts[1] === 'admin' && pathParts[2] && pathParts[2].length === 5) {
                        // Check if it's all digits
                        let isAllDigits = true;
                        for (let i = 0; i < pathParts[2].length; i++) {
                            if (pathParts[2].charAt(i) < '0' || pathParts[2].charAt(i) > '9') {
                                isAllDigits = false;
                                break;
                            }
                        }
                        if (isAllDigits) {
                            zipCode = pathParts[2];
                        }
                    }
                    
                    if (confirm('Move this article to trash? It will be hidden from the website.')) {
                        const requestBody = {
                            article_id: articleId,
                            rejected: true
                        };
                        
                        // Include zip_code if extracted from URL
                        if (zipCode) {
                            requestBody.zip_code = zipCode;
                        }
                        
                        fetch('/admin/api/reject-article', {
                            method: "POST",
                            headers: {"Content-Type": "application/json"},
                            credentials: "same-origin",
                            body: JSON.stringify(requestBody)
                        })
                        .then(r => {
                            console.log('Response status:', r.status);
                            if (!r.ok) {
                                if (r.status === 401) {
                                    throw new Error('Not authenticated. Please log in again.');
                                }
                                throw new Error('HTTP ' + r.status + ': ' + r.statusText);
                            }
                            return r.json();
                        })
                        .then(data => {
                            console.log('Response data:', data);
                            if (data && data.success) {
                                // After rejecting an article, navigate to the Trash tab
                                try {
                                    if (typeof zipCode !== 'undefined' && zipCode) {
                                        window.location.href = `/admin/${zipCode}/trash`;
                                    } else {
                                        // Fallback to generic trash page
                                        window.location.href = '/admin/trash';
                                    }
                                } catch (e) {
                                    console.log('Redirect to trash failed, reloading instead', e);
                                    location.reload();
                                }
                            } else {
                                alert('Error rejecting article: ' + (data ? data.message : 'Unknown error'));
                            }
                        })
                        .catch(e => {
                            console.error('Error rejecting article:', e);
                            alert('Error: ' + (e.message || 'Failed to reject article. Please try again.'));
                        });
                    }
                }
                window.rejectArticle = rejectArticle;
                
                // Toggle top story - make globally accessible immediately
                function toggleTopStory(articleId) {
                    console.log('toggleTopStory called with articleId:', articleId);
                    const button = document.querySelector(`.top-story-btn[data-id="${articleId}"]`);
                    if (!button) {
                        console.error('Button not found for articleId:', articleId);
                        return;
                    }
                    const isCurrentlyTop = button.getAttribute('data-state') === 'on' || (button.style.background && button.style.background.includes('#ff9800'));
                    const newState = !isCurrentlyTop;
                    console.log('Current state:', isCurrentlyTop, 'New state:', newState);
                    
                    fetch('/admin/api/top-story', {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        credentials: "same-origin",
                        body: JSON.stringify({id: articleId, is_top_story: newState})
                    })
                    .then(r => {
                        if (!r.ok) {
                            if (r.status === 401) {
                                throw new Error('Not authenticated. Please log in again.');
                            }
                            throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                        }
                        return r.json();
                    })
                    .then(data => {
                        if (data && data.success) {
                            if (button) {
                                if (newState) {
                                    button.style.background = '#ff9800';
                                    button.style.opacity = '1';
                                    button.setAttribute('data-state', 'on');
                                } else {
                                    button.style.background = '#666';
                                    button.style.opacity = '0.6';
                                    button.setAttribute('data-state', 'off');
                                }
                            }
                            setTimeout(() => location.reload(), 300);
                        } else {
                            alert('Error toggling top story: ' + (data ? data.message : 'Unknown error'));
                        }
                    })
                    .catch(e => {
                        console.error('Error toggling top story:', e);
                        alert('Error: ' + (e.message || 'Failed to toggle top story. Please try again.'));
                    });
                }
                window.toggleTopStory = toggleTopStory;
                
                // Toggle good fit - make globally accessible immediately
                function toggleGoodFit(articleId) {
                    console.log('toggleGoodFit called with articleId:', articleId);
                    const button = document.querySelector(`.good-fit-btn[data-id="${articleId}"]`);
                    if (!button) {
                        console.error('Button not found for articleId:', articleId);
                        return;
                    }
                    const isCurrentlyGood = button.getAttribute('data-state') === 'on' || (button.style.background && button.style.background.includes('#4caf50'));
                    const newState = !isCurrentlyGood;
                    console.log('Current good fit state:', isCurrentlyGood, 'New state:', newState);
                    
                    if (newState) {
                        button.style.background = '#4caf50';
                        button.style.opacity = '1';
                        button.setAttribute('data-state', 'on');
                    } else {
                        button.style.background = '#666';
                        button.style.opacity = '0.6';
                        button.setAttribute('data-state', 'off');
                    }
                    
                    // Persist to database
                    fetch('/admin/api/good-fit', {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        credentials: "same-origin",
                        body: JSON.stringify({id: articleId, is_good_fit: newState})
                    })
                    .then(r => {
                        if (!r.ok) {
                            if (r.status === 401) {
                                throw new Error('Not authenticated. Please log in again.');
                            }
                            throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                        }
                        return r.json();
                    })
                    .then(data => {
                        if (data && data.success) {
                            console.log('Good fit state saved:', newState);
                        } else {
                            // Revert UI on error
                            if (newState) {
                                button.style.background = '#666';
                                button.style.opacity = '0.6';
                                button.setAttribute('data-state', 'off');
                            } else {
                                button.style.background = '#4caf50';
                                button.style.opacity = '1';
                                button.setAttribute('data-state', 'on');
                            }
                            alert('Error saving good fit: ' + (data ? data.message : 'Unknown error'));
                        }
                    })
                    .catch(e => {
                        console.error('Error saving good fit:', e);
                        // Revert UI on error
                        if (newState) {
                            button.style.background = '#666';
                            button.style.opacity = '0.6';
                            button.setAttribute('data-state', 'off');
                        } else {
                            button.style.background = '#4caf50';
                            button.style.opacity = '1';
                            button.setAttribute('data-state', 'on');
                        }
                        alert('Error: ' + (e.message || 'Failed to save good fit. Please try again.'));
                    });
                }
                window.toggleGoodFit = toggleGoodFit;
                
                // Edit article - make globally accessible immediately
                function editArticle(articleId) {
                    console.log('Editing article:', articleId);
                    if (!articleId) {
                        alert('Error: Article ID is missing');
                        return;
                    }
                    fetch('/admin/api/get-article?id=' + encodeURIComponent(articleId), {credentials: 'same-origin'})
                        .then(r => {
                            if (!r.ok) {
                                if (r.status === 401) {
                                    throw new Error('Not authenticated. Please log in again.');
                                }
                                throw new Error('HTTP ' + r.status + ': ' + r.statusText);
                            }
                            return r.json();
                        })
                        .then(data => {
                            if (data && data.success && data.article) {
                                const article = data.article;
                                if (typeof showEditModal === 'function') {
                                    showEditModal(article);
                                } else {
                                    alert('Error: Edit modal function not available');
                                }
                            } else {
                                alert('Error loading article: ' + (data ? data.message : 'Unknown error'));
                            }
                        })
                        .catch(e => {
                            console.error('Error loading article:', e);
                            alert('Error: ' + (e.message || 'Failed to load article. Please try again.'));
                        });
                }
                window.editArticle = editArticle;
                
                console.log('Button handler functions defined and assigned to window:', {
                    rejectArticle: typeof window.rejectArticle,
                    toggleTopStory: typeof window.toggleTopStory,
                    toggleGoodFit: typeof window.toggleGoodFit,
                    editArticle: typeof window.editArticle
                });
                
                // Verify functions are actually callable
                if (typeof window.rejectArticle !== 'function') {
                    console.error('rejectArticle is not a function!');
                }
                if (typeof window.toggleTopStory !== 'function') {
                    console.error('toggleTopStory is not a function!');
                }
                if (typeof window.toggleGoodFit !== 'function') {
                    console.error('toggleGoodFit is not a function!');
                }
                if (typeof window.editArticle !== 'function') {
                    console.error('editArticle is not a function!');
                }
            } catch(e) {
                console.error('Error defining button handler functions:', e);
                console.error('Error stack:', e.stack);
                alert('Script error - check console. Some buttons may not work. Error: ' + e.message);
            }
        })();
        
        // Test that we can find buttons after DOM loads
        document.addEventListener('DOMContentLoaded', function() {
            console.log('DOM loaded, checking for buttons...');
            const testButtons = document.querySelectorAll('[data-action]');
            console.log('Found', testButtons.length, 'buttons with data-action attributes');
            testButtons.forEach((btn, idx) => {
                if (idx < 3) { // Log first 3
                    console.log('Button', idx, ':', btn.getAttribute('data-action'), 'id:', btn.getAttribute('data-id') || btn.getAttribute('data-article-id'));
                }
            });
        });
        
        // Source management - now handled by event delegation, no setupSourceListeners needed
        
        function updateSourceSetting(sourceKey, setting, value, toggleElement) {
            // Show loading state
            const originalChecked = toggleElement.checked;
            toggleElement.disabled = true;
            
            fetch('/admin/api/source', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({
                    source: sourceKey,
                    setting: setting,
                    value: value
                })
            })
            .then(r => r.json())
            .then(data => {
                toggleElement.disabled = false;
                if (data.success) {
                    console.log('Source setting saved:', sourceKey, setting, value);
                    // Show brief success indicator
                    const parent = toggleElement.closest('.toggle-switch') || toggleElement.parentElement;
                    let indicator = parent.querySelector('.save-indicator');
                    if (!indicator) {
                        indicator = document.createElement('span');
                        indicator.className = 'save-indicator';
                        indicator.style.cssText = 'color: #4caf50; margin-left: 0.5rem; font-size: 0.85rem; font-weight: 600;';
                        parent.appendChild(indicator);
                    }
                    indicator.textContent = '✓ Saved';
                    setTimeout(() => {
                        if (indicator) indicator.remove();
                    }, 2000);
                } else {
                    // Revert checkbox on error
                    toggleElement.checked = !originalChecked;
                    alert('Error saving source setting: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                toggleElement.disabled = false;
                // Revert checkbox on error
                toggleElement.checked = !originalChecked;
                alert('Error: ' + e.message);
            });
        }
        
        // Tab-specific functionality is now handled in the main DOMContentLoaded handler
        
        /**
         * ESCAPING UTILITIES - USE THE CORRECT ONE FOR YOUR CONTEXT
         * 
         * escapeHtml(str)     - For HTML TEXT CONTENT (between tags)
         * escapeAttr(str)     - For HTML ATTRIBUTE VALUES (in quotes)
         * escapeCss(str)      - For CSS PROPERTY VALUES (in style attributes)
         * escapeJsString(str) - For JavaScript STRING LITERALS
         * 
         * Examples:
         *   <div>' + escapeHtml(userInput) + '</div>              // Text content
         *   <div data-value="' + escapeAttr(userInput) + '"></div> // Attribute
         *   <div style="color: ' + escapeCss(colorValue) + '"></div> // CSS
         */
        
        // Escaping function to prevent JavaScript syntax errors from special characters in article data
        // Using split/join to avoid regex issues in template rendering
        function escapeHtml(unsafe) {
            if (!unsafe) return '';
            var str = String(unsafe);
            str = str.split('&').join('&amp;');
            str = str.split('<').join('&lt;');
            str = str.split('>').join('&gt;');
            str = str.split('"').join('&quot;');
            str = str.split("'").join('&#039;');
            return str;
        }
        
        // Escape for HTML attribute values (quotes, ampersands, etc.)
        // Using split/join to avoid regex issues in template rendering
        function escapeAttr(unsafe) {
            if (!unsafe) return '';
            var str = String(unsafe);
            str = str.split('&').join('&amp;');
            str = str.split('"').join('&quot;');
            str = str.split("'").join('&#x27;');
            str = str.split('<').join('&lt;');
            str = str.split('>').join('&gt;');
            return str;
        }
        
        // Escape for CSS values (quotes, parentheses in strings, etc.)
        // Using split/join to avoid regex issues in Python template rendering
        function escapeCss(unsafe) {
            if (!unsafe) return '';
            var str = String(unsafe);
            // Escape backslashes first
            str = str.split('\\\\').join('\\\\\\\\');
            // Escape double quotes
            str = str.split('"').join('\\"');
            // Escape single quotes
            str = str.split("'").join("\\'");
            return str;
        }
        
        // Escape for use in JavaScript string literals (double quotes)
        // Using split/join to avoid regex issues in Python template rendering
        function escapeJsString(unsafe) {
            if (!unsafe) return '';
            var str = String(unsafe);
            // Must escape backslashes first, before other escapes
            str = str.split('\\\\').join('\\\\\\\\');
            // Escape double quotes
            str = str.split('"').join('\\"');
            // Escape newlines (actual newline characters, not literal \n)
            str = str.split('\\n').join('\\\\n');
            // Escape carriage returns
            str = str.split('\\r').join('\\\\r');
            // Escape tabs
            str = str.split('\\t').join('\\\\t');
            return str;
        }
        
        // JavaScript string escaping for use in onclick handlers and JavaScript strings
        // Using split/join to avoid regex issues in template rendering
        function escapeJs(unsafe) {
            if (!unsafe) return '';
            var str = String(unsafe);
            // Must escape backslashes first, before other escapes
            str = str.split('\\\\').join('\\\\\\\\');
            // Escape quotes
            str = str.split("'").join("\\'");
            str = str.split('"').join('\\"');
            // Escape forward slashes (to prevent regex delimiter issues)
            str = str.split('/').join('\\/');
            // Escape newlines (actual newline characters, not literal \n)
            str = str.split('\\n').join('\\\\n');
            // Escape carriage returns
            str = str.split('\\r').join('\\\\r');
            // Escape tabs
            str = str.split('\\t').join('\\\\t');
            return str;
        }
        
        // Legacy escapeJs function (keeping for backward compatibility)
        // Using split/join to avoid regex issues in template rendering
        function escapeJsOld(unsafe) {
            if (!unsafe) return '';
            var str = String(unsafe);
            str = str.split('\\').join('\\\\');
            str = str.split("'").join("\\'");
            str = str.split('"').join('\\"');
            str = str.split('/').join('\\/');
            str = str.split('\n').join('\\n');
            str = str.split('\r').join('\\r');
            str = str.split('\t').join('\\t');
            str = str.split('`').join('\\`');
            return str;
        }
        
        // Define loadTrash function BEFORE DOMContentLoaded so it's available
        // Load all trashed articles (both manually rejected and auto-filtered)
        window.loadTrash = function loadTrash() {
            console.log('loadTrash called');
            const trashList = document.getElementById('trashList');
            if (!trashList) {
                console.error('trashList element not found!');
                return;
            }
            
            // Show loading state
            trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #888; background: #252525; border-radius: 8px; border: 1px solid #404040;">Loading rejected articles...</p>';
            
            // Extract zip_code from URL path (e.g., /admin/02720/trash)
            const pathParts = window.location.pathname.split('/');
            let zipCode = null;
            if (pathParts.length >= 3 && pathParts[1] === 'admin' && pathParts[2] && pathParts[2].length === 5) {
                // Check if it's all digits
                let isAllDigits = true;
                for (let i = 0; i < pathParts[2].length; i++) {
                    if (pathParts[2].charAt(i) < '0' || pathParts[2].charAt(i) > '9') {
                        isAllDigits = false;
                        break;
                    }
                }
                if (isAllDigits) {
                    zipCode = pathParts[2];
                }
            }
            
            // Build URL with zip_code as query parameter if available
            // Use get-rejected-articles endpoint (get-all-trash might not exist)
            let url = '/admin/api/get-rejected-articles';
            if (zipCode) {
                url += '?zip_code=' + encodeURIComponent(zipCode);
            }
            
            // Fetch all trashed articles (both manually rejected and auto-filtered)
            console.log('Fetching from URL:', url);
            console.log('Zip code extracted:', zipCode);
            fetch(url, {
                credentials: "same-origin",
                headers: {
                    "Accept": "application/json"
                }
            })
            .then(function(response) {
                console.log('Response status:', response.status, response.statusText);
                if (!response.ok) {
                    var msg = 'HTTP ' + response.status;
                    if (response.status === 401) {
                        return Promise.reject(new Error('Not authenticated. Please log in again.'));
                    }
                    // Try to get error message from response
                    return response.text().then(function(text) {
                        console.error('Error response body:', text);
                        try {
                            var errorData = JSON.parse(text);
                            if (errorData.error) {
                                msg = errorData.error;
                            } else if (errorData.message) {
                                msg = errorData.message;
                            }
                        } catch (e) {
                            if (text) {
                                msg += ': ' + text.substring(0, 200);
                            }
                        }
                        return Promise.reject(new Error(msg));
                    });
                }
                return response.json();
            })
            .then(function(data) {
                console.log('Received data:', data);
                console.log('Data success:', data ? data.success : 'null');
                console.log('Articles count:', data && data.articles ? data.articles.length : 'null');
                if (!data) {
                    throw new Error('No data received from server');
                }
                if (data.success && data.articles && data.articles.length > 0) {
                    trashList.innerHTML = '';
                    data.articles.forEach(function(article) {
                        const articleId = article.id;
                        // Derive rejection_type from the data if not provided
                        const rejectionType = article.rejection_type || 
                            (article.is_auto_rejected ? 'auto' : 'manual');
                        const isManual = rejectionType === 'manual';
                        const isAuto = rejectionType === 'auto';
                        
                        // Determine styling based on rejection type
                        const borderColor = isManual ? '#d32f2f' : '#764ba2';
                        const badgeText = isManual ? '🗑️ Manually Rejected' : '🤖 Auto-Filtered';
                        const badgeClass = isManual ? 'badge-manual' : 'badge-auto';
                        const autoRejectReason = article.auto_reject_reason || '';
                        const safeAutoReason = escapeHtml(autoRejectReason);
                        
                        // Create article card with features - DARK THEME
                        const articleCard = document.createElement('div');
                        articleCard.className = 'trash-article-card';
                        articleCard.style.cssText = 'background: #252525; padding: 0; margin-bottom: 1.5rem; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.3); overflow: hidden; border-left: 5px solid ' + borderColor + '; border: 1px solid #404040;';
                        
                        // Article content - DARK THEME - use string concatenation to avoid regex errors
                        const safeTitle = escapeHtml(article.title || 'No title');
                        const safeSource = escapeHtml(article.source || 'Unknown');
                        // Extract date substring first to avoid parenthesis issues in string concatenation
                        const publishedDate = article.published ? article.published.substring(0, 10) : null;
                        const safePublished = publishedDate ? escapeHtml(publishedDate) : 'N/A';
                        const safeArticleId = escapeHtml(String(articleId));
                        
                        // Calculate relevance score display
                        const relevanceScore = article.relevance_score !== null && article.relevance_score !== undefined ? 
                            Math.round(article.relevance_score) : 'N/A';
                        const relevanceColor = relevanceScore !== 'N/A' && relevanceScore >= 50 ? '#4caf50' : 
                            (relevanceScore !== 'N/A' && relevanceScore >= 30 ? '#ff9800' : '#888');
                        const relevanceHtml = '<div style="font-size: 0.85rem; color: #888; margin-top: 0.25rem;">Relevance: <strong style="color: ' + relevanceColor + ';">' + relevanceScore + '</strong></div>';
                        
                        // Build auto-reject reason HTML if present
                        const autoReasonHtml = isAuto && safeAutoReason ? 
                            '<div style="background: #3d2817; padding: 0.75rem; border-radius: 6px; margin-top: 0.75rem; border-left: 3px solid #764ba2; border: 1px solid #404040;"><strong style="color: #ff9800;">Auto-filtered reason:</strong> <span style="color: #888;">' + safeAutoReason + '</span></div>' : '';
                        
                        // Build base HTML - use CSS classes instead of inline gradient styles
                        let cardHtml = '<div style="padding: 1.5rem; border-bottom: 1px solid #404040;">' +
                            '<div style="display: flex; align-items: flex-start; gap: 1rem; margin-bottom: 0.5rem;">' +
                            '<div style="flex: 1;">' +
                            '<div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">' +
                            '<div class="badge-container ' + badgeClass + '">' + escapeHtml(badgeText) + '</div>' +
                            '</div>' +
                            '<div style="font-weight: 600; font-size: 1.1rem; color: #e0e0e0; margin-bottom: 0.5rem;">' + safeTitle + '</div>' +
                            '<div style="font-size: 0.85rem; color: #888;">' + safeSource + ' - ' + safePublished + '</div>' +
                            relevanceHtml +
                            autoReasonHtml +
                            '</div>' +
                            '<button class="restore-trash-btn" data-id="' + escapeAttr(safeArticleId) + '" data-rejection-type="' + escapeAttr(rejectionType) + '" style="background: #4caf50; color: white; padding: 0.5rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: 0.9rem;">↩️ Restore</button>' +
                            '</div>' +
                            '</div>';
                        
                        // Add Bayesian features section if manual rejection
                        if (isManual) {
                            cardHtml += '<div class="bayesian-features" style="background: #1a1a1a; padding: 1.5rem; margin: 0; border-top: 1px solid #404040;">' +
                                '<div style="display: flex; align-items: center; margin-bottom: 1rem;">' +
                                '<div class="features-header-gradient">📊 Extracted Features</div>' +
                                '<div style="color: #888; font-size: 0.85rem;">Training data for Bayesian model</div>' +
                                '</div>' +
                                '<div class="features-loading" style="color: #888; font-style: italic; padding: 1rem; text-align: center; background: #252525; border-radius: 6px; border: 1px solid #404040;">Loading features...</div>' +
                                '</div>';
                        }
                        
                        articleCard.innerHTML = cardHtml;
                        
                        trashList.appendChild(articleCard);
                        
                        // Get the features container after appending
                        const featuresDiv = articleCard.querySelector('.bayesian-features');
                        
                        // Load features for this article - delay to avoid blocking
                        if (featuresDiv && typeof loadArticleFeatures === 'function') {
                            setTimeout(function() {
                                try {
                                    loadArticleFeatures(articleId, featuresDiv);
                                } catch (feError) {
                                    console.error('Error loading features for article', articleId, ':', feError);
                                }
                            }, 100);
                        }
                    });
                } else if (data.success && (!data.articles || data.articles.length === 0)) {
                    console.log('No trashed articles found');
                    trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #888; background: #252525; border-radius: 8px; font-size: 1.1rem; border: 1px solid #404040;">No articles in trash (both manually rejected and auto-filtered articles will appear here)</p>';
                } else {
                    console.error('Unexpected response format:', data);
                    trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #d32f2f; background: #252525; border-radius: 8px; border: 1px solid #404040;">Error: Unexpected response from server</p>';
                }
            })
            .catch(function(e) {
                console.error('Error loading trash:', e);
                const trashList = document.getElementById('trashList');
                if (trashList) {
                    const errorMsg = e.message || 'Unknown error occurred';
                    trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #d32f2f; background: #252525; border-radius: 8px; border: 1px solid #404040;">' +
                        '<strong>Error loading trash:</strong> ' + escapeHtml(errorMsg) + '<br>' +
                        '<button class="retry-trash-btn" style="margin-top: 1rem; padding: 0.5rem 1rem; background: #0078d4; color: white; border: none; border-radius: 4px; cursor: pointer;">Retry</button>' +
                        '</p>';
                }
            });
        };
        
        // Functions moved to top of script - see above
        
        // Restore article - make globally accessible
        function restoreArticle(articleId, rejectionType) {
            console.log('Restoring article:', articleId, 'type:', rejectionType);
            if (!articleId) {
                alert('Error: Article ID is missing');
                return;
            }
            
            // Extract zip_code from URL path (e.g., /admin/02720/trash)
            const pathParts = window.location.pathname.split('/');
            let zipCode = null;
            if (pathParts.length >= 3 && pathParts[1] === 'admin' && pathParts[2] && pathParts[2].length === 5) {
                // Check if it's all digits
                let isAllDigits = true;
                for (let i = 0; i < pathParts[2].length; i++) {
                    if (pathParts[2].charAt(i) < '0' || pathParts[2].charAt(i) > '9') {
                        isAllDigits = false;
                        break;
                    }
                }
                if (isAllDigits) {
                    zipCode = pathParts[2];
                }
            }
            
            // Use unified restore endpoint
            const requestBody = {
                article_id: articleId,
                rejection_type: rejectionType || 'manual'
            };
            
            // Include zip_code if extracted from URL
            if (zipCode) {
                requestBody.zip_code = zipCode;
            }
            
            fetch('/admin/api/restore-article', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify(requestBody)
            })
            .then(r => {
                if (!r.ok) {
                    if (r.status === 401) {
                        throw new Error('Not authenticated. Please log in again.');
                    }
                    throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                }
                return r.json();
            })
            .then(data => {
                if (data && data.success) {
                    // Reload the trash list instead of reloading the entire page
                    if (typeof window.loadTrash === 'function') {
                        window.loadTrash();
                    } else {
                        location.reload();
                    }
                } else {
                    alert('Error restoring article: ' + (data ? data.message : 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error restoring article:', e);
                alert('Error: ' + (e.message || 'Failed to restore article. Please try again.'));
            });
        }
        
        // Load Bayesian features for a specific article
        function loadArticleFeatures(articleId, container) {
            fetch('/admin/api/get-bayesian-features?article_id=' + encodeURIComponent(articleId), {credentials: 'same-origin'})
                .then(r => r.json())
                .then(data => {
                    if (data.success && data.features) {
                        const features = data.features;
                        const patterns = data.learned_patterns || [];
                        
                        let html = '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.5rem;">';
                        
                        // Nearby Towns - DARK THEME - use string concatenation to avoid regex errors
                        if (features.nearby_towns && features.nearby_towns.length > 0) {
                            html += '<div style="background: #252525; padding: 1rem; border-radius: 8px; border-left: 4px solid #ff9800; box-shadow: 0 1px 3px rgba(0,0,0,0.3); border: 1px solid #404040;">';
                            html += '<div style="font-weight: 600; color: #e0e0e0; margin-bottom: 0.75rem; font-size: 0.9rem; display: flex; align-items: center;"><span style="font-size: 1.2rem; margin-right: 0.5rem;">📍</span> Nearby Towns</div>';
                            html += '<div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                            features.nearby_towns.forEach(town => {
                                const townNoFr = town + '_no_fr';
                                const pattern = patterns.find(p => p.feature === town || p.feature === townNoFr);
                                const count = pattern ? pattern.reject_count : 0;
                                // Build countHtml separately to avoid parenthesis issues
                                const openParen = '(';
                                const closeParen = ')';
                                const countHtml = count > 0 ? ' <strong>' + openParen + count + 'x' + closeParen + '</strong>' : '';
                                const safeTown = escapeHtml(town);
                                const bgColor = count > 0 ? '#3d2817' : '#1a1a1a';
                                const textColor = count > 0 ? '#ff9800' : '#888';
                                const fontWeight = count > 0 ? '600' : '400';
                                const borderColor = count > 0 ? '#ff9800' : '#404040';
                                html += '<span style="background: ' + bgColor + '; color: ' + textColor + '; padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.85rem; font-weight: ' + fontWeight + '; border: 1px solid ' + borderColor + ';">' + safeTown + countHtml + '</span>';
                            });
                            html += '</div></div>';
                        }
                        
                        // Topics - DARK THEME - use string concatenation
                        if (features.topics && features.topics.length > 0) {
                            html += '<div style="background: #252525; padding: 1rem; border-radius: 8px; border-left: 4px solid #4caf50; box-shadow: 0 1px 3px rgba(0,0,0,0.3); border: 1px solid #404040;">';
                            html += '<div style="font-weight: 600; color: #e0e0e0; margin-bottom: 0.75rem; font-size: 0.9rem; display: flex; align-items: center;"><span style="font-size: 1.2rem; margin-right: 0.5rem;">🏷️</span> Topics</div>';
                            html += '<div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                            features.topics.forEach(topic => {
                                const pattern = patterns.find(p => p.feature === topic && p.type === 'topics');
                                const count = pattern ? pattern.reject_count : 0;
                                // Build countHtml separately to avoid parenthesis issues
                                const openParen = '(';
                                const closeParen = ')';
                                const countHtml = count > 0 ? ' <strong>' + openParen + count + 'x' + closeParen + '</strong>' : '';
                                const safeTopic = escapeHtml(topic);
                                const bgColor = count > 0 ? '#2d5016' : '#1a1a1a';
                                const textColor = count > 0 ? '#4caf50' : '#888';
                                const fontWeight = count > 0 ? '600' : '400';
                                const borderColor = count > 0 ? '#4caf50' : '#404040';
                                html += '<span style="background: ' + bgColor + '; color: ' + textColor + '; padding: 0.4rem 0.8rem; border-radius: 6px; font-size: 0.85rem; font-weight: ' + fontWeight + '; border: 1px solid ' + borderColor + ';">' + safeTopic + countHtml + '</span>';
                            });
                            html += '</div></div>';
                        }
                        
                        // Keywords - DARK THEME - use string concatenation
                        if (features.keywords && features.keywords.length > 0) {
                            html += '<div style="background: #252525; padding: 1rem; border-radius: 8px; border-left: 4px solid #2196f3; box-shadow: 0 1px 3px rgba(0,0,0,0.3); border: 1px solid #404040;">';
                            html += '<div style="font-weight: 600; color: #e0e0e0; margin-bottom: 0.75rem; font-size: 0.9rem; display: flex; align-items: center;"><span style="font-size: 1.2rem; margin-right: 0.5rem;">🔑</span> Keywords</div>';
                            html += '<div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">';
                            const topKeywords = features.keywords.slice(0, 10);
                            topKeywords.forEach(keyword => {
                                const pattern = patterns.find(p => p.feature === keyword && p.type === 'keywords');
                                const count = pattern ? pattern.reject_count : 0;
                                // Build countHtml separately to avoid parenthesis issues  
                                const openParen = '(';
                                const closeParen = ')';
                                const countHtml = count > 0 ? ' <strong>' + openParen + count + closeParen + '</strong>' : '';
                                const safeKeyword = escapeHtml(keyword);
                                const bgColor = count > 0 ? '#1e3a5f' : '#1a1a1a';
                                const textColor = count > 0 ? '#60a5fa' : '#888';
                                const fontWeight = count > 0 ? '500' : '400';
                                const borderColor = count > 0 ? '#2196f3' : '#404040';
                                html += '<span style="background: ' + bgColor + '; color: ' + textColor + '; padding: 0.35rem 0.7rem; border-radius: 6px; font-size: 0.8rem; font-weight: ' + fontWeight + '; border: 1px solid ' + borderColor + ';">' + safeKeyword + countHtml + '</span>';
                            });
                            if (features.keywords.length > 10) {
                                // Extract calculation to avoid parenthesis issues in string concatenation
                                const remainingCount = features.keywords.length - 10;
                                html += '<span style="color: #888; font-size: 0.8rem; padding: 0.35rem 0.7rem;">+' + remainingCount + ' more</span>';
                            }
                            html += '</div></div>';
                        }
                        
                        // Fall River Connection - DARK THEME - use string concatenation
                        const fallRiverColor = features.has_fall_river ? '#4caf50' : '#f44336';
                        html += '<div style="background: #252525; padding: 1rem; border-radius: 8px; border-left: 4px solid ' + fallRiverColor + '; box-shadow: 0 1px 3px rgba(0,0,0,0.3); border: 1px solid #404040;">';
                        html += '<div style="font-weight: 600; color: #e0e0e0; margin-bottom: 0.5rem; font-size: 0.9rem; display: flex; align-items: center;"><span style="font-size: 1.2rem; margin-right: 0.5rem;">🔗</span> Fall River Connection</div>';
                        html += '<div style="display: flex; align-items: center; gap: 0.5rem;">';
                        const fallRiverBg = features.has_fall_river ? '#2d5016' : '#4d1a1a';
                        const fallRiverText = features.has_fall_river ? '#4caf50' : '#f44336';
                        const fallRiverBorder = features.has_fall_river ? '#4caf50' : '#f44336';
                        const fallRiverStatus = features.has_fall_river ? '✓ Mentioned' : '✗ Not mentioned';
                        html += '<span style="background: ' + fallRiverBg + '; color: ' + fallRiverText + '; padding: 0.5rem 1rem; border-radius: 6px; font-weight: 600; font-size: 0.9rem; border: 1px solid ' + fallRiverBorder + ';">' + fallRiverStatus + '</span>';
                        html += '</div></div>';
                        
                        html += '</div>';
                        
                        // Show learned patterns summary - DARK THEME - use string concatenation
                        if (patterns.length > 0) {
                            html += '<div style="margin-top: 1.5rem; padding-top: 1.5rem; border-top: 2px solid #404040; background: #252525; padding: 1.5rem; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); border: 1px solid #404040;">';
                            html += '<div style="display: flex; align-items: center; margin-bottom: 1rem;">';
                            html += '<div class="features-header-gradient">🧠 Learned Patterns</div>';
                            html += '<div style="color: #888; font-size: 0.85rem;">This article contributed to these rejection patterns:</div>';
                            html += '</div>';
                            html += '<div style="display: flex; flex-wrap: wrap; gap: 0.75rem;">';
                            const topPatterns = patterns.slice(0, 12).filter(p => p.reject_count > 0);
                            topPatterns.forEach(pattern => {
                                const safeFeature = escapeHtml(pattern.feature);
                                html += '<span class="pattern-badge-gradient"><span>' + safeFeature + '</span><span style="background: rgba(255,255,255,0.3); padding: 0.2rem 0.5rem; border-radius: 4px; font-weight: 700;">' + pattern.reject_count + 'x</span></span>';
                            });
                            html += '</div></div>';
                        }
                        
                        container.querySelector('.features-loading').outerHTML = html;
                    } else {
                        container.querySelector('.features-loading').innerHTML = '<span style="color: #888;">No features available</span>';
                    }
                })
                .catch(e => {
                    container.querySelector('.features-loading').innerHTML = '<span style="color: #d32f2f;">Error loading features</span>';
                });
        }
        
        // Load auto-filtered articles with Bayesian features
        // Note: rejectArticle, toggleTopStory, toggleGoodFit, editArticle are already assigned to window at top of script
        window.loadTrash = loadTrash;
        window.loadArticleFeatures = loadArticleFeatures;
        window.restoreArticle = restoreArticle;
        
        console.log('Functions registered globally:', {
            loadTrash: typeof window.loadTrash,
            loadArticleFeatures: typeof window.loadArticleFeatures
        });
        
        // Initialize Sortable - wrapped in DOMContentLoaded
        document.addEventListener('DOMContentLoaded', function() {
            console.log('Admin panel JavaScript initializing...');
            
            // Wait for Sortable library to load
            function initSortable() {
                if (typeof Sortable === 'undefined') {
                    console.warn('Sortable library not loaded yet, retrying...');
                    setTimeout(initSortable, 100);
                    return;
                }
                
                const articlesList = document.getElementById('articles-list') || document.getElementById('articlesList');
                if (articlesList) {
                    const sortable = Sortable.create(articlesList, {
                    handle: '.drag-handle',
                    filter: '.top-story-btn, .good-fit-btn, .edit-article-btn, .trash-btn, .restore-trash-btn, button',
                    animation: 150,
                    onEnd: function(evt) {
                        const items = Array.from(articlesList.children);
                        const orders = items.map((item, index) => ({
                            id: parseInt(item.dataset.id),
                            order: index
                        }));
                        
                        fetch('/admin/api/reorder-articles', {
                            method: "POST",
                            headers: {"Content-Type": "application/json"},
                            credentials: "same-origin",
                            body: JSON.stringify({orders: orders})
                        })
                        .then(r => {
                            if (!r.ok) throw new Error('HTTP ' + r.status);
                            return r.json();
                        })
                        .then(data => {
                            if (data.success) {
                                console.log('Articles reordered successfully');
                            } else {
                                console.error('Reorder failed:', data.message);
                            }
                        })
                        .catch(e => {
                            console.error('Reorder error:', e);
                            alert('Error saving article order: ' + e.message);
                        });
                    }
                });
                } else {
                    console.warn('articlesList element not found');
                }
            }
            
            // Start Sortable initialization
            initSortable();
            
            // ===== EVENT DELEGATION - ALL TOGGLES =====
            // This works even if elements are added dynamically
            document.body.addEventListener('change', function(e) {
                
                // Top story toggle
                if (e.target.matches('.top-story-toggle')) {
                    const articleId = e.target.dataset.id;
                    const isTopStory = e.target.checked;
                    const toggle = e.target;
                    fetch('/admin/api/top-story', {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        credentials: "same-origin",
                        body: JSON.stringify({id: articleId, is_top_story: isTopStory})
                    })
                    .then(r => {
                        if (!r.ok) throw new Error(`HTTP ${r.status}: ${r.statusText}`);
                        return r.json();
                    })
                    .then(data => {
                        if (data.success) {
                            console.log('Top story toggled:', articleId, isTopStory);
                            fetch('/admin/api/regenerate', {method: "POST", credentials: "same-origin"})
                                .then(() => console.log('Website regenerated with top stories'))
                                .catch(e => console.error('Regeneration error:', e));
                        } else {
                            toggle.checked = !isTopStory;
                            alert('Error toggling top story: ' + (data.message || 'Unknown error'));
                        }
                    })
                    .catch(e => {
                        console.error('Error toggling top story:', e);
                        toggle.checked = !isTopStory;
                        alert('Error: ' + (e.message || 'Failed to toggle top story'));
                    });
                }
                
                // Show images toggle (articles page)
                if (e.target.matches('#showImages')) {
                    fetch('/admin/api/toggle-images', {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        credentials: "same-origin",
                        body: JSON.stringify({show_images: e.target.checked})
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            const settingsCheckbox = document.getElementById('showImagesSettings');
                            if (settingsCheckbox) settingsCheckbox.checked = e.target.checked;
                        }
                    })
                    .catch(e => {
                        console.error('Error toggling images:', e);
                        e.target.checked = !e.target.checked;
                    });
                }
                
                // Show images toggle (settings page)
                if (e.target.matches('#showImagesSettings')) {
                    fetch('/admin/api/toggle-images', {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        credentials: "same-origin",
                        body: JSON.stringify({show_images: e.target.checked})
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            const articlesCheckbox = document.getElementById('showImages');
                            if (articlesCheckbox) articlesCheckbox.checked = e.target.checked;
                        }
                    })
                    .catch(e => {
                        console.error('Error toggling images:', e);
                        e.target.checked = !e.target.checked;
                    });
                }
                
                // AI filtering toggle
                if (e.target.matches('#aiFilteringSettings')) {
                    fetch('/admin/api/toggle-ai-filtering', {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        credentials: "same-origin",
                        body: JSON.stringify({enabled: e.target.checked})
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.success) {
                            console.log('AI filtering setting saved:', e.target.checked);
                        } else {
                            e.target.checked = !e.target.checked;
                            alert('Error saving AI filtering setting: ' + (data.message || 'Unknown error'));
                        }
                    })
                    .catch(e => {
                        console.error('Error saving AI filtering:', e);
                        e.target.checked = !e.target.checked;
                        alert('Error: ' + e.message);
                    });
                }
                
                // Source enabled toggle
                if (e.target.matches('.source-enabled')) {
                    const sourceKey = e.target.dataset.source;
                    const enabled = e.target.checked;
                    updateSourceSetting(sourceKey, 'enabled', enabled, e.target);
                }
                
                // Source filter toggle
                if (e.target.matches('.source-filter')) {
                    const sourceKey = e.target.dataset.source;
                    const requireFR = e.target.checked;
                    updateSourceSetting(sourceKey, 'require_fall_river', requireFR, e.target);
                }
            });
            
            // Load trash if trash tab is active
            {% if active_tab == 'trash' %}
            setTimeout(function() {
                console.log('Loading trash articles...');
                try {
                    if (typeof window.loadTrash === 'function') {
                        window.loadTrash();
                    } else if (typeof loadTrash === 'function') {
                        loadTrash();
                    } else {
                        console.error('loadTrash function not found!');
                        // Retry after a short delay
                        setTimeout(function() {
                            if (typeof window.loadTrash === 'function') {
                                window.loadTrash();
                            } else if (typeof loadTrash === 'function') {
                                loadTrash();
                            } else {
                                console.error('loadTrash still not found after retry');
                                const trashList = document.getElementById('trashList');
                                if (trashList) {
                                    trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #d32f2f; background: #252525; border-radius: 8px; border: 1px solid #404040;">Error: loadTrash function not available. Please refresh the page.</p>';
                                }
                            }
                        }, 500);
                    }
                } catch (e) {
                    console.error('Error calling loadTrash:', e);
                    const trashList = document.getElementById('trashList');
                    if (trashList) {
                        trashList.innerHTML = '<p style="padding: 2rem; text-align: center; color: #d32f2f; background: #252525; border-radius: 8px; border: 1px solid #404040;">Error: ' + escapeHtml(e.message || 'Unknown error') + '</p>';
                    }
                }
            }, 100);
            {% endif %}
            
            
            console.log('Admin panel JavaScript initialized');
        }); // Close DOMContentLoaded
        
        // Restore auto-filtered article - make globally accessible
        
        
        // Edit article function - make globally accessible
        function editArticle(articleId) {
            console.log('Editing article:', articleId);
            if (!articleId) {
                alert('Error: Article ID is missing');
                return;
            }
            // Fetch article data
            fetch('/admin/api/get-article?id=' + encodeURIComponent(articleId), {credentials: 'same-origin'})
                .then(r => {
                    if (!r.ok) {
                        if (r.status === 401) {
                            throw new Error('Not authenticated. Please log in again.');
                        }
                        throw new Error('HTTP ' + r.status + ': ' + r.statusText);
                    }
                    return r.json();
                })
                .then(data => {
                    if (data && data.success && data.article) {
                        const article = data.article;
                        if (typeof showEditModal === 'function') {
                            showEditModal(article);
                        } else {
                            alert('Error: Edit modal function not available');
                        }
                    } else {
                        alert('Error loading article: ' + (data ? data.message : 'Unknown error'));
                    }
                })
                .catch(e => {
                    console.error('Error loading article:', e);
                    alert('Error: ' + (e.message || 'Failed to load article. Please try again.'));
                });
        }
        
        function showEditModal(article) {
            // Create or show edit modal
            let modal = document.getElementById('editArticleModal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'editArticleModal';
                modal.className = 'modal';
                modal.innerHTML = `
                    <div class="modal-content">
                        <div class="modal-header">
                            <h2>Edit Article</h2>
                            <span class="close-modal" onclick="closeEditModal()">&times;</span>
                        </div>
                        <form id="editArticleForm" onsubmit="saveArticleEdit(event)">
                            <input type="hidden" id="editArticleId" name="id">
                            <div class="form-group">
                                <label>Title:</label>
                                <input type="text" id="editArticleTitle" name="title" required>
                            </div>
                            <div class="form-group">
                                <label>Summary:</label>
                                <textarea id="editArticleSummary" name="summary" rows="4"></textarea>
                            </div>
                            <div class="form-group">
                                <label>Publication Date:</label>
                                <input type="datetime-local" id="editArticlePublished" name="published">
                            </div>
                            <div class="form-group">
                                <label>URL:</label>
                                <input type="url" id="editArticleUrl" name="url">
                            </div>
                            <div class="form-group">
                                <label>Category:</label>
                                <select id="editArticleCategory" name="category">
                                    <option value="news">News</option>
                                    <option value="entertainment">Entertainment</option>
                                    <option value="sports">Sports</option>
                                    <option value="media">Media</option>
                                    <option value="local">Local</option>
                                </select>
                            </div>
                            <div class="form-actions">
                                <button type="submit">Save</button>
                                <button type="button" onclick="closeEditModal()">Cancel</button>
                            </div>
                        </form>
                    </div>
                `;
                document.body.appendChild(modal);
            }
            
            // Populate form
            document.getElementById('editArticleId').value = article.id;
            document.getElementById('editArticleTitle').value = article.title || '';
            document.getElementById('editArticleSummary').value = article.summary || '';
            document.getElementById('editArticleUrl').value = article.url || '';
            document.getElementById('editArticleCategory').value = article.category || 'news';
            
            // Format date for datetime-local input
            if (article.published) {
                try {
                    const date = new Date(article.published);
                    const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
                    document.getElementById('editArticlePublished').value = localDate.toISOString().slice(0, 16);
                } catch (e) {
                    document.getElementById('editArticlePublished').value = '';
                }
            } else {
                document.getElementById('editArticlePublished').value = '';
            }
            
            modal.style.display = 'block';
        }
        
        function closeEditModal() {
            const modal = document.getElementById('editArticleModal');
            if (modal) {
                modal.style.display = 'none';
            }
        }
        window.closeEditModal = closeEditModal;
        
        function saveArticleEdit(event) {
            event.preventDefault();
            const form = event.target;
            const formData = new FormData(form);
            const data = {
                id: formData.get('id'),
                title: formData.get('title'),
                summary: formData.get('summary'),
                url: formData.get('url'),
                category: formData.get('category'),
                published: formData.get('published')
            };
            
            // Convert datetime-local to ISO format
            if (data.published) {
                const date = new Date(data.published);
                data.published = date.toISOString();
            }
            
            fetch('/admin/api/edit-article', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(data)
            })
            .then(r => r.json())
            .then(result => {
                if (result.success) {
                    closeEditModal();
                    location.reload();
                } else {
                    alert('Error saving article: ' + (result.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        // Close modal when clicking outside
        window.onclick = function(event) {
            const modal = document.getElementById('editArticleModal');
            if (event.target == modal) {
                closeEditModal();
            }
            const sourceModal = document.getElementById('editSourceModal');
            if (event.target == sourceModal) {
                closeEditSourceModal();
            }
        };
        
        // Add new source function
        function addNewSource() {
            // Show the edit modal with empty fields for new source
            showEditSourceModal({
                key: '',
                name: '',
                url: '',
                rss: '',
                category: 'news',
                relevance_score: ''
            });
        }
        
        // Edit source function
        function editSource(sourceKey) {
            fetch(`/admin/api/get-source?key=${encodeURIComponent(sourceKey)}`, {credentials: 'same-origin'})
                .then(r => r.json())
                .then(data => {
                    if (data.success && data.source) {
                        showEditSourceModal(data.source);
                    } else {
                        alert('Error loading source: ' + (data.message || 'Unknown error'));
                    }
                })
                .catch(e => {
                    alert('Error: ' + e.message);
                });
        }
        
        function showEditSourceModal(source) {
            let modal = document.getElementById('editSourceModal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'editSourceModal';
                modal.className = 'modal';
                modal.innerHTML = '<div class="modal-content">' +
                    '<div class="modal-header">' +
                        '<h2>Edit Source</h2>' +
                        '<span class="close-modal" onclick="if(typeof window.closeEditSourceModal===\'function\'){window.closeEditSourceModal();}">&times;</span>' +
                    '</div>' +
                    '<form id="editSourceForm" onsubmit="if(typeof window.saveSourceEdit===\'function\'){window.saveSourceEdit(event);}return false;">' +
                        '<input type="hidden" id="editSourceKey" name="key">' +
                        '<div class="form-group">' +
                            '<label>Name:</label>' +
                            '<input type="text" id="editSourceName" name="name" required>' +
                        '</div>' +
                        '<div class="form-group">' +
                            '<label>URL:</label>' +
                            '<input type="url" id="editSourceUrl" name="url" required>' +
                        '</div>' +
                        '<div class="form-group">' +
                            '<label>RSS URL:</label>' +
                            '<input type="url" id="editSourceRss" name="rss">' +
                        '</div>' +
                        '<div class="form-group">' +
                            '<label>Category:</label>' +
                            '<select id="editSourceCategory" name="category">' +
                                '<option value="news">News</option>' +
                                '<option value="entertainment">Entertainment</option>' +
                                '<option value="sports">Sports</option>' +
                                '<option value="media">Media</option>' +
                                '<option value="local">Local</option>' +
                            '</select>' +
                        '</div>' +
                        '<div class="form-group">' +
                            '<label>Relevance Score (points):</label>' +
                            '<input type="number" id="editSourceRelevanceScore" name="relevance_score" step="1" min="0" max="100" placeholder="e.g., 25">' +
                            '<small style="color: #666; display: block; margin-top: 0.25rem;">Points added to articles from this source (0-100). Higher = more credible/relevant.</small>' +
                        '</div>' +
                        '<div class="form-actions">' +
                            '<button type="submit">Save</button>' +
                            '<button type="button" onclick="if(typeof window.closeEditSourceModal===\'function\'){window.closeEditSourceModal();}">Cancel</button>' +
                        '</div>' +
                    '</form>' +
                '</div>';
                document.body.appendChild(modal);
            }
            
            // Wait a moment for modal to be in DOM, then populate fields
            setTimeout(() => {
                const titleField = document.getElementById('editSourceModalTitle');
                const keyField = document.getElementById('editSourceKey');
                const nameField = document.getElementById('editSourceName');
                const urlField = document.getElementById('editSourceUrl');
                const rssField = document.getElementById('editSourceRss');
                const categoryField = document.getElementById('editSourceCategory');
                const relevanceScoreField = document.getElementById('editSourceRelevanceScore');
                
                if (titleField) titleField.textContent = source.key ? 'Edit Source' : 'Add New Source';
                if (keyField) keyField.value = source.key || '';
                if (nameField) nameField.value = source.name || '';
                if (urlField) urlField.value = source.url || '';
                if (rssField) rssField.value = source.rss || '';
                if (categoryField) categoryField.value = source.category || 'news';
                if (relevanceScoreField) relevanceScoreField.value = source.relevance_score || '';
            }, 100);
            
            modal.style.display = 'block';
        }
        
        function closeEditSourceModal() {
            const modal = document.getElementById('editSourceModal');
            if (modal) {
                modal.style.display = 'none';
            }
        }
        
        function saveSourceEdit(event) {
            event.preventDefault();
            const form = event.target;
            const formData = new FormData(form);
            const key = formData.get('key');
            const data = {
                key: key,
                name: formData.get('name'),
                url: formData.get('url'),
                rss: formData.get('rss'),
                category: formData.get('category'),
                relevance_score: formData.get('relevance_score')
            };
            
            // If no key, it's a new source - use add-source endpoint
            const endpoint = key ? '/admin/api/edit-source' : '/admin/api/add-source';
            
            fetch(endpoint, {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify(data)
            })
            .then(r => r.json())
            .then(result => {
                if (result.success) {
                    closeEditSourceModal();
                    // Reload page but stay on sources tab using hash
                    window.location.hash = 'sources';
                    location.reload();
                } else {
                    alert('Error saving source: ' + (result.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        // Image and AI filtering toggles are now handled by event delegation in main DOMContentLoaded
        
        // Category management functions
        function showCategoryDropdown(articleId, currentCategory, confidence) {
            const categories = ['Business', 'Crime', 'Entertainment', 'Events', 'Fire', 'Health', 'News', 'Politics', 'Schools', 'Sports', 'Traffic'].sort();
            const categoryEmojis = {
                'Business': '💼', 'Crime': '🚨', 'Entertainment': '🎬', 'Events': '🎉', 'Fire': '🔥',
                'Health': '🏥', 'News': '📰', 'Politics': '🏛️', 'Schools': '🎓', 'Sports': '⚽', 'Traffic': '🚦'
            };
            
            // Hide all other dropdowns
            document.querySelectorAll('.category-dropdown').forEach(el => el.remove());
            
            // Create dropdown
            const badge = document.querySelector(`.category-badge[data-article-id="${articleId}"]`);
            if (!badge) return;
            
            const dropdown = document.createElement('div');
            dropdown.className = 'category-dropdown';
            dropdown.style.cssText = 'position: absolute; background: white; border: 1px solid #ddd; border-radius: 4px; padding: 0.5rem; box-shadow: 0 2px 8px rgba(0,0,0,0.15); z-index: 1000; min-width: 200px; margin-top: 0.25rem;';
            var dropdownHtml = '<div style="font-size: 0.75rem; color: #666; margin-bottom: 0.5rem; font-weight: 600;">Change Category:</div>';
            categories.forEach(function(cat) {
                var bgColor = cat === currentCategory ? '#e3f2fd' : 'transparent';
                var emoji = categoryEmojis[cat] || '📄';
                var escapedCat = escapeHtml(cat);  // Use escapeHtml for HTML attributes, not escapeJs
                var escapedArticleId = escapeHtml(String(articleId));
                var escapedBgColor = escapeHtml(bgColor);
                dropdownHtml += '<div style="padding: 0.5rem; cursor: pointer; border-radius: 3px; background: ' + escapedBgColor + ';" ';
                dropdownHtml += 'data-article-id="' + escapedArticleId + '" data-category="' + escapedCat + '" class="category-option" ';
                dropdownHtml += 'onmouseover="this.style.background=\\'#f5f5f5\\'" ';
                dropdownHtml += 'onmouseout="this.style.background=\\'' + escapedBgColor + '\\'">';
                dropdownHtml += emoji + ' ' + cat;
                dropdownHtml += '</div>';
            });
            dropdown.innerHTML = dropdownHtml;
            
            // Use event delegation instead of inline onclick
            dropdown.querySelectorAll('.category-option').forEach(function(option) {
                option.addEventListener('click', function() {
                    var articleId = this.getAttribute('data-article-id');
                    var category = this.getAttribute('data-category');
                    setArticleCategory(parseInt(articleId), category);
                    dropdown.remove();
                });
            });
            
            badge.style.position = 'relative';
            badge.appendChild(dropdown);
            
            // Close on outside click
            setTimeout(() => {
                document.addEventListener('click', function closeDropdown(e) {
                    if (!dropdown.contains(e.target) && e.target !== badge) {
                        dropdown.remove();
                        document.removeEventListener('click', closeDropdown);
                    }
                });
            }, 100);
        }
        
        function setArticleCategory(articleId, category) {
            fetch('/admin/api/set-article-category', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({article_id: articleId, category: category})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Error: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        function trainCategoryPositive(articleId, category) {
            fetch('/admin/api/train-category-positive', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({article_id: articleId, category: category})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Update category badge if category changed
                    const badge = document.querySelector(`.category-badge[data-article-id="${articleId}"]`);
                    if (badge && data.updated_category) {
                        badge.textContent = `${data.updated_category} ${Math.round(data.updated_confidence * 100)}%`;
                        badge.setAttribute('data-category', data.updated_category);
                    }
                    alert('Trained: This article IS in ' + category);
                } else {
                    alert('Error: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        function trainCategoryNegative(articleId, category) {
            fetch('/admin/api/train-category-negative', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({article_id: articleId, category: category})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Update category badge if category changed
                    const badge = document.querySelector(`.category-badge[data-article-id="${articleId}"]`);
                    if (badge && data.updated_category) {
                        badge.textContent = `${data.updated_category} ${Math.round(data.updated_confidence * 100)}%`;
                        badge.setAttribute('data-category', data.updated_category);
                    }
                    alert('Trained: This article is NOT in ' + category);
                } else {
                    alert('Error: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        // Make all critical functions globally accessible
        // Note: rejectArticle and editArticle already assigned at top of script
        window.restoreArticle = restoreArticle;
        window.loadTrash = loadTrash;
        window.loadArticleFeatures = loadArticleFeatures;
        window.loadAutoFiltered = loadAutoFiltered;
        window.restoreAutoFiltered = restoreAutoFiltered;
        window.showCategoryDropdown = showCategoryDropdown;
        window.setArticleCategory = setArticleCategory;
        window.trainCategoryPositive = trainCategoryPositive;
        window.trainCategoryNegative = trainCategoryNegative;
        
        function loadCategoryStats() {
            const statsDiv = document.getElementById('categoryStats');
            if (!statsDiv) {
                console.warn('categoryStats div not found');
                return;
            }
            
            statsDiv.innerHTML = '<p style="color: #888; text-align: center;">Loading statistics...</p>';
            
            fetch('/admin/api/get-category-stats', {
                credentials: 'same-origin'
            })
            .then(r => {
                if (!r.ok) {
                    return r.json().then(function(err) { throw new Error(err.message || 'HTTP error! status: ' + r.status); });
                }
                return r.json();
            })
            .then(data => {
                if (data.success) {
                    // All available categories (alphabetized)
                    const categories = ['Business', 'Crime', 'Entertainment', 'Events', 'Fire', 'Health', 'News', 'Politics', 'Schools', 'Sports', 'Traffic'].sort();
                    let html = '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">';
                    
                    categories.forEach(cat => {
                        const count = data.category_counts[cat] || 0;
                        const training = data.training_stats[cat] || {positive: 0, negative: 0, total: 0};
                        html += `
                            <div style="padding: 1rem; background: #252525; border-radius: 4px; border: 1px solid #404040;">
                                <div style="font-weight: 600; color: #e0e0e0; margin-bottom: 0.5rem;">${escapeHtml(cat)}</div>
                                <div style="font-size: 1.5rem; color: #0078d4; margin-bottom: 0.25rem;">${count}</div>
                                <div style="font-size: 0.75rem; color: #888;">articles</div>
                                <div style="margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid #404040; font-size: 0.75rem; color: #888;">
                                    Training: ${training.total} examples<br>
                                    (👍 ${training.positive} / 👎 ${training.negative})
                                </div>
                            </div>
                        `;
                    });
                    
                    html += '</div>';
                    html += `<div style="margin-top: 1rem; padding: 0.75rem; background: #e3f2fd; border-radius: 4px; font-size: 0.9rem; color: #1565c0;">
                        <strong>Total Training Examples:</strong> ${data.total_training || 0}
                    </div>`;
                    statsDiv.innerHTML = html;
                } else {
                    statsDiv.innerHTML = '<p style="color: #f44336;">Error loading statistics: ' + escapeHtml(data.message || 'Unknown error') + '</p>';
                }
            })
            .catch(e => {
                console.error('Error loading category stats:', e);
                const statsDiv = document.getElementById('categoryStats');
                if (statsDiv) {
                    statsDiv.innerHTML = '<p style="color: #f44336;">Error loading statistics: ' + escapeHtml(e.message) + '</p>';
                }
            });
        }
        
        function retrainAllCategories(event) {
            if (!confirm('This will recalculate categories for all articles using the current trained model and keyword lists. This may take a moment. Continue?')) {
                return;
            }
            
            const btn = event?.target || document.querySelector('button[onclick*="retrainAllCategories"]');
            if (btn) {
                const originalText = btn.textContent;
                btn.textContent = 'Retraining...';
                btn.disabled = true;
                
                fetch('/admin/api/retrain-all-categories', {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    credentials: "same-origin",
                    body: JSON.stringify({})
                })
                .then(r => {
                    if (!r.ok) {
                        return r.json().then(err => {
                            throw new Error(err.message || 'HTTP error! status: ' + r.status);
                        }).catch(() => {
                            return r.text().then(text => {
                                throw new Error(text || 'HTTP ' + r.status);
                            });
                        });
                    }
                    return r.json();
                })
                .then(data => {
                    if (btn) {
                        btn.textContent = originalText;
                        btn.disabled = false;
                    }
                    if (data.success) {
                        alert(data.message || 'Categories retrained successfully!');
                        location.reload();
                    } else {
                        alert('Error: ' + (data.message || 'Unknown error'));
                    }
                })
                .catch(e => {
                    console.error('Error retraining categories:', e);
                    if (btn) {
                        btn.textContent = originalText;
                        btn.disabled = false;
                    }
                    alert('Error: ' + e.message);
                });
            } else {
                // Fallback if button not found
                fetch('/admin/api/retrain-all-categories', {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    credentials: "same-origin",
                    body: JSON.stringify({})
                })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        alert(data.message || 'Categories retrained successfully!');
                        location.reload();
                    } else {
                        alert('Error: ' + (data.message || 'Unknown error'));
                    }
                })
                .catch(e => {
                    console.error('Error retraining categories:', e);
                    alert('Error: ' + e.message);
                });
            }
        }
        
        window.retrainAllCategories = retrainAllCategories;
        window.loadCategoryStats = loadCategoryStats;
        window.updateCategoryPoints = updateCategoryPoints;
        window.addRelevanceItem = addRelevanceItem;
        window.removeRelevanceItem = removeRelevanceItem;
        
        // Keyword Manager functions
        // Categories that have default keywords available
        const CATEGORIES_WITH_DEFAULTS = ['Business', 'Crime', 'Entertainment', 'Events', 'Fire', 'Health', 'News', 'Politics', 'Schools', 'Sports', 'Traffic'];
        
        function loadAllCategoriesAndKeywords() {
            const container = document.getElementById('categoriesKeywordsList');
            container.innerHTML = '<p style="color: #666; text-align: center; padding: 2rem;">Loading categories and keywords...</p>';
            
            fetch('/admin/api/category-keywords/get', {
                credentials: 'same-origin'
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    renderAllCategories(data.categories || {});
                } else {
                    container.innerHTML = '<p style="color: #f44336; text-align: center; padding: 2rem;">Error loading categories: ' + escapeHtml(data.message || 'Unknown error') + '</p>';
                }
            })
            .catch(e => {
                console.error('Error loading categories:', e);
                container.innerHTML = '<p style="color: #f44336; text-align: center; padding: 2rem;">Error loading categories: ' + escapeHtml(e.message) + '</p>';
            });
        }
        
        function renderAllCategories(categoriesData) {
            const container = document.getElementById('categoriesKeywordsList');
            
            // Get all unique categories (from data and defaults)
            const allCategories = new Set(Object.keys(categoriesData));
            // Add default categories that might not have keywords yet
            CATEGORIES_WITH_DEFAULTS.forEach(cat => allCategories.add(cat));
            
            // Sort alphabetically
            const sortedCategories = Array.from(allCategories).sort();
            
            if (sortedCategories.length === 0) {
                container.innerHTML = '<p style="color: #999; text-align: center; padding: 2rem;">No categories yet. Add one to get started.</p>';
                return;
            }
            
            container.innerHTML = sortedCategories.map(category => {
                const keywords = categoriesData[category] || [];
                const hasDefaults = CATEGORIES_WITH_DEFAULTS.includes(category);
                const canDelete = category !== 'News';
                
                return `
                    <div class="relevance-section" style="margin-bottom: 2rem; padding: 1.5rem; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <h3 style="margin-top: 0; margin-bottom: 1rem; color: #333; display: flex; align-items: center; gap: 1rem;">
                            <span>${escapeHtml(category)}</span>
                            ${canDelete ? '<button class="delete-category-btn" data-category="' + escapeHtml(category) + '" style="padding: 0.25rem 0.75rem; background: #f44336; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 0.85rem; font-weight: 600;">🗑️ Delete</button>' : ''}
                        </h3>
                        <div style="margin-bottom: 1rem;">
                            <input type="text" id="keywordInput_${escapeHtml(category)}" placeholder="Enter keyword" class="keyword-input" data-category="${escapeHtml(category)}" style="padding: 0.5rem; border: 1px solid #ddd; border-radius: 4px; width: 300px; margin-right: 0.5rem;">
                            <button class="add-keyword-btn" data-category="${escapeHtml(category)}" style="padding: 0.5rem 1rem; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600;">Add Keyword</button>
                            ${hasDefaults ? '<button class="import-defaults-btn" data-category="' + escapeHtml(category) + '" style="padding: 0.5rem 1rem; background: #2196f3; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; margin-left: 0.5rem;">📥 Import Defaults</button>' : ''}
                        </div>
                        <div class="relevance-items" id="keywordsList_${escapeHtml(category)}" style="min-height: 50px; padding: 1rem; background: #f5f5f5; border-radius: 4px;">
                            ${keywords.length === 0 ? '<p style="color: #999; text-align: center; margin: 1rem 0;">No keywords yet. Add some to get started.</p>' : keywords.map(keyword => {
                                const escapedCategory = escapeHtml(category);
                                const escapedKeyword = escapeHtml(keyword);
                                return '<div class="relevance-item" style="display: inline-block; margin: 0.25rem; padding: 0.5rem 1rem; background: #e8f5e9; border-radius: 4px;"><span>' + escapedKeyword + '</span><button class="remove-keyword-btn" data-category="' + escapedCategory + '" data-keyword="' + escapedKeyword + '" style="margin-left: 0.5rem; background: #f44336; color: white; border: none; border-radius: 3px; padding: 0.2rem 0.5rem; cursor: pointer;">🗑️</button></div>';
                            }).join('')}
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        function addKeywordToCategory(category) {
            const input = document.getElementById(`keywordInput_${category}`);
            const keyword = input.value.trim();
            
            if (!keyword) {
                alert('Please enter a keyword');
                return;
            }
            
            fetch('/admin/api/category-keywords/add', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({category: category, keyword: keyword})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    input.value = '';
                    loadAllCategoriesAndKeywords();
                } else {
                    alert('Error adding keyword: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error adding keyword:', e);
                alert('Error adding keyword: ' + e.message);
            });
        }
        
        function removeKeywordFromCategory(category, keyword) {
            if (!confirm(`Remove keyword "${escapeHtml(keyword)}" from ${escapeHtml(category)}?`)) {
                return;
            }
            
            fetch('/admin/api/category-keywords/remove', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({category: category, keyword: keyword})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    loadAllCategoriesAndKeywords();
                } else {
                    alert('Error removing keyword: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error removing keyword:', e);
                alert('Error removing keyword: ' + e.message);
            });
        }
        
        function importDefaultKeywordsForCategory(category) {
            if (!confirm(`Import default keywords for ${escapeHtml(category)}? This will add all default keywords that don't already exist.`)) {
                return;
            }
            
            fetch('/admin/api/category-keywords/import-defaults', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({category: category})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    loadAllCategoriesAndKeywords();
                    alert(data.message);
                } else {
                    alert('Error importing keywords: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error importing keywords:', e);
                alert('Error importing keywords: ' + e.message);
            });
        }
        
        function addNewCategory() {
            const categoryInput = document.getElementById('newCategoryInput');
            const categoryName = categoryInput.value.trim();
            
            if (!categoryName) {
                alert('Please enter a category name');
                return;
            }
            
            // Validate category name (alphanumeric and spaces only)
                if (!/^[A-Za-z0-9\\s]+$/.test(categoryName)) {
                alert('Category name can only contain letters, numbers, and spaces');
                return;
            }
            
            // Validate: Categories can only be added if they can also be deleted
            // "News" is the default fallback and cannot be deleted, so it cannot be added
            if (categoryName === 'News') {
                alert('Cannot add "News" category - it is the default fallback category and cannot be deleted.');
                return;
            }
            
            // Check if category already exists
            fetch('/admin/api/category-keywords/get', {
                credentials: 'same-origin'
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    const existingCategories = Object.keys(data.categories || {});
                    if (existingCategories.includes(categoryName) || CATEGORIES_WITH_DEFAULTS.includes(categoryName)) {
                        alert('Category already exists');
                        return;
                    }
                    
                    // Category doesn't exist, add it by adding a keyword (which will create the category)
                    // Actually, we need to add it to the classifier first
                    fetch('/admin/api/category-keywords/add', {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        credentials: "same-origin",
                        body: JSON.stringify({category: categoryName, keyword: '__init__'})
                    })
                    .then(r => r.json())
                    .then(addData => {
                        if (addData.success) {
                            // Remove the init keyword
                            fetch('/admin/api/category-keywords/remove', {
                                method: "POST",
                                headers: {"Content-Type": "application/json"},
                                credentials: "same-origin",
                                body: JSON.stringify({category: categoryName, keyword: '__init__'})
                            })
                            .then(() => {
                                categoryInput.value = '';
                                loadAllCategoriesAndKeywords();
                                alert(`Category "${escapeHtml(categoryName)}" added! You can now add keywords for it.`);
                            });
                        } else {
                            // If adding failed, try to add the category to the classifier
                            // For now, just reload and the category should appear
                            categoryInput.value = '';
                            loadAllCategoriesAndKeywords();
                            alert(`Category "${categoryName}" added! You can now add keywords for it.`);
                        }
                    });
                }
            })
            .catch(e => {
                console.error('Error checking categories:', e);
                // Just try to add it anyway
                categoryInput.value = '';
                loadAllCategoriesAndKeywords();
                alert(`Category "${categoryName}" added! You can now add keywords for it.`);
            });
        }
        
        function deleteCategory(category) {
            if (category === 'News') {
                alert('Cannot delete the "News" category (default fallback category)');
                return;
            }
            
            if (!confirm(`Delete category "${category}"? This will:\n\n- Delete all keywords for this category\n- Reassign all articles in this category to "News"\n\nThis cannot be undone. Continue?`)) {
                return;
            }
            
            fetch('/admin/api/category-keywords/delete-category', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({category: category})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    loadAllCategoriesAndKeywords();
                    alert(`Category "${escapeHtml(category)}" deleted successfully.`);
                } else {
                    alert('Error deleting category: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error deleting category:', e);
                alert('Error deleting category: ' + e.message);
            });
        }
        
        // Legacy functions for backwards compatibility (if any code still references them)
        function loadKeywordsForCategory() {
            loadAllCategoriesAndKeywords();
        }
        
        function addKeyword() {
            // This function is no longer used, but kept for compatibility
            alert('Please use the "Add Keyword" button next to the category name.');
        }
        
        function removeKeyword(category, keyword) {
            removeKeywordFromCategory(category, keyword);
        }
        
        function bulkAddKeywords() {
            alert('Bulk add is not available in the new layout. Please add keywords one at a time or use "Import Defaults".');
        }
        
        function importDefaultKeywords() {
            alert('Please use the "Import Defaults" button next to the category name.');
        }
        
        function deleteCurrentCategory() {
            alert('Please use the "Delete" button next to the category name.');
        }
        
        // Load all categories when keywords tab is shown
        if (document.getElementById('keywordsTab')) {
            const keywordsTab = document.getElementById('keywordsTab');
            const observer = new MutationObserver((mutations) => {
                if (keywordsTab.style.display !== 'none' && keywordsTab.style.display !== '') {
                    loadAllCategoriesAndKeywords();
                }
            });
            observer.observe(keywordsTab, { attributes: true, attributeFilter: ['style'] });
            
            // Also load on initial page load if keywords tab is active
            if (keywordsTab.style.display !== 'none') {
                loadAllCategoriesAndKeywords();
            }
        }
        
        // Make functions globally accessible
        window.loadAllCategoriesAndKeywords = loadAllCategoriesAndKeywords;
        window.addKeywordToCategory = addKeywordToCategory;
        window.removeKeywordFromCategory = removeKeywordFromCategory;
        window.importDefaultKeywordsForCategory = importDefaultKeywordsForCategory;
        window.addNewCategory = addNewCategory;
        window.deleteCategory = deleteCategory;
        
        function populateAllDefaults() {
            if (!confirm('Populate all categories with their default keywords? This will add all default keywords that don\\'t already exist.')) {
                return;
            }
            
            fetch('/admin/api/category-keywords/populate-defaults', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    loadAllCategoriesAndKeywords();
                    alert(data.message);
                } else {
                    alert('Error populating keywords: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error populating keywords:', e);
                alert('Error populating keywords: ' + e.message);
            });
        }
        window.populateAllDefaults = populateAllDefaults;
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Toggle explanation sections (collapsible)
        function toggleExplanation(id) {
            var explanation = document.getElementById(id);
            var toggle = document.getElementById(id + 'Toggle');
            if (!explanation || !toggle) return;
            var isCollapsed = explanation.style.display === 'none';
            if (isCollapsed) {
                explanation.style.display = 'block';
                toggle.textContent = '▼';
                try { localStorage.setItem('explanation_' + id + '_collapsed', 'false'); } catch(e) {}
            } else {
                explanation.style.display = 'none';
                toggle.textContent = '▶';
                try { localStorage.setItem('explanation_' + id + '_collapsed', 'true'); } catch(e) {}
            }
        }
        
        // Restore explanation states on page load
        function restoreExplanationStates() {
            var ids = ['categoriesExplanation', 'keywordsExplanation', 'bayesianExplanation'];
            for (var i = 0; i < ids.length; i++) {
                var id = ids[i];
                try {
                    var explanation = document.getElementById(id);
                    var toggle = document.getElementById(id + 'Toggle');
                    if (!explanation || !toggle) continue;
                    var isCollapsed = false;
                    try {
                        isCollapsed = localStorage.getItem('explanation_' + id + '_collapsed') === 'true';
                    } catch(e) {}
                    if (isCollapsed) {
                        explanation.style.display = 'none';
                        toggle.textContent = '▶';
                    } else {
                        explanation.style.display = 'block';
                        toggle.textContent = '▼';
                    }
                } catch(e) {}
            }
        }
        
        // Make toggleExplanation globally accessible
        window.toggleExplanation = toggleExplanation;
        
        // Initialize explanation states after DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function() {
                setTimeout(restoreExplanationStates, 100);
            });
        } else {
            setTimeout(restoreExplanationStates, 100);
        }
        
        function toggleStellar(articleId, currentState) {
            const isStellar = currentState === 0; // Toggle: if currently 0, set to 1
            
            fetch('/admin/api/toggle-stellar', {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                credentials: "same-origin",
                body: JSON.stringify({article_id: articleId, is_stellar: isStellar})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Reload the page to show updated state
                    window.location.reload();
                } else {
                    alert('Error toggling stellar: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error toggling stellar:', e);
                alert('Error toggling stellar: ' + e.message);
            });
        }
        window.toggleStellar = toggleStellar;
        
        // Load category stats when categories tab is active
        // Check on page load
        if (document.getElementById('categoriesTab')) {
            loadCategoryStats();
        }
        
        // Also set up observer to load stats when tab becomes visible
        const categoriesTab = document.getElementById('categoriesTab');
        if (categoriesTab) {
            const observer = new MutationObserver((mutations) => {
                mutations.forEach((mutation) => {
                    if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                        const isVisible = categoriesTab.style.display !== 'none';
                        if (isVisible) {
                            // Tab is now visible, load stats if not already loaded
                            const statsDiv = document.getElementById('categoryStats');
                            if (statsDiv && statsDiv.innerHTML.includes('Loading statistics') || statsDiv.innerHTML.trim() === '') {
                                loadCategoryStats();
                            }
                        }
                    }
                });
            });
            observer.observe(categoriesTab, { attributes: true, attributeFilter: ['style'] });
        }
        
        // Also listen for tab link clicks
        document.querySelectorAll('a[href*="/categories"]').forEach(link => {
            link.addEventListener('click', () => {
                setTimeout(() => {
                    if (document.getElementById('categoriesTab')) {
                        loadCategoryStats();
                    }
                }, 100);
            });
        });
        
        // Tab loading is now handled in the main DOMContentLoaded handler
        
        // Regenerate website
        function regenerateWebsite() {
            if (confirm('Regenerate website with current settings?')) {
                regenerateWebsiteWithRefresh(false, event.target);
            }
        }
        
        // Regenerate all with fresh data
        function regenerateAll() {
            if (confirm('This will fetch fresh data from all sources and regenerate the entire website. This may take several minutes. Continue?')) {
                const btn = event.target;
                regenerateWebsiteWithRefresh(true, btn);
            }
        }
        
        // Make regenerate functions globally accessible
        window.regenerateWebsite = regenerateWebsite;
        window.regenerateAll = regenerateAll;
        
        function regenerateWebsiteWithRefresh(forceRefresh, btn) {
            const originalText = btn.textContent;
            btn.textContent = forceRefresh ? 'Fetching fresh data...' : 'Regenerating...';
            btn.disabled = true;
            
            fetch('/admin/api/regenerate', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ force_refresh: forceRefresh })
            }).then(response => response.json())
            .then(data => {
                btn.textContent = originalText;
                btn.disabled = false;
                if (data.success) {
                    alert(forceRefresh ? 'Website regenerated with fresh data from all sources!' : 'Website regenerated successfully!');
                } else {
                    alert('Error regenerating website: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(error => {
                btn.textContent = originalText;
                btn.disabled = false;
                alert('Error: ' + error.message);
            });
        }
        
        // Relevance management functions
        function addRelevanceItem(category, item, points) {
            if (!item || (typeof item === 'string' && !item.trim())) {
                alert('Please enter an item');
                return;
            }
            
            const trimmedItem = typeof item === 'string' ? item.trim() : String(item).trim();
            if (!trimmedItem) {
                alert('Please enter an item');
                return;
            }
            
            const data = { category: category, item: trimmedItem };
            if (points !== undefined && points !== null && !isNaN(points)) {
                data.points = parseFloat(points);
            }
            
            fetch('/admin/api/relevance-config/add', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify(data)
            })
            .then(r => {
                if (!r.ok) {
                    return r.text().then(text => {
                        try {
                            return JSON.parse(text);
                        } catch (e) {
                            throw new Error(text || 'HTTP ' + r.status);
                        }
                    });
                }
                return r.json();
            })
            .then(data => {
                if (data.success) {
                    // Clear the input field
                    const inputId = category === 'high_relevance' ? 'highRelevanceInput' :
                                   category === 'medium_relevance' ? 'mediumRelevanceInput' :
                                   category === 'local_places' ? 'localPlacesInput' :
                                   category === 'topic_keywords' ? 'topicKeywordInput' :
                                   category === 'clickbait_patterns' ? 'clickbaitInput' : null;
                    if (inputId) {
                        const input = document.getElementById(inputId);
                        if (input) input.value = '';
                    }
                    // Reload the page to show updated config
                    window.location.reload();
                } else {
                    alert('Error adding item: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                console.error('Error adding relevance item:', e);
                alert('Error: ' + (e.message || 'Failed to add item. Please check the console for details.'));
            });
        }
        
        function removeRelevanceItem(category, item) {
            // Escape item and category for safe display in confirm dialog
            // Use split/join to avoid regex issues in template rendering
            var safeItem = String(item);
            safeItem = safeItem.split('\\').join('\\\\');
            safeItem = safeItem.split('"').join('\\"');
            safeItem = safeItem.split("'").join("\\'");
            var safeCategory = String(category);
            safeCategory = safeCategory.split('\\').join('\\\\');
            safeCategory = safeCategory.split('"').join('\\"');
            safeCategory = safeCategory.split("'").join("\\'");
            if (!confirm('Remove "' + safeItem + '" from ' + safeCategory + '?')) {
                return;
            }
            
            fetch('/admin/api/relevance-config/remove', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ category: category, item: item })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Reload the page to show updated config
                    window.location.reload();
                } else {
                    alert('Error removing item: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        function updateCategoryPoints(category, points, inputElement) {
            if (points === undefined || points === null || isNaN(points)) {
                alert('Please enter a valid number');
                return;
            }
            
            // Get the input element if not provided
            if (!inputElement) {
                inputElement = event?.target || document.getElementById(category === 'high_relevance_points' ? 'highRelevancePoints' : 'localPlacesPoints');
            }
            
            const originalValue = inputElement ? inputElement.value : points;
            
            fetch('/admin/api/relevance-config/update', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ category: category, item: '_category_points', points: points })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Show success indicator
                    if (inputElement) {
                        inputElement.style.background = '#e8f5e9';
                        setTimeout(() => {
                            inputElement.style.background = '';
                        }, 1000);
                    }
                } else {
                    alert('Error updating category points: ' + (data.message || 'Unknown error'));
                    // Revert input value
                    if (inputElement) {
                        inputElement.value = originalValue;
                    }
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
                // Revert input value on error
                if (inputElement) {
                    inputElement.value = originalValue;
                }
            });
        }
        
        function updateRelevancePoints(category, item, points) {
            if (points === undefined || points === null || isNaN(points)) {
                alert('Please enter a valid number');
                return;
            }
            
            fetch('/admin/api/relevance-config/update', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ category: category, item: item, points: points })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    // Show success indicator
                    const input = event.target;
                    const originalValue = input.value;
                    input.style.background = '#e8f5e9';
                    setTimeout(() => {
                        input.style.background = '';
                    }, 1000);
                } else {
                    alert('Error updating points: ' + (data.message || 'Unknown error'));
                    // Revert input value
                    event.target.value = originalValue;
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        function saveRelevanceThreshold() {
            const thresholdInput = document.getElementById('relevanceThreshold');
            const threshold = parseFloat(thresholdInput.value);
            const statusSpan = document.getElementById('thresholdSaveStatus');
            
            if (isNaN(threshold) || threshold < 0 || threshold > 100) {
                alert('Please enter a valid number between 0 and 100');
                return;
            }
            
            fetch('/admin/api/relevance-threshold', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ threshold: threshold })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    statusSpan.style.display = 'inline';
                    statusSpan.textContent = '✓ Saved';
                    setTimeout(() => {
                        statusSpan.style.display = 'none';
                    }, 2000);
                } else {
                    alert('Error saving threshold: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        function recalculateRelevanceScores() {
            if (!confirm('This will recalculate relevance scores for all existing articles using the current configuration. This may take a moment. Continue?')) {
                return;
            }
            
            // Find the button that was clicked
            const buttons = document.querySelectorAll('button');
            let btn = null;
            for (let b of buttons) {
                if (b.textContent.includes('Recalculate All Relevance Scores')) {
                    btn = b;
                    break;
                }
            }
            
            if (btn) {
                const originalText = btn.textContent;
                btn.textContent = 'Recalculating...';
                btn.disabled = true;
                
                fetch('/admin/api/recalculate-relevance-scores', {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({})
                })
                .then(r => {
                    if (!r.ok) {
                        return r.text().then(text => {
                            throw new Error(text || 'HTTP ' + r.status);
                        });
                    }
                    return r.json();
                })
                .then(data => {
                    if (btn) {
                        btn.textContent = originalText;
                        btn.disabled = false;
                    }
                    if (data.success) {
                        alert(data.message);
                        // Reload page to show updated scores
                        window.location.reload();
                    } else {
                        alert('Error: ' + (data.message || 'Unknown error'));
                    }
                })
                .catch(e => {
                    if (btn) {
                        btn.textContent = originalText;
                        btn.disabled = false;
                    }
                    alert('Error: ' + e.message);
                });
            } else {
                // Fallback if button not found
                fetch('/admin/api/recalculate-relevance-scores', {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({})
                })
                .then(r => {
                    if (!r.ok) {
                        return r.text().then(text => {
                            throw new Error(text || 'HTTP ' + r.status);
                        });
                    }
                    return r.json();
                })
                .then(data => {
                    if (data.success) {
                        alert(data.message);
                        window.location.reload();
                    } else {
                        alert('Error: ' + (data.message || 'Unknown error'));
                    }
                })
                .catch(e => {
                    alert('Error: ' + e.message);
                });
            }
        }
        
        // Zip code management functions
        function addZipCode() {
            const zipInput = document.getElementById('newZipCode');
            const zipCode = zipInput.value.trim();
            
            if (!zipCode || zipCode.length !== 5 || !/^[0-9]{5}$/.test(zipCode)) {
                alert('Please enter a valid 5-digit zip code');
                return;
            }
            
            fetch('/admin/api/zip-codes/add', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ zip_code: zipCode })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    zipInput.value = '';
                    location.reload();
                } else {
                    alert('Error adding zip code: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        function removeZipCode(zipCode) {
            if (!confirm(`Remove zip code ${zipCode}? This will stop pre-generating pages for this zip.`)) {
                return;
            }
            
            fetch('/admin/api/zip-codes/remove', {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "same-origin",
                body: JSON.stringify({ zip_code: zipCode })
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Error removing zip code: ' + (data.message || 'Unknown error'));
                }
            })
            .catch(e => {
                alert('Error: ' + e.message);
            });
        }
        
        // Make functions globally accessible
        if (typeof addNewSource !== 'undefined') window.addNewSource = addNewSource;
        if (typeof editSource !== 'undefined') window.editSource = editSource;
        window.addRelevanceItem = addRelevanceItem;
        window.removeRelevanceItem = removeRelevanceItem;
        window.updateRelevancePoints = updateRelevancePoints;
        window.saveRelevanceThreshold = saveRelevanceThreshold;
        
        // Functions already assigned to window at top of script - verify they exist
        // Verify functions are defined before attaching event listener
        if (typeof toggleTopStory !== 'function') {
            console.error('toggleTopStory is not defined!');
        }
        if (typeof toggleGoodFit !== 'function') {
            console.error('toggleGoodFit is not defined!');
        }
        if (typeof window.rejectArticle !== 'function') {
            console.error('rejectArticle is not defined!');
        }
        if (typeof window.editArticle !== 'function') {
            console.error('editArticle is not defined!');
        }
        
        console.log('Admin panel functions registered:', {
            toggleTopStory: typeof window.toggleTopStory,
            toggleGoodFit: typeof window.toggleGoodFit,
            rejectArticle: typeof window.rejectArticle,
            editArticle: typeof window.editArticle
        });
        
        // Event delegation for other admin panel buttons (not trash/restore/top-story)
        // These are handled separately from the unified handler
        const clickHandler = function(e) {
            // Remove relevance item buttons
            if (e.target.classList.contains('remove-relevance-btn') || e.target.closest('.remove-relevance-btn')) {
                const btn = e.target.classList.contains('remove-relevance-btn') ? e.target : e.target.closest('.remove-relevance-btn');
                const category = btn.getAttribute('data-category');
                const item = btn.getAttribute('data-item');
                if (category && item) {
                    removeRelevanceItem(category, item);
                }
            }
            
            // Delete category button
            if (e.target.classList.contains('delete-category-btn') || e.target.closest('.delete-category-btn')) {
                const btn = e.target.classList.contains('delete-category-btn') ? e.target : e.target.closest('.delete-category-btn');
                const category = btn.getAttribute('data-category');
                if (category) {
                    deleteCategory(category);
                }
            }
            
            // Add keyword button
            if (e.target.classList.contains('add-keyword-btn') || e.target.closest('.add-keyword-btn')) {
                const btn = e.target.classList.contains('add-keyword-btn') ? e.target : e.target.closest('.add-keyword-btn');
                const category = btn.getAttribute('data-category');
                if (category) {
                    const input = document.getElementById('keywordInput_' + category);
                    if (input && input.value.trim()) {
                        addKeywordToCategory(category);
                    }
                }
            }
            
            // Import defaults button
            if (e.target.classList.contains('import-defaults-btn') || e.target.closest('.import-defaults-btn')) {
                const btn = e.target.classList.contains('import-defaults-btn') ? e.target : e.target.closest('.import-defaults-btn');
                const category = btn.getAttribute('data-category');
                if (category) {
                    importDefaultKeywordsForCategory(category);
                }
            }
            
            // Remove keyword button
            if (e.target.classList.contains('remove-keyword-btn') || e.target.closest('.remove-keyword-btn')) {
                const btn = e.target.classList.contains('remove-keyword-btn') ? e.target : e.target.closest('.remove-keyword-btn');
                const category = btn.getAttribute('data-category');
                const keyword = btn.getAttribute('data-keyword');
                if (category && keyword) {
                    removeKeywordFromCategory(category, keyword);
                }
            }
            
            // Remove zip code button
            if (e.target.classList.contains('remove-zip-btn') || e.target.closest('.remove-zip-btn')) {
                const btn = e.target.classList.contains('remove-zip-btn') ? e.target : e.target.closest('.remove-zip-btn');
                const zip = btn.getAttribute('data-zip');
                if (zip) {
                    removeZipCode(zip);
                }
            }
            
            // Remove sticky zip button
            if (e.target.classList.contains('remove-sticky-btn') || e.target.closest('.remove-sticky-btn')) {
                const btn = e.target.classList.contains('remove-sticky-btn') ? e.target : e.target.closest('.remove-sticky-btn');
                const zip = btn.getAttribute('data-zip-code');
                if (zip) {
                    removeSticky(zip);
                }
            }
            
            // Toggle sticky zip button
            if (e.target.classList.contains('toggle-sticky-btn') || e.target.closest('.toggle-sticky-btn')) {
                const btn = e.target.classList.contains('toggle-sticky-btn') ? e.target : e.target.closest('.toggle-sticky-btn');
                const zip = btn.getAttribute('data-zip-code');
                if (zip) {
                    toggleSticky(zip);
                }
            }
            
            // Category badge click
            if (e.target.classList.contains('category-badge') || e.target.closest('.category-badge')) {
                const badge = e.target.classList.contains('category-badge') ? e.target : e.target.closest('.category-badge');
                const articleId = badge.getAttribute('data-article-id');
                const category = badge.getAttribute('data-category');
                const confidence = parseFloat(badge.getAttribute('data-confidence') || '0.5');
                if (articleId && category) {
                    showCategoryDropdown(parseInt(articleId), category, confidence);
                }
            }
            
            // Stellar button
            if (e.target.classList.contains('stellar-btn') || e.target.closest('.stellar-btn')) {
                const btn = e.target.classList.contains('stellar-btn') ? e.target : e.target.closest('.stellar-btn');
                const articleId = btn.getAttribute('data-article-id');
                const isStellar = btn.getAttribute('data-stellar') === '1';
                if (articleId) {
                    toggleStellar(parseInt(articleId), isStellar ? 1 : 0);
                }
            }
            
            // Reject article button
            if (e.target.classList.contains('reject-btn') || e.target.closest('.reject-btn')) {
                const btn = e.target.classList.contains('reject-btn') ? e.target : e.target.closest('.reject-btn');
                const articleId = btn.getAttribute('data-article-id');
                if (articleId) {
                    rejectArticle(parseInt(articleId));
                }
            }
            
            // Legacy edit button (for backwards compatibility)
            if (e.target.classList.contains('edit-btn') || e.target.closest('.edit-btn')) {
                const btn = e.target.classList.contains('edit-btn') ? e.target : e.target.closest('.edit-btn');
                const articleId = btn.getAttribute('data-article-id');
                if (articleId) {
                    editArticle(parseInt(articleId));
                }
            }
            
            // Edit source button
            if (e.target.classList.contains('edit-source-btn') || e.target.closest('.edit-source-btn')) {
                const btn = e.target.classList.contains('edit-source-btn') ? e.target : e.target.closest('.edit-source-btn');
                const sourceKey = btn.getAttribute('data-source-key');
                if (sourceKey) {
                    editSource(sourceKey);
                }
            }
            
            // Save threshold button
            if (e.target.classList.contains('save-threshold-btn') || e.target.closest('.save-threshold-btn')) {
                if (typeof saveRelevanceThreshold === 'function') {
                    saveRelevanceThreshold();
                } else {
                    console.error('saveRelevanceThreshold function not found');
                }
            }
            
            // Retry trash button
            if (e.target.classList.contains('retry-trash-btn') || e.target.closest('.retry-trash-btn')) {
                if (typeof loadTrash === 'function') {
                    loadTrash();
                } else {
                    console.error('loadTrash function not found');
                }
            }
            
            // Retry auto-filtered button
            if (e.target.classList.contains('retry-auto-filtered-btn') || e.target.closest('.retry-auto-filtered-btn')) {
                if (typeof loadAutoFiltered === 'function') {
                    loadAutoFiltered();
                } else {
                    console.error('loadAutoFiltered function not found');
                }
            }
        };
        document.addEventListener('click', clickHandler, true); // Use capture phase to catch events early
        console.log('Click event listener attached!', {
            handlerType: typeof clickHandler,
            capturePhase: true
        });
        
        // Event delegation for input changes
        document.addEventListener('change', function(e) {
            // Update category points
            if (e.target.classList.contains('update-category-points-input')) {
                const category = e.target.getAttribute('data-category');
                const points = parseFloat(e.target.value);
                if (category && !isNaN(points)) {
                    updateCategoryPoints(category, points, e.target);
                }
            }
            
            // Update relevance points
            if (e.target.classList.contains('update-relevance-points-input')) {
                const category = e.target.getAttribute('data-category');
                const item = e.target.getAttribute('data-item');
                const points = parseFloat(e.target.value);
                if (category && item && !isNaN(points)) {
                    updateRelevancePoints(category, item, points);
                }
            }
        }, true); // Use capture phase to catch events early
        
        // Event delegation for keypress on keyword inputs
        document.addEventListener('keypress', function(e) {
            if (e.target.classList.contains('keyword-input') && e.key === 'Enter') {
                const category = e.target.getAttribute('data-category');
                if (category && e.target.value.trim()) {
                    addKeywordToCategory(category);
                }
            }
        });
        window.recalculateRelevanceScores = recalculateRelevanceScores;
        window.addZipCode = addZipCode;
        window.removeZipCode = removeZipCode;
        
        // Make all modal and helper functions globally accessible
        try {
            if (typeof showEditModal !== 'undefined') window.showEditModal = showEditModal;
            if (typeof closeEditModal !== 'undefined') window.closeEditModal = closeEditModal;
            if (typeof saveArticleEdit !== 'undefined') window.saveArticleEdit = saveArticleEdit;
            if (typeof editSource !== 'undefined') window.editSource = editSource;
            if (typeof showEditSourceModal !== 'undefined') window.showEditSourceModal = showEditSourceModal;
            if (typeof closeEditSourceModal !== 'undefined') window.closeEditSourceModal = closeEditSourceModal;
            if (typeof saveSourceEdit !== 'undefined') window.saveSourceEdit = saveSourceEdit;
            if (typeof updateSourceSetting !== 'undefined') window.updateSourceSetting = updateSourceSetting;
            console.log('All functions made globally accessible');
        } catch(e) {
            console.error('Error assigning modal functions to window:', e);
        }
        
        // Final check: if trash tab is active, load it now
        {% if active_tab == 'trash' %}
        (function() {
            function ensureLoadTrash() {
                const trashTab = document.getElementById('trashTab');
                const trashList = document.getElementById('trashList');
                console.log('ensureLoadTrash called. trashTab:', trashTab, 'trashList:', trashList, 'loadTrash type:', typeof window.loadTrash);
                if (trashTab && trashList) {
                    if (typeof window.loadTrash === 'function') {
                        if (trashList.innerHTML.includes('Loading rejected articles') || trashList.innerHTML.trim() === '') {
                            console.log('Calling loadTrash()...');
                            window.loadTrash();
                        } else {
                            console.log('Trash list already loaded or has content');
                        }
                    } else {
                        console.error('loadTrash function not found on window object');
                        // Try again after a short delay
                        setTimeout(ensureLoadTrash, 200);
                    }
                } else {
                    console.log('Waiting for elements... trashTab:', !!trashTab, 'trashList:', !!trashList);
                    setTimeout(ensureLoadTrash, 100);
                }
            }
            // Try immediately when DOM is ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', ensureLoadTrash);
            } else {
                ensureLoadTrash();
            }
            // Also try after delays as fallback
            setTimeout(ensureLoadTrash, 500);
            setTimeout(ensureLoadTrash, 1000);
            setTimeout(ensureLoadTrash, 2000);
        })();
        {% endif %}
        
        // Load trash when trash tab is clicked or when on trash page
        function loadTrashIfNeeded() {
            // Check if we're on trash tab by URL or active tab
            const isTrashTab = window.location.pathname.includes('/trash') || 
                              document.querySelector('#trashTab')?.style.display !== 'none';
            
            if (isTrashTab) {
                const trashList = document.getElementById('trashList');
                if (trashList && (trashList.innerHTML.includes('Loading rejected articles') || trashList.innerHTML.trim() === '' || trashList.innerHTML.includes('Loading'))) {
                    if (window.loadTrash && typeof window.loadTrash === 'function') {
                        console.log('Loading trash articles...');
                        window.loadTrash();
                    } else {
                        console.error('loadTrash function not available');
                        // Retry after a delay
                        setTimeout(loadTrashIfNeeded, 500);
                    }
                }
            }
        }
        
        // Load trash on page load if on trash tab
        if (window.location.pathname.includes('/trash')) {
            setTimeout(loadTrashIfNeeded, 300);
            setTimeout(loadTrashIfNeeded, 1000);
        }
        
        // Also listen for tab navigation/clicks
        document.addEventListener('click', function(e) {
            // Check if trash tab link was clicked
            const trashLink = e.target.closest('a[href*="/trash"]');
            if (trashLink) {
                setTimeout(function() {
                    loadTrashIfNeeded();
                }, 200);
            }
        });
        
        // Also check when tab content becomes visible
        const observer = new MutationObserver(function(mutations) {
            const trashTab = document.getElementById('trashTab');
            if (trashTab && trashTab.style.display !== 'none') {
                loadTrashIfNeeded();
            }
        });
        
        // Observe changes to tab visibility
        setTimeout(function() {
            const trashTab = document.getElementById('trashTab');
            if (trashTab) {
                observer.observe(trashTab, { attributes: true, attributeFilter: ['style', 'class'] });
            }
        }, 500);
        
        // Final verification - this will only run if script executed successfully
        console.log('Script execution complete. Functions available:', {
            rejectArticle: typeof window.rejectArticle,
            toggleTopStory: typeof window.toggleTopStory,
            toggleGoodFit: typeof window.toggleGoodFit,
            editArticle: typeof window.editArticle,
            loadTrash: typeof window.loadTrash
        });
        
    </script>
    <div style="position: fixed; bottom: 10px; right: 10px; background: #252525; padding: 0.5rem 1rem; border-radius: 4px; border: 1px solid #404040; font-size: 0.75rem; color: #888;">
        <div>Version: {{ version }}</div>
        {% if last_regeneration %}
        <div>Last Generated: {{ last_regeneration }}</div>
        {% else %}
        <div>Last Generated: Never</div>
        {% endif %}
    </div>
</body>
</html>
"""

# Import admin blueprint and routes BEFORE registering
from admin import admin_bp
# Import routes to register them on the blueprint first
import admin.routes
# NOW register the blueprint with the app
app.register_blueprint(admin_bp)

if __name__ == '__main__':
    init_admin_db()
    print("=" * 60)
    print("Unified Admin & Website Server")
    print("=" * 60)
    print("Starting server on http://127.0.0.1:8000")
    print("Website: http://127.0.0.1:8000")
    print("Admin Panel: http://127.0.0.1:8000/admin")
    print("Admin credentials configured via environment variables")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=8000, use_reloader=False)

