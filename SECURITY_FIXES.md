# Security Fixes Applied

## Summary
Applied critical security fixes to `admin.py` based on code review findings.

## Changes Made

### 1. Environment Variables for Secrets
- **Secret Key**: Now uses `FLASK_SECRET_KEY` environment variable
- **Admin Credentials**: Now uses `ADMIN_USERNAME` and `ADMIN_PASSWORD` environment variables
- **Password Hashing**: Added support for `ADMIN_PASSWORD_HASH` environment variable

### 2. Password Security
- Added `bcrypt` for password hashing
- Implemented `hash_password()` and `verify_password()` functions
- Login supports both hashed and plain text (backward compatibility)

### 3. CORS Security
- Changed from wildcard `*` to specific allowed origins
- Configurable via `ALLOWED_ORIGINS` environment variable
- Defaults to `http://localhost:8000,http://127.0.0.1:8000`

### 4. Rate Limiting
- Added Flask-Limiter for rate limiting
- Login endpoint limited to 5 requests per minute
- Default limits: 200 requests per day, 50 per hour

### 5. Path Traversal Protection
- Added `safe_path()` function to prevent directory traversal attacks
- Applied to all file serving endpoints:
  - `/css/<filename>`
  - `/js/<filename>`
  - `/images/<filename>`
  - `/<zip_code>`
  - `/<path:filename>`

### 6. Input Validation
- Added `validate_zip_code()` function
- Added `validate_article_id()` function
- Applied validation in login and API endpoints

### 7. Database Connection Management
- Added context manager `get_db()` for proper connection handling
- Ensures connections are always closed
- Updated `init_admin_db()` to use context manager

### 8. Session Security
- Added `SESSION_COOKIE_HTTPONLY = True`
- Added `SESSION_COOKIE_SECURE` (configurable, defaults to False for development)
- Added `SESSION_COOKIE_SAMESITE = 'Lax'`

### 9. Constants for Magic Numbers
- `ZIP_CODE_LENGTH = 5`
- `REGENERATION_TIMEOUT_SECONDS = 600`
- `MAX_ARTICLE_ID = 2**31 - 1`

## Required Environment Variables

Create a `.env` file with:

```bash
# Flask Configuration
FLASK_SECRET_KEY=your-secret-key-here-minimum-32-characters

# Admin Authentication
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-secure-password-here
# OR use hashed password (recommended):
# ADMIN_PASSWORD_HASH=$(python -c "import bcrypt; print(bcrypt.hashpw('your-password'.encode(), bcrypt.gensalt()).decode())")

# CORS Configuration
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,https://yourdomain.com

# Session Security (set to true in production with HTTPS)
SESSION_COOKIE_SECURE=false  # Set to true in production
```

## Installation

Install new dependencies:
```bash
pip install -r requirements.txt
```

## Backward Compatibility

- Plain text passwords still work (for migration period)
- Existing sessions will be invalidated (new secret key)
- All validation is backward compatible

## Next Steps (Recommended)

1. **Generate a secure secret key:**
   ```python
   import secrets
   print(secrets.token_hex(32))
   ```

2. **Hash your admin password:**
   ```python
   import bcrypt
   password = "your-password"
   hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
   print(hashed)
   ```

3. **Update environment variables** in production

4. **Enable HTTPS** and set `SESSION_COOKIE_SECURE=true`

5. **Review and test** all file serving endpoints

## Testing

After applying fixes, test:
- [ ] Login with credentials
- [ ] File serving (CSS, JS, images)
- [ ] Zip code routing
- [ ] Rate limiting on login
- [ ] Path traversal protection

