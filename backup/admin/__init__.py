"""
Admin Blueprint for Flask application
"""
from flask import Blueprint
from functools import wraps
from flask import request, redirect, url_for, session, jsonify
from datetime import datetime
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# Create Blueprint
admin_bp = Blueprint(
    'admin',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/admin'
)

# Security Constants
ZIP_CODE_LENGTH = 5
MAX_ARTICLE_ID = 2**31 - 1

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

# Security: Hash password for secure storage/comparison
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    try:
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    except ImportError:
        raise ImportError("bcrypt not installed. Install with: pip install bcrypt")

def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash"""
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except ImportError:
        # Fallback to plain text comparison if bcrypt not available
        return password == hashed
    except Exception:
        return False

# Store hashed password (fallback to plain text comparison for backward compatibility)
_ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH')
if _ADMIN_PASSWORD_HASH:
    _ADMIN_PASSWORD_HASHED = True
else:
    _ADMIN_PASSWORD_HASHED = False
    logger.warning("ADMIN_PASSWORD_HASH not set. Using plain text password comparison (not secure!)")

# Security: CORS configuration
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:8000,http://127.0.0.1:8000').split(',')

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
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated_function

# CORS and security middleware
@admin_bp.after_request
def after_request(response):
    """Add CORS headers and disable caching for admin pages"""
    # Security: Only allow specific origins instead of wildcard
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
    
    return response

# Routes will be imported after blueprint creation to avoid circular imports

