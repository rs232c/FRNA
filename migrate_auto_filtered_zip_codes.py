"""Migrate auto-filtered articles to have zip_code"""
import sqlite3
from config import DATABASE_CONFIG

print("=" * 60)
print("MIGRATING AUTO-FILTERED ARTICLES TO INCLUDE ZIP_CODE")
print("=" * 60)

conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
cursor = conn.cursor()

# Ensure columns exist
try:
    cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
except:
    pass
try:
    cursor.execute('ALTER TABLE article_management ADD COLUMN zip_code TEXT')
except:
    pass
conn.commit()

# Get BEFORE statistics
cursor.execute('''
    SELECT COUNT(*) FROM article_management 
    WHERE is_auto_rejected = 1
''')
total_before = cursor.fetchone()[0]

cursor.execute('''
    SELECT COUNT(*) FROM article_management 
    WHERE is_auto_rejected = 1 
    AND (zip_code IS NULL OR zip_code = '')
''')
null_before = cursor.fetchone()[0]

print(f"\nBEFORE MIGRATION:")
print(f"  Total auto-filtered articles: {total_before}")
print(f"  Without zip_code: {null_before}")
print(f"  With zip_code: {total_before - null_before}")

if null_before == 0:
    print("\n✓ No migration needed - all auto-filtered articles already have zip_code")
    conn.close()
    exit(0)

# Find auto-filtered articles without zip_code that have zip_code in articles table
cursor.execute('''
    SELECT am.article_id, a.zip_code
    FROM article_management am
    JOIN articles a ON am.article_id = a.id
    WHERE am.is_auto_rejected = 1 
    AND (am.zip_code IS NULL OR am.zip_code = '')
    AND a.zip_code IS NOT NULL
''')

rows = cursor.fetchall()
print(f"\nSTEP 1: Migrating {len(rows)} articles from articles.zip_code...")

migrated_count = 0
for article_id, article_zip in rows:
    cursor.execute('''
        UPDATE article_management 
        SET zip_code = ?
        WHERE article_id = ? 
        AND (zip_code IS NULL OR zip_code = '')
        AND is_auto_rejected = 1
    ''', (article_zip, article_id))
    if cursor.rowcount > 0:
        migrated_count += 1

conn.commit()
print(f"✓ Migrated {migrated_count} auto-filtered articles from articles.zip_code")

# For articles without zip_code in articles table, assign default (02720)
cursor.execute('''
    SELECT COUNT(*) FROM article_management 
    WHERE is_auto_rejected = 1 
    AND (zip_code IS NULL OR zip_code = '')
    AND article_id IN (
        SELECT id FROM articles WHERE zip_code IS NULL OR zip_code = ''
    )
''')
count = cursor.fetchone()[0]

default_assigned = 0
if count > 0:
    print(f"\nSTEP 2: Assigning default zip_code (02720) to {count} articles...")
    cursor.execute('''
        UPDATE article_management 
        SET zip_code = '02720'
        WHERE is_auto_rejected = 1 
        AND (zip_code IS NULL OR zip_code = '')
        AND article_id IN (
            SELECT id FROM articles WHERE zip_code IS NULL OR zip_code = ''
        )
    ''')
    default_assigned = cursor.rowcount
    conn.commit()
    print(f"✓ Assigned default zip_code (02720) to {default_assigned} auto-filtered articles")

# Handle any remaining orphaned entries (article_management without matching article)
cursor.execute('''
    SELECT COUNT(*) FROM article_management 
    WHERE is_auto_rejected = 1 
    AND (zip_code IS NULL OR zip_code = '')
    AND article_id NOT IN (SELECT id FROM articles)
''')
orphaned_count = cursor.fetchone()[0]

if orphaned_count > 0:
    print(f"\nSTEP 3: Handling {orphaned_count} orphaned entries...")
    cursor.execute('''
        UPDATE article_management 
        SET zip_code = '02720'
        WHERE is_auto_rejected = 1 
        AND (zip_code IS NULL OR zip_code = '')
        AND article_id NOT IN (SELECT id FROM articles)
    ''')
    orphaned_assigned = cursor.rowcount
    conn.commit()
    print(f"✓ Assigned default zip_code (02720) to {orphaned_assigned} orphaned entries")

# Get AFTER statistics
cursor.execute('''
    SELECT COUNT(*) FROM article_management 
    WHERE is_auto_rejected = 1
''')
total_after = cursor.fetchone()[0]

cursor.execute('''
    SELECT COUNT(*) FROM article_management 
    WHERE is_auto_rejected = 1 
    AND (zip_code IS NULL OR zip_code = '')
''')
null_after = cursor.fetchone()[0]

# Breakdown by zip_code
cursor.execute('''
    SELECT 
        COALESCE(zip_code, 'NULL') as zip_code,
        COUNT(*) as count
    FROM article_management
    WHERE is_auto_rejected = 1
    GROUP BY zip_code
    ORDER BY count DESC
''')
zip_breakdown = cursor.fetchall()

conn.close()

print(f"\n" + "=" * 60)
print("MIGRATION COMPLETE!")
print("=" * 60)
print(f"\nBEFORE:")
print(f"  Total: {total_before}")
print(f"  Without zip_code: {null_before}")
print(f"\nAFTER:")
print(f"  Total: {total_after}")
print(f"  Without zip_code: {null_after}")
print(f"\nMIGRATED:")
print(f"  From articles.zip_code: {migrated_count}")
print(f"  Assigned default (02720): {default_assigned}")
if orphaned_count > 0:
    print(f"  Orphaned entries fixed: {orphaned_assigned}")

print(f"\nBREAKDOWN BY ZIP_CODE:")
for zip_code, count in zip_breakdown:
    print(f"  {zip_code}: {count}")

if null_after > 0:
    print(f"\n⚠️  WARNING: {null_after} auto-filtered articles still have NULL zip_code")
    print("   These may need manual review.")
else:
    print(f"\n✓ All auto-filtered articles now have zip_code assigned!")

print("=" * 60)

