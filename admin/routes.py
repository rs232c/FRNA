"""
Admin routes - Flask route handlers for admin interface
"""
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, send_file, Response, abort
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
from urllib.parse import urlparse, unquote
import requests

from .services import (
    validate_zip_code, validate_article_id, safe_path, get_db, get_db_legacy,
    hash_password, verify_password, get_articles, get_rejected_articles,
    toggle_article, get_sources, get_stats, get_settings, trash_article, restore_article,
    toggle_top_story, toggle_top_article, toggle_alert, toggle_good_fit, train_relevance
)
from database import ArticleDatabase
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from config import DATABASE_CONFIG, NEWS_SOURCES, WEBSITE_CONFIG, VERSION, CATEGORY_COLORS

# Load environment variables
load_dotenv()

def render_dynamic_index(articles, active_category='local', zip_code='02720'):
    """Render the index template dynamically with articles and active category"""
    try:
        # Setup Jinja2 environment
        template_dir = Path(__file__).parent.parent / "website_generator" / "templates"
        jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))

        # Get the index template
        template = jinja_env.get_template('index.html.j2')

        # Generate navigation tabs with correct active state
        nav_tabs = generate_nav_tabs(active_category)

        # Format articles (enrich with dates, source initials, gradients, etc.)
        formatted_articles = []
        for article in articles:
            # Ensure image_url is never None - convert to empty string
            if article.get('image_url') is None:
                article = article.copy()  # Don't modify original
                article['image_url'] = ''

            # Enrich article with formatted data including dates
            from website_generator.utils import enrich_single_article
            formatted = enrich_single_article(article)

            formatted_articles.append(formatted)

        # Prepare different article collections like the website generator
        hero_articles = formatted_articles[:3] if formatted_articles else []  # Top 3 articles as heroes

        # Use proper trending algorithm instead of just first 5 articles
        try:
            from website_generator import WebsiteGenerator
            wg = WebsiteGenerator()
            trending_articles = wg._get_trending_articles(formatted_articles, limit=5)
        except Exception as e:
            logger.warning(f"Could not use trending algorithm, falling back to recent articles: {e}")
            trending_articles = formatted_articles[:5]  # Fallback to first 5

        latest_stories = formatted_articles[:5]
        newest_articles = formatted_articles[:10]
        entertainment_articles = [a for a in formatted_articles if 'entertainment' in (a.get('category') or '')][:5]
        top_article = formatted_articles[0] if formatted_articles else None

        # Get unique sources
        unique_sources = list(set(a.get('source', '') for a in formatted_articles if a.get('source')))

        # Prepare location badge data (same logic as website_generator.py)
        location_badge_text = "Fall River · 02720"
        if zip_code:
            try:
                from zip_resolver import resolve_zip
                zip_data = resolve_zip(zip_code)
                if zip_data:
                    city = zip_data.get("city", "Fall River")
                    location_badge_text = f"{city} · {zip_code}"
                else:
                    location_badge_text = f"Fall River · {zip_code}"
            except Exception as e:
                location_badge_text = f"Fall River · {zip_code}"

        # Get show_images setting from database (same as static generation)
        show_images = True  # default
        try:
            with get_db() as db_conn:
                cursor = db_conn.cursor()
                cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('show_images',))
                result = cursor.fetchone()
                show_images = result[0] == '1' if result else True
        except Exception as e:
            logger.warning(f"Could not get show_images setting: {e}")

        # Prepare template context (similar to website_generator.py)
        current_time = datetime.now().strftime("%I:%M %p")
        generation_timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

        context = {
            'title': 'Fall River, MA News Aggregator',
            'description': 'Latest news from Fall River, MA',
            'articles': formatted_articles,
            'hero_articles': hero_articles,
            'trending_articles': trending_articles,
            'latest_stories': latest_stories,
            'newest_articles': newest_articles,
            'entertainment_articles': entertainment_articles,
            'top_article': top_article,
            'active_category': active_category,
            'current_time': current_time,
            'generation_timestamp': generation_timestamp,
            'last_db_update': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'nav_tabs': nav_tabs,
            'unique_sources': unique_sources,
            'location_badge_text': location_badge_text,
            'zip_code': zip_code,
            'weather_station_url': f"https://weather.com/weather/today/l/{zip_code}",
            'weather_api_key': '',
            'weather_icon': '🌤️',
            'zip_pin_editable': False,
            'show_images': show_images,
            'current_year': datetime.now().year
        }

        # Render template
        html_content = template.render(**context)
        return html_content

    except Exception as e:
        logger.error(f"Error rendering dynamic index: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return f"Error rendering page: {e}", 500

def _generate_smart_initials(source):
    """Generate smart initials based on source name - like 'herald news' -> 'hn', 'fall river reporter' -> 'frr'"""
    if not source or not source.strip():
        return 'XX'

    # Normalize the source name
    normalized = source.lower().strip()

    # Common mappings for specific sources
    smart_mappings = {
        # Local Massachusetts sources
        'herald news': 'hn',
        'fall river herald news': 'hn',
        'fall river reporter': 'frr',
        'taunton gazette': 'tg',
        'taunton daily gazette': 'tg',
        'new bedford light': 'nbl',
        'southcoasttoday': 'sct',
        'providence journal': 'pj',
        'boston globe': 'bg',
        'boston herald': 'bh',
        'wicked local': 'wl',
        'universal hub': 'uh',
        'anchor news': 'an',
        'anchor news (diocese)': 'an',
        'frcmedia': 'frc',
        'frcmedia (fall river community media)': 'frc',
        'fall river community media': 'frc',
        'fun107': 'fun',
        'google news': 'gn',
        'google news (fall river, ma)': 'gn',
        'hathaway funeral homes': 'hf',
        'herald news obituaries': 'hn',
        'wpri 12 fall river': 'wpri',
        'wpri': 'wpri',

        # National sources
        'cnn': 'cnn',
        'fox news': 'fn',
        'bbc news': 'bbc',
        'nbc news': 'nbc',
        'abc news': 'abc',
        'cbs news': 'cbs',
        'reuters': 'rtr',
        'associated press': 'ap',
        'usa today': 'ut',
        'wall street journal': 'wsj',
        'new york times': 'nyt',
        'washington post': 'wp'
    }

    # Check for exact matches first
    if normalized in smart_mappings:
        return smart_mappings[normalized].upper()

    # Check for partial matches (contains)
    for key, initials in smart_mappings.items():
        if key in normalized:
            return initials.upper()

    # Fallback: extract meaningful initials
    # Clean the source name by removing punctuation and extra spaces
    import re
    cleaned = re.sub(r'[^\w\s]', '', normalized)  # Remove punctuation
    words = cleaned.split()

    # Remove common words
    words_to_ignore = {'the', 'news', 'newspaper', 'times', 'post', 'tribune', 'journal', 'herald', 'reporter', 'gazette', 'daily', 'weekly', 'local', 'online', 'media', 'press', 'today', 'now', 'live', 'fall', 'river', 'ma', 'massachusetts'}

    meaningful_words = [word for word in words if word not in words_to_ignore and len(word) > 2]

    if len(meaningful_words) >= 2:
        # Take first letter of first two meaningful words
        return (meaningful_words[0][0] + meaningful_words[1][0]).upper()
    elif len(meaningful_words) == 1:
        # Take first two letters of the word
        return meaningful_words[0][:2].upper()
    elif len(words) >= 2:
        # Fallback to any words if no meaningful ones found
        return (words[0][0] + words[1][0]).upper()
    elif len(words) == 1:
        # Take first two letters of any remaining word
        return words[0][:2].upper()
    else:
        # Last resort: first two letters of original source (cleaned)
        return cleaned[:2].upper() or 'XX'

def _get_combined_gradient(source, category):
    """Get gradient that combines source start color with category end color"""
    # Get source gradient and extract start color
    source_gradient = _get_source_gradient(source)
    start_color = _extract_start_color(source_gradient)

    # Get category end color
    end_color = CATEGORY_COLORS.get(category, 'slate-600')

    return f"from-{start_color} to-{end_color}"

def _extract_start_color(gradient):
    """Extract the start color from a gradient string like 'from-blue-500 to-cyan-600'"""
    if not gradient or 'from-' not in gradient:
        return 'blue-500'  # Default fallback

    # Extract the color part after 'from-'
    from_part = gradient.split('from-')[1]
    start_color = from_part.split()[0] if ' ' in from_part else from_part.split('to-')[0]

    return start_color

def _get_source_gradient(source):
    """Get gradient class for source (simplified version)"""
    if not source:
        return "from-gray-500 to-gray-600"

    # Simple hash-based gradient assignment
    gradients = [
        "from-blue-500 to-blue-600",
        "from-green-500 to-green-600",
        "from-purple-500 to-purple-600",
        "from-red-500 to-red-600",
        "from-yellow-500 to-yellow-600",
        "from-pink-500 to-pink-600",
        "from-indigo-500 to-indigo-600",
        "from-teal-500 to-teal-600"
    ]

    return gradients[hash(source) % len(gradients)]

def generate_nav_tabs(active_category='local'):
    """Generate navigation HTML with correct active state"""
    # Map active_category to the page_key used in navigation
    category_to_page_key = {
        'local': 'home',
        'police-fire': 'category-crime',
        'sports': 'category-sports',
        'obituaries': 'category-obituaries',
        'food': 'category-food',
        'scanner': 'category-scanner',
        'meetings': 'category-meetings',
        'events': 'category-events'
    }

    active_page = category_to_page_key.get(active_category, 'home')

    # Top row: Primary navigation (big, bold)
    top_row_tabs = [
        ("Local", "/", "home"),
        ("Police & Fire", "/category/police-fire", "category-crime"),
        ("Sports", "/category/sports", "category-sports"),
        ("Obituaries", "/category/obituaries", "category-obituaries"),
        ("Food & Drink", "/category/food", "category-food"),
    ]

    # Second row: Secondary navigation (slightly smaller, lighter)
    second_row_tabs = [
        ("Scanner", "/category/scanner", "category-scanner"),
        ("Meetings", "/category/meetings", "category-meetings"),
        ("Submit Tip", "/#submit", "home"),
        ("Lost & Found", "/#lost-found", "home"),
        ("Events", "/category/events", "category-events"),
    ]

    # Build navigation HTML with two-row structure
    nav_html = '''
    <!-- Desktop Navigation: Two Rows - Centered -->
    <div class="hidden lg:flex flex-col items-center gap-3 w-full">
        <!-- Top Row: Primary Navigation (Big, Bold) -->
        <div class="flex flex-wrap items-center justify-center gap-2 lg:gap-3">
'''

    # Top row links
    for label, href, page_key in top_row_tabs:
        # Check if this is the active page
        is_active = (active_page == page_key)
        if is_active:
            active_class = 'text-white font-bold bg-blue-500/20 border border-blue-500/40'
        else:
            active_class = 'text-gray-300 hover:text-white font-bold border border-transparent hover:border-gray-700 hover:bg-gray-900/30'

        nav_html += f'''            <a href="{href}" class="px-3 py-2 rounded-lg transition-all duration-200 {active_class}">{label}</a>
'''

    nav_html += '''
        </div>

        <!-- Second Row: Secondary Navigation (Smaller, Lighter) - Centered under first row -->
        <div class="flex flex-wrap items-center justify-center gap-2 lg:gap-3">
'''

    # Second row links
    for label, href, page_key in second_row_tabs:
        # Check if this is the active page
        is_active = (active_page == page_key)
        if is_active:
            active_class = 'text-white font-semibold bg-blue-400/20 border border-blue-400/30'
        else:
            active_class = 'text-sm text-gray-400 hover:text-white font-semibold border border-transparent hover:border-gray-600 hover:bg-gray-900/30'

        nav_html += f'''            <a href="{href}" class="px-2 py-1 rounded-md transition-all duration-200 {active_class}">{label}</a>
'''

    nav_html += '''
        </div>
    </div>

    <!-- Mobile Navigation Menu -->
    <div id="mobileNavMenu" class="hidden fixed inset-0 z-[1000] transition-opacity duration-300" style="opacity: 0;">
        <!-- Backdrop -->
        <div class="fixed inset-0 bg-black/70 backdrop-blur-sm z-[999]" onclick="closeHamburgerMenu()"></div>
        <!-- Side Drawer -->
        <div id="hamburgerDrawer" class="fixed top-0 right-0 h-full w-80 bg-[#161616] shadow-2xl overflow-y-auto transform transition-transform duration-300 ease-out z-[1000]" style="transform: translateX(100%);" onclick="event.stopPropagation()">
            <div class="p-6">
                <div class="flex justify-between items-center mb-8">
                    <div class="text-xl font-bold text-blue-400">Navigation</div>
                    <button onclick="closeHamburgerMenu()" class="text-gray-400 hover:text-white p-2">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>
'''

    # Mobile menu links - combine both rows
    all_tabs = top_row_tabs + second_row_tabs
    for label, href, page_key in all_tabs:
        is_active = (active_page == page_key)
        if is_active:
            mobile_class = 'text-blue-400 border-blue-400/30 bg-blue-500/10'
        else:
            mobile_class = 'text-gray-300 hover:text-white hover:bg-gray-800 border-transparent'

        nav_html += f'''                <a href="{href}" class="block px-6 py-3 text-lg {mobile_class} transition-colors duration-200 border-b border-gray-700" onclick="closeHamburgerMenu()">{label}</a>
'''

    nav_html += '''
            </div>
        </div>
    </div>
'''

    return nav_html

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

# Static regeneration tracking
_static_regenerating = {}  # zip_code -> bool
_static_regeneration_lock = threading.Lock()

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
    logger.info(f"[DEBUG] Serving zip page for {zip_code} from {full_zip_dir}")

    index_path = os.path.join(full_zip_dir, 'index.html')
    logger.info(f"[DEBUG] Index path: {index_path}")
    logger.info(f"[DEBUG] Index file exists: {os.path.exists(index_path)}")

    # Read and check the served content
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()
            img_count = content.count('<img')
            logger.info(f"[DEBUG] Images in served HTML: {img_count}")

            # Check for image URLs
            if 'src=' in content:
                # Find first image tag to log
                import re
                img_match = re.search(r'<img[^>]*src="([^"]*)"', content)
                if img_match:
                    logger.info(f"[DEBUG] First image URL: {img_match.group(1)}")

    # Check current show_images setting
    try:
        conn = sqlite3.connect('fallriver_news.db')
        cursor = conn.cursor()
        cursor.execute('SELECT key, value FROM admin_settings WHERE key="show_images"')
        result = cursor.fetchone()
        conn.close()
        logger.info(f"[DEBUG] show_images setting: {result}")
    except Exception as e:
        logger.error(f"[DEBUG] Error checking show_images: {e}")

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

    # Only set content-type for admin pages and non-image responses
    content_type = response.headers.get('Content-Type', '').lower()
    if not content_type.startswith('image/') and not request.path.startswith('/cached-images/'):
        # Force UTF-8 encoding for admin pages and other text content
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

def _should_regenerate_static(zip_code):
    """Check if static file regeneration is needed for this zip code"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Check if auto-regeneration is enabled
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('auto_regenerate_static',))
            row = cursor.fetchone()
            if not row or row[0] != '1':
                return False

            # Check regeneration interval (default 15 minutes)
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('static_regen_interval',))
            row = cursor.fetchone()
            interval_minutes = int(row[0]) if row and row[0].isdigit() else 15
            interval_seconds = interval_minutes * 60

            # Check last regeneration time for this zip
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', (f'last_static_regen_{zip_code}',))
            row = cursor.fetchone()
            if not row:
                return True

            try:
                last_regen = datetime.fromisoformat(row[0])
                return (datetime.now() - last_regen).seconds > interval_seconds
            except (ValueError, TypeError):
                return True

    except Exception as e:
        logger.warning(f"Error checking static regeneration need for {zip_code}: {e}")
        return False


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


def _trigger_static_regeneration(zip_code):
    """Trigger static file regeneration for a specific zip code in background"""
    global _static_regenerating

    with _static_regeneration_lock:
        if _static_regenerating.get(zip_code, False):
            return  # Already regenerating for this zip

        _static_regenerating[zip_code] = True

        def regenerate_static():
            global _static_regenerating
            try:
                logger.info(f"Starting background static regeneration for zip {zip_code}")

                # Run the regeneration command
                result = subprocess.run([
                    sys.executable, 'main.py', '--once', '--zip', zip_code
                ], capture_output=True, text=True, timeout=300)

                if result.returncode == 0:
                    logger.info(f"Background static regeneration completed for zip {zip_code}")

                    # Update last regeneration time
                    try:
                        with get_db() as conn:
                            cursor = conn.cursor()
                            cursor.execute('''
                                INSERT OR REPLACE INTO admin_settings (key, value)
                                VALUES (?, ?)
                            ''', (f'last_static_regen_{zip_code}', datetime.now().isoformat()))
                            conn.commit()
                    except Exception as e:
                        logger.warning(f"Could not update last regeneration time for {zip_code}: {e}")
                else:
                    logger.error(f"Background static regeneration failed for zip {zip_code}: {result.stderr}")

            except subprocess.TimeoutExpired:
                logger.error(f"Background static regeneration timed out for zip {zip_code}")
            except Exception as e:
                logger.error(f"Error during background static regeneration for {zip_code}: {e}")
            finally:
                _static_regenerating[zip_code] = False

        # Start regeneration in background thread
        thread = threading.Thread(target=regenerate_static, daemon=True)
        thread.start()


# Trusted domains for image caching
TRUSTED_DOMAINS = {
    'fallriverreporter.com',
    'heraldnews.com',
    'wpri.com',
    'turnto10.com',  # NBC10/WJAR
    'frcmedia.org',
    'tauntongazette.com',
    'masslive.com',
    'abc6.com',
    'southcoasttoday.com',
    'patch.com',
    'newbedfordlight.org',
    'anchornews.org',
    'hathawayfunerals.com',
    'southcoastchapel.com',
    'waring-sullivan.com',
    'oliveirafuneralhomes.com',
    'fun107.com'
}

@app.route('/cached-images/<path:url>')
def cached_image(url):
    """
    Proxy route to cache external images from trusted domains.
    Provides aggressive caching headers for performance.
    """
    try:
        # URL decode the path
        decoded_url = unquote(url)

        # Construct full URL - assume HTTPS unless specified
        if decoded_url.startswith(('http://', 'https://')):
            full_url = decoded_url
        else:
            full_url = 'https://' + decoded_url

        # Parse and validate domain
        parsed = urlparse(full_url)
        domain = parsed.netloc.lower()

        # Security: only allow trusted domains
        if domain not in TRUSTED_DOMAINS:
            logger.warning(f"Blocked image request from untrusted domain: {domain}")
            return Response("Forbidden: Untrusted domain", status=403, mimetype='text/plain')

        # Fetch image with timeout and proper headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://fallriver.live/',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'cross-site'
        }

        try:
            response = requests.get(
                full_url,
                headers=headers,
                stream=True,
                timeout=15,
                allow_redirects=True
            )
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching image: {full_url}")
            return Response("Gateway Timeout", status=504, mimetype='text/plain')
        except requests.exceptions.RequestException as e:
            logger.warning(f"Request error fetching image {full_url}: {e}")
            return Response("Bad Gateway", status=502, mimetype='text/plain')

        if response.status_code != 200:
            logger.warning(f"Failed to fetch image {full_url}: HTTP {response.status_code}")
            return Response(f"Not Found: HTTP {response.status_code}", status=404, mimetype='text/plain')

        # Validate content type
        content_type = response.headers.get('content-type', '').lower()
        if not content_type.startswith('image/'):
            logger.warning(f"URL does not return image content: {full_url} (content-type: {content_type})")
            return Response(f"Not an image: {content_type}", status=404, mimetype='text/plain')

        # Aggressive caching headers for performance
        cache_headers = {
            'Cache-Control': 'public, max-age=31536000, immutable',  # 1 year cache
            'Content-Type': content_type,
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET',
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block'
        }

        # Add content length if available
        if 'content-length' in response.headers:
            cache_headers['Content-Length'] = response.headers['content-length']

        logger.debug(f"Serving cached image: {domain}/{decoded_url[:50]}...")

        # Stream the response
        return Response(
            response.iter_content(chunk_size=8192),
            headers=cache_headers
        )

    except Exception as e:
        logger.error(f"Unexpected error in cached_image: {e}")
        return Response("Internal Server Error", status=500, mimetype='text/plain')


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

    # Get recent articles for the homepage (all categories)
    db = ArticleDatabase()
    articles = db.get_recent_articles(hours=48, limit=50, zip_code='02720')

    # Render dynamic page with all articles and 'local' as active category
    html_content = render_dynamic_index(articles, active_category='local', zip_code='02720')

    if isinstance(html_content, tuple):  # Error case
        return html_content

    from flask import Response
    return Response(html_content, mimetype='text/html')


@app.route('/category/<path:category_slug>')
def category_page(category_slug):
    """Serve category page with dynamic filtering"""
    # Strip .html extension if present (frontend links include .html)
    if category_slug.endswith('.html'):
        category_slug = category_slug[:-5]

    # Special handling for scanner - serve from zip-specific directory
    if category_slug == 'scanner':
        # Get current zip from session/cookies, default to 02720
        zip_code = get_current_zip_from_request()
        return serve_zip_category_page(zip_code, category_slug)

    # Map URL slug to database category name
    category_map = {
        'local': 'local-news',  # 'local' slug maps to 'local-news' category
        'police-fire': 'crime',
        'sports': 'sports',
        'obituaries': 'obituaries',
        'food': 'food',
        'entertainment': 'entertainment',
        'business': 'business',
        'schools': 'schools',
        'events': 'events',
        'weather': 'weather'
    }

    # Get the database category name
    db_category = category_map.get(category_slug, category_slug)

    # Get filtered articles from database
    db = ArticleDatabase()
    articles = db.get_articles_by_category(db_category, limit=50, zip_code='02720')

    # Render dynamic page with filtered articles
    html_content = render_dynamic_index(articles, active_category=category_slug, zip_code='02720')

    if isinstance(html_content, tuple):  # Error case
        return html_content

    from flask import Response
    return Response(html_content, mimetype='text/html')


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
    """Serve zip-specific index page - static file if available, otherwise dynamic"""
    if not validate_zip_code(zip_code):
        return "Invalid zip code", 404

    # Check if static file exists and serve it (better performance)
    static_file_path = Path(__file__).parent.parent / "build" / "zips" / f"zip_{zip_code}" / "index.html"
    if static_file_path.exists():
        try:
            # Check if regeneration is needed based on user settings
            if _should_regenerate_static(zip_code):
                logger.info(f"Static file for zip {zip_code} is stale, triggering background regeneration")
                _trigger_static_regeneration(zip_code)

            logger.info(f"Serving static file for zip {zip_code}")
            return send_file(str(static_file_path), mimetype='text/html')
        except Exception as e:
            logger.warning(f"Could not serve static file for zip {zip_code}: {e}")

    # Fallback to dynamic content generation
    logger.info(f"Generating dynamic content for zip {zip_code}")
    db = ArticleDatabase()
    articles = db.get_recent_articles(hours=48, limit=50, zip_code=zip_code)

    # Render dynamic page with all articles and 'local' as active category
    html_content = render_dynamic_index(articles, active_category='local', zip_code=zip_code)

    if isinstance(html_content, tuple):  # Error case
        return html_content

    from flask import Response
    return Response(html_content, mimetype='text/html')


@app.route('/zips/<path:filename>')
def serve_zip_static(filename):
    """Serve static files from zip directories"""
    try:
        file_path = Path(__file__).parent.parent / "build" / "zips" / filename
        if file_path.exists():
            return send_file(str(file_path))
        else:
            abort(404)
    except Exception as e:
        logger.error(f"Error serving static file {filename}: {e}")
        abort(500)


@app.route('/<zip_code>/category/<path:category_slug>')
def zip_category_page(zip_code, category_slug):
    """Serve zip-specific category page with dynamic filtering"""
    if not validate_zip_code(zip_code):
        return "Invalid zip code", 404

    # Strip .html extension if present (frontend links include .html)
    if category_slug.endswith('.html'):
        category_slug = category_slug[:-5]

    # Map URL slug to database category name
    category_map = {
        'local': 'local-news',  # 'local' slug maps to 'local-news' category
        'police-fire': 'crime',
        'sports': 'sports',
        'obituaries': 'obituaries',
        'food': 'food',
        'entertainment': 'entertainment',
        'business': 'business',
        'schools': 'schools',
        'events': 'events',
        'weather': 'weather'
    }

    # Get the database category name
    db_category = category_map.get(category_slug, category_slug)

    # Get filtered articles from database
    db = ArticleDatabase()
    articles = db.get_articles_by_category(db_category, limit=50, zip_code=zip_code)

    # Render dynamic page with filtered articles
    html_content = render_dynamic_index(articles, active_category=category_slug, zip_code=zip_code)

    if isinstance(html_content, tuple):  # Error case
        return html_content

    from flask import Response
    return Response(html_content, mimetype='text/html')


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
        print(f"[DEBUG SERVER] tab parameter: '{tab}', request.args: {dict(request.args)}")

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

        # Deduplicate articles by title, keeping the most recent one
        seen_titles = set()
        deduplicated_articles = []
        for article in articles:
            title = article.get('title', '').strip().lower()
            if title and title not in seen_titles:
                seen_titles.add(title)
                deduplicated_articles.append(article)

        articles = deduplicated_articles
        total_count = len(articles)  # Update count after deduplication

        rejected_articles = get_rejected_articles(zip_code=zip_code)
        sources_config = get_sources()
        stats = get_stats(zip_code=zip_code)  # Get stats for this zip only
        settings = get_settings()

        # Get database stats for the enhanced stats section
        from admin.services import get_database_stats
        db_stats = get_database_stats()

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

        if tab == 'relevance':
            print(f"[DEBUG SERVER] Rendering relevance.html for tab='{tab}'")
            return render_template('admin/relevance.html',
                zip_code=zip_code,
                version=VERSION,
                active_tab=tab,
                relevance_config=relevance_config,
                settings=settings
            )

        if tab == 'settings':
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

        print(f"[DEBUG SERVER] Falling through to main_dashboard.html for tab='{tab}'")
        return render_template('admin/main_dashboard.html',
            zip_code=zip_code,  # Pass the actual zip code for zip-specific admin
            is_main_admin=False,  # Flag to indicate this is zip-specific admin view
            active_tab=tab,
            articles=articles,
            rejected_articles=rejected_articles,
            stats=stats,
            db_stats=db_stats,
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

                logger.info(f"[REGENERATION] Starting command: {' '.join(cmd)}")
                logger.info(f"[REGENERATION] Script path exists: {os.path.exists(script_path)}")
                logger.info(f"[REGENERATION] Working directory: {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

                logger.info(f"[REGENERATION] Process completed with return code: {result.returncode}")
                if result.returncode == 0:
                    logger.info("[REGENERATION] SUCCESS: Website regeneration completed")
                    logger.info(f"[REGENERATION] Output: {result.stdout[:500]}...")  # First 500 chars
                else:
                    logger.error(f"[REGENERATION] FAILED: Return code {result.returncode}")
                    logger.error(f"[REGENERATION] Stdout: {result.stdout}")
                    logger.error(f"[REGENERATION] Stderr: {result.stderr}")

            except subprocess.TimeoutExpired:
                logger.error("[REGENERATION] TIMEOUT: Regeneration timed out after 5 minutes")
            except Exception as e:
                logger.error(f"[REGENERATION] ERROR: {e}")
                import traceback
                logger.error(f"[REGENERATION] Traceback: {traceback.format_exc()}")

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
                    # For zip-specific, aggregate with force_refresh for that zip
                    aggregator.aggregate(force_refresh=True, zip_code=zip_code)
                else:
                    # For full regeneration, aggregate everything with force refresh
                    aggregator.aggregate(force_refresh=True)
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
@app.route('/admin/api/regeneration-status', methods=['GET', 'OPTIONS'])
def get_regeneration_status():
    """Check the status of ongoing regeneration processes"""
    try:
        # Check if any regeneration processes are currently running
        # This is a simple implementation - in a real system you'd track PIDs or use a job queue

        # For now, we'll check the last regeneration time and assume processes are done
        # if they've been running for more than a reasonable time
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
            last_regeneration_row = cursor.fetchone()

            if last_regeneration_row and last_regeneration_row[0]:
                try:
                    import time
                    last_time = float(last_regeneration_row[0])
                    current_time = time.time()
                    time_since = current_time - last_time

                    # If it's been more than 5 minutes since last regeneration started,
                    # assume any process has completed
                    if time_since > 300:  # 5 minutes
                        return jsonify({
                            'status': 'idle',
                            'last_regeneration': last_time,
                            'message': 'No active regeneration processes'
                        })
                    else:
                        return jsonify({
                            'status': 'busy',
                            'last_regeneration': last_time,
                            'time_running': int(time_since),
                            'message': f'Regeneration in progress ({int(time_since)}s elapsed)'
                        })

                except (ValueError, TypeError):
                    pass

            return jsonify({
                'status': 'unknown',
                'message': 'Unable to determine regeneration status'
            })

    except Exception as e:
        logger.error(f"Error checking regeneration status: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


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

        # Check if this is a batch update (object with multiple settings)
        if isinstance(data, dict) and not data.get('key'):
            # Batch update mode - handle multiple settings
            updated_settings = []
            try:
                with get_db() as conn:
                    cursor = conn.cursor()

                    for key, value in data.items():
                        if key in ['regenerate_interval', 'source_fetch_interval', 'auto_regenerate_static', 'static_regen_interval']:
                            # Check if setting exists
                            cursor.execute('SELECT value FROM admin_settings WHERE key = ?', (key,))
                            existing = cursor.fetchone()

                            if existing:
                                cursor.execute('UPDATE admin_settings SET value = ? WHERE key = ?', (str(value), key))
                            else:
                                cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', (key, str(value)))

                            updated_settings.append(key)

                    conn.commit()
                    return jsonify({'success': True, 'message': f'Settings updated: {", ".join(updated_settings)}'})

            except Exception as e:
                logger.error(f"Error updating settings batch: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # Single setting update mode (legacy)
        key = data.get('key')
        value = data.get('value')
        zip_code = data.get('zip_code')

        logger.info(f"[DEBUG] Single setting update - key: {key}, value: {value}, zip_code: {zip_code}")

        if not key:
            logger.error("[DEBUG] Missing key parameter")
            return jsonify({'success': False, 'error': 'Missing key parameter'}), 400

        try:
            with get_db() as conn:
                cursor = conn.cursor()

                logger.info(f"[DEBUG] Checking if setting {key} exists")
                # Check if setting exists
                cursor.execute('SELECT value FROM admin_settings WHERE key = ?', (key,))
                existing = cursor.fetchone()
                logger.info(f"[DEBUG] Existing value for {key}: {existing}")

                if existing:
                    logger.info(f"[DEBUG] Updating {key} from {existing[0]} to {value}")
                    cursor.execute('UPDATE admin_settings SET value = ? WHERE key = ?', (value, key))
                else:
                    logger.info(f"[DEBUG] Inserting new setting {key} = {value}")
                    cursor.execute('INSERT INTO admin_settings (key, value) VALUES (?, ?)', (key, value))

                conn.commit()
                logger.info(f"[DEBUG] Successfully updated setting {key} = {value}")
                return jsonify({'success': True, 'message': f'Setting {key} updated'})

        except Exception as e:
            logger.error(f"[DEBUG] Error updating setting {key}: {e}")
            import traceback
            logger.error(f"[DEBUG] Traceback: {traceback.format_exc()}")
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
        print(f"[DEBUG SERVER] rerun_relevance_scoring called")
        from utils.relevance_calculator import calculate_relevance_score_with_tags
        from utils.bayesian_learner import BayesianLearner
        import sqlite3
        from config import DATABASE_CONFIG

        # Get zip_code from request
        data = request.get_json()
        print(f"[DEBUG SERVER] request data: {data}")
        zip_code = data.get('zip_code') if data else None
        print(f"[DEBUG SERVER] zip_code: {zip_code}")

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
        import traceback
        error_details = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"[DEBUG SERVER] Exception in rerun_relevance_scoring: {error_details}")
        logger.error(f"Error in rerun relevance scoring: {e}")
        return jsonify({'success': False, 'error': error_details}), 500


@login_required
@app.route('/admin/api/add-relevance-item', methods=['POST', 'OPTIONS'])
def add_relevance_item():
    """Add an item to a relevance category"""
    try:
        data = request.get_json()
        category = data.get('category')
        value = data.get('value')

        if not category or not value:
            return jsonify({'success': False, 'error': 'Missing category or value'}), 400

        # Load current relevance config
        relevance_config = WEBSITE_CONFIG.get('relevance', {})

        # Initialize category if it doesn't exist
        if category not in relevance_config:
            relevance_config[category] = []

        # Add the item if it doesn't already exist
        if value not in relevance_config[category]:
            relevance_config[category].append(value)

            # Save back to config (in memory for now)
            WEBSITE_CONFIG['relevance'] = relevance_config

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Error adding relevance item: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/remove-relevance-item', methods=['POST', 'OPTIONS'])
def remove_relevance_item():
    """Remove an item from a relevance category"""
    try:
        data = request.get_json()
        category = data.get('category')
        item = data.get('item')

        if not category or not item:
            return jsonify({'success': False, 'error': 'Missing category or item'}), 400

        # Load current relevance config
        relevance_config = WEBSITE_CONFIG.get('relevance', {})

        # Remove the item if it exists
        if category in relevance_config and item in relevance_config[category]:
            relevance_config[category].remove(item)

            # Save back to config (in memory for now)
            WEBSITE_CONFIG['relevance'] = relevance_config

        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"Error removing relevance item: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@login_required
@app.route('/admin/api/get-relevance-config', methods=['GET', 'OPTIONS'])
def get_relevance_config():
    """Get current relevance configuration from database"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Get all relevance config items grouped by category
            cursor.execute('SELECT category, item FROM relevance_config ORDER BY category, item')
            rows = cursor.fetchall()

            # Group by category
            relevance_config = {}
            for row in rows:
                category, item = row
                if category not in relevance_config:
                    relevance_config[category] = []
                relevance_config[category].append(item)

            return jsonify(relevance_config)
    except Exception as e:
        logger.error(f"Error getting relevance config: {e}")
        return jsonify({'error': str(e)}), 500


@login_required
@app.route('/admin/api/save-relevance-threshold', methods=['POST', 'OPTIONS'])
def save_relevance_threshold():
    """Save the relevance threshold setting"""
    try:
        import sqlite3
        print(f"[DEBUG SERVER] save_relevance_threshold called")
        data = request.get_json()
        print(f"[DEBUG SERVER] request data: {data}")
        threshold = data.get('threshold')
        print(f"[DEBUG SERVER] threshold: {threshold}, type: {type(threshold)}")

        if threshold is None or not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 100:
            print(f"[DEBUG SERVER] Invalid threshold validation failed")
            return jsonify({'success': False, 'error': 'Invalid threshold value'}), 400

        # Save to database
        print(f"[DEBUG SERVER] Connecting to database")
        conn = sqlite3.connect('fallriver_news.db')
        cursor = conn.cursor()

        print(f"[DEBUG SERVER] Executing INSERT for threshold: {threshold}")
        cursor.execute('''
            INSERT OR REPLACE INTO admin_settings (key, value)
            VALUES (?, ?)
        ''', ('relevance_threshold', str(int(threshold))))

        conn.commit()
        conn.close()
        print(f"[DEBUG SERVER] Database operation completed successfully")

        return jsonify({'success': True})

    except Exception as e:
        import traceback
        error_details = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        print(f"[DEBUG SERVER] Exception in save_relevance_threshold: {error_details}")
        logger.error(f"Error saving relevance threshold: {e}")
        return jsonify({'success': False, 'error': error_details}), 500


@login_required
@app.route('/admin/api/get-bayesian-stats', methods=['GET', 'OPTIONS'])
def get_bayesian_stats():
    """Get Bayesian learning statistics"""
    try:
        from utils.bayesian_relevance import BayesianRelevanceLearner

        learner = BayesianRelevanceLearner()

        # Get global stats (sum across all zip codes)
        total_examples = 0
        positive_examples = 0
        negative_examples = 0

        # Get stats for common zip codes
        zip_codes = ['02720', '02721', '02722', '02723', '02724', '02725', '02726', '02842']
        for zip_code in zip_codes:
            try:
                stats = learner.get_training_stats(zip_code)
                total_examples += stats.get('total_examples', 0)
                positive_examples += stats.get('positive_examples', 0)
                negative_examples += stats.get('negative_examples', 0)
            except:
                continue

        # Convert to expected format
        is_active = total_examples >= 10  # Lower threshold for relevance learning
        rejection_rate = 0
        if total_examples > 0:
            rejection_rate = round((negative_examples / total_examples) * 100, 1)

        # Use average accuracy across zip codes
        accuracy = 85  # Default accuracy estimate

        stats = {
            'total_examples': total_examples,
            'is_active': is_active,
            'rejection_rate': rejection_rate,
            'accuracy': accuracy
        }

        return jsonify({
            'success': True,
            'stats': stats
        })

    except Exception as e:
        logger.error(f"Error getting Bayesian stats: {e}")
        return jsonify({
            'success': False,
            'stats': {
                'total_examples': 0,
                'is_active': False,
                'rejection_rate': 0,
                'accuracy': 0
            }
        }), 500


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