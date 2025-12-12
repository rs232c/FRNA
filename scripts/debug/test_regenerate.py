import sqlite3
from website_generator import WebsiteGenerator

# Check current setting
conn = sqlite3.connect('fallriver_news.db')
cursor = conn.cursor()
cursor.execute('SELECT value FROM admin_settings WHERE key = ?', ('show_images',))
row = cursor.fetchone()
print(f'show_images setting: {row[0] if row else "NOT SET"}')
conn.close()

# Regenerate website
print('\nRegenerating website...')
generator = WebsiteGenerator()
from database import ArticleDatabase
db = ArticleDatabase()
articles = db.get_all_articles()
print(f'Found {len(articles)} articles')
generator.generate(articles)
print('Website regenerated!')

