"""
Backend script for admin actions - no Flask needed
"""
import sqlite3
import json
import sys
from config import DATABASE_CONFIG
from website_generator import WebsiteGenerator
from aggregator import NewsAggregator
from ingestors.weather_ingestor import WeatherIngestor

def get_db():
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    return conn

def toggle_article(article_id, enabled):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order)
        VALUES (?, ?, COALESCE((SELECT display_order FROM article_management WHERE article_id = ?), ?))
    ''', (article_id, 1 if enabled else 0, article_id, article_id))
    conn.commit()
    conn.close()
    print(f"Article {article_id} {'enabled' if enabled else 'disabled'}")

def set_image_visibility(show):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('show_images', ?)
    ''', ('1' if show else '0',))
    conn.commit()
    conn.close()
    print(f"Images {'shown' if show else 'hidden'}")

def reorder_articles(orders):
    conn = get_db()
    cursor = conn.cursor()
    for item in orders:
        article_id = item.get('id')
        order = item.get('order')
        cursor.execute('''
            INSERT OR REPLACE INTO article_management (article_id, enabled, display_order)
            VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ?), 1), ?)
        ''', (article_id, article_id, order))
    conn.commit()
    conn.close()
    print("Order saved")

def regenerate():
    print("Regenerating website...")
    try:
        aggregator = NewsAggregator()
        articles = aggregator.aggregate()
        weather = WeatherIngestor().fetch_weather()
        generator = WebsiteGenerator()
        generator.generate(articles)
        print("✓ Website regenerated successfully!")
        return True
    except Exception as e:
        print(f"✗ Error regenerating: {e}")
        return False

def update_source_setting(source_key, setting, value):
    """Update source configuration"""
    import sqlite3
    from config import DATABASE_CONFIG
    
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    cursor = conn.cursor()
    
    key = f"source_{source_key}_{setting}"
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES (?, ?)
    ''', (key, '1' if value else '0'))
    
    conn.commit()
    conn.close()
    print(f"Source {source_key} setting {setting} updated to {value}")

def make_top_article(article_id):
    """Set an article as top article"""
    conn = get_db()
    cursor = conn.cursor()
    
    # First, unset all other top articles
    cursor.execute('UPDATE article_management SET is_top_article = 0')
    
    # Set this article as top
    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, is_top_article, is_top_story)
        VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ?), 1), 
                COALESCE((SELECT display_order FROM article_management WHERE article_id = ?), ?), 1,
                COALESCE((SELECT is_top_story FROM article_management WHERE article_id = ?), 0))
    ''', (article_id, article_id, article_id, article_id, article_id))
    
    conn.commit()
    conn.close()
    print(f"✓ Article {article_id} set as top article")

def toggle_top_story(article_id, is_top_story):
    """Toggle top story status for an article"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO article_management (article_id, enabled, display_order, is_top_article, is_top_story)
        VALUES (?, COALESCE((SELECT enabled FROM article_management WHERE article_id = ?), 1), 
                COALESCE((SELECT display_order FROM article_management WHERE article_id = ?), ?),
                COALESCE((SELECT is_top_article FROM article_management WHERE article_id = ?), 0), ?)
    ''', (article_id, article_id, article_id, article_id, article_id, 1 if is_top_story else 0))
    
    conn.commit()
    conn.close()
    print(f"✓ Article {article_id} top story set to {is_top_story}")

def edit_article(article_id, title, summary, category=None, url=None):
    """Edit article title, summary, category, and URL"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Clean bad characters
    import re
    title = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', title) if title else ''
    summary = re.sub(r'[^\x00-\x7F\u00A0-\uFFFF]', '', summary) if summary else ''
    url = url if url else None
    
    if category and url:
        cursor.execute('''
            UPDATE articles
            SET title = ?, summary = ?, category = ?, url = ?
            WHERE id = ?
        ''', (title, summary, category, url, article_id))
    elif category:
        cursor.execute('''
            UPDATE articles
            SET title = ?, summary = ?, category = ?
            WHERE id = ?
        ''', (title, summary, category, article_id))
    elif url:
        cursor.execute('''
            UPDATE articles
            SET title = ?, summary = ?, url = ?
            WHERE id = ?
        ''', (title, summary, url, article_id))
    else:
        cursor.execute('''
            UPDATE articles
            SET title = ?, summary = ?
            WHERE id = ?
        ''', (title, summary, article_id))
    
    conn.commit()
    conn.close()
    print(f"✓ Article {article_id} updated: title, summary" + (f", category={category}" if category else "") + (f", url={url}" if url else ""))

def set_regenerate_settings(auto_regenerate, interval, regenerate_on_load=False):
    """Set auto-regenerate settings"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('auto_regenerate', ?)
    ''', ('1' if auto_regenerate else '0',))
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('regenerate_interval', ?)
    ''', (str(interval),))
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('regenerate_on_load', ?)
    ''', ('1' if regenerate_on_load else '0',))
    conn.commit()
    conn.close()
    print(f"Regenerate settings: auto={auto_regenerate}, interval={interval}min, on_load={regenerate_on_load}")

def add_custom_article(title, content, url="", source="Custom Article", summary=""):
    """Add a custom article"""
    from datetime import datetime
    from database import ArticleDatabase
    
    db = ArticleDatabase()
    
    article = {
        "title": title,
        "url": url or f"#custom-{datetime.now().timestamp()}",
        "published": datetime.now().isoformat(),
        "summary": summary or content[:200] + "..." if len(content) > 200 else content,
        "content": content,
        "source": source,
        "source_type": "custom",
        "ingested_at": datetime.now().isoformat()
    }
    
    article_ids = db.save_articles([article])
    print(f"✓ Article added! ID: {article_ids[0] if article_ids else 'N/A'}")
    return article_ids[0] if article_ids else None

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python admin_backend.py <action> [args]")
        sys.exit(1)
    
    action = sys.argv[1]
    
    if action == 'toggle':
        article_id = int(sys.argv[2])
        enabled = sys.argv[3].lower() == 'true'
        toggle_article(article_id, enabled)
    elif action == 'images':
        show = sys.argv[2].lower() == 'true'
        set_image_visibility(show)
    elif action == 'order':
        orders_json = sys.argv[2]
        orders = json.loads(orders_json)
        reorder_articles(orders)
    elif action == 'regenerate':
        regenerate()
    elif action == 'add':
        title = sys.argv[2]
        content = sys.argv[3]
        source = sys.argv[4] if len(sys.argv) > 4 else 'Custom Article'
        url = sys.argv[5] if len(sys.argv) > 5 else ''
        add_custom_article(title, content, url, source)
    elif action == 'source':
        source_key = sys.argv[2]
        setting = sys.argv[3]
        value = sys.argv[4].lower() == 'true'
        update_source_setting(source_key, setting, value)
    elif action == 'top-article':
        article_id = int(sys.argv[2])
        make_top_article(article_id)
    elif action == 'top-story':
        article_id = int(sys.argv[2])
        is_top_story = sys.argv[3].lower() == 'true'
        toggle_top_story(article_id, is_top_story)
    elif action == 'edit-article':
        article_id = int(sys.argv[2])
        title = sys.argv[3]
        summary = sys.argv[4]
        category = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] != 'None' else None
        url = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] != 'None' else None
        edit_article(article_id, title, summary, category, url)
    elif action == 'regenerate-settings':
        auto_regen = sys.argv[2].lower() == 'true'
        interval = int(sys.argv[3])
        set_regenerate_settings(auto_regen, interval)
    else:
        print(f"Unknown action: {action}")

