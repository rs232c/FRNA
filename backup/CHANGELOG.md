# Changelog

All notable changes to the Fall River News Aggregator project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2024-12-07

### Added
- Initial release of Fall River News Aggregator
- News aggregation from multiple local sources (Herald News, Fall River Reporter, Fun107, WPRI, etc.)
- Static website generation with MSN-style layout
- Admin dashboard for article and source management
- Weather integration with Fall River location
- Mobile-responsive design with breakpoints for 320px, 480px, 768px, and 1024px
- Emoji icons for article categories (📰 News, 🎬 Entertainment, ⚽ Sports, 📍 Local, 🎥 Media)
- Weather map page with OpenStreetMap embed and location pin
- CI/CD workflow with GitHub Actions
- Unit tests for aggregator and database operations
- Performance monitoring and metrics tracking
- Image optimization (WebP conversion, resizing)
- Caching layer for RSS feeds and scraped content
- Async/parallel article fetching
- Retry logic with circuit breaker pattern
- Incremental website regeneration

### Changed
- Improved article date handling to use publication date instead of ingestion date
- Enhanced mobile responsiveness with better touch targets and navigation
- Optimized database queries with indexes

### Fixed
- Article dates now correctly display publication date instead of current date
- Admin panel settings now persist across page reloads
- Database indentation errors resolved

### Security
- All dependencies pinned to specific versions in requirements.txt
