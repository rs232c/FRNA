# Fix Zip-Specific Data Isolation - All Tabs

## Problem
No data is showing in any admin tabs (articles, sources, trash, etc.) for any zip code. The database shows:
- 97 articles for 02720, 0 for 02840
- 486 article_management entries with NULL zip_code (old unmigrated data)
- Sources not showing correctly
- All tabs empty

## Root Cause
1. **Article queries too strict**: The query filters articles by zip_code, but article_management entries with NULL zip_code don't match
2. **Old data not migrated**: 486 article_management entries have NULL zip_code and aren't being shown
3. **Sources isolation too strict**: Removed NEWS_SOURCES fallback but sources aren't being created properly
4. **New zips have no data**: 02840 has no articles, sources, or management entries

## Solution
Ensure each zip has its own isolated data while making sure data actually displays:

### 1. Fix Article Loading Logic
**File**: `[admin.py](admin.py)` lines 594-618

**Current issue**: Query requires `article_management.zip_code = ?` but many entries have NULL zip_code

**Fix**: 
- For articles: Show articles where `a.zip_code = ? OR a.zip_code IS NULL` (allow NULL articles to be shown for any zip until assigned)
- For article_management: Match on `am.zip_code = ? OR (am.zip_code IS NULL AND a.zip_code = ?)` to handle old data
- OR migrate all NULL zip_code entries to 02720

### 2. Migrate Old Data to 02720
**File**: Create migration script or add to `scrub_database_to_02720.py`

- Set all NULL zip_code in `article_management` to '02720'
- Set all NULL zip_code in `articles` to '02720' (if desired)
- Clean up old `admin_settings` source entries (move to admin_settings_zip for 02720 or delete)

### 3. Fix Source Loading
**File**: `[admin.py](admin.py)` lines 742-804

**Current issue**: Sources only load from admin_settings_zip, but new zips have no sources

**Fix**:
- Keep zip-specific isolation (only load from admin_settings_zip)
- Ensure "Add Source" button works to create sources for that zip
- Don't merge with NEWS_SOURCES unless explicitly added to that zip

### 4. Fix Stats and Other Tabs
**File**: `[admin.py](admin.py)` lines 868-1000

- Ensure all stats queries filter by zip_code correctly
- Trash tab: Filter rejected articles by zip_code
- Auto-filtered tab: Filter by zip_code
- Settings: Load from admin_settings_zip for that zip

### 5. Data Migration Strategy
**Decision needed**: How should new zips get data?

**Option A**: Start completely empty (current behavior)
- New zips have zero articles, zero sources
- Admin must manually add sources and wait for articles to be fetched

**Option B**: Copy template from 02720
- When creating new zip, copy sources and settings from 02720 as starting point
- Articles remain empty until fetched

**Option C**: Show shared articles until assigned
- Articles with NULL zip_code shown for all zips
- Admin can assign articles to specific zips

## Implementation Steps

1. **Migrate NULL zip_code data to 02720**
   - Update all NULL article_management entries to zip_code = '02720'
   - Update all NULL articles to zip_code = '02720' (if desired)

2. **Fix article query to handle NULL zip_code gracefully**
   - Update JOIN logic to match article_management even if zip_code is NULL initially
   - OR ensure all entries have zip_code set

3. **Fix source loading**
   - Remove NEWS_SOURCES merge (already done)
   - Ensure sources only come from admin_settings_zip
   - Add "Add Source" functionality works correctly

4. **Verify all tabs filter by zip_code**
   - Articles tab: Filter by zip_code
   - Trash tab: Filter rejected by zip_code  
   - Auto-filtered: Filter by zip_code
   - Sources: Only from admin_settings_zip
   - Stats: All stats filtered by zip_code
   - Settings: From admin_settings_zip

5. **Test with both zips**
   - Verify 02720 shows its 97 articles
   - Verify 02840 shows empty (or template data if Option B)
   - Verify sources are zip-specific

## Expected Result
- 02720 shows its 97 articles and configured sources
- 02840 shows empty (or template if copying)
- Each zip has completely isolated data
- All tabs work correctly with zip-specific filtering
- New zips start with no data (or template copy)

