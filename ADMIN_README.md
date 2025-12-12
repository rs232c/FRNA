# Admin Panel Guide

## Starting the Admin Panel

Run the admin panel with:
```bash
python server.py
```

Or use the batch file:
```bash
start_admin.bat
```

The admin panel will be available at: **http://localhost:8000/admin**

**Login credentials:**
- Username: Set via `ADMIN_USERNAME` environment variable
- Password: Set via `ADMIN_PASSWORD` environment variable
- Per-zip admin password: Set via `ZIP_LOGIN_PASSWORD` environment variable

**Setup:**
Create a `.env` file with:
```
ADMIN_USERNAME=your_username
ADMIN_PASSWORD=your_secure_password
ZIP_LOGIN_PASSWORD=your_zip_password
```

## Primary Admin System

**admin.py** (Flask-based) is the primary and recommended admin system. It includes:
- Full authentication system
- Articles management (enable/disable, reorder, edit)
- Trash/Rejected articles management
- Auto-filtered articles view
- Sources management
- Statistics dashboard
- Settings management
- Better error handling and API

## Legacy Admin Systems

This project has legacy admin systems that are deprecated:
- **admin_server.py** - Simple HTTP server (deprecated)

These are kept for backward compatibility but should not be used for new deployments.

## Features

### 1. Enable/Disable Articles
- Toggle articles on/off using the switch next to each article
- Disabled articles won't appear on the website
- Changes are saved immediately

### 2. Reorder Articles
- Drag articles by the ☰ handle on the left
- Articles will appear in the order you set
- Changes are saved automatically

### 3. Show/Hide Images
- Toggle "Show Images" to hide all images on the website
- Useful for faster loading or data-saving
- Changes require regenerating the website

### 4. Regenerate Website
- Click "Regenerate Website" to rebuild the site with current settings
- This will:
  - Apply enabled/disabled settings
  - Apply new article order
  - Apply image visibility settings
  - Fetch latest articles

### 5. Trash Management
- View and restore rejected articles
- Permanently delete articles from trash
- Manage auto-filtered articles

### 6. Statistics Dashboard
- View article counts by status
- See source statistics
- Monitor system health

## How It Works

1. **Article Management:** Settings are stored in the `article_management` table
2. **Display Settings:** Stored in the `admin_settings` table
3. **Website Generation:** The website generator reads these settings when building the site

## Security Notes

- The admin panel uses session-based authentication
- Default credentials are `admin` / `admin` - change these in production!
- Change the `secret_key` in `admin.py` for production
- Consider adding IP restrictions or stronger authentication
- The admin panel should not be exposed to the public internet without proper security
