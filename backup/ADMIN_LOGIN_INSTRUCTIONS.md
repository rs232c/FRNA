# Admin Panel Login Instructions

## Two Types of Admin Access

### 1. Zip-Specific Admin (Per-Zip Management)

**URL Format:** `http://localhost:8000/admin/02720` (replace 02720 with your zip code)

**Login Credentials:**
- **Username:** Your zip code (e.g., `02720`)
- **Password:** Set via `ZIP_LOGIN_PASSWORD` environment variable

**What it manages:**
- Articles for that specific zip code
- Relevance configuration for that zip
- Sources for that zip
- Settings for that zip
- Trash and auto-filtered articles for that zip
- Statistics for that zip

**All data is completely isolated per zip code!**

### 2. Main Admin (Global Settings)

**URL Format:** `http://localhost:8000/admin/main`

**Login Credentials:**
- **Username:** Set via `ADMIN_USERNAME` environment variable
- **Password:** Set via `ADMIN_PASSWORD` environment variable

**What it manages:**
- Global system settings
- All zip codes overview
- System-wide configuration

## How to Access

### For Zip-Specific Admin:

1. **From the main site:**
   - Navigate to a zip code (e.g., `http://localhost:8000/02720`)
   - Click the settings/admin icon in the navigation
   - You'll be redirected to `/admin/02720`
   - Login with:
     - Username: `02720` (the zip code)
     - Password: Your `ZIP_LOGIN_PASSWORD` environment variable value

2. **Direct URL:**
   - Go to `http://localhost:8000/admin/02720`
   - Login with zip code as username and your `ZIP_LOGIN_PASSWORD` as password

### For Main Admin:

1. **Direct URL:**
   - Go to `http://localhost:8000/admin/main`
   - Login with:
     - Username: Your `ADMIN_USERNAME` environment variable value
     - Password: Your `ADMIN_PASSWORD` environment variable value

2. **From zip admin:**
   - Click the "Main Admin" link in the login page

## Admin Features (Zip-Specific)

Once logged into a zip-specific admin (`/admin/02720`), you have access to:

### 📰 Articles Tab
- View all articles for this zip
- Enable/disable articles
- Mark as top story (🔥)
- Mark as good fit (👍)
- Trash articles (🗑️)

### 🗑️ Trash Tab
- View trashed articles
- Restore articles
- Permanently delete articles

### 🤖 Auto-Filtered Tab
- View auto-filtered articles
- Restore articles that were auto-filtered

### 📡 Sources Tab
- View configured sources for this zip
- Add new sources
- Delete sources

### 📊 Stats Tab
- View statistics for this zip
- Article counts
- Source breakdowns

### ⚙️ Settings Tab
- Show/hide images
- Relevance threshold
- AI filtering enabled/disabled
- Auto-regenerate settings
- Regenerate interval

### 🎯 Relevance Tab
- High relevance keywords
- Medium relevance keywords
- Local places
- Topic keywords
- Source credibility scores
- Clickbait patterns

## Important Notes

1. **Complete Isolation:** Each zip code has completely separate data. Changes in `/admin/02720` do NOT affect `/admin/10001`.

2. **Login Persistence:** Login is stored in `sessionStorage` and persists until you close the browser tab.

3. **Path-Based URLs:** All admin URLs use path-based routing:
   - ✅ `/admin/02720` (correct)
   - ❌ `/admin.html?z=02720` (legacy, will redirect)

4. **Main Admin:** Main admin (`/admin/main`) is separate from zip-specific admins and manages global settings.

## Troubleshooting

**Can't login?**
- Make sure environment variables are set in your `.env` file:
  - `ADMIN_USERNAME` - Main admin username
  - `ADMIN_PASSWORD` - Main admin password
  - `ZIP_LOGIN_PASSWORD` - Password for per-zip admin login
- Zip admin: Username = zip code (5 digits), Password = `ZIP_LOGIN_PASSWORD`
- Main admin: Username = `ADMIN_USERNAME`, Password = `ADMIN_PASSWORD`

**Not seeing articles?**
- Make sure you're logged into the correct zip code
- Articles are fetched dynamically - they may take a moment to load
- Check the browser console for errors

**Settings not saving?**
- All settings are stored in `localStorage` and `IndexedDB`
- Make sure your browser allows local storage
- Check browser console for errors

