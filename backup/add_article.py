"""
Add custom articles to the database
"""
import sqlite3
from datetime import datetime
from config import DATABASE_CONFIG
from database import ArticleDatabase

def add_custom_article(title, content, url="", source="Custom Article", summary=""):
    """Add a custom article"""
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
    return article

if __name__ == '__main__':
    print("=" * 60)
    print("Add Custom Article")
    print("=" * 60)
    print()
    
    title = input("Article Title: ")
    if not title:
        print("Title is required!")
        exit(1)
    
    print("\nArticle Content (press Enter twice when done):")
    lines = []
    while True:
        line = input()
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)
    
    content = "\n".join(lines).strip()
    if not content:
        print("Content is required!")
        exit(1)
    
    url = input("\nURL (optional, press Enter to skip): ").strip()
    source = input("Source name (default: 'Custom Article'): ").strip() or "Custom Article"
    summary = input("Summary (optional, press Enter to auto-generate): ").strip()
    
    add_custom_article(title, content, url, source, summary)
    print("\n✓ Article added successfully!")
    print("Run 'python main.py --once' to regenerate the website.")



