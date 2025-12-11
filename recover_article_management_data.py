"""Recover lost article_management data (is_top_story, is_good_fit, etc.) from older entries"""
import sqlite3
from config import DATABASE_CONFIG
from datetime import datetime, timedelta

def recover_article_management_data():
    """Attempt to recover lost data from older article_management entries"""
    conn = sqlite3.connect(DATABASE_CONFIG.get("path", "fallriver_news.db"))
    cursor = conn.cursor()
    
    # Get all current article_management entries that might have lost data
    # (entries where is_top_story, is_good_fit, etc. are 0 or NULL but might have had values before)
    cursor.execute('''
        SELECT DISTINCT article_id, zip_code
        FROM article_management
        WHERE (is_top_story = 0 OR is_top_story IS NULL)
           OR (is_good_fit = 0 OR is_good_fit IS NULL)
        ORDER BY article_id, zip_code
    ''')
    
    articles_to_check = cursor.fetchall()
    print(f"Found {len(articles_to_check)} articles that might have lost data")
    
    recovered_count = 0
    
    for article_id, zip_code in articles_to_check:
        # Look for older entries for this article_id + zip_code that might have the data
        # Check ALL entries, not just the latest one
        cursor.execute('''
            SELECT is_top_story, is_good_fit, display_order, is_stellar, ROWID
            FROM article_management
            WHERE article_id = ? AND zip_code = ?
            ORDER BY ROWID DESC
        ''', (article_id, zip_code))
        
        all_entries = cursor.fetchall()
        
        if len(all_entries) > 1:
            # Multiple entries exist - check if any older entry has non-zero values
            newest_entry = all_entries[0]
            current_top_story = newest_entry[0] or 0
            current_good_fit = newest_entry[1] or 0
            current_display_order = newest_entry[2] or article_id
            current_stellar = newest_entry[3] or 0
            newest_rowid = newest_entry[4]
            
            # Check older entries for non-zero values
            for entry in all_entries[1:]:  # Skip the first (newest) one
                top_story, good_fit, display_order, stellar, rowid = entry
                
                # If this older entry has any non-zero values, use them
                if (top_story and top_story != 0) or (good_fit and good_fit != 0) or (stellar and stellar != 0) or (display_order and display_order != article_id):
                    # Use older values if they're non-zero and current is zero/default
                    new_top_story = top_story if (top_story and top_story != 0 and current_top_story == 0) else current_top_story
                    new_good_fit = good_fit if (good_fit and good_fit != 0 and current_good_fit == 0) else current_good_fit
                    new_display_order = display_order if (display_order and display_order != article_id and current_display_order == article_id) else current_display_order
                    new_stellar = stellar if (stellar and stellar != 0 and current_stellar == 0) else current_stellar
                    
                    # Only update if we found better values
                    if (new_top_story != current_top_story or new_good_fit != current_good_fit or 
                        new_display_order != current_display_order or new_stellar != current_stellar):
                        # Update the newest entry
                        cursor.execute('''
                            UPDATE article_management
                            SET is_top_story = ?, is_good_fit = ?, display_order = ?, is_stellar = ?
                            WHERE ROWID = ?
                        ''', (new_top_story, new_good_fit, new_display_order, new_stellar, newest_rowid))
                        
                        recovered_count += 1
                        print(f"Recovered data for article {article_id} (zip {zip_code}): top_story={new_top_story}, good_fit={new_good_fit}, stellar={new_stellar}, display_order={new_display_order}")
                        break
    
    conn.commit()
    print(f"\nRecovery complete: Restored data for {recovered_count} articles")
    conn.close()

if __name__ == '__main__':
    print("Attempting to recover lost article_management data...")
    print("This script looks for older article_management entries that might have preserved values.")
    print("=" * 60)
    recover_article_management_data()
    print("=" * 60)
    print("Recovery script finished. Check the output above for details.")

