# Netlify Deployment Guide

## Quick Deploy

### Option 1: Netlify Dashboard (Drag & Drop)
1. Go to [Netlify Drop](https://app.netlify.com/drop)
2. Drag and drop the `website_output` folder
3. Your site will be live!

### Option 2: Netlify CLI
```bash
# Install Netlify CLI (if not installed)
npm install -g netlify-cli

# Login to Netlify
netlify login

# Deploy
netlify deploy --dir=website_output --prod
```

### Option 3: Git Integration
1. Connect your repository to Netlify
2. Set build settings:
   - **Base directory**: (leave empty)
   - **Build command**: (leave empty)
   - **Publish directory**: `website_output`
3. Deploy!

## Configuration Files

- `netlify.toml` - Main Netlify configuration (in project root)
- `website_output/_redirects` - URL redirects and routing rules
- `.netlifyignore` - Files to exclude from deployment

## URL Structure

- `/` → Redirects to `/02720`
- `/02720` → Serves `/zip_02720/index.html`
- `/02720/category/crime` → Serves `/zip_02720/category/crime.html`

## Troubleshooting

### Routes not working?
- Check that `_redirects` file is in `website_output/` folder
- Verify zip code folders exist (e.g., `zip_02720/`)

### Assets not loading?
- Ensure CSS/JS paths are relative (not absolute)
- Check browser console for 404 errors

### 404 errors?
- Verify redirects are correct in `_redirects` file
- Check that files exist in the expected locations

## Notes

- The admin panel (`/admin`) won't work on Netlify since it requires Flask
- Only static files from `website_output/` are deployed
- To update the site, regenerate files and redeploy

