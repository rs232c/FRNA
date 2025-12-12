"""Diagnostic script to check auto-filtered articles in database"""
import sqlite3
from datetime import datetime
from config import DATABASE_CONFIG

print("=" * 60)
print("AUTO-FILTERED ARTICLES DIAGNOSTIC")
print("=" * 60)

conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
cursor = conn.cursor()

# Ensure columns exist
try:
    cursor.execute('ALTER TABLE article_management ADD COLUMN is_auto_rejected INTEGER DEFAULT 0')
except:
    pass
try:
    cursor.execute('ALTER TABLE article_management ADD COLUMN auto_reject_reason TEXT')
except:
    pass
try:
    cursor.execute('ALTER TABLE article_management ADD COLUMN zip_code TEXT')
except:
    pass
conn.commit()

# Total auto-filtered articles
cursor.execute('''
    SELECT COUNT(*) 
    FROM article_management 
    WHERE is_auto_rejected = 1
''')
total_auto_filtered = cursor.fetchone()[0]

print(f"\n1. TOTAL AUTO-FILTERED ARTICLES: {total_auto_filtered}")

# Auto-filtered by zip_code
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

print(f"\n2. AUTO-FILTERED BY ZIP_CODE:")
print(f"{'Zip Code':<15} {'Count':<10}")
print("-" * 25)
for zip_code, count in zip_breakdown:
    print(f"{zip_code:<15} {count:<10}")

# Articles with NULL zip_code
cursor.execute('''
    SELECT COUNT(*) 
    FROM article_management 
    WHERE is_auto_rejected = 1 
    AND (zip_code IS NULL OR zip_code = '')
''')
null_zip_count = cursor.fetchone()[0]

print(f"\n3. AUTO-FILTERED WITH NULL/EMPTY ZIP_CODE: {null_zip_count}")

# Sample auto-filtered articles
cursor.execute('''
    SELECT 
        a.id,
        a.title,
        a.source,
        am.auto_reject_reason,
        COALESCE(am.zip_code, 'NULL') as zip_code,
        a.created_at
    FROM articles a
    JOIN article_management am ON a.id = am.article_id
    WHERE am.is_auto_rejected = 1
    ORDER BY a.created_at DESC
    LIMIT 10
''')

samples = cursor.fetchall()

print(f"\n4. SAMPLE AUTO-FILTERED ARTICLES (last 10):")
print("-" * 80)
for article_id, title, source, reason, zip_code, created_at in samples:
    title_short = (title[:50] + "...") if title and len(title) > 50 else (title or "No title")
    reason_short = (reason[:30] + "...") if reason and len(reason) > 30 else (reason or "No reason")
    print(f"ID: {article_id:<6} | Zip: {zip_code:<8} | Source: {source[:20]:<20}")
    print(f"  Title: {title_short}")
    print(f"  Reason: {reason_short}")
    print(f"  Created: {created_at}")
    print()

# Check if articles exist in articles table
cursor.execute('''
    SELECT COUNT(DISTINCT am.article_id)
    FROM article_management am
    LEFT JOIN articles a ON am.article_id = a.id
    WHERE am.is_auto_rejected = 1
    AND a.id IS NULL
''')
orphaned_count = cursor.fetchone()[0]

if orphaned_count > 0:
    print(f"⚠️  WARNING: {orphaned_count} auto-filtered article_management entries have no matching article")
else:
    print("✓ All auto-filtered entries have matching articles")

# Check rejection reasons breakdown
cursor.execute('''
    SELECT 
        CASE 
            WHEN auto_reject_reason LIKE '%relevance score%' THEN 'Relevance Threshold'
            WHEN auto_reject_reason LIKE '%Bayesian%' OR auto_reject_reason LIKE '%similarity%' THEN 'Bayesian Filter'
            ELSE 'Other'
        END as reject_type,
        COUNT(*) as count
    FROM article_management
    WHERE is_auto_rejected = 1
    AND auto_reject_reason IS NOT NULL
    GROUP BY reject_type
    ORDER BY count DESC
''')
reject_types = cursor.fetchall()

print(f"\n5. REJECTION TYPE BREAKDOWN:")
for reject_type, count in reject_types:
    print(f"  {reject_type}: {count}")

conn.close()

print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
print("\nNext steps:")
print("1. If you see NULL zip_code entries, run: python migrate_auto_filtered_zip_codes.py")
print("2. Check trash tab in admin - should now show auto-filtered articles")
print("3. Run new ingestion to verify new auto-filtered articles appear with zip_code")

