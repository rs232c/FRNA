# Fall River News Aggregator

A comprehensive news aggregation system for Fall River, MA that collects news from multiple sources, aggregates content, and distributes it across multiple platforms.

## Features

- **Multi-Source Ingestion**: Collects news from:
  - Herald News
  - Fall River Reporter
  - City of Fall River Facebook page
  - Local columnist Facebook pages

- **Intelligent Aggregation**:
  - Deduplication of similar articles
  - Relevance filtering
  - Content enrichment with hashtags and metadata

- **Website Generation**: Automatically generates a beautiful, responsive static website

- **Multi-Platform Distribution**:
  - Facebook Page
  - Instagram
  - TikTok (requires video content)
  - All posts include relevant hashtags like #FallRiverMA

## Quick Start

Run the setup script to get started:

```bash
python setup.py
```

This will:
- Check and install dependencies
- Create `.env` file from template
- Create necessary directories

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Or use the setup script:
```bash
python setup.py
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your:
- Facebook App credentials and Page Access Token
- Instagram credentials
- TikTok credentials (if using)
- Website deployment settings

### 3. Facebook Setup

To get Facebook API access:

1. Go to [Facebook Developers](https://developers.facebook.com/)
2. Create a new app
3. Add "Pages" permission
4. Generate a Page Access Token for your page
5. Add the token to `.env`

### 4. Configure News Sources

Edit `config.py` to:
- Add/remove news sources
- Configure Facebook page IDs for city and columnists
- Adjust filtering keywords
- Set posting schedules

## Usage

### Run Once

```bash
python main.py --once
```

This will:
1. Collect all news articles
2. Generate the website
3. Post to social media (if at scheduled time)

### Run Continuously

```bash
python main.py
```

This will run the aggregator on a schedule (default: hourly) and keep running until stopped.

## Project Structure

```
.
├── config.py                 # Configuration settings
├── main.py                   # Main orchestrator
├── setup.py                  # Setup script
├── aggregator.py             # News aggregation logic
├── database.py               # Database for tracking articles
├── website_generator.py      # Static website generator
├── social_poster.py          # Social media posting
├── deploy.py                 # Website deployment helper
├── ingestors/
│   ├── __init__.py
│   ├── news_ingestor.py      # News source scrapers
│   └── facebook_ingestor.py  # Facebook content fetcher
├── website_output/           # Generated website files
├── fallriver_news.db         # SQLite database (created automatically)
├── requirements.txt          # Python dependencies
└── .env                      # Environment variables (create from .env.example)
```

## Website Deployment

The generated website is in `website_output/`. You can deploy it to:

- **GitHub Pages**: Push to a GitHub repository and enable Pages
- **Netlify**: Drag and drop the folder or connect via Git
- **Vercel**: Import the folder as a static site
- **Any static hosting**: The files are ready to upload

## Customization

### Adding News Sources

Edit `config.py` and add to `NEWS_SOURCES`:

```python
"new_source": {
    "name": "New Source Name",
    "url": "https://example.com",
    "rss": "https://example.com/rss",  # Optional
    "enabled": True
}
```

### Adjusting Filters

Edit `AGGREGATION_CONFIG` in `config.py` to:
- Change minimum article length
- Add/remove keywords
- Adjust deduplication settings

### Posting Schedule

Edit `POSTING_SCHEDULE` in `config.py`:
- Change frequency (hourly, daily, twice_daily)
- Set specific posting times
- Adjust max posts per day

## Database

The system uses SQLite to track articles and prevent duplicate postings. The database:
- Stores all aggregated articles
- Tracks which articles have been posted to which platforms
- Prevents duplicate posts
- Can be cleaned up with old articles (configurable)

## Notes

- **Facebook API**: Requires a Facebook App and Page Access Token. Free tier has rate limits.
  - Get tokens from: https://developers.facebook.com/
  - You need "pages_read_engagement" and "pages_manage_posts" permissions
- **Instagram**: Uses instagrapi library. Instagram may require 2FA setup.
  - Note: Instagram's API has strict rate limits and may require manual approval
- **TikTok**: Business API required. Text-only posts not supported (needs video).
  - TikTok API is primarily for video content, not text articles
- **Web Scraping**: Be respectful of websites' robots.txt and rate limits
- **Database**: Articles are stored in SQLite. Old articles are automatically cleaned up after 30 days (configurable)

## Legal Considerations

- Respect copyright and fair use
- Check terms of service for each platform
- Some sources may require permission for aggregation
- Consider adding attribution and disclaimers

## Testing

### Setup Testing

Before running the full system, test your setup:

```bash
python test_setup.py
```

This will verify:
- All dependencies are installed
- Configuration is valid
- Database can be initialized
- All modules can be imported

### Unit Tests

Run the test suite:

```bash
pytest tests/ -v
```

Or run specific test files:

```bash
pytest tests/test_aggregator.py -v
pytest tests/test_database.py -v
```

### CI/CD

The project includes a GitHub Actions workflow (`.github/workflows/ci.yml`) that:
- Runs tests on push and pull requests
- Tests against multiple Python versions (3.9, 3.10, 3.11)
- Checks imports and basic functionality
- Performs optional linting with flake8

To use CI/CD:
1. Push your code to a GitHub repository
2. The workflow will automatically run on pushes and PRs
3. Check the Actions tab in GitHub to see test results

### Version Tracking

The project uses semantic versioning. Check `config.py` for the current version and `CHANGELOG.md` for a history of changes.

## Troubleshooting

### No articles collected
- Check internet connection
- Verify news source URLs are correct
- Check if sources require authentication
- Some sites may block automated requests - you may need to adjust User-Agent or add delays

### Facebook posting fails
- Verify Page Access Token is valid
- Check token has required permissions (pages_read_engagement, pages_manage_posts)
- Ensure page ID is correct
- Facebook API has rate limits - you may need to wait between posts

### Instagram posting fails
- Instagram may require 2FA
- Check username/password
- Instagram may rate limit automated posting
- Instagram's API is restrictive - consider using manual posting for Instagram

### Database errors
- Ensure write permissions in the directory
- Check if database file is locked (close any other connections)
- Database is created automatically on first run

## License

This project is provided as-is for educational and local news aggregation purposes.

" " 
