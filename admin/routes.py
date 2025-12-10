"""
Admin routes for Flask Blueprint
"""
from flask import render_template, request, redirect, url_for, session, jsonify
from datetime import datetime
import os
import logging
import json
import sqlite3
from admin import admin_bp, login_required, validate_zip_code, ADMIN_USERNAME, ADMIN_PASSWORD, verify_password, _ADMIN_PASSWORD_HASHED, _ADMIN_PASSWORD_HASH
from admin.utils import (
    get_articles, get_rejected_articles, get_sources, get_stats, get_settings,
    trash_article, restore_article, toggle_top_story, toggle_good_fit,
    get_db_legacy, init_admin_db
)
from config import DATABASE_CONFIG, NEWS_SOURCES, VERSION

logger = logging.getLogger(__name__)

# Optional rate limiting - use dummy limiter for blueprint routes
# (Rate limiting would need app instance, so we'll use a no-op limiter here)
class DummyLimiter:
    def limit(self, *args, **kwargs):
        def decorator(f):
            return f
        return decorator

limiter = DummyLimiter()


@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    """Login route"""
    zip_code = request.args.get('z', '').strip()
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            error = 'Username and password are required'
            if request.headers.get('Content-Type') == 'application/json' or request.is_json:
                return jsonify({'success': False, 'error': error}), 401
            return render_template('admin/login.html', error=error, zip_code=zip_code)
        
        # Check if it's a zip code login (5 digits) or main admin login
        if validate_zip_code(username):
            # Per-zip login: username = zip code, password from ZIP_LOGIN_PASSWORD env var
            from admin import ZIP_LOGIN_PASSWORD
            if not ZIP_LOGIN_PASSWORD:
                error = 'Per-zip admin login is not configured. Contact administrator.'
            elif password == ZIP_LOGIN_PASSWORD:
                session['logged_in'] = True
                session['zip_code'] = username
                session['is_main_admin'] = False
                if request.headers.get('Content-Type') == 'application/json' or request.is_json:
                    return jsonify({'success': True, 'zip_code': username})
                return redirect(url_for('admin.dashboard', zip_code=username))
            else:
                error = 'Invalid password for zip code login.'
        elif username == ADMIN_USERNAME:
            # Main admin login
            if _ADMIN_PASSWORD_HASHED and _ADMIN_PASSWORD_HASH:
                password_valid = verify_password(password, _ADMIN_PASSWORD_HASH)
            else:
                password_valid = (password == ADMIN_PASSWORD)
            
            if password_valid:
                session['logged_in'] = True
                session['is_main_admin'] = True
                if zip_code and validate_zip_code(zip_code):
                    session['zip_code'] = zip_code
                    return redirect(url_for('admin.dashboard', zip_code=zip_code))
                return redirect(url_for('admin.main_dashboard'))
            else:
                error = 'Invalid credentials'
        else:
            error = 'Invalid credentials'
        
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'error': error}), 401
        return render_template('admin/login.html', error=error, zip_code=zip_code)
    
    return render_template('admin/login.html', zip_code=zip_code)


@admin_bp.route('/logout')
def logout():
    """Logout route"""
    session.pop('logged_in', None)
    session.pop('zip_code', None)
    session.pop('is_main_admin', None)
    return redirect(url_for('admin.login'))


@admin_bp.route('/')
@login_required
def main_dashboard():
    """Main admin dashboard - shows all zip codes"""
    # Ensure database is initialized with new categories
    init_admin_db()
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Get all unique zip codes
    cursor.execute('SELECT DISTINCT zip_code FROM articles WHERE zip_code IS NOT NULL ORDER BY zip_code')
    zip_codes_from_articles = [row[0] for row in cursor.fetchall()]
    
    cursor.execute('SELECT DISTINCT zip_code FROM article_management WHERE zip_code IS NOT NULL ORDER BY zip_code')
    zip_codes_from_management = [row[0] for row in cursor.fetchall()]
    
    cursor.execute('SELECT DISTINCT zip_code FROM admin_settings_zip WHERE zip_code IS NOT NULL ORDER BY zip_code')
    zip_codes_from_settings = [row[0] for row in cursor.fetchall()]
    
    cursor.execute('SELECT DISTINCT zip_code FROM relevance_config WHERE zip_code IS NOT NULL ORDER BY zip_code')
    zip_codes_from_relevance = [row[0] for row in cursor.fetchall()]
    
    all_zip_codes = set(zip_codes_from_articles + zip_codes_from_management + zip_codes_from_settings + zip_codes_from_relevance)
    zip_codes = sorted(list(all_zip_codes))
    
    # Get sticky zips
    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('sticky_zips',))
    sticky_row = cursor.fetchone()
    sticky_zips = []
    if sticky_row:
        try:
            sticky_zips = json.loads(sticky_row['value'])
        except:
            sticky_zips = []
    
    conn.close()
    
    return render_template('admin/main_dashboard.html', zip_codes=zip_codes, sticky_zips=sticky_zips)


@admin_bp.route('/<zip_code>')
@admin_bp.route('/<zip_code>/articles')
@login_required
def dashboard(zip_code):
    """Articles tab - default dashboard"""
    # Ensure database is initialized with new categories for this zip
    init_admin_db()
    
    return render_dashboard_tab(zip_code, 'articles')


@admin_bp.route('/<zip_code>/trash', methods=['GET', 'POST', 'OPTIONS'])
@login_required
def trash_tab(zip_code):
    """Trash tab - GET shows page, POST handles trash action"""
    if request.method == 'POST' or request.method == 'OPTIONS':
        if request.method == 'OPTIONS':
            return '', 200
        
        data = request.json or {}
        article_id = data.get('id') or data.get('article_id')
        action = data.get('action', 'trash')
        rejected = (action == 'trash')
        
        if not article_id:
            return jsonify({'success': False, 'error': 'Article ID required'}), 400
        
        if not validate_zip_code(zip_code):
            return jsonify({'success': False, 'error': 'Invalid zip code'}), 400
        
        result = trash_article(article_id, zip_code)
        return jsonify(result)
    
    return render_dashboard_tab(zip_code, 'trash')


@admin_bp.route('/<zip_code>/sources')
@login_required
def sources_tab(zip_code):
    """Sources tab"""
    return render_dashboard_tab(zip_code, 'sources')


@admin_bp.route('/<zip_code>/stats')
@login_required
def stats_tab(zip_code):
    """Stats tab"""
    return render_dashboard_tab(zip_code, 'stats')


@admin_bp.route('/<zip_code>/settings')
@login_required
def settings_tab(zip_code):
    """Settings tab"""
    return render_dashboard_tab(zip_code, 'settings')


@admin_bp.route('/<zip_code>/relevance')
@login_required
def relevance_tab(zip_code):
    """Relevance tab"""
    return render_dashboard_tab(zip_code, 'relevance')


@admin_bp.route('/<zip_code>/categories')
@login_required
def categories_tab(zip_code):
    """Categories tab"""
    # Ensure database is initialized with new categories for this zip
    init_admin_db()
    
    return render_dashboard_tab(zip_code, 'categories')




def render_dashboard_tab(zip_code: str, tab: str = 'articles'):
    """Render dashboard for a specific tab"""
    # Validate zip code
    if not validate_zip_code(zip_code):
        return redirect(url_for('admin.login'))
    
    # Check permissions
    is_main_admin = session.get('is_main_admin', False)
    session_zip = session.get('zip_code')
    
    if not is_main_admin:
        if not session_zip or session_zip != zip_code:
            return redirect(url_for('admin.login'))
    
    # Update session zip for main admin
    if is_main_admin:
        session['zip_code'] = zip_code
    
    # Get data
    show_trash = (tab == 'trash')
    articles = get_articles(zip_code, show_trash=show_trash) if tab in ['articles', 'trash'] else []
    sources = get_sources(zip_code) if tab == 'sources' else {}
    stats = get_stats(zip_code)
    settings = get_settings(zip_code)
    
    # Get relevance config if needed
    relevance_config = None
    if tab in ['relevance', 'sources', 'categories']:
        relevance_config = get_relevance_config(zip_code)
    
    # Get last regeneration time
    last_regeneration = get_last_regeneration(zip_code)
    
    # Get enabled zips
    enabled_zips = get_enabled_zips()
    
    # Get rejected article features for trash tab
    rejected_features = {}
    if show_trash:
        try:
            from utils.bayesian_learner import BayesianLearner
            learner = BayesianLearner()
            for article in articles:
                if article.get('is_rejected'):
                    features = learner.extract_features(article)
                    rejected_features[article.get('id')] = {
                        'keywords': list(features.get('keywords', set()))[:10],
                        'nearby_towns': list(features.get('nearby_towns', set())),
                        'topics': list(features.get('topics', set())),
                        'has_fall_river': features.get('has_fall_river', False),
                        'n_grams': list(features.get('n_grams', set()))[:5]
                    }
        except Exception as e:
            logger.warning(f"Could not extract features: {e}")
    
    cache_bust = int(datetime.now().timestamp())
    
    return render_template(
        f'admin/{tab}.html',
        articles=articles,
        settings=settings,
        sources=sources,
        stats=stats,
        rejected_features=rejected_features,
        active_tab=tab,
        cache_bust=cache_bust,
        relevance_config=relevance_config,
        zip_code=zip_code,
        enabled_zips=enabled_zips,
        version=VERSION,
        last_regeneration=last_regeneration
    )


def get_relevance_config(zip_code: str) -> dict:
    """Get relevance configuration for a zip code"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('SELECT category, item, points FROM relevance_config WHERE zip_code = ? ORDER BY category, item', (zip_code,))
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
    
    # Get category-level points
    cursor.execute('SELECT key, value FROM admin_settings_zip WHERE zip_code = ? AND key IN (?, ?)', 
                 (zip_code, 'high_relevance_points', 'local_places_points'))
    for row in cursor.fetchall():
        key = row[0]
        value = row[1]
        try:
            relevance_config[key] = float(value)
        except (ValueError, TypeError):
            pass
    
    # Set defaults
    if 'high_relevance_points' not in relevance_config:
        relevance_config['high_relevance_points'] = 15.0
    if 'local_places_points' not in relevance_config:
        relevance_config['local_places_points'] = 3.0
    
    conn.close()
    return relevance_config


def get_last_regeneration(zip_code: str) -> str:
    """Get formatted last regeneration time"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('last_regeneration_time',))
    regen_row = cursor.fetchone()
    last_regeneration_raw = regen_row['value'] if regen_row else None
    
    last_regeneration = None
    if last_regeneration_raw:
        try:
            from datetime import datetime, timezone
            from zoneinfo import ZoneInfo
            
            timestamp_str = last_regeneration_raw.replace('Z', '+00:00')
            dt = datetime.fromisoformat(timestamp_str)
            
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            eastern_tz = ZoneInfo('America/New_York')
            dt_eastern = dt.astimezone(eastern_tz)
            last_regeneration = dt_eastern.strftime('%Y-%m-%d %I:%M %p %Z')
        except Exception as e:
            logger.warning(f"Error formatting timestamp: {e}")
            last_regeneration = last_regeneration_raw
    
    conn.close()
    return last_regeneration


def get_enabled_zips() -> list:
    """Get enabled zip codes"""
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('enabled_zips',))
    enabled_zips_row = cursor.fetchone()
    enabled_zips = []
    if enabled_zips_row:
        try:
            enabled_zips = json.loads(enabled_zips_row['value'])
        except:
            enabled_zips = []
    
    if not enabled_zips:
        cursor.execute('SELECT DISTINCT zip_code FROM articles WHERE zip_code IS NOT NULL ORDER BY zip_code')
        enabled_zips = [row[0] for row in cursor.fetchall()]
    
    conn.close()
    return enabled_zips


# API Routes
@admin_bp.route('/api/reject-article', methods=['POST', 'OPTIONS'])
@login_required
def reject_article():
    """Reject article API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    article_id = data.get('article_id')
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not article_id or not zip_code:
        return jsonify({'success': False, 'error': 'Article ID and zip code required'}), 400
    
    result = trash_article(article_id, zip_code)
    return jsonify(result)


@admin_bp.route('/<zip_code>/restore', methods=['POST', 'OPTIONS'])
@admin_bp.route('/api/restore-article', methods=['POST', 'OPTIONS'])
@login_required
def restore_article_api(zip_code=None):
    """Restore article API - supports both /admin/<zip_code>/restore and /admin/api/restore-article"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    article_id = data.get('article_id') or data.get('id')
    if not zip_code:
        zip_code = data.get('zip_code') or session.get('zip_code')
    rejection_type = data.get('rejection_type', 'manual')
    
    if not article_id or not zip_code:
        return jsonify({'success': False, 'error': 'Article ID and zip code required'}), 400
    
    result = restore_article(article_id, zip_code, rejection_type)
    return jsonify(result)


@admin_bp.route('/api/top-story', methods=['POST', 'OPTIONS'])
@login_required
def toggle_top_story_api():
    """Toggle top story API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    article_id = data.get('id')
    is_top_story = data.get('is_top_story', False)
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not article_id or not zip_code:
        return jsonify({'success': False, 'error': 'Article ID and zip code required'}), 400
    
    result = toggle_top_story(article_id, zip_code, is_top_story)
    return jsonify(result)


@admin_bp.route('/api/good-fit', methods=['POST', 'OPTIONS'])
@login_required
def toggle_good_fit_api():
    """Toggle good fit API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    article_id = data.get('id') or data.get('article_id')
    is_good_fit = data.get('is_good_fit', True)
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not article_id or not zip_code:
        return jsonify({'success': False, 'error': 'Article ID and zip code required'}), 400
    
    result = toggle_good_fit(article_id, zip_code, is_good_fit)
    return jsonify(result)


@admin_bp.route('/api/get-rejected-articles', methods=['GET', 'OPTIONS'])
@login_required
def get_rejected_articles_api():
    """Get rejected articles API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    zip_code = request.args.get('zip_code') or session.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    articles = get_rejected_articles(zip_code)
    return jsonify({'success': True, 'articles': articles})


@admin_bp.route('/api/reorder-articles', methods=['POST', 'OPTIONS'])
@login_required
def reorder_articles():
    """Reorder articles API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    article_orders = data.get('orders', [])
    zip_code = data.get('zip_code') or session.get('zip_code')
    
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


@admin_bp.route('/api/toggle-images', methods=['POST', 'OPTIONS'])
@login_required
def toggle_images():
    """Toggle images API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    show_images = data.get('show_images', True)
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
        VALUES (?, 'show_images', ?)
    ''', (zip_code, '1' if show_images else '0'))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})


@admin_bp.route('/api/settings', methods=['POST', 'OPTIONS'])
@login_required
def update_setting():
    """Update a setting"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    key = data.get('key')
    value = data.get('value')
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not key or value is None or not zip_code:
        return jsonify({'success': False, 'error': 'Key, value, and zip_code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings_zip (zip_code, key, value)
        VALUES (?, ?, ?)
    ''', (zip_code, key, str(value)))
    
    conn.commit()
    
    # If relevance threshold changed, clear cache (scores will recalc on next aggregation)
    if key == 'relevance_threshold':
        try:
            from utils.relevance_calculator import load_relevance_config
            load_relevance_config(force_reload=True, zip_code=zip_code)
            logger.info(f"Cleared relevance config cache after threshold update for zip {zip_code}")
        except Exception as e:
            logger.warning(f"Could not clear relevance config cache: {e}")
    
    conn.close()
    
    return jsonify({'success': True, 'message': 'Setting updated'})


@admin_bp.route('/api/get-article', methods=['GET'])
@login_required
def get_article():
    """Get article data for editing"""
    article_id = request.args.get('id')
    if not article_id:
        return jsonify({'success': False, 'message': 'Article ID required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({'success': False, 'message': 'Article not found'}), 404
    
    article = {key: row[key] for key in row.keys()}
    return jsonify({'success': True, 'article': article})


@admin_bp.route('/api/edit-article', methods=['POST', 'OPTIONS'])
@login_required
def edit_article_api():
    """Edit article API"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    article_id = data.get('id') or data.get('article_id')
    title = data.get('title', '')
    summary = data.get('summary', '')
    category = data.get('category')
    url = data.get('url')
    published = data.get('published')
    
    if not article_id:
        return jsonify({'success': False, 'error': 'Article ID required'}), 400
    
    # Clean bad characters
    import re
    title = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', title) if title else ''
    summary = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', summary) if summary else ''
    
    # Validate and format published date if provided
    if published:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
            published = dt.isoformat()
        except:
            try:
                dt = datetime.fromisoformat(published.split('T')[0])
                published = dt.isoformat()
            except:
                published = None
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    # Build update query dynamically
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
    if url:
        updates.append('url = ?')
        values.append(url)
    if published:
        updates.append('published = ?')
        values.append(published)
    
    if updates:
        values.append(article_id)
        query = f'UPDATE articles SET {", ".join(updates)} WHERE id = ?'
        cursor.execute(query, values)
    
    # If category was edited, train the classifier with this feedback
    if category:
        try:
            from utils.category_classifier import CategoryClassifier
            from admin.utils import map_category_to_classifier
            from config import CATEGORY_MAPPING
            
            # Get zip_code from session or article
            zip_code = session.get('zip_code')
            if not zip_code:
                # Try to get from article
                cursor.execute('SELECT zip_code FROM articles WHERE id = ?', (article_id,))
                row = cursor.fetchone()
                zip_code = row[0] if row else None
            
            if zip_code:
                # Map category to classifier category name
                # First map old category to new slug if needed
                category_slug = CATEGORY_MAPPING.get(category, category)
                classifier_category = map_category_to_classifier(category_slug)
                
                # Get full article data for training
                cursor.execute('SELECT title, content, summary, source FROM articles WHERE id = ?', (article_id,))
                article_row = cursor.fetchone()
                
                if article_row:
                    article = {
                        'title': article_row[0] or '',
                        'content': article_row[1] or '',
                        'summary': article_row[2] or '',
                        'source': article_row[3] or ''
                    }
                    
                    # Train the classifier with positive feedback
                    classifier = CategoryClassifier(zip_code)
                    classifier.train_from_feedback(article, classifier_category, is_positive=True)
                    logger.info(f"Trained classifier from category edit: article {article_id}, category {classifier_category}")
        except Exception as e:
            logger.warning(f"Could not train classifier from category edit: {e}")
            # Don't fail the edit if training fails
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Article updated'})


@admin_bp.route('/api/relevance-item', methods=['POST', 'DELETE', 'OPTIONS'])
@login_required
def manage_relevance_item():
    """Add or remove relevance configuration item"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    category = data.get('category')
    item = data.get('item')
    points = data.get('points')
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not category or not item or not zip_code:
        return jsonify({'success': False, 'error': 'Category, item, and zip_code required'}), 400
    
    conn = get_db_legacy()
    cursor = conn.cursor()
    
    try:
        if request.method == 'DELETE':
            # Remove item
            cursor.execute('''
                DELETE FROM relevance_config 
                WHERE category = ? AND item = ? AND zip_code = ?
            ''', (category, item, zip_code))
            conn.commit()
            item_removed = True
        else:
            # Add item
            # For categories with points (topic_keywords, source_credibility)
            if category in ['topic_keywords', 'source_credibility']:
                if points is None:
                    return jsonify({'success': False, 'error': 'Points required for this category'}), 400
                cursor.execute('''
                    INSERT OR REPLACE INTO relevance_config (category, item, points, zip_code)
                    VALUES (?, ?, ?, ?)
                ''', (category, item, points, zip_code))
            else:
                # For list categories (no points)
                cursor.execute('''
                    INSERT OR IGNORE INTO relevance_config (category, item, points, zip_code)
                    VALUES (?, ?, NULL, ?)
                ''', (category, item, zip_code))
            
            conn.commit()
            item_removed = False
        
        # Clear relevance config cache for this zip_code
        try:
            from utils.relevance_calculator import load_relevance_config
            load_relevance_config(force_reload=True, zip_code=zip_code)
            logger.info(f"Cleared relevance config cache for zip {zip_code}")
        except Exception as e:
            logger.warning(f"Could not clear relevance config cache: {e}")
        
        # Recalculate relevance scores for all articles in this zip_code
        try:
            from utils.relevance_calculator import calculate_relevance_score
            
            # Get all articles for this zip_code
            cursor.execute('''
                SELECT * FROM articles 
                WHERE zip_code = ? OR zip_code IS NULL
                ORDER BY id DESC
                LIMIT 500
            ''', (zip_code,))
            
            articles_updated = 0
            for row in cursor.fetchall():
                article = {key: row[key] for key in row.keys()}
                
                # Recalculate relevance score
                relevance_score = calculate_relevance_score(article, zip_code=zip_code)
                
                # Calculate local focus score (0-10)
                from admin.utils import calculate_local_focus_score
                local_focus_score = calculate_local_focus_score(article, zip_code=zip_code)
                
                # Update article with new scores
                cursor.execute('''
                    UPDATE articles 
                    SET relevance_score = ?, local_score = ?
                    WHERE id = ?
                ''', (relevance_score, local_focus_score, article['id']))
                
                articles_updated += 1
            
            conn.commit()
            logger.info(f"Recalculated relevance scores for {articles_updated} articles in zip {zip_code}")
        except Exception as e:
            logger.warning(f"Could not recalculate relevance scores: {e}")
            # Don't fail the request if recalculation fails
        
        if item_removed:
            return jsonify({'success': True, 'message': 'Item removed and relevance scores recalculated'})
        else:
            return jsonify({'success': True, 'message': 'Item added and relevance scores recalculated'})
    except Exception as e:
        logger.error(f"Error managing relevance item: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        conn.close()


@admin_bp.route('/api/get-relevance-breakdown', methods=['GET', 'OPTIONS'])
@login_required
def get_relevance_breakdown():
    """Get relevance breakdown for an article"""
    if request.method == 'OPTIONS':
        return '', 200
    
    article_id = request.args.get('id')
    if not article_id:
        return jsonify({'success': False, 'error': 'Article ID required'}), 400
    
    try:
        article_id = int(article_id)
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Invalid article ID'}), 400
    
    zip_code = session.get('zip_code')
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        from utils.relevance_calculator import load_relevance_config
        from datetime import datetime
        
        # Get article from database
        conn = get_db_legacy()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM articles WHERE id = ?', (article_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return jsonify({'success': False, 'error': 'Article not found'}), 404
        
        article = {key: row[key] for key in row.keys()}
        
        # Load relevance config
        config = load_relevance_config(zip_code=zip_code)
        
        content = article.get("content", article.get("summary", "")).lower()
        title = article.get("title", "").lower()
        combined = f"{title} {content}"
        
        breakdown = []
        
        # Check for stellar article
        is_stellar = article.get('is_stellar', 0)
        if is_stellar:
            breakdown.append("✓ Stellar article boost (+50 pts)")
        
        # High relevance keywords
        high_relevance = config.get('high_relevance', [])
        high_relevance_points = config.get('high_relevance_points', 15.0)
        found_high = [kw for kw in high_relevance if kw in combined]
        if found_high:
            breakdown.append(f"✓ High relevance keywords: {', '.join(found_high[:3])}{'...' if len(found_high) > 3 else ''} (+{len(found_high) * high_relevance_points:.0f} pts)")
        
        # Local places
        local_places = config.get('local_places', [])
        local_places_points = config.get('local_places_points', 3.0)
        found_places = [place for place in local_places if place in combined]
        if found_places:
            breakdown.append(f"✓ Local places: {', '.join(found_places[:3])}{'...' if len(found_places) > 3 else ''} (+{len(found_places) * local_places_points:.0f} pts)")
        
        # Topic keywords
        topic_keywords = config.get('topic_keywords', {})
        found_topics = [(kw, pts) for kw, pts in topic_keywords.items() if kw in combined]
        if found_topics:
            total_topic_points = sum(pts for _, pts in found_topics)
            topic_names = [kw for kw, _ in found_topics[:3]]
            breakdown.append(f"✓ Topic keywords: {', '.join(topic_names)}{'...' if len(found_topics) > 3 else ''} (+{total_topic_points:.0f} pts)")
        
        # Source credibility
        source = article.get("source", "").lower()
        source_credibility = config.get('source_credibility', {})
        for source_name, points in source_credibility.items():
            if source_name in source:
                breakdown.append(f"✓ Source credibility: {source_name} (+{points:.0f} pts)")
                break
        
        # Recency
        published = article.get("published")
        if published:
            try:
                pub_date = datetime.fromisoformat(published.replace('Z', '+00:00').split('+')[0])
                days_old = (datetime.now() - pub_date.replace(tzinfo=None)).days
                if days_old == 0:
                    breakdown.append("✓ Recency: Today's news (+5 pts)")
                elif days_old <= 1:
                    breakdown.append("✓ Recency: Yesterday (+3 pts)")
                elif days_old <= 7:
                    breakdown.append("✓ Recency: This week (+1 pt)")
            except:
                pass
        
        # Medium relevance (only if Fall River mentioned)
        medium_relevance = config.get('medium_relevance', [])
        has_fall_river_mention = any(kw in combined for kw in ['fall river', 'fallriver'])
        found_medium = [kw for kw in medium_relevance if kw in combined]
        if found_medium:
            if has_fall_river_mention:
                breakdown.append(f"✓ Nearby towns (with Fall River): {', '.join(found_medium[:2])}{'...' if len(found_medium) > 2 else ''} (+{len(found_medium)} pts)")
            else:
                breakdown.append(f"✗ Nearby towns (without Fall River): {', '.join(found_medium[:2])}{'...' if len(found_medium) > 2 else ''} (-{len(found_medium) * 15} pts)")
        
        # Clickbait patterns
        clickbait_patterns = config.get('clickbait_patterns', [])
        found_clickbait = [pattern for pattern in clickbait_patterns if pattern in combined]
        if found_clickbait:
            breakdown.append(f"✗ Clickbait patterns: {', '.join(found_clickbait[:2])}{'...' if len(found_clickbait) > 2 else ''} (-{len(found_clickbait) * 5} pts)")
        
        if not breakdown:
            breakdown.append("No relevance factors found")
        
        return jsonify({'success': True, 'breakdown': breakdown})
    except Exception as e:
        logger.error(f"Error getting relevance breakdown: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/api/bayesian-stats', methods=['GET', 'OPTIONS'])
@login_required
def get_bayesian_stats():
    """Get Bayesian learning system statistics"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from utils.bayesian_learner import BayesianLearner
        learner = BayesianLearner()
        
        # Get pattern count
        import sqlite3
        from config import DATABASE_CONFIG
        db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM rejection_patterns')
        pattern_count = cursor.fetchone()[0]
        conn.close()
        
        stats = {
            'reject_count': learner.reject_count,
            'accept_count': learner.accept_count,
            'pattern_count': pattern_count
        }
        
        return jsonify({'success': True, 'stats': stats})
    except Exception as e:
        logger.warning(f"Could not get Bayesian stats: {e}")
        return jsonify({'success': True, 'stats': {'reject_count': 0, 'accept_count': 0, 'pattern_count': 0}})


@admin_bp.route('/api/category-stats', methods=['GET', 'OPTIONS'])
@login_required
def get_category_stats():
    """Get category statistics for a zip code"""
    if request.method == 'OPTIONS':
        return '', 200
    
    # Check authentication explicitly
    if 'logged_in' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    zip_code = request.args.get('zip_code') or session.get('zip_code')
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Get categories from database
        try:
            cursor.execute('''
                SELECT name FROM categories WHERE zip_code = ? ORDER BY name
            ''', (zip_code,))
            db_categories = [row[0] for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            db_categories = []
        
        # Get category usage from articles
        cursor.execute('''
            SELECT 
                COALESCE(category, 'uncategorized') as cat,
                COUNT(*) as count
            FROM articles 
            WHERE zip_code = ? OR zip_code IS NULL
            GROUP BY cat
            ORDER BY count DESC
        ''', (zip_code,))
        category_counts = [{'category': row[0], 'count': row[1]} for row in cursor.fetchall()]
        
        # Get keywords per category (both counts and actual keywords)
        keyword_counts = {}
        category_keywords = {}  # Map category slug to list of keywords
        try:
            # Get keyword counts
            cursor.execute('''
                SELECT category, COUNT(*) as keyword_count
                FROM category_keywords
                WHERE zip_code = ?
                GROUP BY category
                ORDER BY category
            ''', (zip_code,))
            keyword_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Get actual keywords for each category
            cursor.execute('''
                SELECT category, keyword
                FROM category_keywords
                WHERE zip_code = ?
                ORDER BY category, keyword
            ''', (zip_code,))
            for row in cursor.fetchall():
                category = row[0]
                keyword = row[1]
                if category not in category_keywords:
                    category_keywords[category] = []
                category_keywords[category].append(keyword)
        except sqlite3.OperationalError:
            keyword_counts = {}
            category_keywords = {}
        
        # Get primary_category usage (from category classifier)
        cursor.execute('''
            SELECT 
                COALESCE(primary_category, 'uncategorized') as cat,
                COUNT(*) as count
            FROM articles 
            WHERE (zip_code = ? OR zip_code IS NULL)
            AND primary_category IS NOT NULL
            GROUP BY cat
            ORDER BY count DESC
        ''', (zip_code,))
        primary_category_counts = [{'category': row[0], 'count': row[1]} for row in cursor.fetchall()]
        
        # Get training statistics from category_patterns table
        training_stats = {
            'total_positive': 0,
            'total_negative': 0,
            'total_examples': 0,
            'bayesian_active': False,
            'category_training': {}
        }
        
        try:
            table_name = f"category_patterns_{zip_code}"
            # Check if table exists
            cursor.execute(f'''
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            ''', (table_name,))
            if cursor.fetchone():
                # Get total training examples
                cursor.execute(f'''
                    SELECT SUM(positive_count), SUM(negative_count) 
                    FROM {table_name}
                ''')
                row = cursor.fetchone()
                if row and (row[0] or row[1]):
                    training_stats['total_positive'] = row[0] or 0
                    training_stats['total_negative'] = row[1] or 0
                    training_stats['total_examples'] = (row[0] or 0) + (row[1] or 0)
                    training_stats['bayesian_active'] = training_stats['total_examples'] >= 50
                
                # Get training examples per category
                cursor.execute(f'''
                    SELECT category, SUM(positive_count) as pos, SUM(negative_count) as neg
                    FROM {table_name}
                    GROUP BY category
                    ORDER BY category
                ''')
                for row in cursor.fetchall():
                    category = row[0]
                    pos = row[1] or 0
                    neg = row[2] or 0
                    training_stats['category_training'][category] = {
                        'positive': pos,
                        'negative': neg,
                        'total': pos + neg
                    }
        except sqlite3.OperationalError as e:
            # Table doesn't exist yet, that's okay
            logger.debug(f"Category patterns table not found for {zip_code}: {e}")
        except Exception as e:
            logger.warning(f"Error getting training stats: {e}")
        
        conn.close()
        
        response = jsonify({
            'success': True,
            'db_categories': db_categories,
            'category_counts': category_counts,
            'keyword_counts': keyword_counts,
            'category_keywords': category_keywords,  # Actual keywords per category
            'primary_category_counts': primary_category_counts,
            'training_stats': training_stats
        })
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        logger.error(f"Error getting category stats: {e}", exc_info=True)
        response = jsonify({'success': False, 'error': str(e)})
        response.headers['Content-Type'] = 'application/json'
        return response, 500


@admin_bp.route('/api/regenerate', methods=['POST', 'OPTIONS'])
@login_required
def regenerate_website_api():
    """Regenerate website for a specific zip code"""
    if request.method == 'OPTIONS':
        return '', 200
    
    zip_code = request.args.get('zip') or session.get('zip_code')
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        # Import regenerate_zip_website from the main admin.py file
        # Since it's in the parent module, we need to import it differently
        import importlib.util
        import os
        
        # Get the path to admin.py in the parent directory
        admin_py_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'admin.py')
        if os.path.exists(admin_py_path):
            spec = importlib.util.spec_from_file_location("admin_main", admin_py_path)
            admin_main = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(admin_main)
            
            if hasattr(admin_main, 'regenerate_zip_website'):
                success, message = admin_main.regenerate_zip_website(zip_code, force_refresh=False)
                if success:
                    return jsonify({'success': True, 'message': message})
                else:
                    return jsonify({'success': False, 'message': message}), 500
        
        # Fallback: return a message that regeneration needs to be done manually
        return jsonify({
            'success': False, 
            'message': 'Regenerate function not available. Please use the main admin interface.'
        }), 500
    except Exception as e:
        logger.error(f"Error regenerating website: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/regenerate-all', methods=['POST', 'OPTIONS'])
@login_required
def regenerate_all_websites_api():
    """Regenerate websites for all zip codes - MAIN ADMIN ONLY"""
    if request.method == 'OPTIONS':
        return '', 200
    
    is_main_admin = session.get('is_main_admin', False)
    if not is_main_admin:
        return jsonify({'success': False, 'error': 'Main admin access required'}), 403
    
    try:
        import subprocess
        import sys
        import os
        
        # Clear cache
        try:
            from cache import get_cache
            cache = get_cache()
            cache.clear_all()
            logger.info("Cache cleared before regeneration")
        except Exception as e:
            logger.warning(f"Could not clear cache: {e}")
        
        # Run the main aggregator
        cmd = [sys.executable, 'main.py', '--once']
        env = os.environ.copy()
        env['FORCE_REFRESH'] = '1'
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            env=env
        )
        
        if result.returncode == 0:
            logger.info("All websites regenerated successfully")
            return jsonify({'success': True, 'message': 'All websites regenerated successfully'})
        else:
            error_msg = result.stderr or result.stdout or 'Unknown error'
            logger.error(f"Regeneration failed: {error_msg}")
            return jsonify({'success': False, 'message': error_msg})
    except subprocess.TimeoutExpired:
        logger.error("Regeneration timed out")
        return jsonify({'success': False, 'message': 'Regeneration timed out'})
    except Exception as e:
        logger.error(f"Error in regenerate_all_websites: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/retrain-categories', methods=['POST', 'OPTIONS'])
@login_required
def retrain_categories_api():
    """Retrain all categories for a zip code"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        from utils.category_classifier import CategoryClassifier
        
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
        
        from admin.utils import map_classifier_to_category
        
        for row in articles:
            article_id = row[0]
            article = {
                'title': row[1] or '',
                'content': row[2] or '',
                'summary': row[3] or '',
                'source': row[4] or ''
            }
            
            primary_category, primary_confidence, secondary_category, secondary_confidence = classifier.predict_category(article)
            
            # Map classifier category names to new category slugs
            category_slug = map_classifier_to_category(primary_category)
            secondary_category_slug = map_classifier_to_category(secondary_category) if secondary_category else None
            
            # Update both primary_category (classifier name) and category (new slug)
            cursor.execute('''
                UPDATE articles 
                SET primary_category = ?, category_confidence = ?, secondary_category = ?, category = ?
                WHERE id = ?
            ''', (primary_category, primary_confidence, secondary_category, category_slug, article_id))
            
            updated_count += 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"Retrained categories for {updated_count} articles in zip {zip_code}")
        return jsonify({'success': True, 'message': f'Retrained categories for {updated_count} articles'})
    except Exception as e:
        logger.error(f"Error retraining categories: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/add-category', methods=['POST', 'OPTIONS'])
@login_required
def add_category_api():
    """Add a new category"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    category = data.get('category', '').strip()
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not category:
        return jsonify({'success': False, 'error': 'Category name required'}), 400
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Check if category already exists
        cursor.execute('''
            SELECT id FROM categories 
            WHERE name = ? AND zip_code = ?
        ''', (category, zip_code))
        
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'error': 'Category already exists'}), 400
        
        # Add category
        cursor.execute('''
            INSERT INTO categories (name, zip_code)
            VALUES (?, ?)
        ''', (category, zip_code))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Added category '{category}' for zip {zip_code}")
        return jsonify({'success': True, 'message': 'Category added successfully'})
    except Exception as e:
        logger.error(f"Error adding category: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/category-keyword', methods=['POST', 'DELETE', 'OPTIONS'])
@login_required
def manage_category_keyword():
    """Add or remove a keyword from a category"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    category = data.get('category', '').strip()
    keyword = data.get('keyword', '').strip()
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not category:
        return jsonify({'success': False, 'error': 'Category required'}), 400
    
    if not keyword:
        return jsonify({'success': False, 'error': 'Keyword required'}), 400
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    # Validate keyword length
    if len(keyword) < 2:
        return jsonify({'success': False, 'error': 'Keyword must be at least 2 characters'}), 400
    
    if len(keyword) > 100:
        return jsonify({'success': False, 'error': 'Keyword must be less than 100 characters'}), 400
    
    try:
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Ensure category_keywords table exists
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS category_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zip_code TEXT NOT NULL,
                    category TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(zip_code, category, keyword)
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_category_keywords_lookup 
                ON category_keywords(zip_code, category)
            ''')
            conn.commit()
        except Exception as e:
            logger.warning(f"Error ensuring category_keywords table exists: {e}")
        
        if request.method == 'POST':
            # Add keyword
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO category_keywords (zip_code, category, keyword)
                    VALUES (?, ?, ?)
                ''', (zip_code, category, keyword.lower()))
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"Added keyword '{keyword}' to category '{category}' for zip {zip_code}")
                    return jsonify({'success': True, 'message': f'Keyword "{keyword}" added to {category}'})
                else:
                    return jsonify({'success': False, 'error': 'Keyword already exists'}), 400
            except sqlite3.IntegrityError:
                return jsonify({'success': False, 'error': 'Keyword already exists'}), 400
        
        elif request.method == 'DELETE':
            # Remove keyword
            cursor.execute('''
                DELETE FROM category_keywords
                WHERE zip_code = ? AND category = ? AND keyword = ?
            ''', (zip_code, category, keyword.lower()))
            conn.commit()
            
            if cursor.rowcount > 0:
                logger.info(f"Removed keyword '{keyword}' from category '{category}' for zip {zip_code}")
                return jsonify({'success': True, 'message': f'Keyword "{keyword}" removed from {category}'})
            else:
                return jsonify({'success': False, 'error': 'Keyword not found'}), 404
        
        conn.close()
    except Exception as e:
        logger.error(f"Error managing category keyword: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/recalculate-categories', methods=['POST', 'OPTIONS'])
@login_required
def recalculate_categories():
    """Recalculate category, primary_category, and local_score for all articles"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        from utils.category_classifier import CategoryClassifier
        from admin.utils import map_classifier_to_category, calculate_local_focus_score
        
        classifier = CategoryClassifier(zip_code)
        conn = get_db_legacy()
        cursor = conn.cursor()
        
        # Ensure byline/author columns exist
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN byline TEXT')
            conn.commit()
        except:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE articles ADD COLUMN author TEXT')
            conn.commit()
        except:
            pass  # Column already exists
        
        # Get all articles for this zip
        cursor.execute('''
            SELECT id, title, content, summary, source, byline, author
            FROM articles 
            WHERE zip_code = ?
        ''', (zip_code,))
        
        articles = cursor.fetchall()
        updated_count = 0
        
        for row in articles:
            article_id = row[0]
            article = {
                'title': row[1] or '',
                'content': row[2] or '',
                'summary': row[3] or '',
                'source': row[4] or '',
                'byline': row[5] or row[6] or ''
            }
            
            # Skip articles with no content
            if not article['title'] and not article['content'] and not article['summary']:
                continue
            
            # Reclassify article
            primary_category, primary_confidence, secondary_category, secondary_confidence = classifier.predict_category(article)
            category_slug = map_classifier_to_category(primary_category)
            
            # Recalculate local focus score
            local_focus_score = calculate_local_focus_score(article, zip_code=zip_code)
            
            # Update article
            cursor.execute('''
                UPDATE articles 
                SET primary_category = ?, category_confidence = ?, 
                    secondary_category = ?, category = ?, local_score = ?
                WHERE id = ?
            ''', (primary_category, primary_confidence, secondary_category, category_slug, local_focus_score, article_id))
            
            updated_count += 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"Recalculated categories for {updated_count} articles in zip {zip_code}")
        return jsonify({'success': True, 'message': f'Recalculated categories for {updated_count} articles'})
    except Exception as e:
        logger.error(f"Error recalculating categories: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/recategorize-all', methods=['POST', 'OPTIONS'])
@login_required
def recategorize_all_articles():
    """Recategorize all articles based on current keywords and training data"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not zip_code:
        return jsonify({'success': False, 'error': 'Zip code required'}), 400
    
    try:
        from utils.category_classifier import CategoryClassifier
        from admin.utils import map_classifier_to_category
        
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
            
            # Skip articles with no content
            if not article['title'] and not article['content'] and not article['summary']:
                continue
            
            # Reclassify article
            primary_category, primary_confidence, secondary_category, secondary_confidence = classifier.predict_category(article)
            
            # Map classifier category names to new category slugs
            category_slug = map_classifier_to_category(primary_category)
            secondary_category_slug = map_classifier_to_category(secondary_category) if secondary_category else None
            
            # Update both primary_category (classifier name) and category (new slug)
            cursor.execute('''
                UPDATE articles 
                SET primary_category = ?, category_confidence = ?, secondary_category = ?, category = ?
                WHERE id = ?
            ''', (primary_category, primary_confidence, secondary_category, category_slug, article_id))
            
            updated_count += 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"Recategorized {updated_count} articles in zip {zip_code}")
        return jsonify({'success': True, 'message': f'Recategorized {updated_count} articles'})
    except Exception as e:
        logger.error(f"Error recategorizing articles: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500


@admin_bp.route('/api/add-source', methods=['POST', 'OPTIONS'])
@login_required
def add_source_api():
    """Add a new source"""
    if request.method == 'OPTIONS':
        return '', 200
    
    data = request.json or {}
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()
    zip_code = data.get('zip_code') or session.get('zip_code')
    
    if not name or not url:
        return jsonify({'success': False, 'error': 'Name and URL required'}), 400
    
    try:
        # For now, return a message that this needs to be configured in config.py
        # In a full implementation, this would add to a sources table or config
        return jsonify({
            'success': False, 
            'message': 'Adding sources via API is not yet implemented. Please add sources in config.py'
        }), 501
    except Exception as e:
        logger.error(f"Error adding source: {e}", exc_info=True)
        return jsonify({'success': False, 'message': str(e)}), 500

