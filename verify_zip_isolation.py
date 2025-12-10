#!/usr/bin/env python3
"""Verify zip code data isolation"""
import sqlite3
from pathlib import Path
from config import DATABASE_CONFIG, WEBSITE_CONFIG

def verify_zip_isolation():
    db_path = DATABASE_CONFIG.get("path", "fallriver_news.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=" * 60)
    print("ZIP CODE ISOLATION VERIFICATION")
    print("=" * 60)
    
    # 1. Check articles per zip
    print("\n1. Articles per zip_code:")
    cursor.execute('''
        SELECT zip_code, COUNT(*) as count 
        FROM articles 
        GROUP BY zip_code 
        ORDER BY zip_code
    ''')
    articles_by_zip = cursor.fetchall()
    for row in articles_by_zip:
        zip_code, count = row
        print(f"   {zip_code or 'NULL'}: {count} articles")
    
    if not articles_by_zip:
        print("   ⚠️  WARNING: No articles found in database")
    
    # 2. Check for NULL zip_code
    cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code IS NULL')
    null_count = cursor.fetchone()[0]
    if null_count > 0:
        print(f"\n   ⚠️  WARNING: {null_count} articles with NULL zip_code")
    else:
        print("\n   ✓ No NULL zip_code entries")
    
    # 3. Check article_management per zip
    print("\n2. Article management entries per zip_code:")
    cursor.execute('''
        SELECT zip_code, COUNT(DISTINCT article_id) as count 
        FROM article_management 
        GROUP BY zip_code 
        ORDER BY zip_code
    ''')
    mgmt_by_zip = cursor.fetchall()
    for row in mgmt_by_zip:
        zip_code, count = row
        print(f"   {zip_code or 'NULL'}: {count} articles")
    
    # 4. Check for cross-contamination (articles with wrong zip in management)
    print("\n3. Checking for cross-contamination...")
    cursor.execute('''
        SELECT a.id, a.zip_code as article_zip, am.zip_code as mgmt_zip, COUNT(*) as count
        FROM articles a
        INNER JOIN article_management am ON a.id = am.article_id
        WHERE a.zip_code IS NOT NULL 
          AND am.zip_code IS NOT NULL
          AND a.zip_code != am.zip_code
        GROUP BY a.id, a.zip_code, am.zip_code
        LIMIT 10
    ''')
    leaks = cursor.fetchall()
    if leaks:
        print(f"   ⚠️  WARNING: Found {len(leaks)} potential leaks:")
        for leak in leaks[:5]:
            print(f"      Article {leak[0]}: article.zip={leak[1]}, mgmt.zip={leak[2]}")
    else:
        print("   ✓ No cross-contamination detected")
    
    # 5. Check website output directories
    print("\n4. Website output directories:")
    output_dir = Path(WEBSITE_CONFIG.get("output_dir", "website_output"))
    if output_dir.exists():
        zip_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("zip_")]
        if zip_dirs:
            for zip_dir in sorted(zip_dirs):
                zip_code = zip_dir.name.replace("zip_", "")
                index_file = zip_dir / "index.html"
                category_dir = zip_dir / "category"
                print(f"   {zip_code}: {'✓' if index_file.exists() else '✗'} index.html | "
                      f"{'✓' if category_dir.exists() else '✗'} category/")
        else:
            print("   No zip-specific directories found")
            # Check for root index.html
            root_index = output_dir / "index.html"
            if root_index.exists():
                print(f"   Root index.html exists (default/02720)")
    else:
        print(f"   ⚠️  Output directory does not exist: {output_dir}")
    
    # 6. Check specific zip codes (02720, 02840)
    print("\n5. Specific zip code verification:")
    test_zips = ["02720", "02840"]
    for test_zip in test_zips:
        cursor.execute('SELECT COUNT(*) FROM articles WHERE zip_code = ?', (test_zip,))
        count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(DISTINCT article_id) FROM article_management WHERE zip_code = ?', (test_zip,))
        mgmt_count = cursor.fetchone()[0]
        print(f"   {test_zip}: {count} articles, {mgmt_count} management entries")
    
    # 7. Summary
    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)
    
    # Recommendations
    if null_count > 0:
        print(f"\n⚠️  RECOMMENDATION: Migrate {null_count} NULL zip_code articles to '02720'")
    if leaks:
        print(f"\n⚠️  RECOMMENDATION: Fix {len(leaks)} cross-contamination issues")
    
    conn.close()

if __name__ == "__main__":
    verify_zip_isolation()

