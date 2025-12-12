"""
Admin routes - Flask route handlers for admin interface
"""
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, send_file
from functools import wraps
import os
import logging
import threading
import subprocess
import sys
import time
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
    """Add CORS headers and disable caching for admin pages"""
    # Security: Only allow specific origins instead of wildcard
    ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')
    origin = request.headers.get('Origin')
    if origin and origin in ALLOWED_ORIGINS:
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
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
        # For API endpoints, return JSON error instead of redirect
        path = request.path
        is_api = path.startswith('/admin/api') or '/api/' in path
        if is_api:
            if 'logged_in' not in session:
                return jsonify({'success': False, 'error': 'Not authenticated'}), 401
        elif 'logged_in' not in session:
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
    """Serve main website index - redirects to default zip code (02720) which resolves to city directory"""
    logger.info("Index route called")
    zip_code = request.args.get('zip_code')
    if zip_code and validate_zip_code(zip_code):
        logger.info(f"Redirecting to zip code: {zip_code}")
        return redirect(f'/{zip_code}')

    # Default to 02720 (Fall River) which resolves to city_fall-river-ma
    default_zip = '02720'
    logger.info(f"Redirecting to default zip code: {default_zip}")
    return redirect(f'/{default_zip}')


@app.route('/category/<path:category_slug>')
def category_page(category_slug):
    """Serve category page"""
    # Strip .html extension if present (frontend links include .html)
    if category_slug.endswith('.html'):
        category_slug = category_slug[:-5]

    # Calculate the correct path to the build directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    category_path = os.path.join(project_root, 'build', 'category', f'{category_slug}.html')

    try:
        return send_file(category_path)
    except (ValueError, OSError) as e:
        logger.error(f"Error serving category page {category_slug}: {e}")
        return "Category page not found", 404


@app.route('/<zip_code>')
def zip_page(zip_code):
    """Serve zip-specific index page - resolves to city-based directory"""
    if not validate_zip_code(zip_code):
        return "Invalid zip code", 404
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # Try city-based directory first (preferred)
        if get_city_state_for_zip:
            city_state = get_city_state_for_zip(zip_code)
            if city_state:
                # Convert "Fall River, MA" to "fall-river-ma"
                city_slug = city_state.lower().replace(", ", "-").replace(" ", "-")
                city_index_path = os.path.join(project_root, 'build', f'city_{city_slug}', 'index.html')
                if os.path.exists(city_index_path):
                    return send_file(city_index_path)
        
        # Fallback to zip-based directory
        zip_index_path = os.path.join(project_root, 'build', f'zip_{zip_code}', 'index.html')
        if os.path.exists(zip_index_path):
            return send_file(zip_index_path)
        
        return "Zip code not found", 404
    except (ValueError, OSError) as e:
        logger.error(f"Error serving zip page {zip_code}: {e}")
        return "Zip code not found", 404


@app.route('/<zip_code>/category/<path:category_slug>')
def zip_category_page(zip_code, category_slug):
    """Serve zip-specific category page - resolves to city-based directory"""
    if not validate_zip_code(zip_code):
        return "Invalid zip code", 404

    # Strip .html extension if present
    if category_slug.endswith('.html'):
        category_slug = category_slug[:-5]

    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # Try city-based directory first (preferred)
        if get_city_state_for_zip:
            city_state = get_city_state_for_zip(zip_code)
            if city_state:
                # Convert "Fall River, MA" to "fall-river-ma"
                city_slug = city_state.lower().replace(", ", "-").replace(" ", "-")
                city_category_path = os.path.join(project_root, 'build', f'city_{city_slug}', 'category', f'{category_slug}.html')
                if os.path.exists(city_category_path):
                    return send_file(city_category_path)
        
        # Fallback to zip-based directory
        zip_category_path = os.path.join(project_root, 'build', f'zip_{zip_code}', 'category', f'{category_slug}.html')
        if os.path.exists(zip_category_path):
            return send_file(zip_category_path)
        
        return "Page not found", 404
    except (ValueError, OSError) as e:
        logger.error(f"Error serving zip category page {zip_code}/{category_slug}: {e}")
        return "Page not found", 404


@app.route('/css/<path:filename>')
def serve_css(filename):
    """Serve CSS files"""
    # Calculate the correct path to the build directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    build_path = os.path.join(project_root, 'build')
    safe_filename = safe_path(Path(os.path.join(build_path, 'css')), filename)
    if not safe_filename.exists():
        return "File not found", 404
    return send_from_directory(str(safe_filename.parent), safe_filename.name)


@app.route('/js/<path:filename>')
def serve_js(filename):
    """Serve JavaScript files"""
    # Calculate the correct path to the build directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    build_path = os.path.join(project_root, 'build')
    safe_filename = safe_path(Path(os.path.join(build_path, 'js')), filename)
    if not safe_filename.exists():
        return "File not found", 404
    return send_from_directory(str(safe_filename.parent), safe_filename.name)


@app.route('/images/<path:filename>')
def serve_images(filename):
    """Serve image files"""
    # Calculate the correct path to the build directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    build_path = os.path.join(project_root, 'build')
    safe_filename = safe_path(Path(os.path.join(build_path, 'images')), filename)
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


@app.route('/admin', strict_slashes=False)
@login_required
def admin_redirect():
    """Redirect /admin to blueprint route /admin/"""
    return redirect('/admin/', code=301)


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
def admin_main_dashboard():
    """Main admin dashboard"""
    try:
        zip_code = request.args.get('zip_code')
        tab = request.args.get('tab', 'articles')
        page = int(request.args.get('page', 1))
        category_filter = request.args.get('category', 'all')
        source_filter = request.args.get('source', '')
        search_filter = request.args.get('search', '').strip()
        date_range_filter = request.args.get('date_range', '')

        # Validate inputs
        if zip_code and not validate_zip_code(zip_code):
            zip_code = None

        # Get data for dashboard
        articles, total_count = get_articles(
            zip_code=zip_code,
            limit=50,
            offset=(page - 1) * 50,
            category=category_filter if category_filter != 'all' else None,
            search=search_filter
        )

        rejected_articles = get_rejected_articles(zip_code=zip_code)
        sources_config = get_sources()
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

        # Calculate pagination
        total_pages = (total_count + 49) // 50  # Ceiling division
        has_next = page < total_pages
        has_prev = page > 1

        # Get rejected article features for display
        rejected_features = []
        for article in rejected_articles[:5]:  # Show only first 5
            features = []
            if hasattr(article, 'title') and article.get('title'):
                # Extract potential rejection features from title
                title_lower = article['title'].lower()
                if any(word in title_lower for word in ['meeting', 'agenda', 'minutes']):
                    features.append('meeting')
                if any(word in title_lower for word in ['obituary', 'died', 'passed']):
                    features.append('obituary')
                if any(word in title_lower for word in ['weather', 'forecast', 'temperature']):
                    features.append('weather')
            rejected_features.append(features)

        logger.info(f"About to get category stats for zip_code={zip_code}")
        # Get category stats for the categories tab
        logger.info(f"Getting category stats for zip_code={zip_code}")
        category_stats = []
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                logger.info("Got database connection")

                # First ensure categories table exists and has default categories
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS categories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                logger.info("Ensured categories table exists")

                # Insert default categories if table is empty
                cursor.execute('SELECT COUNT(*) FROM categories')
                count = cursor.fetchone()[0]
                logger.info(f"Found {count} existing categories")
                if count == 0:
                    default_categories = ['News', 'Sports', 'Business', 'Crime', 'Events', 'Food', 'Schools', 'Local News', 'Obituaries', 'Weather']
                    for cat in default_categories:
                        try:
                            cursor.execute('INSERT INTO categories (name) VALUES (?)', (cat,))
                            logger.info(f"Inserted category: {cat}")
                        except Exception as e:
                            logger.info(f"Category {cat} already exists: {e}")

                conn.commit()
                logger.info("Committed category insertions")

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

                for row in cursor.fetchall():
                    category_stats.append({
                        'id': row[0],
                        'name': row[1],
                        'article_count': row[2],
                        'recent_count': row[3]
                    })

            logger.info(f"Found {len(category_stats)} categories for zip_code={zip_code}")

        except Exception as e:
            logger.error(f"Error getting category stats: {e}")
            category_stats = []

        # Cache busting
        cache_bust = datetime.now().strftime('%Y%m%d%H%M%S')

        # Relevance config (placeholder for now)
        relevance_config = {}

        # Enabled zips (placeholder for now)
        enabled_zips = ['02720', '02721', '02722', '02723', '02724', '02725', '02726', '02842']

        return render_template('admin/main_dashboard.html',
            articles=articles,
            settings=settings,
            sources=sources_config,
            version=VERSION,
            last_regeneration=last_regeneration,
            latest_ingestion=latest_ingestion,
            stats=stats,
            rejected_features=rejected_features,
            active_tab=tab,
            cache_bust=cache_bust,
            relevance_config=relevance_config,
            zip_code=zip_code,
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
        logger.error(f"Error in admin_zip_dashboard for {zip_code}: {e}")
        return f"Admin dashboard error for {zip_code}: {str(e)}", 500


@login_required
@app.route('/admin/<zip_code>', methods=['GET'])
def admin_zip_dashboard(zip_code):
    """Admin dashboard for specific zip code"""
    logger.info(f"admin_zip_dashboard called with zip_code={zip_code}")
    try:
        logger.info(f"Starting admin_zip_dashboard for {zip_code}")
        if not validate_zip_code(zip_code):
            return "Invalid zip code", 404

        # Set this zip code in session for convenience
        session['zip_code'] = zip_code

        tab = request.args.get('tab', 'articles')
        page = int(request.args.get('page', 1))
        category_filter = request.args.get('category', 'all')
        source_filter = request.args.get('source', '')
        search_filter = request.args.get('search', '').strip()
        date_range_filter = request.args.get('date_range', '')

        # Get data for dashboard filtered to this zip code
        logger.info(f"Calling get_articles for zip_code={zip_code}")
        articles, total_count = get_articles(
            zip_code=zip_code,
            limit=50,
            offset=(page - 1) * 50,
            category=category_filter if category_filter != 'all' else None,
            search=search_filter
        )
        logger.info(f"get_articles returned {len(articles)} articles")

        rejected_articles = get_rejected_articles(zip_code=zip_code)
        logger.info(f"Got {len(rejected_articles)} rejected articles")
        logger.info("Calling get_sources")
        sources_config = get_sources()
        logger.info("Calling get_stats")
        stats = get_stats(zip_code=zip_code)
        logger.info("Calling get_settings")
        settings = get_settings()
        logger.info("All data calls completed")
        logger.info("About to get additional metadata")

        # Get additional metadata
        logger.info("Opening database connection for metadata")
        with get_db() as conn:
            cursor = conn.cursor()
            logger.info("Got database cursor for metadata")

            # Last regeneration time
            logger.info("Querying last regeneration time")
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            last_regeneration = cursor.fetchone()
            last_regeneration = last_regeneration[0] if last_regeneration else None
            logger.info(f"Last regeneration: {last_regeneration}")

            # Latest ingestion time
            logger.info("Querying latest ingestion time")
            cursor.execute('SELECT MAX(ingested_at) FROM articles')
            latest_ingestion = cursor.fetchone()
            latest_ingestion = latest_ingestion[0] if latest_ingestion and latest_ingestion[0] else None
            logger.info(f"Latest ingestion: {latest_ingestion}")

            logger.info("Metadata queries completed")

        logger.info("About to calculate pagination")
        # Calculate pagination
        total_pages = (total_count + 49) // 50  # Ceiling division
        has_next = page < total_pages
        has_prev = page > 1

        # Get rejected article features for display
        rejected_features = []
        for article in rejected_articles[:5]:  # Show only first 5
            features = []
            if hasattr(article, 'title') and article.get('title'):
                # Extract potential rejection features from title
                title_lower = article['title'].lower()
                if any(word in title_lower for word in ['meeting', 'agenda', 'minutes']):
                    features.append('meeting')
                if any(word in title_lower for word in ['obituary', 'died', 'passed']):
                    features.append('obituary')
                if len(features) > 0:
                    rejected_features.append({'title': article['title'], 'features': features})

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
        cache_bust = str(int(time.time()))

        # Relevance configuration
        relevance_config = WEBSITE_CONFIG.get('relevance', {})

        enabled_zips = ['02720', '02721', '02722', '02723', '02724', '02725', '02726', '02842']

        return render_template('admin/main_dashboard.html',
            zip_code=zip_code,
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
        logger.error(f"Error in admin_zip_dashboard for {zip_code}: {e}")
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
@app.route('/admin/api/get-rejected-articles', methods=['GET', 'OPTIONS'])
def get_rejected_articles_route():
    """Get rejected articles"""
    zip_code = request.args.get('zip_code')
    if zip_code and not validate_zip_code(zip_code):
        zip_code = None

    articles = get_rejected_articles(zip_code=zip_code)
    return jsonify({'articles': articles})


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
@app.route('/admin/api/settings', methods=['GET', 'OPTIONS'])
def get_settings_api():
    """Get admin settings"""
    try:
        settings = get_settings()
        return jsonify(settings)
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({'error': 'Database error'}), 500


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
@app.route('/admin/api/get-all-trash', methods=['GET', 'OPTIONS'])
def get_all_trash():
    """Get all trashed articles"""
    zip_code = request.args.get('zip_code')
    if zip_code and not validate_zip_code(zip_code):
        zip_code = None

    with get_db() as conn:
        cursor = conn.cursor()

        query = '''
            SELECT a.*, COALESCE(am.is_rejected, 0) as is_rejected,
                   COALESCE(am.is_featured, 0) as is_featured
            FROM articles a
            LEFT JOIN article_management am ON a.id = am.article_id
            WHERE a.trashed = 1
        '''
        params = []

        if zip_code:
            query += ' AND a.zip_code = ?'
            params.append(zip_code)

        query += ' ORDER BY a.id DESC'

        cursor.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        articles = [dict(zip(columns, row)) for row in cursor.fetchall()]

        return jsonify({'articles': articles})


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
@app.route('/admin/api/recalculate-categories', methods=['POST', 'OPTIONS'])
def recalculate_categories():
    """Recalculate category relevance scores"""
    try:
        # This would recalculate relevance scores
        return jsonify({'success': True, 'message': 'Recalculation completed'})

    except Exception as e:
        logger.error(f"Error recalculating: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
            return send_file(file_path)
        else:
            # SPA fallback: serve index.html for client-side routes
            # This fixes routes like /obituaries, /news, /events, etc.
            return send_from_directory(build_dir, 'index.html')
    except (ValueError, OSError):
        return "File not found", 404


# App is imported by server.py for execution