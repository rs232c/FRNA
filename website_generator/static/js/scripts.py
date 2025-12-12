"""
JavaScript for the website generator
Extracted from website_generator.py for better organization
Moved to website_generator/static/js/scripts.py
"""

def get_js_content() -> str:
    """Get JavaScript content"""
    return """document.addEventListener('DOMContentLoaded', function() {
    // Lazy load images using Intersection Observer
    if ('IntersectionObserver' in window) {
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    if (img.dataset.src) {
                        img.src = img.dataset.src;
                        img.removeAttribute('data-src');
                        observer.unobserve(img);
                    }
                }
            });
        }, {
            rootMargin: '50px' // Start loading 50px before image enters viewport
        });
        
        // Observe all images with data-src
        document.querySelectorAll('img[data-src]').forEach(img => {
            imageObserver.observe(img);
        });
    } else {
        // Fallback for browsers without IntersectionObserver
        document.querySelectorAll('img[data-src]').forEach(img => {
            img.src = img.dataset.src;
            img.removeAttribute('data-src');
        });
    }
    
    // Infinite scroll with article looping
    const articlesGrid = document.getElementById('articlesGrid');
    if (articlesGrid) {
        const allArticles = Array.from(articlesGrid.querySelectorAll('article'));
        let visibleCount = Math.min(20, allArticles.length);
        let currentIndex = 0;
        let loading = false;
        
        // Initially show first batch
        allArticles.forEach((article, index) => {
            if (index >= visibleCount) {
                article.style.display = 'none';
            }
        });
        
        // Infinite scroll that loops articles
        window.addEventListener('scroll', function() {
            if (loading) return;
            
            // Check if user scrolled near bottom (within 500px)
            if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 500) {
                loading = true;
                
                // Show next batch of articles
                const batchSize = 10;
                const originalLength = allArticles.length;
                
                for (let i = 0; i < batchSize && originalLength > 0; i++) {
                    // Loop back to start if we've shown all articles
                    const articleIndex = currentIndex % originalLength;
                    const article = allArticles[articleIndex];
                    
                    // If we've already shown all original articles once, clone them for seamless looping
                    if (currentIndex >= originalLength) {
                        const clonedArticle = article.cloneNode(true);
                        clonedArticle.style.display = '';
                        articlesGrid.appendChild(clonedArticle);
                        allArticles.push(clonedArticle);
                    } else {
                        // Show the original article
                        article.style.display = '';
                    }
                    
                    currentIndex++;
                }
                
                // Re-observe new images for lazy loading
                if ('IntersectionObserver' in window) {
                    const imageObserver = new IntersectionObserver((entries, observer) => {
                        entries.forEach(entry => {
                            if (entry.isIntersecting) {
                                const img = entry.target;
                                if (img.dataset.src) {
                                    img.src = img.dataset.src;
                                    img.removeAttribute('data-src');
                                    img.classList.add('loaded');
                                    observer.unobserve(img);
                                }
                            }
                        });
                    }, { rootMargin: '50px' });
                    
                    articlesGrid.querySelectorAll('img[data-src]').forEach(img => {
                        imageObserver.observe(img);
                    });
                }
                
                loading = false;
            }
        });
    }
    
    // Navigation tab switching
    const navTabs = document.querySelectorAll('.nav-tab[data-tab]');
    const allTiles = document.querySelectorAll('.tile[data-category]');
    const featuredTile = document.querySelector('.featured-tile');
    
    navTabs.forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            navTabs.forEach(t => t.classList.remove('active'));
            this.classList.add('active');
            
            const targetTab = this.dataset.tab;
            
            // Show/hide featured tile
            if (featuredTile) {
                if (targetTab === 'all' || targetTab === 'news' || !targetTab || featuredTile.dataset.category === targetTab) {
                    featuredTile.style.display = '';
                } else {
                    featuredTile.style.display = 'none';
                }
            }
            
            // Filter articles in grid
            if (articlesGrid) {
                const articleTiles = articlesGrid.querySelectorAll('.article-tile');
                articleTiles.forEach(tile => {
                    const tileCategory = tile.dataset.category;
                    if (targetTab === 'all' || !targetTab) {
                        tile.style.display = '';
                    } else if (tileCategory === targetTab) {
                        tile.style.display = '';
                    } else {
                        tile.style.display = 'none';
                    }
                });
            }
            
            // Also filter all tiles (for featured tile)
            allTiles.forEach(tile => {
                const tileCategory = tile.dataset.category;
                if (targetTab === 'all' || !targetTab) {
                    tile.style.display = '';
                } else if (tileCategory === targetTab) {
                    tile.style.display = '';
                } else {
                    tile.style.display = 'none';
                }
            });
        });
    });
    
    // Related articles toggle function
    function toggleRelated(button) {
        const list = button.nextElementSibling;
        if (list.style.display === 'none') {
            list.style.display = 'block';
            button.textContent = button.textContent.replace('📎', '📌');
        } else {
            list.style.display = 'none';
            button.textContent = button.textContent.replace('📌', '📎');
        }
    }
    window.toggleRelated = toggleRelated;
    
    // Advanced search filters
    function toggleSearchFilters() {
        const filters = document.getElementById('searchFilters');
        if (filters) {
            filters.style.display = filters.style.display === 'none' ? 'block' : 'none';
        }
    }
    window.toggleSearchFilters = toggleSearchFilters;
    
    function clearFilters() {
        document.getElementById('searchInput').value = '';
        document.getElementById('filterCategory').value = '';
        document.getElementById('filterNeighborhood').value = '';
        document.getElementById('filterSource').value = '';
        document.getElementById('filterDateRange').value = '';
        performSearch();
    }
    window.clearFilters = clearFilters;
    
    // Populate source filter dropdown (if not already populated from template)
    function populateSourceFilter() {
        const sourceSelect = document.getElementById('filterSource');
        // If dropdown already has options (from template), skip population
        if (sourceSelect && sourceSelect.options.length > 1) {
            return;
        }
        if (!sourceSelect) return;
        
        const sources = new Set();
        document.querySelectorAll('.tile-source').forEach(el => {
            const sourceText = el.textContent.split(' - ')[0].trim();
            if (sourceText) sources.add(sourceText);
        });
        
        sources.forEach(source => {
            const option = document.createElement('option');
            option.value = source;
            option.textContent = source;
            sourceSelect.appendChild(option);
        });
    }
    
    function performSearch() {
        const searchTerm = (document.getElementById('searchInput')?.value || '').toLowerCase();
        const categoryFilter = document.getElementById('filterCategory')?.value || '';
        const neighborhoodFilter = document.getElementById('filterNeighborhood')?.value || '';
        const sourceFilter = document.getElementById('filterSource')?.value || '';
        const dateRangeFilter = document.getElementById('filterDateRange')?.value || '';
        
        const allTiles = document.querySelectorAll('.article-tile, .featured-tile');
        let visibleCount = 0;
        
        allTiles.forEach(tile => {
            let matches = true;
            
            // Text search
            if (searchTerm.length >= 2) {
                const title = tile.querySelector('.tile-title, .tile-title-small')?.textContent.toLowerCase() || '';
                const summary = tile.querySelector('.tile-summary, .tile-summary-small')?.textContent.toLowerCase() || '';
                if (!title.includes(searchTerm) && !summary.includes(searchTerm)) {
                    matches = false;
                }
            }
            
            // Category filter
            if (categoryFilter && matches) {
                const tileCategory = tile.dataset.category || '';
                if (tileCategory !== categoryFilter) {
                    matches = false;
                }
            }
            
            // Neighborhood filter
            if (neighborhoodFilter && matches) {
                const neighborhoods = tile.dataset.neighborhoods || '';
                if (!neighborhoods.includes(neighborhoodFilter)) {
                    matches = false;
                }
            }
            
            // Source filter
            if (sourceFilter && matches) {
                const sourceEl = tile.querySelector('.tile-source');
                if (sourceEl) {
                    const sourceText = sourceEl.textContent.split(' - ')[0].trim();
                    if (sourceText !== sourceFilter) {
                        matches = false;
                    }
                }
            }
            
            // Date range filter
            if (dateRangeFilter && matches) {
                const sourceEl = tile.querySelector('.tile-source');
                if (sourceEl) {
                    const dateText = sourceEl.textContent;
                    const now = new Date();
                    let cutoffDate = null;
                    
                    if (dateRangeFilter === 'today') {
                        cutoffDate = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                    } else if (dateRangeFilter === 'week') {
                        cutoffDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
                    } else if (dateRangeFilter === 'month') {
                        cutoffDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
                    }
                    
                    // Simple date check - if date text doesn't contain today's date or recent dates, hide
                    // This is a simplified check; full implementation would parse dates properly
                    if (cutoffDate && !dateText.includes(now.getMonth() + 1 + '/' + now.getDate())) {
                        // Could be improved with proper date parsing
                    }
                }
            }
            
            if (matches) {
                tile.style.display = '';
                if (searchTerm.length >= 2) {
                    tile.style.border = '2px solid #1e88e5';
                } else {
                    tile.style.border = '';
                }
                visibleCount++;
            } else {
                tile.style.display = 'none';
                tile.style.border = '';
            }
        });
        
        // Show message if no results
        const articlesGrid = document.getElementById('articlesGrid');
        if (articlesGrid) {
            let noResultsMsg = articlesGrid.querySelector('.no-results-message');
            if (visibleCount === 0 && (searchTerm || categoryFilter || neighborhoodFilter || sourceFilter || dateRangeFilter)) {
                if (!noResultsMsg) {
                    noResultsMsg = document.createElement('div');
                    noResultsMsg.className = 'no-results-message';
                    noResultsMsg.style.cssText = 'text-align:center; padding:3rem; color:#888;';
                    noResultsMsg.textContent = 'No articles found matching your search criteria.';
                    articlesGrid.appendChild(noResultsMsg);
                }
                noResultsMsg.style.display = 'block';
            } else if (noResultsMsg) {
                noResultsMsg.style.display = 'none';
            }
        }
    }
    
    // Enhanced search with filters
    const searchInput = document.getElementById('searchInput');
    const filterCategory = document.getElementById('filterCategory');
    const filterSource = document.getElementById('filterSource');
    const filterDateRange = document.getElementById('filterDateRange');
    
    let searchTimeout;
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(performSearch, 300);
        });
        
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                clearTimeout(searchTimeout);
                performSearch();
            }
        });
    }
    
    if (filterCategory) {
        filterCategory.addEventListener('change', performSearch);
    }
    const filterNeighborhood = document.getElementById('filterNeighborhood');
    if (filterNeighborhood) {
        filterNeighborhood.addEventListener('change', performSearch);
    }
    if (filterSource) {
        filterSource.addEventListener('change', performSearch);
    }
    if (filterDateRange) {
        filterDateRange.addEventListener('change', performSearch);
    }
    
    // Populate source filter on page load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', populateSourceFilter);
    } else {
        populateSourceFilter();
    }
    
    // Back to top button
    const backToTopBtn = document.getElementById('backToTop');
    if (backToTopBtn) {
        window.addEventListener('scroll', function() {
            if (window.pageYOffset > 300) {
                backToTopBtn.classList.add('show');
            } else {
                backToTopBtn.classList.remove('show');
            }
        });
    }
    
    function scrollToTop() {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    }
    window.scrollToTop = scrollToTop;
    
    // Set active mobile nav item based on current page
    const currentPath = window.location.pathname;
    document.querySelectorAll('.mobile-nav-item').forEach(item => {
        const href = item.getAttribute('href');
        if (currentPath.includes(href) || (currentPath === '/' && href === 'index.html')) {
            item.classList.add('active');
        }
    });
    
    // Initialize weather pill - fetch fresh data on every page load
    async function updateWeatherPill() {
        // Try header weather widget first, then fallback to main weather pill
        const weatherPill = document.getElementById('weatherPillHeader') || document.getElementById('weatherPill');
        const weatherTemp = document.getElementById('weatherTempHeader') || document.getElementById('weatherTemp');
        const weatherCondition = document.getElementById('weatherConditionHeader') || document.getElementById('weatherCondition');
        const weatherIcon = document.getElementById('weatherIconHeader') || document.getElementById('weatherIcon');
        
        if (!weatherPill || !weatherTemp || !weatherCondition || !weatherIcon) {
            return; // Weather pill elements not found
        }
        
        // Always use 02720 (Fall River) for weather
        const zipCode = '02720';
        
        // Fetch fresh weather data (no cache)
        if (window.weatherFetcher) {
            try {
                // Add updating class for visual feedback
                weatherPill.classList.add('weather-updating');
                
                // Set API key if available from window config
                if (window.WEATHER_API_KEY) {
                    window.weatherFetcher.apiKey = window.WEATHER_API_KEY;
                } else {
                    console.warn('Weather API key not configured. Weather data will not be available.');
                }
                
                const weather = await window.weatherFetcher.fetchWeather(zipCode);
                
                if (weather && weather.current) {
                    // Update DOM with fresh weather data
                    weatherTemp.textContent = `${weather.current.temperature}${weather.current.unit}`;
                    weatherCondition.textContent = weather.current.condition;
                    weatherIcon.textContent = weather.current.icon || '🌤️';
                    
                    // Also update header widget if it exists separately
                    const headerTemp = document.getElementById('weatherTempHeader');
                    const headerCondition = document.getElementById('weatherConditionHeader');
                    const headerIcon = document.getElementById('weatherIconHeader');
                    if (headerTemp) headerTemp.textContent = `${weather.current.temperature}${weather.current.unit}`;
                    if (headerCondition) headerCondition.textContent = weather.current.condition;
                    if (headerIcon) headerIcon.textContent = weather.current.icon || '🌤️';
                } else {
                    // Fallback to default
                    weatherTemp.textContent = '--°F';
                    weatherCondition.textContent = 'Unable to load';
                    weatherIcon.textContent = '🌤️';
                }
                
                // Remove updating class and add updated class for smooth transition
                weatherPill.classList.remove('weather-updating');
                weatherPill.classList.add('weather-updated');
                setTimeout(() => {
                    weatherPill.classList.remove('weather-updated');
                }, 300);
            } catch (error) {
                console.error('Error updating weather pill:', error);
                weatherTemp.textContent = '--°F';
                weatherCondition.textContent = 'Error';
                weatherIcon.textContent = '🌤️';
                weatherPill.classList.remove('weather-updating');
            }
        } else {
            console.warn('Weather fetcher not available');
            weatherTemp.textContent = '--°F';
            weatherCondition.textContent = 'Not available';
            weatherIcon.textContent = '🌤️';
        }
    }
    
    // Fetch weather on every page load (no caching) - wait for DOM to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', updateWeatherPill);
    } else {
        updateWeatherPill();
    }
    
    // Newsletter signup
    function handleNewsletterSignup(event) {
        event.preventDefault();
        const email = document.getElementById('newsletterEmail').value;
        const messageEl = document.getElementById('newsletterMessage');
        
        // Store in localStorage for now (can be sent to server later)
        const subscribers = JSON.parse(localStorage.getItem('newsletter_subscribers') || '[]');
        if (!subscribers.includes(email)) {
            subscribers.push(email);
            localStorage.setItem('newsletter_subscribers', JSON.stringify(subscribers));
            messageEl.textContent = '✓ Thank you for subscribing!';
            messageEl.style.color = '#4caf50';
            document.getElementById('newsletterEmail').value = '';
        } else {
            messageEl.textContent = 'You are already subscribed.';
            messageEl.style.color = '#ff9800';
        }
        
        setTimeout(() => {
            messageEl.textContent = '';
        }, 5000);
    }
    window.handleNewsletterSignup = handleNewsletterSignup;
    
    // Copy article link function
    function copyArticleLink(url, button) {
        navigator.clipboard.writeText(url).then(() => {
            const originalText = button.textContent;
            button.textContent = '✓';
            button.style.color = '#4caf50';
            setTimeout(() => {
                button.textContent = originalText;
                button.style.color = '';
            }, 2000);
        }).catch(err => {
            console.error('Failed to copy:', err);
            // Fallback: select text
            const textArea = document.createElement('textarea');
            textArea.value = url;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            button.textContent = '✓';
            setTimeout(() => {
                button.textContent = '🔗';
            }, 2000);
        });
    }
    window.copyArticleLink = copyArticleLink;
    
    
    // Top Stories Slider
    let currentTopStorySlide = 0;
    let sliderAutoRotateInterval = null;
    const topStoriesTrack = document.querySelector('.top-stories-track');
    const topStoriesSlides = document.querySelectorAll('.story-slide');
    const topStoriesDots = document.querySelectorAll('.slider-dots .dot');
    
    function updateTopStoriesSlider() {
        if (topStoriesTrack && topStoriesSlides.length > 0) {
            topStoriesTrack.style.transform = `translateX(-${currentTopStorySlide * 100}%)`;
            
            // Update dots
            topStoriesDots.forEach((dot, index) => {
                if (index === currentTopStorySlide) {
                    dot.classList.remove('bg-white/40');
                    dot.classList.add('bg-white');
                } else {
                    dot.classList.remove('bg-white');
                    dot.classList.add('bg-white/40');
                }
            });
        }
    }
    
    function nextTopStory() {
        if (!topStoriesSlides || topStoriesSlides.length === 0) return;
        currentTopStorySlide = (currentTopStorySlide + 1) % topStoriesSlides.length;
        updateTopStoriesSlider();
    }
    
    function prevTopStory() {
        if (!topStoriesSlides || topStoriesSlides.length === 0) return;
        currentTopStorySlide = (currentTopStorySlide - 1 + topStoriesSlides.length) % topStoriesSlides.length;
        updateTopStoriesSlider();
    }
    
    function goToTopStory(index) {
        if (!topStoriesSlides || index < 0 || index >= topStoriesSlides.length) return;
        currentTopStorySlide = index;
        updateTopStoriesSlider();
    }
    
    // Initialize slider on page load
    if (topStoriesTrack && topStoriesSlides.length > 0) {
        // Calculate and set track width based on number of slides
        const slideCount = topStoriesSlides.length;
        topStoriesTrack.style.width = `${slideCount * 100}%`;
        
        updateTopStoriesSlider(); // Set initial position
        
        // Auto-advance slider every 8 seconds
        if (topStoriesSlides.length > 1) {
            sliderAutoRotateInterval = setInterval(() => {
                nextTopStory();
            }, 8000);
        }
    }
    
    // Expose functions globally for event delegation
    window.nextTopStory = nextTopStory;
    window.prevTopStory = prevTopStory;
    window.goToTopStory = goToTopStory;
});

// Helper functions for copy functionality - defined globally
function copyToClipboard(url, button) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => {
            const originalText = button.textContent;
            button.textContent = '✓';
            button.style.color = '#4caf50';
            setTimeout(() => {
                button.textContent = originalText;
                button.style.color = '';
            }, 2000);
        }).catch(err => {
            console.error('Failed to copy:', err);
            fallbackCopy(url, button);
        });
    } else {
        fallbackCopy(url, button);
    }
}

// Fallback copy method using document.execCommand
function fallbackCopy(url, button) {
    const textArea = document.createElement('textarea');
    textArea.value = url;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
        document.execCommand('copy');
        button.textContent = '✓';
        button.style.color = '#4caf50';
        setTimeout(() => {
            button.textContent = '🔗';
            button.style.color = '';
        }, 2000);
    } catch (err) {
        console.error('Fallback copy failed:', err);
    }
    document.body.removeChild(textArea);
}

// Hero slider event delegation - handle arrow and dot clicks
document.addEventListener('click', function(e) {
    // Check for slider navigation buttons
    const prevBtn = e.target.closest('[data-slider="prev"]');
    const nextBtn = e.target.closest('[data-slider="next"]');
    const dotBtn = e.target.closest('[data-slider-dot]');
    
    if (prevBtn) {
        e.preventDefault();
        e.stopPropagation();
        if (window.prevTopStory) {
            window.prevTopStory();
        }
        return;
    }
    
    if (nextBtn) {
        e.preventDefault();
        e.stopPropagation();
        if (window.nextTopStory) {
            window.nextTopStory();
        }
        return;
    }
    
    if (dotBtn) {
        e.preventDefault();
        e.stopPropagation();
        const index = parseInt(dotBtn.getAttribute('data-slider-dot'), 10);
        if (!isNaN(index) && window.goToTopStory) {
            window.goToTopStory(index);
        }
        return;
    }
}, true); // Use capture phase

// Copy link button handler - MUST be outside DOMContentLoaded to catch all clicks
// Uses capture phase to intercept clicks before inline handlers execute
document.addEventListener('click', function(e) {
    // Check if click is on a copy button or its parent
    let copyBtn = null;
    
    // First, check if target is a button with copy-link-btn class
    if (e.target.tagName === 'BUTTON' && e.target.classList && e.target.classList.contains('copy-link-btn')) {
        copyBtn = e.target;
    }
    
    // Also check for buttons with copy-link-btn class using closest
    if (!copyBtn) {
        copyBtn = e.target.closest('.copy-link-btn');
    }
    
    // Also check parent elements in case click is on emoji/text inside button
    if (!copyBtn) {
        let element = e.target;
        while (element && element !== document.body) {
            if (element.tagName === 'BUTTON') {
                // Check for copy-link-btn class
                if (element.classList && element.classList.contains('copy-link-btn')) {
                    copyBtn = element;
                    break;
                }
                // Also check for inline onclick (legacy support)
                const onclick = element.getAttribute('onclick') || '';
                if (onclick.includes('copyArticleLink')) {
                    copyBtn = element;
                    // Remove inline onclick to prevent double execution
                    element.removeAttribute('onclick');
                    break;
                }
            }
            element = element.parentElement;
        }
    }
    
    if (copyBtn) {
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        
        // Extract URL from data attribute (preferred method)
        let url = copyBtn.dataset.copyUrl;
        
        // If no data attribute, try to extract from onclick attribute (legacy support)
        if (!url) {
            const onclick = copyBtn.getAttribute('onclick') || '';
            // Match: copyArticleLink('url', this) or copyArticleLink("url", this)
            const match = onclick.match(/copyArticleLink\\(['"]([^'"]+)['"]/);
            if (match && match[1]) {
                url = match[1];
            }
        }
        
        if (!url) {
            console.warn('Could not find URL for copy button');
            return;
        }
        
        // Use the global function if available
        if (window.copyArticleLink && typeof window.copyArticleLink === 'function') {
            try {
                window.copyArticleLink(url, copyBtn);
            } catch (err) {
                console.error('Error calling copyArticleLink:', err);
                // Fallback to direct copy
                copyToClipboard(url, copyBtn);
            }
        } else {
            // Fallback: copy directly
            copyToClipboard(url, copyBtn);
        }
    }
}, true); // Use capture phase to intercept before inline handlers"""
