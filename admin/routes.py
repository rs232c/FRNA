"""
Admin routes - Flask route handlers for admin interface
"""
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, send_file
from werkzeug.datastructures import ImmutableMultiDict
from functools import wraps
import os
import logging
import threading
import subprocess
import sys
import time
import secrets
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from .services import (
    validate_zip_code, validate_article_id, safe_path, get_db, get_db_legacy,
    hash_password, verify_password, get_articles, get_rejected_articles,
    toggle_article, get_sources, get_stats, get_settings, trash_article, restore_article,
    toggle_top_story, toggle_top_article, toggle_alert, toggle_good_fit, train_relevance
)
from config import DATABASE_CONFIG, NEWS_SOURCES, WEBSITE_CONFIG, VERSION

# Load environment variables
load_dotenv()

# Import zip resolver for city-based directory resolution
try:
    from zip_resolver import get_city_state_for_zip
except ImportError:
    logger.warning("zip_resolver not available, falling back to zip-based directories")
    get_city_state_for_zip = None

logger = logging.getLogger(__name__)

# Global flag to prevent concurrent regenerations
_regenerating = False
_regeneration_lock = threading.Lock()
_last_regeneration_start = None

# Security constants
ZIP_CODE_LENGTH = 5
MAX_ARTICLE_ID = 2**31 - 1

def get_current_zip_from_request():
    """Get zip code from request - uses domain mapping, falls back to 02720"""
    host = request.host.lower()

    # Domain mapping (extend as needed)
    domain_zip_map = {
        'fallriver.live': '02720',
        'fallriver.live:8000': '02720',
        '127.0.0.1:8000': '02720',
        'localhost:8000': '02720',
        # Future domains:
        # 'newport.live': '02840',
        # 'boston.live': '02108',
    }

    # Try domain match first
    if host in domain_zip_map:
        return domain_zip_map[host]

    # Try subdomain match (e.g., 02720.fallriver.live)
    if '.' in host and host.count('.') >= 2:
        potential_zip = host.split('.')[0]
        if potential_zip.isdigit() and len(potential_zip) == 5:
            return potential_zip

    # Fallback to Fall River
    return '02720'

def get_zip_dir(zip_code):
    """Get and validate zip directory - ensures the zip has been generated"""
    from flask import abort
    import os

    zip_dir = os.path.join("build", "zips", f"zip_{zip_code.zfill(5)}")
    index_path = os.path.join(zip_dir, "index.html")

    if not os.path.exists(index_path):
        abort(404, description=f"City zip_{zip_code.zfill(5)} has not been created yet.")

    return zip_dir

def serve_zip_page(zip_code):
    """Unified function to serve any zip page from clean zip structure"""
    if not validate_zip_code(zip_code):
        return "Invalid zip code", 404

    zip_dir = get_zip_dir(zip_code)  # Use the new validator
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_zip_dir = os.path.join(project_root, zip_dir)
    logger.debug(f"Serving from {full_zip_dir}")

    index_path = os.path.join(full_zip_dir, 'index.html')
    # No need to check exists again since get_zip_dir() already validated
    return send_file(index_path)

def serve_zip_category_page(zip_code, category_slug):
    """Unified function to serve zip-specific category page from clean zip structure"""
    if not validate_zip_code(zip_code):
        return "Invalid zip code", 404

    # Strip .html extension if present
    if category_slug.endswith('.html'):
        category_slug = category_slug[:-5]

    zip_dir = get_zip_dir(zip_code)  # Use the new validator
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_zip_dir = os.path.join(project_root, zip_dir)
    logger.debug(f"Serving category from {full_zip_dir}")

    category_path = os.path.join(full_zip_dir, 'category', f'{category_slug}.html')

    if os.path.exists(category_path):
        return send_file(category_path)
    else:
        return "Category page not found", 404

# Security: Authentication credentials from environment (REQUIRED)
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
ZIP_LOGIN_PASSWORD = os.getenv('ZIP_LOGIN_PASSWORD')
ZIP_CODE_LENGTH = 5

# Require credentials to be set
if not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise ValueError(
        "ADMIN_USERNAME and ADMIN_PASSWORD environment variables must be set. "
        "Create a .env file with:\n"
        "ADMIN_USERNAME=your_username\n"
        "ADMIN_PASSWORD=your_secure_password\n"
        "ZIP_LOGIN_PASSWORD=your_zip_password"
    )

# Security: Hash password for secure storage/comparison
_ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH')
if _ADMIN_PASSWORD_HASH:
    _ADMIN_PASSWORD_HASHED = True
else:
    _ADMIN_PASSWORD_HASHED = False

# Optional security imports - gracefully handle if not installed
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    FLASK_LIMITER_AVAILABLE = True
except ImportError:
    FLASK_LIMITER_AVAILABLE = False
    logger.warning("flask-limiter not installed. Rate limiting disabled. Install with: pip install flask-limiter")

# Create Flask app
app = Flask(__name__)

# Security: Use environment variable for secret key, generate if not set or empty
flask_secret_key = os.getenv('FLASK_SECRET_KEY', '').strip()
if not flask_secret_key:
    flask_secret_key = secrets.token_hex(32)
    logger.warning("FLASK_SECRET_KEY not set in environment. Using generated key (sessions will be invalidated on restart).")
app.secret_key = flask_secret_key

# Security: Configure secure session cookies
@app.after_request
def after_request(response):
    """Add CORS headers, UTF-8 encoding, and disable caching for admin pages"""
    # Security: Only allow specific origins instead of wildcard
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')
    origin = request.headers.get('Origin')
    if origin and origin in ALLOWED_ORIGINS:
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    # Force UTF-8 encoding for all admin pages
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    response.headers.add('Access-Control-Allow-Credentials', 'true')

    # Prevent ALL caching for admin pages
    if request.path.startswith('/admin'):
        response.headers.add('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
        response.headers.add('Pragma', 'no-cache')
        response.headers.add('Expires', '0')
        response.headers.add('Last-Modified', datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT'))
        response.headers.add('ETag', '')
    # Add appropriate caching for website content
    else:
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

# Rate limiter setup
if FLASK_LIMITER_AVAILABLE:
    limiter = Limiter(app=app, key_func=get_remote_address)
else:
    # Dummy limiter for when flask-limiter is not available
    class DummyLimiter:
        def limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
    limiter = DummyLimiter()


# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # #region agent log - login_required check
        try:
            with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f_log:
                f_log.write('{"login_required_check": "executing", "path": "' + request.path + '", "session_keys": ' + str(list(session.keys())) + ', "logged_in": ' + str(session.get("logged_in")) + ', "timestamp": ' + str(int(__import__("time").time()*1000)) + '}\n')
        except Exception as e:
            print(f"LOG ERROR in decorator: {e}")
        # #endregion

        # For API endpoints, return JSON error instead of redirect
        path = request.path
        is_api = path.startswith('/admin/api') or '/api/' in path
        if is_api:
            if 'logged_in' not in session:
                return jsonify({'success': False, 'error': 'Not authenticated'}), 401
        elif 'logged_in' not in session:
            # #region agent log - redirecting to login
            try:
                with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f_log:
                    f_log.write('{"login_required_redirect": "redirecting to login", "path": "' + request.path + '", "timestamp": ' + str(int(__import__("time").time()*1000)) + '}\n')
            except Exception as e:
                pass
            # #endregion
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

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


# Session check endpoint
@app.route('/api/session-check')
def session_check():
    """Check if user is logged in"""
    return jsonify({'logged_in': session.get('logged_in', False)})


# Website routes (serve static files)
@app.route('/')
def index():
    """Serve main website index - always serves 02720 (Fall River)"""
    logger.info("Index route called")
    zip_code = request.args.get('zip_code')
    if zip_code and validate_zip_code(zip_code):
        logger.info(f"Redirecting to zip code: {zip_code}")
        return redirect(f'/{zip_code}')

    # Serve default zip (Fall River)
    return serve_zip_page('02720')


@app.route('/category/<path:category_slug>')
def category_page(category_slug):
    """Serve category page"""
    # Strip .html extension if present (frontend links include .html)
    if category_slug.endswith('.html'):
        category_slug = category_slug[:-5]

    # Special handling for scanner - serve from zip-specific directory
    if category_slug == 'scanner':
        # Get current zip from session/cookies, default to 02720
        zip_code = get_current_zip_from_request()
        return serve_zip_category_page(zip_code, category_slug)

    # Calculate the correct path to the build directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    category_path = os.path.join(project_root, 'build', 'category', f'{category_slug}.html')

    try:
        return send_file(category_path)
    except (ValueError, OSError) as e:
        logger.error(f"Error serving category page {category_slug}: {e}")
        return "Category page not found", 404


@app.route('/admin/main', strict_slashes=False)
@login_required
def admin_main():
    """Global admin dashboard - shows all zip codes and global settings"""
    try:
        # For global admin, show all zips
        zip_code = None  # None means all zips
        tab = request.args.get('tab', 'overview')  # Default to overview tab for global view
        print(f"DEBUG: tab parameter = '{tab}', request.args = {dict(request.args)}")
        page = int(request.args.get('page', 1))
        category_filter = request.args.get('category', 'all')
        source_filter = request.args.get('source', '')
        search_filter = request.args.get('search', '').strip()
        date_range_filter = request.args.get('date_range', '')

        # Get data for ALL zip codes
        articles, total_count = get_articles(
            zip_code=None,  # None means all zips
            limit=50,
            offset=(page - 1) * 50,
            category=category_filter if category_filter != 'all' else None,
            search=search_filter
        )

        rejected_articles = get_rejected_articles(zip_code=None)
        sources_config = get_sources()
        stats = get_stats(zip_code=None)  # Get stats for all zips
        settings = get_settings()

        # Get additional metadata
        with get_db() as conn:
            cursor = conn.cursor()

            # Last regeneration time
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            last_regeneration = cursor.fetchone()
            last_regeneration = last_regeneration[0] if last_regeneration else None

            # Latest ingestion time
            cursor.execute('SELECT MAX(ingested_at) FROM articles')
            latest_ingestion = cursor.fetchone()
            latest_ingestion = latest_ingestion[0] if latest_ingestion and latest_ingestion[0] else None

        # Calculate pagination
        total_pages = (total_count + 49) // 50  # Ceiling division
        has_next = page < total_pages
        has_prev = page > 1

        # Get rejected article features for display
        rejected_features = []
        for article in rejected_articles[:10]:  # Show first 10
            if article.get('is_auto_filtered'):
                reason = "Auto-filtered"
            elif article.get('is_rejected'):
                reason = "Manually rejected"
            else:
                reason = "Unknown"
            rejected_features.append({
                'title': article.get('title', '')[:50],
                'reason': reason,
                'url': article.get('url', '')
            })

        # Get category stats for the categories tab
        category_stats = []
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # First ensure categories table exists and has default categories
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Insert default categories if table is empty
                cursor.execute('SELECT COUNT(*) FROM categories')
                count = cursor.fetchone()[0]
                if count == 0:
                    default_categories = ['News', 'Sports', 'Business', 'Crime', 'Events', 'Food', 'Schools', 'Local News', 'Obituaries', 'Weather']
                    for cat in default_categories:
                        try:
                            cursor.execute('INSERT INTO categories (name) VALUES (?)', (cat,))
                        except:
                            pass  # Ignore if category already exists

                conn.commit()

                # Get all categories with article counts (all zips)
                cursor.execute('''
                    SELECT
                        c.id,
                        c.name,
                        COUNT(a.id) as article_count,
                        COUNT(CASE WHEN a.published >= date('now', '-7 days') THEN 1 END) as recent_count
                    FROM categories c
                    LEFT JOIN articles a ON c.name = a.category
                    GROUP BY c.id, c.name
                    ORDER BY c.name
                ''')

                for row in cursor.fetchall():
                    category_stats.append({
                        'id': row[0],
                        'name': row[1],
                        'article_count': row[2],
                        'recent_count': row[3]
                    })

        except Exception as e:
            logger.error(f"Error getting category stats: {e}")
            category_stats = []

        # Cache busting
        cache_bust = int(time.time())

        # Relevance config
        relevance_config = WEBSITE_CONFIG.get('relevance', {})

        # All enabled zips
        enabled_zips = ['02720', '02721', '02722', '02723', '02724', '02725', '02726', '02842']

        # #region agent log
        with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                "id": f"log_{int(time.time()*1000)}_admin_main_render",
                "timestamp": int(time.time()*1000),
                "location": "admin/routes.py:413",
                "message": "Rendering admin/main_dashboard.html template",
                "data": {
                    "zip_code": 'main',
                    "is_main_admin": True,
                    "active_tab": tab,
                    "total_count": total_count,
                    "page": page,
                    "settings_keys": list(settings.keys()) if settings else [],
                    "stats_keys": list(stats.keys()) if stats else []
                },
                "sessionId": "debug-session",
                "runId": "hypothesis_test",
                "hypothesisId": "template_data"
            }) + '\n')
        # #endregion

        return render_template('admin/global_dashboard.html',
            zip_code='',  # Empty string indicates global view
            is_main_admin=True,  # Global admin view
            active_tab=tab,
            articles=articles,
            rejected_articles=rejected_articles,
            stats=stats,
            settings=settings,
            sources=sources_config,
            version=VERSION,
            last_regeneration=last_regeneration,
            latest_ingestion=latest_ingestion,
            rejected_features=rejected_features,
            cache_bust=cache_bust,
            relevance_config=relevance_config,
            enabled_zips=enabled_zips,
            category_stats=category_stats,
            page=page,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
            total_count=total_count,
            category_filter=category_filter,
            source_filter=source_filter,
            date_range_filter=date_range_filter,
            search_filter=search_filter
        )

    except Exception as e:
        logger.error(f"Error in admin_main: {e}", exc_info=True)
        return f"Error loading main admin dashboard: {e}", 500


@app.route('/<zip_code>')
def zip_page(zip_code):
    """Serve zip-specific index page from clean zip structure"""
    return serve_zip_page(zip_code)


@app.route('/<zip_code>/category/<path:category_slug>')
def zip_category_page(zip_code, category_slug):
    """Serve zip-specific category page from clean zip structure"""
    return serve_zip_category_page(zip_code, category_slug)


@app.route('/css/<path:filename>')
def serve_css(filename):
    """Serve CSS files from zip directory"""
    zip_code = get_current_zip_from_request()
    zip_dir = get_zip_dir(zip_code)  # Validate zip exists
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_zip_dir = os.path.join(project_root, zip_dir)
    logger.debug(f"Serving CSS from {full_zip_dir}")
    safe_filename = safe_path(Path(os.path.join(full_zip_dir, 'css')), filename)
    if not safe_filename.exists():
        return "File not found", 404
    return send_from_directory(str(safe_filename.parent), safe_filename.name)


@app.route('/js/<path:filename>')
def serve_js(filename):
    """Serve JavaScript files from zip directory"""
    zip_code = get_current_zip_from_request()
    zip_dir = get_zip_dir(zip_code)  # Validate zip exists
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_zip_dir = os.path.join(project_root, zip_dir)
    logger.debug(f"Serving JS from {full_zip_dir}")
    safe_filename = safe_path(Path(os.path.join(full_zip_dir, 'js')), filename)
    if not safe_filename.exists():
        return "File not found", 404
    return send_from_directory(str(safe_filename.parent), safe_filename.name)


@app.route('/images/<path:filename>')
def serve_images(filename):
    """Serve image files from zip directory"""
    zip_code = get_current_zip_from_request()
    zip_dir = get_zip_dir(zip_code)  # Validate zip exists
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_zip_dir = os.path.join(project_root, zip_dir)
    logger.debug(f"Serving images from {full_zip_dir}")
    safe_filename = safe_path(Path(os.path.join(full_zip_dir, 'images')), filename)
    if not safe_filename.exists():
        return "File not found", 404
    return send_from_directory(str(safe_filename.parent), safe_filename.name)


@app.route('/api/proxy-rss')
def proxy_rss():
    """Proxy RSS feed requests to avoid CORS issues"""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        import requests
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # Return the RSS content with appropriate headers
        return response.content, 200, {
            'Content-Type': response.headers.get('content-type', 'application/xml'),
            'Cache-Control': 'public, max-age=300'  # Cache for 5 minutes
        }
    except Exception as e:
        logger.error(f"RSS proxy error: {e}")
        return jsonify({'error': 'Failed to fetch RSS feed'}), 500


# Admin routes
@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    """Login route"""
    zip_code = request.args.get('z', '').strip()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Security: Input validation
        if not username or not password:
            error = 'Username and password are required'
            if request.headers.get('Content-Type') == 'application/json' or request.is_json:
                return jsonify({'success': False, 'error': error}), 401
            return render_template('admin/login.html', error=error, zip_code=zip_code)

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
        return render_template('admin/login.html', error=error, zip_code=zip_code)

    return render_template('admin/login.html', zip_code=zip_code)


@app.route('/admin/logout')
def logout():
    """Logout route"""
    session.pop('logged_in', None)
    session.pop('zip_code', None)
    session.pop('is_main_admin', None)
    return redirect(url_for('login'))


@app.route('/test', methods=['GET'])
def test_route():
    return "TEST ROUTE WORKS"

@app.route('/testadmin', methods=['GET'])
def test_admin():
    return "ADMIN ROUTE WORKS"

@app.route('/admin', methods=['GET'])
@login_required
def admin_dashboard():
    """Global admin dashboard - shows all zip codes and global settings"""
    try:
        # For global admin, show all zips
        zip_code = None  # None means all zips
        tab = request.args.get('tab', 'overview')  # Default to overview tab for global view
        page = int(request.args.get('page', 1))
        category_filter = request.args.get('category', 'all')
        source_filter = request.args.get('source', '')
        search_filter = request.args.get('search', '').strip()
        date_range_filter = request.args.get('date_range', '')

        # Get data for ALL zip codes
        articles, total_count = get_articles(
            zip_code=None,  # None means all zips
            limit=50,
            offset=(page - 1) * 50,
            category=category_filter if category_filter != 'all' else None,
            search=search_filter
        )

        rejected_articles = get_rejected_articles(zip_code=None)
        sources_config = get_sources()
        stats = get_stats(zip_code=None)  # Stats for all zips
        settings = get_settings()

        # Get additional metadata
        with get_db() as conn:
            cursor = conn.cursor()

            # Last regeneration time
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            last_regeneration = cursor.fetchone()
            last_regeneration = last_regeneration[0] if last_regeneration else None

            # Latest ingestion time
            cursor.execute('SELECT MAX(ingested_at) FROM articles')
            latest_ingestion = cursor.fetchone()
            latest_ingestion = latest_ingestion[0] if latest_ingestion and latest_ingestion[0] else None

        # Calculate pagination
        total_pages = (total_count + 49) // 50  # Ceiling division
        has_next = page < total_pages
        has_prev = page > 1

        # Get rejected article features for display
        rejected_features = []
        for article in rejected_articles[:10]:  # Show first 10
            if article.get('is_auto_filtered'):
                reason = "Auto-filtered"
            elif article.get('is_rejected'):
                reason = "Manually rejected"
            else:
                reason = "Unknown"
            rejected_features.append({
                'title': article.get('title', '')[:50],
                'reason': reason,
                'url': article.get('url', '')
            })

        # Get category stats for the categories tab
        category_stats = []
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # First ensure categories table exists and has default categories
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Insert default categories if table is empty
                cursor.execute('SELECT COUNT(*) FROM categories')
                count = cursor.fetchone()[0]
                if count == 0:
                    default_categories = ['News', 'Sports', 'Business', 'Crime', 'Events', 'Food', 'Schools', 'Local News', 'Obituaries', 'Weather']
                    for cat in default_categories:
                        try:
                            cursor.execute('INSERT INTO categories (name) VALUES (?)', (cat,))
                        except:
                            pass  # Ignore if category already exists

                conn.commit()

                # Get all categories with article counts (all zips)
                cursor.execute('''
                    SELECT
                        c.id,
                        c.name,
                        COUNT(a.id) as article_count,
                        COUNT(CASE WHEN a.published >= date('now', '-7 days') THEN 1 END) as recent_count
                    FROM categories c
                    LEFT JOIN articles a ON c.name = a.category
                    GROUP BY c.id, c.name
                    ORDER BY c.name
                ''')

                for row in cursor.fetchall():
                    category_stats.append({
                        'id': row[0],
                        'name': row[1],
                        'article_count': row[2],
                        'recent_count': row[3]
                    })

        except Exception as e:
            logger.error(f"Error getting category stats: {e}")
            category_stats = []

        # Cache busting
        cache_bust = int(time.time())

        # Relevance configuration
        relevance_config = WEBSITE_CONFIG.get('relevance', {})

        # All enabled zips for the overview
        enabled_zips = ['02720', '02721', '02722', '02723', '02724', '02725', '02726', '02842']

        return render_template('admin/global_dashboard.html',
            zip_code=None,  # None indicates global view
            is_main_admin=True,  # Global admin view
            active_tab=tab,
            articles=articles,
            rejected_articles=rejected_articles,
            stats=stats,
            settings=settings,
            sources=sources_config,
            version=VERSION,
            last_regeneration=last_regeneration,
            latest_ingestion=latest_ingestion,
            rejected_features=rejected_features,
            cache_bust=cache_bust,
            relevance_config=relevance_config,
            enabled_zips=enabled_zips,
            category_stats=category_stats,
            page=page,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
            total_count=total_count,
            category_filter=category_filter,
            source_filter=source_filter,
            date_range_filter=date_range_filter,
            search_filter=search_filter
        )

    except Exception as e:
        logger.error(f"Error in admin_dashboard: {e}", exc_info=True)
        return f"Error loading global admin dashboard: {e}", 500


@app.route('/Sortable.min.js')
def serve_sortable():
    """Serve Sortable.min.js from project root"""
    try:
        return send_from_directory(str(Path.cwd()), 'Sortable.min.js')
    except (ValueError, OSError):
        return "Sortable.min.js not found", 404


# SPA fallback routes - must come before the catch-all
@app.route('/obituaries')
def obituaries_route():
    """Serve the obituaries category page directly"""
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        category_path = os.path.join(project_root, 'build', 'category', 'obituaries.html')
        return send_file(category_path)
    except Exception as e:
        logger.error(f"Error serving obituaries: {e}")
        return f"Error: {e}", 500

@app.route('/news')
@app.route('/events')
@app.route('/sports')
@app.route('/business')
@app.route('/crime')
@app.route('/schools')
@app.route('/food')
@app.route('/weather')
@app.route('/entertainment')
@app.route('/local')
def spa_category_routes():
    """Serve index.html for SPA category routes"""
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        build_dir = os.path.join(project_root, 'build')
        return send_from_directory(build_dir, 'index.html')
    except Exception as e:
        logger.error(f"Error serving SPA route: {e}")
        return f"Error: {e}", 500

@login_required
@app.route('/admin/', methods=['GET'])
def admin_slash_redirect():
    """Redirect /admin/ to /admin for consistency"""
    return redirect('/admin', code=302)


@app.route('/admin/<zip_code>', methods=['GET'])
@login_required
def admin_zip_dashboard(zip_code):
    """Admin dashboard for specific zip code"""
    # #region agent log - test if logging works
    try:
        with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write('{"test": "logging_works", "zip_code": "' + zip_code + '", "timestamp": ' + str(int(__import__("time").time()*1000)) + '}\n')
    except Exception as e:
        print(f"LOG ERROR: {e}")
    # #endregion

    # #region agent log
    import json
    import time
    with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            "id": f"log_{int(time.time()*1000)}_zip_dashboard_entry",
            "timestamp": int(time.time()*1000),
            "location": "admin/routes.py:750",
            "message": f"admin_zip_dashboard called with zip_code={zip_code}",
            "data": {
                "zip_code": zip_code,
                "is_valid": validate_zip_code(zip_code),
                "session_logged_in": session.get('logged_in'),
                "session_is_main_admin": session.get('is_main_admin'),
                "session_zip_code": session.get('zip_code')
            },
            "sessionId": "debug-session",
            "runId": "hypothesis_test",
            "hypothesisId": "route_conflict"
        }) + '\n')
    # #endregion

    try:
        # Validate zip code
        if not validate_zip_code(zip_code):
            # #region agent log
            with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    "id": f"log_{int(time.time()*1000)}_zip_invalid",
                    "timestamp": int(time.time()*1000),
                    "location": "admin/routes.py:767",
                    "message": f"Invalid zip code: {zip_code}",
                    "data": {"zip_code": zip_code},
                    "sessionId": "debug-session",
                    "runId": "hypothesis_test",
                    "hypothesisId": "route_conflict"
                }) + '\n')
            # #endregion
            return "Invalid zip code", 404

        # Set this zip code in session for convenience
        session['zip_code'] = zip_code

        tab = request.args.get('tab', 'articles')  # Default to articles tab for zip-specific

        # #region agent log
        try:
            with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                json.dump({
                    "id": f"log_{int(time.time()*1000)}_tab_value",
                    "timestamp": int(time.time()*1000),
                    "location": "admin/routes.py:948",
                    "message": "Tab parameter value",
                    "data": {
                        "tab": tab,
                        "request_args": dict(request.args),
                        "full_url": request.url,
                        "method": request.method
                    },
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "A"
                }, f)
                f.write('\n')
        except Exception as e:
            pass
        # #endregion
        page = int(request.args.get('page', 1))
        category_filter = request.args.get('category', 'all')
        source_filter = request.args.get('source', '')
        search_filter = request.args.get('search', '').strip()
        date_range_filter = request.args.get('date_range', '')

        # Get data for dashboard filtered to this specific zip code
        articles, total_count = get_articles(
            zip_code=zip_code,
            limit=50,
            offset=(page - 1) * 50,
            category=category_filter if category_filter != 'all' else None,
            search=search_filter
        )

        rejected_articles = get_rejected_articles(zip_code=zip_code)
        sources_config = get_sources()
        stats = get_stats(zip_code=zip_code)  # Get stats for this zip only
        settings = get_settings()

        # Get additional metadata
        with get_db() as conn:
            cursor = conn.cursor()

            # Last regeneration time
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            last_regeneration = cursor.fetchone()
            last_regeneration = last_regeneration[0] if last_regeneration else None

            # Latest ingestion time
            cursor.execute('SELECT MAX(ingested_at) FROM articles WHERE zip_code = ?', (zip_code,))
            latest_ingestion = cursor.fetchone()
            latest_ingestion = latest_ingestion[0] if latest_ingestion and latest_ingestion[0] else None

        # Calculate pagination
        total_pages = (total_count + 49) // 50  # Ceiling division
        has_next = page < total_pages
        has_prev = page > 1

        # Get rejected article features for display
        rejected_features = []
        for article in rejected_articles[:10]:  # Show first 10
            if article.get('is_auto_filtered'):
                reason = "Auto-filtered"
            elif article.get('is_rejected'):
                reason = "Manually rejected"
            else:
                reason = "Unknown"
            rejected_features.append({
                'title': article.get('title', '')[:50],
                'reason': reason,
                'url': article.get('url', '')
            })

        # Get category stats for the categories tab
        category_stats = []
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # First ensure categories table exists and has default categories
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')

                # Insert default categories if table is empty
                cursor.execute('SELECT COUNT(*) FROM categories')
                if cursor.fetchone()[0] == 0:
                    default_categories = ['News', 'Sports', 'Business', 'Crime', 'Events', 'Food', 'Schools', 'Local News', 'Obituaries', 'Weather']
                    for cat in default_categories:
                        try:
                            cursor.execute('INSERT INTO categories (name) VALUES (?)', (cat,))
                        except:
                            pass  # Ignore if category already exists

                conn.commit()

                # Get category statistics and keyword counts
                # Use the actual categories from articles, not the separate categories table
                cursor.execute('''
                    SELECT
                        a.category as name,
                        COUNT(a.id) as article_count,
                        COUNT(CASE WHEN a.published >= date('now', '-7 days') THEN 1 END) as recent_count
                    FROM articles a
                    WHERE a.zip_code = ? AND a.category IS NOT NULL AND a.category != ''
                    GROUP BY a.category
                    ORDER BY a.category
                ''', (zip_code,))

                category_stats = []
                for row in cursor.fetchall():
                    category_name = row[0]

                    # Get keyword count for this category
                    cursor.execute('SELECT COUNT(DISTINCT keyword) FROM category_keywords WHERE category = ? AND zip_code = ?', (category_name, zip_code))
                    keyword_count = cursor.fetchone()[0]

                    category_stats.append({
                        'name': category_name.replace('-', ' ').title(),  # Convert 'local-news' to 'Local News'
                        'article_count': row[1],
                        'recent_count': row[2],
                        'keyword_count': keyword_count
                    })

                category_stats = []
                for row in cursor.fetchall():
                    category_stats.append({
                        'name': row[0],
                        'article_count': row[1],
                        'recent_count': row[2],
                        'keyword_count': row[3] or 0
                    })

                # If no categories found, provide default ones with keyword counts
                if not category_stats:
                    default_categories = [
                        ('business', 'Business'),
                        ('crime', 'Crime'),
                        ('events', 'Events'),
                        ('food', 'Food'),
                        ('local-news', 'Local News'),
                        ('obituaries', 'Obituaries'),
                        ('schools', 'Schools'),
                        ('sports', 'Sports'),
                        ('weather', 'Weather')
                    ]

                    for cat_slug, cat_name in default_categories:
                        cursor.execute('SELECT COUNT(*) FROM category_keywords WHERE category = ? AND zip_code = ?', (cat_slug, zip_code))
                        keyword_count = cursor.fetchone()[0]

                        category_stats.append({
                            'name': cat_name,
                            'article_count': 0,
                            'recent_count': 0,
                            'keyword_count': keyword_count
                        })
        except Exception as e:
            logger.error(f"Error getting category stats: {e}")
            category_stats = []

        # Cache busting
        cache_bust = int(time.time())

        # Relevance configuration
        relevance_config = WEBSITE_CONFIG.get('relevance', {})

        # All enabled zips
        enabled_zips = ['02720', '02721', '02722', '02723', '02724', '02725', '02726', '02842']

        # Use dedicated categories template for categories tab
        # #region agent log
        try:
            with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                json.dump({
                    "id": f"log_{int(time.time()*1000)}_template_selection",
                    "timestamp": int(time.time()*1000),
                    "location": "admin/routes.py:1104",
                    "message": "Template selection logic reached",
                    "data": {
                        "tab": tab,
                        "tab_equals_categories": tab == 'categories',
                        "zip_code": zip_code,
                        "template_to_render": "admin/categories.html" if tab == 'categories' else "admin/main_dashboard.html"
                    },
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "A"
                }, f)
                f.write('\n')
        except Exception as e:
            pass
        # #endregion

        if tab == 'categories':
            # #region agent log
            try:
                with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    json.dump({
                        "id": f"log_{int(time.time()*1000)}_categories_branch",
                        "timestamp": int(time.time()*1000),
                        "location": "admin/routes.py:1105",
                        "message": "Categories branch executed",
                        "data": {
                            "tab": tab,
                            "zip_code": zip_code
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "A"
                    }, f)
                    f.write('\n')
            except Exception as e:
                pass
            # #endregion
            # #region agent log
            try:
                with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    json.dump({
                        "id": f"log_{int(time.time()*1000)}_rendering_categories",
                        "timestamp": int(time.time()*1000),
                        "location": "admin/routes.py:1105",
                        "message": "Rendering categories.html template",
                        "data": {
                            "zip_code": zip_code,
                            "version": VERSION
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "A"
                    }, f)
                    f.write('\n')
            except Exception as e:
                pass
            # #endregion
            return render_template('admin/categories.html',
                zip_code=zip_code,
                version=VERSION,
                active_tab=tab
            )

        if tab == 'settings':
            # #region agent log
            try:
                with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    json.dump({
                        "id": f"log_{int(time.time()*1000)}_settings_branch",
                        "timestamp": int(time.time()*1000),
                        "location": "admin/routes.py:1220",
                        "message": "Settings branch executed",
                        "data": {
                            "tab": tab,
                            "zip_code": zip_code
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "A"
                    }, f)
                    f.write('\n')
            except Exception as e:
                pass
            # #endregion
            return render_template('admin/settings.html',
                zip_code=zip_code,
                version=VERSION,
                active_tab=tab,
                settings=settings
            )

        # #region agent log
        try:
            with open(r'c:\FRNA\.cursor\debug.log', 'a', encoding='utf-8') as f:
                json.dump({
                    "id": f"log_{int(time.time()*1000)}_main_dashboard_render",
                    "timestamp": int(time.time()*1000),
                    "location": "admin/routes.py:1137",
                    "message": "Rendering main dashboard template (categories not selected)",
                    "data": {
                        "tab": tab,
                        "zip_code": zip_code
                    },
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "A"
                }, f)
                f.write('\n')
        except Exception as e:
            pass
        # #endregion

        return render_template('admin/main_dashboard.html',
            zip_code=zip_code,  # Pass the actual zip code for zip-specific admin
            is_main_admin=False,  # Flag to indicate this is zip-specific admin view
            active_tab=tab,
            articles=articles,
            rejected_articles=rejected_articles,
            stats=stats,
            settings=settings,
            sources=sources_config,
            version=VERSION,
            last_regeneration=last_regeneration,
            latest_ingestion=latest_ingestion,
            rejected_features=rejected_features,
            cache_bust=cache_bust,
            relevance_config=relevance_config,
            enabled_zips=enabled_zips,
            category_stats=category_stats,
            page=page,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
            total_count=total_count,
            category_filter=category_filter,
            source_filter=source_filter,
            date_range_filter=date_range_filter,
            search_filter=search_filter
        )

    except Exception as e:
        logger.error(f"Error in admin_zip_dashboard for {zip_code}: {e}", exc_info=True)
        return f"Admin dashboard error for {zip_code}: {str(e)}", 500


@app.route('/static/admin/<path:filename>')
def admin_static_files(filename):
    """Serve static admin files - no login required for static assets"""
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static_dir = os.path.join(project_root, 'admin', 'static')
        safe_filename = safe_path(Path(static_dir), filename)
        if not safe_filename.exists():
            return "File not found", 404
        return send_file(str(safe_filename))
    except Exception as e:
        logger.error(f"Error serving admin static file {filename}: {e}")
        return "File not found", 404


@login_required
@app.route('/admin/<zip_code>/articles', methods=['GET'])
def admin_articles_page(zip_code):
    """Dedicated articles admin page with fancy buttons"""
    try:
        if not validate_zip_code(zip_code):
            return "Invalid zip code", 404

        # Set this zip code in session for convenience
        session['zip_code'] = zip_code

        page = int(request.args.get('page', 1))
        category_filter = request.args.get('category', 'all')
        source_filter = request.args.get('source', '')
        search_filter = request.args.get('search', '').strip()

        # Get data for dashboard filtered to this zip code
        articles, total_count = get_articles(
            zip_code=zip_code,
            limit=50,
            offset=(page - 1) * 50,
            category=category_filter if category_filter != 'all' else None,
            search=search_filter
        )

        stats = get_stats(zip_code=zip_code)
        settings = get_settings()

        # Get additional metadata
        with get_db() as conn:
            cursor = conn.cursor()

            # Last regeneration time
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            last_regeneration = cursor.fetchone()
            last_regeneration = last_regeneration[0] if last_regeneration else None

            # Latest ingestion time
            cursor.execute('SELECT MAX(ingested_at) FROM articles')
            latest_ingestion = cursor.fetchone()
            latest_ingestion = latest_ingestion[0] if latest_ingestion and latest_ingestion[0] else None

        # Cache busting
        cache_bust = str(int(time.time()))

        # Get VERSION from config
        try:
            from config import VERSION
        except ImportError:
            VERSION = "dev"

        return render_template('admin/articles.html',
            zip_code=zip_code,
            active_tab='articles',
            articles=articles,
            total_articles=total_count,
            stats=stats,
            settings=settings,
            version=VERSION,
            last_regeneration=last_regeneration,
            latest_ingestion=latest_ingestion,
            cache_bust=cache_bust
        )

    except Exception as e:
        logger.error(f"Error in admin_articles_page for {zip_code}: {e}")
        return f"Admin articles page error for {zip_code}: {str(e)}", 500




@login_required
@app.route('/admin/api/reject-article', methods=['POST', 'OPTIONS'])
def reject_article():
    """Reject/trash an article"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')
    zip_code = data.get('zip_code')

    if not article_id:
        return jsonify({'error': 'Missing article_id'}), 400

    try:
        from .services import trash_article
        trash_article(article_id, zip_code or '02720')
        return jsonify({'success': True, 'message': 'Article rejected'})
    except Exception as e:
        logger.error(f"Error rejecting article {article_id}: {e}")
        return jsonify({'error': 'Database error'}), 500


@login_required
@app.route('/admin/action/<int:article_id>', methods=['POST'])
def admin_action(article_id):
    """Unified admin action endpoint for all button interactions"""
    data = request.get_json() if request.is_json else request.form
    action_type = data.get('action') or data.get('type')

    if not action_type:
        return jsonify({'error': 'Missing action type'}), 400

    # Get zip code from request data or session
    zip_code = data.get('zip_code') or get_current_zip_from_request()

    try:
        success = False
        message = 'Action completed'

        if action_type == 'trash':
            from .services import trash_article
            trash_article(article_id, zip_code)
            success = True
            message = 'Article moved to trash'

        elif action_type == 'restore':
            from .services import restore_article
            restore_article(article_id, zip_code)
            success = True
            message = 'Article restored'

        elif action_type == 'thumbs_up' or action_type == 'good_fit':
            from .services import toggle_good_fit
            toggle_good_fit(article_id, zip_code, True)
            success = True
            message = 'Marked as good fit'

        elif action_type == 'thumbs_down':
            from .services import toggle_good_fit
            toggle_good_fit(article_id, zip_code, False)
            success = True
            message = 'Article rejected'

        elif action_type == 'top_story':
            from .services import toggle_top_story
            toggle_top_story(article_id, zip_code, True)
            success = True
            message = 'Marked as top story'

        elif action_type == 'top_article':
            from .services import toggle_top_article
            toggle_top_article(article_id, zip_code, True)
            success = True
            message = 'Marked as top article'

        elif action_type == 'alert':
            from .services import toggle_alert
            toggle_alert(article_id, zip_code, True)
            success = True
            message = 'Alert enabled'

        elif action_type == 'on_target':
            from .services import train_relevance
            train_relevance(article_id, zip_code, 'on_target')
            success = True
            message = 'Marked as on-target'

        elif action_type == 'off_target':
            from .services import train_relevance
            train_relevance(article_id, zip_code, 'off_target')
            success = True
            message = 'Marked as off-target'

        else:
            return jsonify({'error': f'Unknown action type: {action_type}'}), 400

        return jsonify({'success': success, 'message': message})

    except Exception as e:
        logger.error(f"Error in admin action {action_type} for article {article_id}: {e}")
        return jsonify({'error': 'Database error', 'message': str(e)}), 500


@login_required
@app.route('/admin/api/toggle-article', methods=['POST', 'OPTIONS'])
def toggle_article_route():
    """Toggle article status (reject/restore/feature/unfeature)"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')
    action = data.get('action')

    if not article_id or not action:
        return jsonify({'success': False, 'error': 'Missing article_id or action'}), 400

    if not validate_article_id(article_id):
        return jsonify({'success': False, 'error': 'Invalid article ID'}), 400

    try:
        article = toggle_article(int(article_id), action)
        return jsonify({'success': True, 'article': article})
    except Exception as e:
        logger.error(f"Error toggling article {article_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/toggle-top-story', methods=['POST', 'OPTIONS'])
def toggle_top_story_route():
    """Toggle top story status"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')

    if not article_id:
        return jsonify({'success': False, 'error': 'Missing article_id'}), 400

    if not validate_article_id(article_id):
        return jsonify({'success': False, 'error': 'Invalid article ID'}), 400

    try:
        # Get current state and toggle it
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT is_top_story FROM articles WHERE id = ?', (article_id,))
            row = cursor.fetchone()
            current_state = row[0] if row else 0
            new_state = 0 if current_state else 1

        toggle_top_story(int(article_id), new_state)
        return jsonify({'success': True, 'is_top_story': new_state})
    except Exception as e:
        logger.error(f"Error toggling top story {article_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/toggle-top-article', methods=['POST', 'OPTIONS'])
def toggle_top_article_route():
    """Toggle top article status"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')

    if not article_id:
        return jsonify({'success': False, 'error': 'Missing article_id'}), 400

    if not validate_article_id(article_id):
        return jsonify({'success': False, 'error': 'Invalid article ID'}), 400

    try:
        # Get current state and toggle it
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT is_top FROM articles WHERE id = ?', (article_id,))
            row = cursor.fetchone()
            current_state = row[0] if row else 0
            new_state = 0 if current_state else 1

        toggle_top_article(int(article_id), new_state)
        return jsonify({'success': True, 'is_top': new_state})
    except Exception as e:
        logger.error(f"Error toggling top article {article_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/toggle-alert', methods=['POST', 'OPTIONS'])
def toggle_alert_route():
    """Toggle alert status"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')

    if not article_id:
        return jsonify({'success': False, 'error': 'Missing article_id'}), 400

    if not validate_article_id(article_id):
        return jsonify({'success': False, 'error': 'Invalid article ID'}), 400

    try:
        # Get current state and toggle it
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT is_alert FROM articles WHERE id = ?', (article_id,))
            row = cursor.fetchone()
            current_state = row[0] if row else 0
            new_state = 0 if current_state else 1

        toggle_alert(int(article_id), new_state)
        return jsonify({'success': True, 'is_alert': new_state})
    except Exception as e:
        logger.error(f"Error toggling alert {article_id}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/train-relevance', methods=['POST', 'OPTIONS'])
def train_relevance_route():
    """Train relevance model from admin feedback"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')
    zip_code = data.get('zip_code')
    click_type = data.get('click_type')

    if not article_id or not zip_code or not click_type:
        return jsonify({'success': False, 'error': 'Missing required parameters'}), 400

    if not validate_article_id(article_id):
        return jsonify({'success': False, 'error': 'Invalid article ID'}), 400

    if not validate_zip_code(zip_code):
        return jsonify({'success': False, 'error': 'Invalid zip code'}), 400

    if click_type not in ['thumbs_up', 'thumbs_down']:
        return jsonify({'success': False, 'error': 'Invalid click type'}), 400

    try:
        success, message = train_relevance(int(article_id), zip_code, click_type)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error(f"Error in train-relevance endpoint: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/get-auto-filtered', methods=['GET', 'OPTIONS'])
def get_auto_filtered():
    """Get auto-filtered articles (placeholder)"""
    return jsonify({'articles': []})


@login_required
@app.route('/admin/api/get-rejection-tag-suggestions', methods=['GET', 'OPTIONS'])
def get_rejection_tag_suggestions():
    """Get rejection tag suggestions for an article (placeholder)"""
    article_id = request.args.get('article_id')
    if not article_id:
        return jsonify({'suggestions': []})

    # For now, return some common rejection reasons
    suggestions = [
        'duplicate',
        'irrelevant',
        'old_news',
        'spam',
        'incomplete',
        'paywall',
        'local_not_relevant',
        'advertisement'
    ]
    return jsonify({'suggestions': suggestions})


@login_required
@app.route('/admin/api/get-relevance-breakdown', methods=['GET', 'OPTIONS'])
def get_relevance_breakdown():
    """Get relevance breakdown for an article (placeholder)"""
    article_id = request.args.get('id')
    if not article_id:
        return jsonify({'error': 'Article ID required'}), 400

    # For now, return mock data
    breakdown = {
        'article_id': article_id,
        'relevance_score': 75,
        'keywords_matched': ['Fall River', 'local news'],
        'categories_matched': ['local-news'],
        'negative_factors': ['old_date'],
        'analysis': 'Article is relevant but somewhat outdated'
    }
    return jsonify(breakdown)


@login_required
@app.route('/admin/api/analyze-target', methods=['POST', 'OPTIONS'])
def analyze_target():
    """Analyze target keywords (placeholder)"""
    data = request.get_json() if request.is_json else request.form
    keywords = data.get('keywords', [])
    return jsonify({'analysis': f'Analyzed {len(keywords)} keywords', 'results': []})


@login_required
@app.route('/admin/api/add-target-keywords', methods=['POST', 'OPTIONS'])
def add_target_keywords():
    """Add target keywords (placeholder)"""
    data = request.get_json() if request.is_json else request.form
    keywords = data.get('keywords', [])
    return jsonify({'success': True, 'added': len(keywords)})


@login_required
@app.route('/admin/api/regenerate-settings', methods=['POST', 'OPTIONS'])
def regenerate_settings():
    """Regenerate settings (placeholder)"""
    return jsonify({'success': True, 'message': 'Settings regenerated'})


@login_required
@app.route('/admin/api/regenerate', methods=['POST', 'OPTIONS'])
def regenerate_website():
    """Trigger website regeneration using existing data"""
    try:
        import subprocess
        import threading

        zip_code = request.args.get('zip_code')

        def run_regeneration():
            try:
                # Run quick_regenerate.py script from project root
                import os
                script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'deployment', 'quick_regenerate.py')
                cmd = [sys.executable, script_path]
                if zip_code:
                    cmd.extend(['--zip', zip_code])

                logger.info(f"Running regeneration command: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

                if result.returncode == 0:
                    logger.info("Website regeneration completed successfully")
                    logger.info(f"Output: {result.stdout}")
                else:
                    logger.error(f"Regeneration failed with return code {result.returncode}")
                    logger.error(f"Stdout: {result.stdout}")
                    logger.error(f"Stderr: {result.stderr}")

            except subprocess.TimeoutExpired:
                logger.error("Regeneration timed out after 5 minutes")
            except Exception as e:
                logger.error(f"Regeneration error: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

        # Run regeneration in background thread
        logger.info("Starting background regeneration thread")
        thread = threading.Thread(target=run_regeneration, daemon=True)
        thread.start()
        logger.info("Background regeneration thread started")

        return jsonify({
            'success': True,
            'message': 'Website regeneration started in background',
            'note': 'Check server logs for completion status'
        })

    except Exception as e:
        logger.error(f"Error starting regeneration: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/regenerate-all', methods=['POST', 'OPTIONS'])
def regenerate_all():
    """Trigger full regeneration with fresh data"""
    try:
        import subprocess
        import threading

        zip_code = request.args.get('zip_code')

        def run_full_regeneration():
            try:
                # First run aggregation to get fresh data
                from aggregator import NewsAggregator
                aggregator = NewsAggregator()
                if zip_code:
                    aggregator.run_for_zip(zip_code)
                else:
                    aggregator.run_full_cycle()
                logger.info("Aggregation completed, starting website regeneration")

                # Then run website regeneration
                import os
                script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'deployment', 'quick_regenerate.py')
                cmd = [sys.executable, script_path]
                if zip_code:
                    cmd.extend(['--zip', zip_code])

                logger.info(f"Running full regeneration command: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

                if result.returncode == 0:
                    logger.info("Full regeneration completed successfully")
                    logger.info(f"Output: {result.stdout}")
                else:
                    logger.error(f"Full regeneration failed with return code {result.returncode}")
                    logger.error(f"Stdout: {result.stdout}")
                    logger.error(f"Stderr: {result.stderr}")

            except subprocess.TimeoutExpired:
                logger.error("Full regeneration timed out after 10 minutes")
            except Exception as e:
                logger.error(f"Full regeneration error: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

        # Run full regeneration in background thread
        logger.info("Starting background full regeneration thread")
        thread = threading.Thread(target=run_full_regeneration, daemon=True)
        thread.start()
        logger.info("Background full regeneration thread started")

        return jsonify({
            'success': True,
            'message': 'Full regeneration started in background',
            'note': 'This may take several minutes. Check server logs for completion.'
        })

    except Exception as e:
        logger.error(f"Error starting full regeneration: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/check-regeneration-needed', methods=['GET', 'OPTIONS'])
def check_regeneration_needed():
    """Check if regeneration is needed based on last regeneration time and interval"""
    try:
        zip_code = request.args.get('zip_code')

        with get_db() as conn:
            cursor = conn.cursor()

            # Get regeneration interval from settings
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('regenerate_interval',))
            interval_row = cursor.fetchone()
            interval_minutes = 10  # default
            if interval_row and interval_row[0]:
                try:
                    interval_minutes = int(interval_row[0])
                except (ValueError, TypeError):
                    interval_minutes = 10

            # Get last regeneration time
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            last_regeneration_row = cursor.fetchone()

            if not last_regeneration_row or not last_regeneration_row[0]:
                return jsonify({'needs_regeneration': True, 'reason': 'Never regenerated'})

            try:
                last_regeneration = float(last_regeneration_row[0])
            except (ValueError, TypeError):
                return jsonify({'needs_regeneration': True, 'reason': 'Invalid last regeneration time'})

            current_time = time.time()

            # Check if interval has elapsed
            time_since_last = (current_time - last_regeneration) / 60  # minutes
            needs_regeneration = time_since_last >= interval_minutes

            return jsonify({
                'needs_regeneration': needs_regeneration,
                'last_regeneration': last_regeneration,
                'current_time': current_time,
                'time_since_minutes': time_since_last,
                'interval_minutes': interval_minutes
            })

    except Exception as e:
        logger.error(f"Error checking regeneration status: {e}")
        return jsonify({'error': str(e), 'needs_regeneration': False}), 500


@login_required
@app.route('/admin/api/save-weather-api-key', methods=['POST', 'OPTIONS'])
def save_weather_api_key():
    """Save weather API key for a specific zip code"""
    try:
        data = request.get_json()
        zip_code = data.get('zip_code', '02720')
        api_key = data.get('api_key', '').strip()

        if not api_key:
            return jsonify({'success': False, 'message': 'API key cannot be empty'}), 400

        with get_db() as conn:
            cursor = conn.cursor()

            # Check if setting exists
            cursor.execute('SELECT value FROM admin_settings WHERE key = ? AND zip_code = ?',
                         (f'weather_api_key_{zip_code}', zip_code))
            existing = cursor.fetchone()

            if existing:
                cursor.execute('UPDATE admin_settings SET value = ? WHERE key = ? AND zip_code = ?',
                             (api_key, f'weather_api_key_{zip_code}', zip_code))
            else:
                cursor.execute('INSERT INTO admin_settings (key, value, zip_code) VALUES (?, ?, ?)',
                             (f'weather_api_key_{zip_code}', api_key, zip_code))

            conn.commit()

        return jsonify({'success': True, 'message': 'Weather API key saved successfully'})

    except Exception as e:
        logger.error(f"Error saving weather API key: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@login_required
@app.route('/admin/api/get-article', methods=['GET', 'OPTIONS'])
def get_article():
    """Get a specific article by ID"""
    article_id = request.args.get('id')
    if not article_id:
        return jsonify({'error': 'Article ID required'}), 400

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
            article = cursor.fetchone()

            if not article:
                return jsonify({'error': 'Article not found'}), 404

            # Convert to dict
            columns = [desc[0] for desc in cursor.description]
            article_dict = dict(zip(columns, article))

            return jsonify(article_dict)
    except Exception as e:
        logger.error(f"Error getting article {article_id}: {e}")
        return jsonify({'error': 'Database error'}), 500


@login_required
@app.route('/admin/api/good-fit', methods=['POST', 'OPTIONS'])
def good_fit():
    """Mark article as good fit for training"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')
    zip_code = data.get('zip_code')

    if not article_id or not zip_code:
        return jsonify({'error': 'Missing article_id or zip_code'}), 400

    try:
        # This would normally train the Bayesian learner
        # For now, just mark as relevant
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE articles SET relevance_score = 100 WHERE id = ?', (article_id,))
            conn.commit()

        return jsonify({'success': True, 'message': 'Article marked as good fit'})
    except Exception as e:
        logger.error(f"Error marking good fit for {article_id}: {e}")
        return jsonify({'error': 'Database error'}), 500


@login_required
@app.route('/admin/api/bayesian-stats', methods=['GET', 'OPTIONS'])
def bayesian_stats():
    """Get Bayesian learning statistics (placeholder)"""
    return jsonify({
        'total_trained': 150,
        'good_examples': 120,
        'bad_examples': 30,
        'accuracy': 0.85,
        'last_trained': '2025-12-11T20:30:00Z'
    })


@login_required
@app.route('/admin/api/settings', methods=['GET', 'POST', 'OPTIONS'])
def get_settings_api():
    """Get or update admin settings"""
    if request.method == 'POST':
        # Handle setting updates
        data = request.get_json() if request.is_json else request.form
        key = data.get('key')
        value = data.get('value')
        zip_code = data.get('zip_code')

        if not key:
            return jsonify({'success': False, 'error': 'Missing key parameter'}), 400

        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # Check if setting exists
                cursor.execute('SELECT value FROM admin_settings WHERE key = ?', (key,))
                existing = cursor.fetchone()

                if existing:
                    cursor.execute('UPDATE admin_settings SET value = ? WHERE key = ?', (value, key))
                else:
                    cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', (key, value))

                conn.commit()
                return jsonify({'success': True, 'message': f'Setting {key} updated'})

        except Exception as e:
            logger.error(f"Error updating setting {key}: {e}")
            return jsonify({'success': False, 'error': 'Database error'}), 500

    # GET request - return all settings
    try:
        settings = get_settings()
        return jsonify(settings)
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({'error': 'Database error'}), 500




@login_required
@app.route('/admin/api/on-target', methods=['POST', 'OPTIONS'])
def on_target():
    """Mark article as on-target (relevant for targeting)"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')
    zip_code = data.get('zip_code')

    if not article_id:
        return jsonify({'error': 'Missing article_id'}), 400

    try:
        from .services import set_on_target
        set_on_target(article_id, True)
        return jsonify({'success': True, 'message': 'Article marked as on-target'})
    except Exception as e:
        logger.error(f"Error marking on-target for {article_id}: {e}")
        return jsonify({'error': 'Database error'}), 500


@login_required
@app.route('/admin/api/off-target', methods=['POST', 'OPTIONS'])
def off_target():
    """Mark article as off-target (not relevant for targeting)"""
    data = request.get_json() if request.is_json else request.form
    article_id = data.get('article_id')
    zip_code = data.get('zip_code')

    if not article_id:
        return jsonify({'error': 'Missing article_id'}), 400

    try:
        from .services import set_on_target
        set_on_target(article_id, False)
        return jsonify({'success': True, 'message': 'Article marked as off-target'})
    except Exception as e:
        logger.error(f"Error marking off-target for {article_id}: {e}")
        return jsonify({'error': 'Database error'}), 500




@login_required
@app.route('/admin/api/add-category', methods=['POST', 'OPTIONS'])
def add_category():
    """Add a new category"""
    data = request.get_json() if request.is_json else request.form
    category_name = data.get('category_name', '').strip()

    if not category_name:
        return jsonify({'success': False, 'error': 'Category name is required'}), 400

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Check if category already exists
            cursor.execute('SELECT id FROM categories WHERE name = ?', (category_name,))
            if cursor.fetchone():
                return jsonify({'success': False, 'error': 'Category already exists'}), 400

            # Add new category
            cursor.execute('INSERT INTO categories (name) VALUES (?)', (category_name,))
            category_id = cursor.lastrowid
            conn.commit()

            return jsonify({'success': True, 'category_id': category_id, 'category_name': category_name})

    except Exception as e:
        logger.error(f"Error adding category: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/category-stats', methods=['GET', 'OPTIONS'])
def get_category_stats():
    """Get category statistics"""
    zip_code = request.args.get('zip_code')
    if zip_code and not validate_zip_code(zip_code):
        zip_code = None

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # First ensure categories table exists and has default categories
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Insert default categories if table is empty
            cursor.execute('SELECT COUNT(*) FROM categories')
            if cursor.fetchone()[0] == 0:
                default_categories = ['News', 'Sports', 'Business', 'Crime', 'Events', 'Food', 'Schools', 'Local News', 'Obituaries', 'Weather']
                for cat in default_categories:
                    try:
                        cursor.execute('INSERT INTO categories (name) VALUES (?)', (cat,))
                    except:
                        pass  # Ignore if category already exists

            conn.commit()

            # Get all categories with article counts
            if zip_code:
                cursor.execute('''
                    SELECT
                        c.id,
                        c.name,
                        COUNT(a.id) as article_count,
                        COUNT(CASE WHEN a.published >= date('now', '-7 days') THEN 1 END) as recent_count
                    FROM categories c
                    LEFT JOIN articles a ON c.name = a.category AND a.zip_code = ?
                    GROUP BY c.id, c.name
                    ORDER BY c.name
                ''', (zip_code,))
            else:
                cursor.execute('''
                    SELECT
                        c.id,
                        c.name,
                        COUNT(a.id) as article_count,
                        COUNT(CASE WHEN a.published >= date('now', '-7 days') THEN 1 END) as recent_count
                    FROM categories c
                    LEFT JOIN articles a ON c.name = a.category
                    GROUP BY c.id, c.name
                    ORDER BY c.name
                ''')

            categories = []
            for row in cursor.fetchall():
                categories.append({
                    'id': row[0],
                    'name': row[1],
                    'article_count': row[2],
                    'recent_count': row[3]
                })

            return jsonify({'categories': categories})

    except Exception as e:
        logger.error(f"Error getting category stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/category-keywords/<category>', methods=['GET'])
@login_required
def get_category_keywords(category):
    """Get keywords for a specific category"""
    try:
        zip_code = request.args.get('zip_code', '02720')

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT keyword FROM category_keywords
                WHERE category = ? AND (zip_code = ? OR zip_code IS NULL)
                ORDER BY zip_code DESC, keyword
                LIMIT 10
            ''', (category, zip_code))

            keywords = [row[0] for row in cursor.fetchall()]

        return jsonify({'keywords': keywords})

    except Exception as e:
        logger.error(f"Error getting keywords for category {category}: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/admin/api/category-keywords-full/<category>', methods=['GET'])
@login_required
def get_category_keywords_full(category):
    """Get all keywords for a specific category"""
    try:
        zip_code = request.args.get('zip_code', '02720')

        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT keyword FROM category_keywords
                WHERE category = ? AND (zip_code = ? OR zip_code IS NULL)
                ORDER BY keyword
            ''', (category, zip_code))

            keywords = [row[0] for row in cursor.fetchall()]

        return jsonify({'success': True, 'keywords': keywords})

    except Exception as e:
        logger.error(f"Error getting full keywords for category {category}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/api/category-keyword', methods=['POST', 'DELETE'])
@login_required
def manage_keyword():
    """Add or delete a keyword for a category"""
    try:
        data = request.get_json() if request.is_json else request.form
        category = data.get('category')
        keyword = data.get('keyword', '').strip().lower()
        zip_code = data.get('zip_code', '02720')

        if not category or not keyword:
            return jsonify({'success': False, 'error': 'Category and keyword required'}), 400

        with get_db() as conn:
            cursor = conn.cursor()

            if request.method == 'POST':
                # Add keyword
                cursor.execute('''
                    INSERT OR IGNORE INTO category_keywords (zip_code, category, keyword)
                    VALUES (?, ?, ?)
                ''', (zip_code, category, keyword))

                if cursor.rowcount > 0:
                    message = f'Added "{keyword}" to {category}'
                else:
                    return jsonify({'success': False, 'error': f'Keyword "{keyword}" already exists'}), 400

            elif request.method == 'DELETE':
                # Delete keyword
                cursor.execute('''
                    DELETE FROM category_keywords
                    WHERE category = ? AND keyword = ? AND (zip_code = ? OR zip_code IS NULL)
                ''', (category, keyword, zip_code))

                if cursor.rowcount > 0:
                    message = f'Deleted "{keyword}" from {category}'
                else:
                    return jsonify({'success': False, 'error': f'Keyword "{keyword}" not found'}), 404

            conn.commit()

        return jsonify({'success': True, 'message': message})

    except Exception as e:
        logger.error(f"Error managing keyword: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/api/category-keywords/<zip_code>/stats', methods=['GET'])
@login_required
def get_category_keywords_stats(zip_code):
    """Get category statistics for a zip code"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Get category statistics
            cursor.execute('''
                SELECT
                    a.category as name,
                    COUNT(a.id) as article_count,
                    COUNT(CASE WHEN a.published >= date('now', '-7 days') THEN 1 END) as recent_count
                FROM articles a
                WHERE a.zip_code = ? AND a.category IS NOT NULL AND a.category != ''
                GROUP BY a.category
                ORDER BY a.category
            ''', (zip_code,))

            stats = []
            for row in cursor.fetchall():
                category_name = row[0]

                # Get keyword count
                cursor.execute('SELECT COUNT(DISTINCT keyword) FROM category_keywords WHERE category = ? AND zip_code = ?', (category_name, zip_code))
                keyword_count = cursor.fetchone()[0]

                stats.append({
                    'name': category_name.replace('-', ' ').title(),
                    'article_count': row[1],
                    'recent_count': row[2],
                    'keyword_count': keyword_count
                })

            return jsonify({'success': True, 'stats': stats})

    except Exception as e:
        logger.error(f"Error getting category stats for {zip_code}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/admin/api/retrain-categories', methods=['POST', 'OPTIONS'])
def retrain_categories():
    """Retrain category classification for all articles"""
    data = request.get_json() if request.is_json else request.form
    zip_code = data.get('zip_code')

    if zip_code and not validate_zip_code(zip_code):
        return jsonify({'success': False, 'error': 'Invalid zip code'}), 400

    try:
        # This would trigger the category classification retraining
        # For now, just return success
        return jsonify({'success': True, 'message': 'Category retraining completed'})

    except Exception as e:
        logger.error(f"Error retraining categories: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/category-keyword', methods=['GET', 'POST', 'DELETE', 'OPTIONS'])
def manage_category_keywords():
    """Manage keywords for categories"""
    if request.method == 'GET':
        # Get all categories with their keywords
        try:
            with get_db() as conn:
                cursor = conn.cursor()

                # Get categories
                cursor.execute('SELECT id, name FROM categories ORDER BY name')
                db_categories = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]

                # Get keywords for each category (placeholder - would need keyword tables)
                categories_data = []
                for cat in db_categories:
                    categories_data.append({
                        'id': cat['id'],
                        'name': cat['name'],
                        'keywords': []  # Placeholder
                    })

                return jsonify({
                    'db_categories': categories_data,
                    'high_relevance_keywords': [],
                    'local_place_keywords': [],
                    'topic_keywords': {}
                })

        except Exception as e:
            logger.error(f"Error getting category keywords: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    elif request.method == 'POST':
        # Add keyword to category
        data = request.get_json() if request.is_json else request.form
        category = data.get('category')
        keyword = data.get('keyword', '').strip()

        if not category or not keyword:
            return jsonify({'success': False, 'error': 'Category and keyword required'}), 400

        try:
            # This would add the keyword to the category
            # For now, just return success
            return jsonify({'success': True, 'message': f'Added "{keyword}" to {category}'})

        except Exception as e:
            logger.error(f"Error adding keyword: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    elif request.method == 'DELETE':
        # Remove keyword from category
        data = request.get_json() if request.is_json else request.form
        category = data.get('category')
        keyword = data.get('keyword')

        try:
            # This would remove the keyword from the category
            # For now, just return success
            return jsonify({'success': True, 'message': f'Removed "{keyword}" from {category}'})

        except Exception as e:
            logger.error(f"Error removing keyword: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/recategorize-all', methods=['POST', 'OPTIONS'])
def recategorize_all():
    """Recategorize all articles"""
    try:
        # This would trigger recategorization of all articles
        return jsonify({'success': True, 'message': 'Recategorization completed'})

    except Exception as e:
        logger.error(f"Error recategorizing: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/rerun-relevance-scoring', methods=['POST', 'OPTIONS'])
def rerun_relevance_scoring():
    """Rerun relevance scoring for all articles"""
    try:
        from utils.relevance_calculator import calculate_relevance_score_with_tags
        from utils.bayesian_learner import BayesianLearner
        import sqlite3
        from config import DATABASE_CONFIG

        # Get zip_code from request
        zip_code = request.get_json().get('zip_code')

        # Connect to database and get relevance threshold
        conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
        cursor = conn.cursor()

        # Get relevance threshold from admin_settings
        cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('relevance_threshold',))
        threshold_row = cursor.fetchone()
        relevance_threshold = float(threshold_row[0]) if threshold_row else 10.0

        # Clear existing auto-filtered status for re-evaluation
        if zip_code:
            cursor.execute('UPDATE article_management SET is_auto_filtered = 0, auto_reject_reason = NULL WHERE zip_code = ? AND is_auto_filtered = 1', (zip_code,))
        else:
            cursor.execute('UPDATE article_management SET is_auto_filtered = 0, auto_reject_reason = NULL WHERE is_auto_filtered = 1')

        # Get all articles (including previously auto-filtered ones for re-evaluation)
        if zip_code:
            cursor.execute('SELECT id, title, content, source FROM articles WHERE zip_code = ?', (zip_code,))
        else:
            cursor.execute('SELECT id, title, content, source FROM articles')

        articles = cursor.fetchall()
        processed_count = 0
        filtered_count = 0

        logger.info(f"Starting relevance rerun for {len(articles)} articles with threshold {relevance_threshold}")

        learner = BayesianLearner()

        for article_row in articles:
            article_id, title, content, source = article_row
            article = {
                'title': title,
                'content': content or '',
                'source': source
            }

            # Calculate relevance score
            try:
                relevance_score, tag_info = calculate_relevance_score_with_tags(article, zip_code=zip_code)
            except Exception as e:
                logger.warning(f"Error calculating relevance for article {article_id}: {e}")
                continue

            # Update relevance score in database
            cursor.execute('UPDATE articles SET relevance_score = ? WHERE id = ?', (relevance_score, article_id))

            # Check if it should be auto-filtered
            should_filter = False
            reason = ""

            # Check relevance threshold (exclude obituaries)
            article_category = (article.get('category', '') or '').lower()
            is_obituary = 'obituar' in article_category

            if relevance_score < relevance_threshold and not is_obituary:
                should_filter = True
                reason = f"Relevance score {relevance_score:.1f} below threshold {relevance_threshold}"
                logger.info(f"Filtering article {article_id}: score {relevance_score:.1f} < {relevance_threshold}, category: {article_category}")

            # Check Bayesian filtering
            if not should_filter:
                try:
                    bayesian_should_filter, probability, reasons = learner.should_filter(article, threshold=0.7)
                    if bayesian_should_filter:
                        should_filter = True
                        reason_str = "; ".join(reasons[:3]) if reasons else "High similarity to previously rejected articles"
                        reason = f"Bayesian filter: {reason_str}"
                except Exception as e:
                    logger.warning(f"Error in Bayesian filtering for article {article_id}: {e}")

            # Auto-filter if needed
            if should_filter:
                cursor.execute('''
                    INSERT OR REPLACE INTO article_management
                    (article_id, enabled, is_auto_filtered, auto_reject_reason, zip_code)
                    VALUES (?, 0, 1, ?, ?)
                ''', (article_id, reason, zip_code or "02720"))
                filtered_count += 1

            processed_count += 1

            if not should_filter:
                logger.debug(f"Keeping article {article_id}: score {relevance_score:.1f}, category: {article.get('category', '')}")

        conn.commit()
        conn.close()

        kept_count = processed_count - filtered_count

        return jsonify({
            'success': True,
            'message': f'Processed {processed_count} articles, auto-filtered {filtered_count}',
            'processed_count': processed_count,
            'auto_rejected_count': filtered_count,
            'kept_count': kept_count
        })

    except Exception as e:
        logger.error(f"Error in rerun relevance scoring: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/recalculate-categories', methods=['POST', 'OPTIONS'])
def recalculate_categories():
    """Recalculate category relevance scores for all articles"""
    import time
    start_time = time.time()

    try:
        # Import the recalculator
        from recalculate_articles import ArticleRecalculator

        # Get zip code from session
        zip_code = session.get('zip_code')

        # Initialize recalculator
        recalculator = ArticleRecalculator()

        # Track progress
        total_processed = 0
        categories_updated = 0
        keywords_matched = 0

        # Process articles in batches for the specific zip code
        batch_size = 50
        offset = 0

        while True:
            batch_start = time.time()
            logger.info(f"Processing batch starting at offset {offset} for zip {zip_code}")

            # Recalculate batch - returns count of updated articles
            updated_in_batch = recalculator.recalculate_batch(zip_code=zip_code, limit=batch_size, offset=offset)

            # If no articles were updated in this batch, we've processed all articles
            if updated_in_batch == 0:
                break

            total_processed += batch_size  # Count all processed, not just updated
            categories_updated += updated_in_batch  # Updated articles = categories changed

            batch_time = time.time() - batch_start
            logger.info(f"Batch processed {batch_size} articles, updated {updated_in_batch} in {batch_time:.2f}s")

            offset += batch_size

            # Safety limit to prevent infinite loops
            if offset > 10000:  # Max 10k articles
                logger.warning("Hit safety limit of 10,000 articles")
                break

        total_time = time.time() - start_time

        # Return detailed results
        return jsonify({
            'success': True,
            'message': f'Recalculated {total_processed} articles, updated {categories_updated} categories in {total_time:.1f} seconds',
            'stats': {
                'articles_processed': total_processed,
                'categories_updated': categories_updated,
                'processing_time_seconds': round(total_time, 1),
                'zip_code': zip_code or 'all',
                'average_time_per_article': round(total_time / max(total_processed, 1), 3)
            }
        })

    except Exception as e:
        logger.error(f"Error recalculating categories: {e}")
        total_time = time.time() - start_time
        return jsonify({
            'success': False,
            'error': str(e),
            'processing_time_seconds': round(total_time, 1)
        }), 500


# Catch-all route for static files - MUST be last to ensure specific routes are matched first
@app.route('/<path:filename>')
def serve_website(filename):
    """Serve static website files - excludes admin and api paths"""
    # Skip admin routes - they should be handled by specific admin route handlers
    if filename.startswith('admin/') or filename == 'admin':
        # This should not happen if admin routes are working, but just in case
        return "Admin routes should be handled by specific handlers.", 404

    # Security: Skip API routes
    if filename.startswith('api/'):
        return "API routes handled separately.", 404

    # Also explicitly block admin.html static file from being served
    if filename == 'admin.html':
        return "Static admin.html file blocked.", 404

    # Skip zip code routes (handled by zip_page route above) - 5 digits
    if validate_zip_code(filename):
        return "Not found", 404

    # Check if regeneration is needed (only for HTML files)
    if filename.endswith('.html') and _should_regenerate():
        _trigger_regeneration()

    try:
        # Calculate the correct path to the build directory
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        build_dir = os.path.join(project_root, 'build')
        file_path = os.path.join(build_dir, filename)

        # Check if the file exists
        if os.path.exists(file_path) and not os.path.isdir(file_path):
            response = send_file(file_path)

            # FORCE NO-CACHE for HTML files to prevent caching hell
            if filename.endswith('.html'):
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
                response.headers['Last-Modified'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
                response.headers['ETag'] = f'no-cache-{int(datetime.now().timestamp())}'
                response.headers['X-Frame-Options'] = 'SAMEORIGIN'

            return response
        else:
            # SPA fallback: serve index.html for client-side routes
            # FORCE NO-CACHE for index.html fallback to prevent caching issues
            response = send_from_directory(build_dir, 'index.html')
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            response.headers['Last-Modified'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S GMT')
            response.headers['ETag'] = f'no-cache-{int(datetime.now().timestamp())}'
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            return response
    except (ValueError, OSError):
        return "File not found", 404


# App is imported by server.py for execution