# Trash Page Debugging & Fixes

## Issues Found and Fixed

### 1. **Missing zip_code Parameter** ⚠️ CRITICAL
**Problem**: The `/admin/api/get-rejected-articles` endpoint requires a `zip_code` parameter, but the client-side code wasn't sending it.

**Location**: `website_output/js/admin.js` line 563

**Before**:
```javascript
const response = await fetch('/admin/api/get-rejected-articles', {
    credentials: 'same-origin'
});
```

**After**:
```javascript
const response = await fetch(`/admin/api/get-rejected-articles?zip_code=${encodeURIComponent(this.currentZip)}`, {
    credentials: 'same-origin'
});
```

**Why it failed**: The API endpoint checks for `zip_code` and returns a 400 error if it's missing:
```python
if not zip_code:
    return jsonify({'success': False, 'error': 'Zip code required...'}), 400
```

---

### 2. **Missing HTTP Response Status Check** ⚠️ HIGH PRIORITY
**Problem**: The code wasn't checking if the HTTP response was successful before trying to parse JSON.

**Fix**: Added response status check:
```javascript
if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
}
```

This prevents trying to parse error responses as JSON, which would cause confusing errors.

---

### 3. **Missing zip_code in Restore/Delete Operations** ⚠️ HIGH PRIORITY
**Problem**: The `restoreArticle()` and `deleteArticlePermanently()` functions weren't sending `zip_code` in the request body.

**Fix**: Added `zip_code` to all API requests:
```javascript
body: JSON.stringify({
    article_id: parseInt(articleId),
    enabled: true,
    zip_code: this.currentZip  // CRITICAL: Include zip_code
})
```

---

### 4. **Event Listener Issues** ⚠️ MEDIUM PRIORITY
**Problem**: Event listeners were attached to individual buttons, which could fail if the button structure changes or if there are nested elements.

**Fix**: Changed to event delegation pattern:
```javascript
// Before: Individual listeners
container.querySelectorAll('.restore-trash-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const articleId = e.target.getAttribute('data-article-id');
        // ...
    });
});

// After: Event delegation
container.addEventListener('click', (e) => {
    const restoreBtn = e.target.closest('.restore-trash-btn');
    if (restoreBtn) {
        const articleId = restoreBtn.getAttribute('data-article-id');
        // ...
    }
});
```

**Benefits**:
- Works even if buttons are dynamically recreated
- Handles nested elements correctly (e.g., if button contains an icon)
- More efficient (one listener instead of many)

---

### 5. **Auto-Filtered Tab Also Fixed** ✅
Applied the same fixes to the auto-filtered tab:
- Added `zip_code` parameter to `/admin/api/get-auto-filtered`
- Added response status check
- Fixed event listeners to use delegation
- Added `zip_code` to restore operation

---

## Testing Checklist

After these fixes, test the following:

1. **Trash Tab Loading**:
   - [ ] Open admin panel for a zip code (e.g., `/admin/02720`)
   - [ ] Click on "🗑️ Trash" tab
   - [ ] Verify articles load (or "No trashed articles" message appears)
   - [ ] Check browser console for errors

2. **Restore Functionality**:
   - [ ] Click "Restore" button on a trashed article
   - [ ] Confirm the dialog
   - [ ] Verify article disappears from trash
   - [ ] Verify article appears in main articles list

3. **Delete Functionality**:
   - [ ] Click "Delete" button on a trashed article
   - [ ] Confirm the dialog
   - [ ] Verify article disappears from trash

4. **Auto-Filtered Tab**:
   - [ ] Click on "🤖 Auto-Filtered" tab
   - [ ] Verify articles load
   - [ ] Test restore functionality

5. **Error Handling**:
   - [ ] Test with invalid zip code
   - [ ] Test with network errors (disable network in DevTools)
   - [ ] Verify error messages are user-friendly

---

## Common Errors to Watch For

1. **"Zip code required"** → Fixed by adding `zip_code` parameter
2. **"Unexpected token < in JSON"** → Fixed by checking response status before parsing
3. **Buttons not working** → Fixed by using event delegation
4. **"Cannot read property 'success' of undefined"** → Fixed by proper error handling

---

## Debugging Tips

If the trash page still doesn't work:

1. **Open Browser DevTools Console**:
   - Look for red error messages
   - Check Network tab to see API requests/responses

2. **Check API Response**:
   ```javascript
   // In browser console, test the API directly:
   fetch('/admin/api/get-rejected-articles?zip_code=02720', {
       credentials: 'same-origin'
   }).then(r => r.json()).then(console.log);
   ```

3. **Verify zip_code**:
   ```javascript
   // In browser console on admin page:
   console.log('Current zip:', window.adminPanel?.currentZip);
   ```

4. **Check Session/Authentication**:
   - Make sure you're logged in
   - Check if session cookie is set
   - Verify the admin route is accessible

---

## Files Modified

- `website_output/js/admin.js`:
  - `renderTrash()` - Added zip_code parameter and response check
  - `renderAutoFiltered()` - Added zip_code parameter and response check
  - `renderSources()` - Added response check
  - `restoreArticle()` - Added zip_code to request body
  - `deleteArticlePermanently()` - Added zip_code to request body
  - `restoreAutoFiltered()` - Added zip_code to request body
  - Event listeners - Changed to delegation pattern

---

## Summary

The main issue was that the client-side admin panel wasn't sending the required `zip_code` parameter to the API endpoints. The API requires this to filter articles by zip code (for per-zip isolation). 

All fixes maintain the per-zip isolation pattern that's critical to the system's architecture.

