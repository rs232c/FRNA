"""
Simple admin interface - no web server needed
Directly modifies database and regenerates website
"""
import sqlite3
from config import DATABASE_CONFIG
from website_generator import WebsiteGenerator
from aggregator import NewsAggregator
from ingestors.weather_ingestor import WeatherIngestor

def get_db():
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    conn.row_factory = sqlite3.Row
    return conn

def show_articles():
    """Show all articles with their status"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT a.*, 
               COALESCE(am.enabled, 1) as enabled,
               COALESCE(am.display_order, a.id) as display_order
        FROM articles a
        LEFT JOIN article_management am ON a.id = am.article_id
        ORDER BY COALESCE(am.display_order, a.id) ASC
    ''')
    
    articles = cursor.fetchall()
    conn.close()
    
    print("\n" + "="*80)
    print("ARTICLES")
    print("="*80)
    for i, article in enumerate(articles, 1):
        status = "✓" if article['enabled'] else "✗"
        print(f"{i}. [{status}] {article['title'][:60]}")
        print(f"   Source: {article['source']} | Order: {article['display_order']}")
    print("="*80)
    return articles

def toggle_article(article_id, enabled):
    """Enable/disable an article"""
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
    """Toggle image visibility"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO admin_settings (key, value)
        VALUES ('show_images', ?)
    ''', ('1' if show else '0',))
    
    conn.commit()
    conn.close()
    print(f"Images {'shown' if show else 'hidden'}")

def regenerate():
    """Regenerate website"""
    print("\nRegenerating website...")
    aggregator = NewsAggregator()
    articles = aggregator.aggregate()
    
    weather = WeatherIngestor().fetch_weather()
    generator = WebsiteGenerator()
    generator.generate(articles)
    
    print("✓ Website regenerated!")

def main():
    while True:
        articles = show_articles()
        
        print("\nOptions:")
        print("1. Toggle article (enable/disable)")
        print("2. Show/hide images")
        print("3. Regenerate website")
        print("4. Exit")
        
        choice = input("\nEnter choice (1-4): ").strip()
        
        if choice == '1':
            try:
                num = int(input("Enter article number: "))
                if 1 <= num <= len(articles):
                    article = articles[num - 1]
                    current = article['enabled']
                    toggle_article(article['id'], not current)
                else:
                    print("Invalid number")
            except ValueError:
                print("Invalid input")
        
        elif choice == '2':
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM admin_settings WHERE key='show_images'")
            result = cursor.fetchone()
            current = result['value'] == '1' if result else True
            conn.close()
            
            set_image_visibility(not current)
        
        elif choice == '3':
            regenerate()
        
        elif choice == '4':
            print("Goodbye!")
            break
        
        else:
            print("Invalid choice")

if __name__ == '__main__':
    main()



