/**
 * News Fetcher - Dynamic news fetching per zip code
 */

class NewsFetcher {
    constructor() {
        this.cache = new Map();
        this.localRSSFeeds = {
            '02720': [
                'https://fallriverreporter.com/feed/',
                'https://fun107.com/feed/',
                'https://www.wpri.com/feed/'
            ],
            '02721': [
                'https://fallriverreporter.com/feed/',
                'https://fun107.com/feed/',
                'https://www.wpri.com/feed/'
            ]
        };
    }

    async fetchForZip(zipCode) {
        if (!zipCode || !/^\d{5}$/.test(zipCode)) {
            console.error('Invalid zip code:', zipCode);
            return [];
        }

        // Check cache first
        const cacheKey = `news_${zipCode}`;
        const cached = this.cache.get(cacheKey);
        if (cached && Date.now() - cached.timestamp < 30 * 60 * 1000) { // 30 min cache
            console.log('Using cached news for zip', zipCode);
            return cached.articles;
        }

        try {
            // Resolve zip to city/state
            const location = await this.resolveZip(zipCode);
            if (!location) {
                console.error('Could not resolve zip code:', zipCode);
                return [];
            }

            // Fetch Google News RSS
            const googleNewsArticles = await this.fetchGoogleNews(location.city, location.state);

            // Fetch local RSS feeds if available
            const localArticles = await this.fetchLocalRSS(zipCode);

            // Merge and deduplicate articles
            let allArticles = this.mergeArticles([...googleNewsArticles, ...localArticles]);
            
            // Auto-categorize articles
            if (window.categorizer) {
                allArticles = window.categorizer.categorizeBatch(allArticles);
            }

            // Store in IndexedDB
            if (window.storageManager) {
                for (const article of allArticles) {
                    await window.storageManager.saveArticle(zipCode, article);
                }
            }

            // Cache results
            this.cache.set(cacheKey, {
                articles: allArticles,
                timestamp: Date.now()
            });

            // Trigger UI update - preserve scroll position
            const scrollY = window.scrollY;
            setTimeout(async () => {
                if (window.articleRenderer) {
                    try {
                        await window.articleRenderer.renderArticles(allArticles, zipCode);
                        // Restore scroll position after render completes
                        requestAnimationFrame(() => {
                            window.scrollTo(0, scrollY);
                        });
                    } catch (err) {
                        console.error('Error rendering articles:', err);
                    }
                }
            }, 100);

            return allArticles;
        } catch (error) {
            console.error('Error fetching news for zip', zipCode, error);
            return [];
        }
    }

    async resolveZip(zipCode) {
        try {
            // Try zippopotam.us first
            const response = await fetch(`https://api.zippopotam.us/us/${zipCode}`);
            if (response.ok) {
                const data = await response.json();
                if (data.places && data.places.length > 0) {
                    const place = data.places[0];
                    return {
                        city: place['place name'],
                        state: place['state abbreviation'],
                        fullState: place['state']
                    };
                }
            }
        } catch (error) {
            console.warn('Zippopotam API failed, trying fallback:', error);
        }

        try {
            // Fallback to ziptasticapi.com
            const response = await fetch(`https://ziptasticapi.com/${zipCode}`);
            if (response.ok) {
                const data = await response.json();
                if (data.city && data.state) {
                    return {
                        city: data.city,
                        state: data.state,
                        fullState: data.state
                    };
                }
            }
        } catch (error) {
            console.error('Ziptastic API also failed:', error);
        }

        return null;
    }

    async fetchGoogleNews(city, state) {
        const query = `when:7d+${encodeURIComponent(city)}+${encodeURIComponent(state)}`;
        const rssUrl = `https://news.google.com/rss/search?q=${query}&hl=en-US&gl=US&ceid=US:en`;
        
        try {
            // Use proxy to avoid CORS
            const proxyUrl = `/api/proxy-rss?url=${encodeURIComponent(rssUrl)}`;
            const response = await fetch(proxyUrl);
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const xmlText = await response.text();
            return this.parseRSS(xmlText, 'Google News');
        } catch (error) {
            console.error('Error fetching Google News:', error);
            return [];
        }
    }

    async fetchLocalRSS(zipCode) {
        const feeds = this.localRSSFeeds[zipCode] || [];
        const allArticles = [];

        for (const feedUrl of feeds) {
            try {
                const proxyUrl = `/api/proxy-rss?url=${encodeURIComponent(feedUrl)}`;
                const response = await fetch(proxyUrl);
                
                if (response.ok) {
                    const xmlText = await response.text();
                    const articles = this.parseRSS(xmlText, this.getSourceNameFromURL(feedUrl));
                    allArticles.push(...articles);
                }
            } catch (error) {
                console.warn('Error fetching local RSS feed:', feedUrl, error);
            }
        }

        return allArticles;
    }

    parseRSS(xmlText, sourceName) {
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(xmlText, 'text/xml');
        const items = xmlDoc.querySelectorAll('item');
        const articles = [];

        items.forEach((item, index) => {
            try {
                const title = item.querySelector('title')?.textContent || '';
                const link = item.querySelector('link')?.textContent || '';
                const description = item.querySelector('description')?.textContent || '';
                const pubDate = item.querySelector('pubDate')?.textContent || '';
                const guid = item.querySelector('guid')?.textContent || link;

                // Generate unique ID from URL or use guid
                const articleId = this.generateArticleId(link, guid);

                articles.push({
                    id: articleId,
                    title: this.cleanText(title),
                    url: link,
                    summary: this.cleanText(description),
                    published: this.parseDate(pubDate),
                    source: sourceName,
                    source_display: sourceName,
                    category: this.categorizeArticle(title, description),
                    image_url: this.extractImage(description) || null
                });
            } catch (error) {
                console.warn('Error parsing RSS item:', error);
            }
        });

        return articles;
    }

    generateArticleId(url, guid) {
        // Use URL hash or guid hash
        const str = url || guid || Math.random().toString();
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash; // Convert to 32bit integer
        }
        return Math.abs(hash).toString();
    }

    cleanText(text) {
        if (!text) return '';
        // Remove HTML tags
        const div = document.createElement('div');
        div.innerHTML = text;
        return div.textContent || div.innerText || '';
    }

    parseDate(dateString) {
        if (!dateString) return new Date().toISOString();
        try {
            const date = new Date(dateString);
            return date.toISOString();
        } catch (error) {
            return new Date().toISOString();
        }
    }

    extractImage(description) {
        const imgMatch = description.match(/<img[^>]+src="([^"]+)"/i);
        return imgMatch ? imgMatch[1] : null;
    }

    categorizeArticle(title, description) {
        const text = `${title} ${description}`.toLowerCase();
        
        if (text.match(/\b(sport|game|team|player|coach|stadium|match|score)\b/)) {
            return 'sports';
        }
        if (text.match(/\b(entertainment|movie|show|music|concert|celebrity|actor)\b/)) {
            return 'entertainment';
        }
        if (text.match(/\b(video|youtube|watch|stream|media)\b/)) {
            return 'media';
        }
        if (text.match(/\b(event|meeting|festival|concert|workshop|seminar)\b/)) {
            return 'events';
        }
        return 'news';
    }

    getSourceNameFromURL(url) {
        if (url.includes('fallriverreporter')) return 'Fall River Reporter';
        if (url.includes('fun107')) return 'Fun107';
        if (url.includes('wpri')) return 'WPRI 12 Fall River';
        if (url.includes('heraldnews')) return 'Herald News';
        return 'Local News';
    }

    mergeArticles(articles) {
        // Deduplicate by URL
        const seen = new Set();
        const unique = [];

        for (const article of articles) {
            if (!seen.has(article.url)) {
                seen.add(article.url);
                unique.push(article);
            }
        }

        // Sort by published date (newest first)
        unique.sort((a, b) => {
            const dateA = new Date(a.published);
            const dateB = new Date(b.published);
            return dateB - dateA;
        });

        return unique;
    }
}

// Initialize news fetcher
let newsFetcher;
if (typeof window !== 'undefined') {
    newsFetcher = new NewsFetcher();
    window.newsFetcher = newsFetcher;
}

